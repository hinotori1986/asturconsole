"""Herramientas de conversión para ROMs de Sega Mega Drive / Genesis:
conversión entre el formato plano (.bin/.gen/.md) y el formato entrelazado
del Super Magic Drive (.smd).

El formato SMD: división en par/impar
-------------------------------------
Un archivo .smd consta de una cabecera de 512 bytes seguida de los datos
del ROM organizados en bloques de 16 KB. Dentro de cada bloque los bytes
NO van en orden: los primeros 8 KB son los bytes de una paridad y los
segundos 8 KB los de la otra.

Por qué: la BIOS del Super Magic Drive carga los juegos en modo de
compatibilidad con Master System. En ese modo quien accede a la memoria es
el Z80, un procesador de 8 BITS, mientras que la Mega Drive usa un 68000
de 16 bits. Al no poder leer palabras completas de 16 bits, los datos
tienen que llegar separados por paridad.

Conviene no confundirlo con el BYTE SWAP, que es otra cosa: aquel invierte
los dos bytes de cada palabra (una cuestión de endianness del volcado) y
este reagrupa los bytes por paridad en bloques de 16 KB.

Nota sobre las fuentes
-----------------------
Las descripciones publicadas se contradicen entre sí sobre QUÉ paridad va
primero: unas dicen "primero los pares, después los impares" y otras
justo lo contrario. El origen de la discrepancia es que "par/impar" se usa
a veces contando desde 0 y a veces desde 1.

Para no depender de esa ambigüedad, aquí se implementan las dos variantes
y se elige la correcta COMPROBANDO EL RESULTADO: un ROM de Mega Drive
válido tiene la cadena "SEGA" en el offset 0x100. `smd_to_bin()` prueba la
conversión y verifica ese marcador, de modo que el acierto no depende de
qué fuente tuviera razón. La variante que produce una cabecera válida es,
por definición, la correcta para ese archivo.
"""
from __future__ import annotations

from dataclasses import dataclass

import rom_formats as rf
import snes_crack as _crack  # motor genérico de patrones, reutilizado tal cual

SMD_HEADER_SIZE = 512
SMD_BLOCK_SIZE = 0x4000      # 16 KB
SMD_HALF_BLOCK = 0x2000      # 8 KB

GENESIS_SIGNATURE_OFFSET = 0x100
GENESIS_SIGNATURES = (b"SEGA", b"\x20SEG")  # "SEGA MEGA DRIVE", " SEGA GENESIS"...


@dataclass
class SmdHeaderInfo:
    present: bool
    size: int
    block_count: int | None = None
    notes: str = ""


def has_genesis_signature(data: bytes) -> bool:
    """Comprueba la firma SEGA en el offset 0x100 de un ROM plano."""
    if len(data) < GENESIS_SIGNATURE_OFFSET + 16:
        return False
    chunk = data[GENESIS_SIGNATURE_OFFSET:GENESIS_SIGNATURE_OFFSET + 16].upper()
    return b"SEGA" in chunk


def detect_smd_header(data: bytes) -> SmdHeaderInfo:
    """Detecta la cabecera de 512 bytes propia del Super Magic Drive.

    Señales usadas (las dos primeras son las documentadas para SMD):
      - byte 0: número de bloques de 16 KB
      - byte 1: 0x03 en los volcados habituales
      - bytes 8-9: 0xAA 0xBB (marca de identificación)
    """
    if len(data) < SMD_HEADER_SIZE + SMD_BLOCK_SIZE:
        return SmdHeaderInfo(False, 0)

    resto = len(data) - SMD_HEADER_SIZE
    tamano_encaja = resto % SMD_BLOCK_SIZE == 0

    h = data[:SMD_HEADER_SIZE]
    marca = h[8] == 0xAA and h[9] == 0xBB

    if marca:
        return SmdHeaderInfo(True, SMD_HEADER_SIZE, block_count=h[0],
                              notes="marca 0xAA 0xBB detectada en offsets 8-9")

    # Sin la marca, se recurre a una heurística de respaldo — pero antes
    # bastaba con "tamaño coherente con bloques de 16 KB más cabecera, y
    # sin firma SEGA en 0x100", y eso da demasiados falsos positivos: CUALQUIER
    # ROM sin firma SEGA visible (un homebrew, un prototipo, un dump con la
    # cabecera interna ligeramente distinta) cuyo tamaño coincidiera con la
    # cuenta se consideraba "ya tiene cabecera SMD" — el bug real que hacía
    # que "añadir cabecera y dividir" se saltase la parte de añadir cabecera
    # sin avisar. Ahora también se exige que el byte 0 (número de bloques
    # declarado) coincida EXACTAMENTE con el tamaño real del resto del
    # archivo, y que el byte 1 sea el valor documentado (0x03): una cabecera
    # real siempre cumple ambas cosas, mientras que datos de ROM genéricos
    # solo lo harían por pura coincidencia (con estas dos comprobaciones
    # juntas, la probabilidad baja a menos de 1 entre 65000).
    bloques_declarados = h[0]
    bloques_reales = resto // SMD_BLOCK_SIZE
    if (tamano_encaja and not has_genesis_signature(data)
            and bloques_declarados == (bloques_reales & 0xFF) and h[1] == 0x03):
        return SmdHeaderInfo(True, SMD_HEADER_SIZE,
                              notes="sin marca 0xAA 0xBB; deducida por tamaño y nº de bloques")

    return SmdHeaderInfo(False, 0)


