"""Parser del formato ImageDisk (.IMD) de Dave Dunfield.

Formato (dominio público, especificación en IMD.TXT de la distribución
oficial): cabecera de texto libre terminada en 0x1A, seguida de un
registro por cada pista leída:

  1 byte  modo (velocidad + FM/MFM): 0=500k FM 1=300k FM 2=250k FM
                                     3=500k MFM 4=300k MFM 5=250k MFM
  1 byte  cilindro
  1 byte  cabeza (bit7=hay mapa de cilindro por sector, bit6=hay mapa de
          cabeza por sector; bits 0-5 = número de cabeza real)
  1 byte  número de sectores en la pista
  1 byte  código de tamaño de sector (0=128 ... 6=8192; ver TAM_SECTOR)
  N bytes mapa de numeración física de sectores (1 por sector)
  N bytes mapa de cilindro por sector (si el bit7 de arriba está activo)
  N bytes mapa de cabeza por sector (si el bit6 de arriba está activo)
  por cada sector, un byte de tipo de registro + los datos:
    0 = sin datos (no se pudo leer)
    1 = datos normales sin comprimir (tantos bytes como el tamaño)
    2 = comprimidos: un único byte que se repite en todo el sector
    3/4 = igual que 1/2 pero con marca "deleted data"
    5-8 = igual que 1-4 pero el sector se leyó con error de CRC
"""
from __future__ import annotations

from dataclasses import dataclass, field

TAM_SECTOR = {0: 128, 1: 256, 2: 512, 3: 1024, 4: 2048, 5: 4096, 6: 8192}
NOMBRE_MODO = {
    0: "500 kbps FM", 1: "300 kbps FM", 2: "250 kbps FM",
    3: "500 kbps MFM", 4: "300 kbps MFM", 5: "250 kbps MFM",
}


@dataclass
class PistaIMD:
    modo: int
    cilindro: int
    cabeza: int
    n_sectores: int
    tam_sector: int
    mapa_sectores: list
    datos: dict  # numero_de_sector_fisico -> bytes (o None si no se pudo leer)
    tipos: dict  # numero_de_sector_fisico -> tipo de registro (para detectar errores/deleted)


@dataclass
class DiscoIMD:
    comentario: str
    pistas: list = field(default_factory=list)


def leer_imd(data: bytes) -> DiscoIMD:
    idx_fin_cabecera = data.index(0x1A)
    comentario = data[:idx_fin_cabecera].decode("ascii", errors="replace")
    pos = idx_fin_cabecera + 1

    pistas = []
    while pos < len(data):
        modo = data[pos]; pos += 1
        cilindro = data[pos]; pos += 1
        cabeza_byte = data[pos]; pos += 1
        n_sectores = data[pos]; pos += 1
        tam_codigo = data[pos]; pos += 1

        tiene_mapa_cyl = bool(cabeza_byte & 0x80)
        tiene_mapa_head = bool(cabeza_byte & 0x40)
        cabeza = cabeza_byte & 0x3F

        mapa_sectores = list(data[pos:pos + n_sectores]); pos += n_sectores
        if tiene_mapa_cyl:
            pos += n_sectores  # mapa de cilindro por sector: no lo necesitamos
        if tiene_mapa_head:
            pos += n_sectores  # mapa de cabeza por sector: tampoco

        if tam_codigo == 0xFF:
            raise ValueError("tamaños de sector variables (0xFF) no soportados")
        tam_sector = TAM_SECTOR[tam_codigo]

        datos = {}
        tipos = {}
        for num_sector in mapa_sectores:
            tipo = data[pos]; pos += 1
            tipos[num_sector] = tipo
            if tipo == 0:
                datos[num_sector] = None
            elif tipo in (2, 4, 6, 8):
                relleno = data[pos]; pos += 1
                datos[num_sector] = bytes([relleno]) * tam_sector
            else:
                datos[num_sector] = data[pos:pos + tam_sector]
                pos += tam_sector

        pistas.append(PistaIMD(modo, cilindro, cabeza, n_sectores, tam_sector,
                               mapa_sectores, datos, tipos))

    return DiscoIMD(comentario, pistas)


def a_imagen_logica(disco: DiscoIMD) -> bytes:
    """Reconstruye una imagen de disco lógica (sectores en orden físico
    1..N, cilindro por cilindro, cabeza por cabeza), asumiendo que todas
    las pistas comparten geometría. Lanza ValueError si hay huecos (algún
    sector no se pudo leer) o si la geometría no es uniforme.
    """
    piezas = []
    for pista in sorted(disco.pistas, key=lambda p: (p.cilindro, p.cabeza)):
        for num_sector in sorted(pista.mapa_sectores):
            contenido = pista.datos.get(num_sector)
            if contenido is None:
                raise ValueError(
                    f"cil={pista.cilindro} cab={pista.cabeza} sector={num_sector}: "
                    "no se pudo leer (hueco en la imagen)")
            piezas.append(contenido)
    return b"".join(piezas)
