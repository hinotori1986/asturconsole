"""Analizador de volcados de cartuchos MSX multi-juego (tipo "Physical
Dreams" / compilaciones caseras con menu en BASIC como cargador).

Automatiza el proceso manual usado para desmontar usas16.rom:
1. Divide el volcado en bloques de 8KB y clasifica cada uno: vacio (todo
   0xFF, flash borrada), vacio (todo 0x00), o contenido real.
2. Agrupa bloques "reales" contiguos en zonas.
3. Para cada zona: comprueba si contiene un sector de arranque FAT12
   valido (patron "EB xx 90" + BPB coherente) en la posicion donde un
   disco dsk2rom lo colocaria (tras 2 bloques de nucleo) -> zona=DISCO.
   Si no, se trata como ROM directa y se buscan sub-cabeceras "41 42"
   (AB) en distintas direcciones de init dentro de la zona, tratando
   cada cambio de direccion como el posible inicio de un juego nuevo.
4. Extrae cada zona/sub-juego a un fichero .rom o .dsk independiente.

Uso:
    python3 analizar_multicart_msx.py volcado.rom [directorio_salida]
"""
import struct
import sys
from pathlib import Path

TAM_BLOQUE = 8192


def _es_boot_sector_valido(datos: bytes, off: int) -> bool:
    """Comprueba si en `off` hay un sector de arranque FAT12 minimamente
    coherente: salto inicial tipico + BPB con bytes/sector=512 y un
    numero de sectores totales que no sea absurdo."""
    if datos[off:off+1] not in (b"\xeb", b"\xe9"):
        return False
    if len(datos) < off + 32:
        return False
    bytes_sector = struct.unpack_from("<H", datos, off + 0x0B)[0]
    total_sectores = struct.unpack_from("<H", datos, off + 0x13)[0]
    return bytes_sector == 512 and 0 < total_sectores <= 65535


def clasificar_bloque(bloque: bytes) -> str:
    if bloque == b"\xff" * len(bloque):
        return "FF"
    if bloque == b"\x00" * len(bloque):
        return "00"
    return "REAL"


def encontrar_zonas(datos: bytes) -> list:
    """Devuelve lista de (bloque_inicio, bloque_fin_inclusive, estado)."""
    n_bloques = len(datos) // TAM_BLOQUE
    zonas = []
    estado_actual = None
    inicio = 0
    for n in range(n_bloques):
        off = n * TAM_BLOQUE
        estado = clasificar_bloque(datos[off:off + TAM_BLOQUE])
        if estado != estado_actual:
            if estado_actual is not None:
                zonas.append((inicio, n - 1, estado_actual))
            inicio, estado_actual = n, estado
    zonas.append((inicio, n_bloques - 1, estado_actual))
    return zonas


def analizar_zona_real(datos: bytes, bloque_ini: int, bloque_fin: int) -> dict:
    """Determina si una zona 'REAL' es un disco (dsk2rom-style, nucleo de
    2 bloques + FAT12) o una ROM directa, y en este ultimo caso busca
    posibles sub-juegos por cambio de direccion de init."""
    off_ini = bloque_ini * TAM_BLOQUE
    off_fin = (bloque_fin + 1) * TAM_BLOQUE
    zona = datos[off_ini:off_fin]

    # ¿disco? el sector de arranque deberia estar justo al empezar el
    # banco 2 (tras 2 bloques de nucleo), igual que en los discos ya
    # confirmados de esta serie.
    if len(zona) > 3 * TAM_BLOQUE and _es_boot_sector_valido(zona, 2 * TAM_BLOQUE):
        return {"tipo": "disco", "contenido_dsk": zona[2 * TAM_BLOQUE:]}

    # si no, tratar como ROM directa y buscar sub-juegos por cambio de
    # cabecera AB + direccion de init, bloque a bloque
    subinicios = []
    direccion_actual = None
    for n in range(bloque_ini, bloque_fin + 1):
        off = n * TAM_BLOQUE
        if datos[off:off + 2] == b"\x41\x42":
            direccion = datos[off + 2:off + 4]
            if direccion != direccion_actual:
                subinicios.append(n)
                direccion_actual = direccion
    if not subinicios or subinicios[0] != bloque_ini:
        subinicios.insert(0, bloque_ini)

    subjuegos = []
    for i, sub_ini in enumerate(subinicios):
        sub_fin = subinicios[i + 1] - 1 if i + 1 < len(subinicios) else bloque_fin
        subjuegos.append((sub_ini, sub_fin))
    return {"tipo": "rom", "subjuegos": subjuegos}


def analizar(ruta_volcado: str, directorio_salida: str = "juegos_extraidos"):
    datos = Path(ruta_volcado).read_bytes()
    print(f"volcado: {ruta_volcado} ({len(datos)} bytes = {len(datos)//TAM_BLOQUE} bloques de 8K)")
    zonas = encontrar_zonas(datos)

    Path(directorio_salida).mkdir(parents=True, exist_ok=True)
    contador = 0
    print()
    print("=== mapa de zonas ===")
    for inicio, fin, estado in zonas:
        tam_kb = (fin - inicio + 1) * 8
        if estado != "REAL":
            print(f"  bloques {inicio:5}-{fin:5} ({tam_kb:6}KB): vacio ({estado})")
            continue

        info = analizar_zona_real(datos, inicio, fin)
        if info["tipo"] == "disco":
            contador += 1
            nombre = f"{directorio_salida}/{contador:02}_disco_bloque{inicio}_{tam_kb}KB.dsk"
            Path(nombre).write_bytes(info["contenido_dsk"])
            print(f"  bloques {inicio:5}-{fin:5} ({tam_kb:6}KB): DISCO -> {nombre}")
        else:
            print(f"  bloques {inicio:5}-{fin:5} ({tam_kb:6}KB): ROM directa, {len(info['subjuegos'])} sub-juego(s):")
            for sub_ini, sub_fin in info["subjuegos"]:
                contador += 1
                sub_tam_kb = (sub_fin - sub_ini + 1) * 8
                off_ini, off_fin = sub_ini * TAM_BLOQUE, (sub_fin + 1) * TAM_BLOQUE
                nombre = f"{directorio_salida}/{contador:02}_rom_bloque{sub_ini}_{sub_tam_kb}KB.rom"
                Path(nombre).write_bytes(datos[off_ini:off_fin])
                print(f"      bloques {sub_ini:5}-{sub_fin:5} ({sub_tam_kb:5}KB) -> {nombre}")

    print()
    print(f"total de ficheros extraidos: {contador}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("uso: python3 analizar_multicart_msx.py volcado.rom [directorio_salida]")
        sys.exit(1)
    analizar(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "juegos_extraidos")