def _deinterleave_block(block: bytes, first_half_is_odd: bool) -> bytes:
    """Desentrelaza un bloque de 16 KB."""
    mitad = len(block) // 2
    primera = block[:mitad]
    segunda = block[mitad:]
    out = bytearray(len(block))
    for i in range(mitad):
        if first_half_is_odd:
            out[i * 2 + 1] = primera[i]
            out[i * 2] = segunda[i]
        else:
            out[i * 2] = primera[i]
            out[i * 2 + 1] = segunda[i]
    return bytes(out)


def _interleave_block(block: bytes, first_half_is_odd: bool) -> bytes:
    """Entrelaza un bloque de 16 KB (operación inversa de la anterior)."""
    mitad = len(block) // 2
    primera = bytearray(mitad)
    segunda = bytearray(mitad)
    for i in range(mitad):
        if first_half_is_odd:
            primera[i] = block[i * 2 + 1]
            segunda[i] = block[i * 2]
        else:
            primera[i] = block[i * 2]
            segunda[i] = block[i * 2 + 1]
    return bytes(primera) + bytes(segunda)


def _convert(data: bytes, first_half_is_odd: bool, deinterleave: bool) -> bytes:
    out = bytearray()
    for off in range(0, len(data), SMD_BLOCK_SIZE):
        block = data[off:off + SMD_BLOCK_SIZE]
        if len(block) < SMD_BLOCK_SIZE:
            # Bloque final incompleto: se rellena para poder procesarlo y
            # después se recorta al tamaño original.
            block = block + bytes(SMD_BLOCK_SIZE - len(block))
        if deinterleave:
            out += _deinterleave_block(block, first_half_is_odd)
        else:
            out += _interleave_block(block, first_half_is_odd)
    return bytes(out[:len(data)])


def byteswap(data: bytes) -> bytes:
    """Intercambia los bytes de cada pareja (byte swap de 16 bits).

    Es una operación DISTINTA del entrelazado por bloques del formato SMD:
    aquí simplemente se invierte el orden de los dos bytes de cada palabra
    de 16 bits, en todo el archivo. Corresponde a la diferencia de
    "endianness" con la que algunos volcadores guardaron las ROMs.

    Se reconoce a simple vista en la cabecera: un volcado correcto muestra
    "SEGA GENESIS" en el offset 0x100, mientras que uno con los bytes
    intercambiados muestra "ESAGG NESESI".

    La operación es su propia inversa: aplicarla dos veces devuelve el
    archivo original.

    Verificado byte a byte contra un par de archivos reales del mismo juego
    (Aero the Acro-Bat 2, versión normal y versión "Swapped Bytes").
    """
    n = len(data) - (len(data) % 2)   # última pareja completa
    out = bytearray(data)
    out[0:n:2] = data[1:n:2]
    out[1:n:2] = data[0:n:2]
    return bytes(out)


def is_byteswapped(data: bytes) -> bool | None:
    """Indica si el ROM parece tener los bytes intercambiados.

    Devuelve True/False si puede determinarlo mirando la firma en 0x100, o
    None si no reconoce ninguna de las dos formas (archivo no estándar).
    """
    if has_genesis_signature(data):
        return False
    if has_genesis_signature(byteswap(data)):
        return True
    return None


def smd_to_bin(data: bytes) -> tuple[bytes, str]:
    """Convierte .smd (entrelazado) a formato plano .bin.

    Prueba las dos convenciones de entrelazado posibles y devuelve la que
    produce un ROM con firma SEGA válida en 0x100. Devuelve (datos, nota).
    """
    info = detect_smd_header(data)
    payload = data[info.size:] if info.present else data

    if len(payload) < SMD_BLOCK_SIZE:
        raise ValueError("el archivo es demasiado pequeño para ser un SMD válido")

    candidatos = []
    for first_half_is_odd in (True, False):
        resultado = _convert(payload, first_half_is_odd, deinterleave=True)
        candidatos.append((first_half_is_odd, resultado, has_genesis_signature(resultado)))

    validos = [c for c in candidatos if c[2]]
    if len(validos) == 1:
        orden, resultado, _ = validos[0]
        nota = ("primera mitad = bytes impares" if orden else "primera mitad = bytes pares")
        return resultado, f"Verificado: firma SEGA correcta en 0x100 ({nota})."

    if len(validos) == 2:
        # Improbable, pero si ambas dieran firma válida se usa la convención
        # más extendida en las implementaciones de emuladores.
        return validos[0][1], ("Ambas convenciones producen firma válida; se usó la más "
                                "habitual (primera mitad = bytes impares). Verifica el resultado.")

    # Ninguna produce firma válida: se devuelve la convención habitual, pero
    # avisando claramente en vez de dar por bueno un resultado sin verificar.
    return candidatos[0][1], (
        "AVISO: no se encontró la firma SEGA en 0x100 tras la conversión. El archivo "
        "puede no ser un SMD válido, estar dañado, o ser un volcado poco común. "
        "Se aplicó la convención habitual (primera mitad = bytes impares), pero el "
        "resultado NO está verificado."
    )


def bin_to_smd(data: bytes, add_header: bool = True, split: bool = False) -> bytes:
    """Convierte un ROM plano a formato .smd entrelazado.

    Usa la convención habitual (primera mitad de cada bloque = bytes
    impares), que es la que reconocen los volcados y herramientas más
    extendidas. Si `add_header`, antepone la cabecera de 512 bytes del
    Super Magic Drive.

    `split` activa el campo "split" de la cabecera (offset 2), presente en
    la propia especificación del formato (struct st_smd_header_t de
    uCON64) pero que uCON64 nunca llega a usar (queda siempre en 0). Es el
    candidato más razonable para el mecanismo de "hay más partes que
    cargar" que usa el propio firmware del Super Magic Drive, análogo al
    bit "Last File of the Game (Multi File Loading)" que la documentación
    del Super Wild Card describe para su propia cabecera, en la misma
    posición (offset 2).

    Esto es EXPERIMENTAL: no se ha podido confirmar contra hardware ni
    firmware real qué valor exacto espera el SMD en este campo, ni siquiera
    si lo usa igual que el SWC pese a compartir buena parte del firmware
    (la tabla de geometría de disco es idéntica byte a byte entre ambos, y
    los mensajes de error también). La hipótesis más simple, y la que se
    aplica aquí, es 0 = último archivo, 1 = hay una parte siguiente.
    Conviene verificarlo primero con un HxC antes que con un disquete físico.
    """
    if len(data) < SMD_BLOCK_SIZE:
        raise ValueError("el archivo es demasiado pequeño para convertirlo a SMD")

    if detect_smd_header(data).present:
        raise ValueError("el archivo ya parece estar en formato SMD")

    # Rellenar hasta múltiplo de 16 KB
    resto = len(data) % SMD_BLOCK_SIZE
    payload = data + bytes(SMD_BLOCK_SIZE - resto) if resto else data

    entrelazado = _convert(payload, first_half_is_odd=True, deinterleave=False)

    if not add_header:
        return entrelazado

    bloques = len(payload) // SMD_BLOCK_SIZE
    header = bytearray(SMD_HEADER_SIZE)
    header[0] = bloques & 0xFF      # nº de bloques de 16 KB       (size)
    header[1] = 0x03                 # valor habitual en volcados SMD (id0)
    header[2] = 0x01 if split else 0x00   # ver docstring: EXPERIMENTAL
    header[8] = 0xAA                 # marca de identificación     (id1)
    header[9] = 0xBB                 #                              (id2)
    header[10] = 0x06                # tipo de contenido: 6 = ROM, frente
    #                                  a 7 = SRAM en uCON64 (genesis_smd()
    #                                  / genesis_smds() de src/console/
    #                                  genesis.c). No he encontrado ningún
    #                                  sitio del propio uCON64 que LEA este
    #                                  campo de vuelta, pero se incluye por
    #                                  fidelidad byte a byte con el formato
    #                                  que genera la herramienta original,
    #                                  por si alguna otra utilidad de la
    #                                  escena sí lo comprueba.
    return bytes(header) + entrelazado


@dataclass
class SmdDiskPart:
    filename: str        # nombre del disco (para guardar el .dsk)
    inner_name: str      # nombre 8.3 del archivo dentro del disco
    image: bytes         # imagen de disco completa (formato SMD_DISK_FORMATS)


def split_smd_disks(data: bytes, base_name: str, fmt: str = "1600") -> list["SmdDiskPart"]:
    """Divide una ROM ya convertida a formato SMD (con cabecera) en tantos
    discos del Super Magic Drive como haga falta, activando el campo
    "split" de la cabecera en todas las partes menos la última.

    EXPERIMENTAL — igual que el parámetro `split` de bin_to_smd (ver su
    docstring): el mecanismo de continuación entre discos no se ha podido
    confirmar contra hardware ni firmware real. Se basa en la analogía con
    el Super Wild Card, cuyo mecanismo equivalente SÍ está verificado byte
    a byte con discos reales (ver split_swc_disks en snes_tools.py): ambos
    dispositivos comparten la misma tabla de geometría de disco y los
    mismos mensajes de error letra por letra, señal de que comparten
    buena parte del firmware, así que es razonable — pero no seguro — que
    también compartan este mecanismo.

    A diferencia del SWC (que reparte por páginas de 8 KB sueltas), aquí
    el reparto se hace en bloques de 16 KB completos: el formato SMD
    entrelaza el contenido en bloques de ese tamaño (ver bin_to_smd/
    _convert), así que cortar a mitad de un bloque rompería su
    entrelazado. Por eso cada parte contiene un número entero de bloques.
    """
    info = detect_smd_header(data)
    if not info.present:
        raise ValueError(
            "el archivo debe tener ya cabecera SMD antes de dividirlo "
            "(usa antes 'Añadir cabecera SMD')"
        )
    if fmt not in rf.SMD_DISK_FORMATS:
        raise ValueError(f"formato de disco desconocido: {fmt}")

    original_header = bytearray(data[:SMD_HEADER_SIZE])
    rom_data = data[SMD_HEADER_SIZE:]

    formato = rf.SMD_DISK_FORMATS[fmt]
    max_por_parte = formato.free_bytes
    max_por_parte -= max_por_parte % SMD_BLOCK_SIZE  # bloques de 16 KB completos
    if max_por_parte <= 0:
        raise ValueError(f"el disco de {fmt} KB no tiene espacio ni para un bloque de 16 KB")

    chunks = [rom_data[i:i + max_por_parte] for i in range(0, len(rom_data), max_por_parte)]
    if not chunks:
        chunks = [b""]

    short_base = "".join(c for c in base_name.upper() if c.isalnum())[:6] or "GAME"

    partes: list[SmdDiskPart] = []
    for i, chunk in enumerate(chunks):
        es_ultima = (i == len(chunks) - 1)
        cabecera = bytearray(original_header)
        cabecera[0] = (len(chunk) // SMD_BLOCK_SIZE) & 0xFF
        cabecera[2] = 0x00 if es_ultima else 0x01   # ver docstring: EXPERIMENTAL
        datos_parte = bytes(cabecera) + chunk
        inner_name = rf.rename_to_8_3(f"{short_base}.{i + 1}")
        imagen = rf.write_files_to_smd_disk(
            [(inner_name, datos_parte)], fmt=fmt, volume_label=short_base[:8])
        partes.append(SmdDiskPart(
            filename=f"{base_name}_disco{i + 1}_{fmt}kb.dsk",
            inner_name=inner_name,
            image=imagen,
        ))
    return partes


def genesis_checksum(datos: bytes) -> int:
    """Calcula el checksum de un ROM de Genesis (el cuerpo plano, SIN
    cabecera de copiador SMD si la tuviera).

    Algoritmo confirmado en el código fuente de uCON64
    (console/genesis.c, función genesis_chksum): suma de palabras de 16
    bits (big-endian) desde el offset 512 hasta el final del ROM — los
    primeros 512 bytes son los vectores de interrupción del 68000 y la
    cabecera interna del juego, y no entran en el cálculo.
    """
    total = 0
    for i in range(512, len(datos) - 1, 2):
        total += (datos[i] << 8) | datos[i + 1]
    return total & 0xFFFF


def fix_checksum(datos: bytes) -> tuple[bytes, int, bool]:
    """Recalcula y corrige el checksum de un ROM de Genesis — equivalente
    a la opción --chk de uCON64 para este sistema.

    `datos` debe ser el cuerpo plano del ROM, SIN cabecera de copiador
    SMD (si la tiene, hay que quitarla antes de llamar a esta función y
    volver a ponerla después, igual que se hace en SNES). El checksum se
    guarda en la cabecera interna del propio ROM, en el offset 0x18E-0x18F
    (2 bytes, big-endian) — 256 (donde empieza la cabecera interna) + 142.

    Devuelve (datos corregidos, checksum calculado, si YA era correcto
    antes de tocar nada).
    """
    if len(datos) < 0x190:
        raise ValueError("el archivo es demasiado pequeño para tener cabecera de Genesis")
    checksum_actual = (datos[0x18E] << 8) | datos[0x18F]
    checksum_calculado = genesis_checksum(datos)
    ya_era_correcto = (checksum_actual == checksum_calculado)
    resultado = bytearray(datos)
    resultado[0x18E] = (checksum_calculado >> 8) & 0xFF
    resultado[0x18F] = checksum_calculado & 0xFF
    return bytes(resultado), checksum_calculado, ya_era_correcto


def es_region_ntsc(region_field: str) -> bool:
    """Replica el criterio exacto de uCON64 (console/genesis.c) para
    decidir si un ROM es NTSC o PAL a partir del campo "region" de la
    cabecera interna (offset 0x1F0, 16 caracteres — normalmente letras
    de país concatenadas, como "JUE" o "U").

    Por defecto se asume PAL; si CUALQUIERA de los caracteres es 'J'
    (Japón), 'U' (EE.UU.) o '4' (Brasil NTSC), pasa a considerarse NTSC
    — NTSC tiene prioridad si hay cualquier indicio de esas regiones,
    igual que en el código original.
    """
    return any(c in region_field for c in ("J", "U", "4"))


# Patrones de "-f" de uCON64 para Genesis: código de protección regional
# (el juego comprueba si la consola es NTSC o PAL, y si no coincide con
# lo que espera, no arranca o se queda en pantalla negra/congelado).
# uCON64 NO trae ningún patrón incluido de fábrica para esto — a
# diferencia de SNES, donde sí vienen hardcodeados en el propio binario,
# los archivos que uCON64 trae para rellenar con patrones propios
# (genpal.txt, mdntsc.txt) están completamente vacíos, solo con un
# comentario explicando el formato. Estas listas quedan preparadas con
# la misma infraestructura de snes_crack (Patron/aplicar_patron) para
# añadir patrones verificados según se vayan confirmando con hardware
# real o con una lista de terceros de confianza.
PATRONES_REGION_NTSC: list = [
    # (buscar, reemplazar, offset, sets, comodín, escape, descripción)
]
PATRONES_REGION_PAL: list = [
]


def aplicar_fix_region(datos: bytes, es_ntsc: bool) -> tuple:
    """Aplica los patrones conocidos de eliminación de protección
    regional (-f de uCON64) sobre `datos` (trabaja sobre una copia; el
    original no se modifica). uCON64 decide automáticamente qué lista de
    patrones usar según lo que el propio ROM declare ser (NTSC o PAL) —
    se replica ese mismo criterio con `es_region_ntsc()`.

    Devuelve (datos_parcheados, lista_de_cambios), igual que
    snes_crack.aplicar_crack.
    """
    patrones_crudos = PATRONES_REGION_NTSC if es_ntsc else PATRONES_REGION_PAL
    buf = bytearray(datos)
    cambios = []
    for search, replace, offset, sets, wildcard, escape, desc in patrones_crudos:
        patron = _crack.Patron(search, replace, offset, sets, desc, wildcard, escape)
        n = _crack.aplicar_patron(buf, patron)
        if n:
            texto = desc or f"patrón sin descripción ({search.hex()})"
            cambios.append(f"{texto}  (×{n})" if n > 1 else texto)
    return bytes(buf), cambios
