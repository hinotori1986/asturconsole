"""Parsers para cabeceras de ROM/disco: MSX, Sega Mega Drive y Super Nintendo.

Este módulo es puro Python (sin dependencias de Qt) para poder probarlo o
reutilizarlo de forma independiente de la interfaz gráfica.
"""
from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def ascii_str(data: bytes, offset: int, length: int) -> str:
    chunk = data[offset:offset + length]
    out = []
    for b in chunk:
        out.append(chr(b) if 32 <= b < 127 else "·")
    return "".join(out).strip()


def fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


def hexn(n: int, width: int) -> str:
    return "0x" + format(n, "X").zfill(width)


# ---------------------------------------------------------------------------
# MSX
# ---------------------------------------------------------------------------

@dataclass
class MSXRomHeader:
    init: int
    statement: int
    device: int
    text: int


@dataclass
class MSXBinHeader:
    start: int
    end: int
    exec_addr: int


@dataclass
class DskEntry:
    name: str
    attr: int
    cluster: int
    size: int
    is_dir: bool
    children: list = field(default_factory=list)  # solo poblado si is_dir=True


@dataclass
class DskImage:
    bps: int
    spc: int
    reserved: int
    nfat: int
    root_entries: int
    total_sectors: int
    media: int
    spf: int
    fat_start: int
    root_start: int
    data_start: int
    entries: list
    raw: bytes


def parse_msx_rom_header(data: bytes) -> MSXRomHeader:
    init, statement, device, text = struct.unpack_from("<HHHH", data, 2)
    return MSXRomHeader(init, statement, device, text)


def parse_msx_bin_header(data: bytes) -> MSXBinHeader:
    start, end, exec_addr = struct.unpack_from("<HHH", data, 1)
    return MSXBinHeader(start, end, exec_addr)


def parse_dir_entries(raw: bytes) -> list[DskEntry]:
    """Interpreta un bloque de entradas de directorio FAT12 (32 bytes cada
    una). Sirve tanto para el directorio raíz como para el contenido
    reconstruido de un subdirectorio.
    """
    entries: list[DskEntry] = []
    for off in range(0, len(raw), 32):
        if off + 32 > len(raw):
            break
        b0 = raw[off]
        if b0 == 0x00:
            break
        if b0 == 0xE5:
            continue
        attr = raw[off + 11]
        if attr & 0x08:  # etiqueta de volumen
            continue
        if attr == 0x0F:  # entrada de nombre largo (no aplica a MSX-DOS clásico)
            continue
        fname = ascii_str(raw, off, 8)
        fext = ascii_str(raw, off + 8, 3)
        if not fname:
            continue
        if fname in (".", ".."):  # entradas administrativas: no se listan
            continue
        cluster = struct.unpack_from("<H", raw, off + 26)[0]
        size = struct.unpack_from("<I", raw, off + 28)[0]
        name = f"{fname}.{fext}" if fext else fname
        entries.append(DskEntry(name, attr, cluster, size, bool(attr & 0x10)))
    return entries


def parse_dsk(data: bytes) -> DskImage:
    if len(data) < 512:
        raise ValueError("archivo demasiado pequeño para ser un DSK")

    bps = struct.unpack_from("<H", data, 0x0B)[0] or 512
    spc = data[0x0D] or 2
    reserved = struct.unpack_from("<H", data, 0x0E)[0] or 1
    nfat = data[0x10] or 2
    root_entries = struct.unpack_from("<H", data, 0x11)[0] or 112
    total_sectors = struct.unpack_from("<H", data, 0x13)[0]
    media = data[0x15]
    spf = struct.unpack_from("<H", data, 0x16)[0] or 3

    fat_start = reserved
    root_start = reserved + nfat * spf
    root_sectors = -(-(root_entries * 32) // bps)  # división entera hacia arriba
    data_start = root_start + root_sectors

    dsk = DskImage(
        bps, spc, reserved, nfat, root_entries, total_sectors, media, spf,
        fat_start, root_start, data_start, [], data,
    )

    root_bytes = data[root_start * bps: root_start * bps + root_entries * 32]
    dsk.entries = parse_dir_entries(root_bytes)
    for e in dsk.entries:
        if e.is_dir:
            e.children = _parse_subdir(dsk, e.cluster)

    return dsk


def _fat_entry(fat_bytes: bytes, n: int) -> int:
    off = (n * 3) // 2
    if off + 1 >= len(fat_bytes):
        return 0xFFF
    if n % 2 == 0:
        return fat_bytes[off] | ((fat_bytes[off + 1] & 0x0F) << 8)
    return (fat_bytes[off] >> 4) | (fat_bytes[off + 1] << 4)


def reconstruct_dsk_clusters(dsk: DskImage, start_cluster: int) -> bytes:
    """Reconstruye los bytes de la cadena de clústeres a partir de un
    clúster inicial, SIN truncar por tamaño (útil para subdirectorios, que
    no tienen un campo de tamaño fiable)."""
    fat_bytes = dsk.raw[dsk.fat_start * dsk.bps: dsk.fat_start * dsk.bps + dsk.spf * dsk.bps]
    cluster_bytes = dsk.spc * dsk.bps
    chain: list[int] = []
    cur = start_cluster
    guard = 0
    while 2 <= cur < 0xFF0 and guard < 4096:
        chain.append(cur)
        cur = _fat_entry(fat_bytes, cur)
        guard += 1

    out = bytearray(len(chain) * cluster_bytes)
    p = 0
    for c in chain:
        sector = dsk.data_start + (c - 2) * dsk.spc
        start = sector * dsk.bps
        out[p:p + cluster_bytes] = dsk.raw[start:start + cluster_bytes]
        p += cluster_bytes
    return bytes(out)


def _parse_subdir(dsk: DskImage, start_cluster: int, _depth: int = 0) -> list[DskEntry]:
    if _depth > 16 or start_cluster < 2:  # cortafuegos ante discos corruptos/cíclicos
        return []
    raw = reconstruct_dsk_clusters(dsk, start_cluster)
    entries = parse_dir_entries(raw)
    for e in entries:
        if e.is_dir:
            e.children = _parse_subdir(dsk, e.cluster, _depth + 1)
    return entries


def reconstruct_dsk_file(dsk: DskImage, entry: DskEntry) -> bytes:
    raw = reconstruct_dsk_clusters(dsk, entry.cluster)
    size = entry.size or len(raw)
    return raw[:size]


def count_entries(entries: list[DskEntry]) -> tuple[int, int]:
    """Cuenta (nº de archivos, nº de subcarpetas) de forma recursiva."""
    files = dirs = 0
    for e in entries:
        if e.is_dir:
            dirs += 1
            f2, d2 = count_entries(e.children)
            files += f2
            dirs += d2
        else:
            files += 1
    return files, dirs


# ---------------------------------------------------------------------------
# Generación de imágenes de disquete FAT12 de 1.44 MB (un solo archivo)
# ---------------------------------------------------------------------------
# El sector de arranque de abajo se extrajo BYTE A BYTE de una imagen .img
# real de una Super Wild Card (creada con WinImage 6.50, texto identificativo
# incluido en el propio sector) que carga correctamente en hardware físico.
# Se reutiliza tal cual: el BPB (parámetros del sistema de archivos) es
# siempre el mismo para 1.44 MB y no depende del contenido — solo cambian la
# FAT, el directorio raíz y los datos, que se generan por archivo.

FAT12_1440_TOTAL_SECTORS = 2880
FAT12_1440_BPS = 512
FAT12_1440_SPC = 1
FAT12_1440_RESERVED = 1
FAT12_1440_NFAT = 2
FAT12_1440_ROOT_ENTRIES = 224
FAT12_1440_SPF = 9
FAT12_1440_MEDIA = 0xF0

_FAT12_1440_BOOT_SECTOR = bytes.fromhex(
    "EB589057494E494D414745000201010002E000400BF009001200020000000000"
    "000000000000290C685B2D202020202020202020202046415431322020200000"
    "0000000000000000000000000000000000000000000000000000FA33C08ED0BC"
    "007CB8B0078ED88EC0B900018BF1BF0003F3A5B8D007508ED88EC0B8800150CB"
    "FBBE1302E83A00B80102B90100BA800033DB8EC3BB007C0653CD13720A26813E"
    "FE7D55AA7501CBBED001E81400B401CD16740632E4CD16EBF432E4CD1633D2CD"
    "19FCAC0AC0740856B40ECD105EEBF3C343616E6E6F74206C6F61642066726F6D"
    "20686172646469736B2E0D0A496E736572742053797374656D6469736B20616E"
    "6420707265737320616E79206B65792E0D0A004469736B20666F726D61747465"
    "6420776974682057696E496D61676520362E35302028632920313939332D3230"
    "30342047696C6C657320566F6C6C616E740D0A73656520687474703A2F2F7777"
    "772E77696E696D6167652E636F6D0D0A426F6F74736563746F722066726F6D20"
    "432E482E20486F6368737461747465720D0A0D0A4E6F2053797374656D646973"
    "6B2E20426F6F74696E672066726F6D20686172646469736B2E0D0A0000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000055AA"
)
assert len(_FAT12_1440_BOOT_SECTOR) == 512

_FAT12_1440_ROOT_SECTORS = -(-(FAT12_1440_ROOT_ENTRIES * 32) // FAT12_1440_BPS)
_FAT12_1440_DATA_START = (FAT12_1440_RESERVED + FAT12_1440_NFAT * FAT12_1440_SPF
                           + _FAT12_1440_ROOT_SECTORS)
FAT12_1440_MAX_FILE_BYTES = (FAT12_1440_TOTAL_SECTORS - _FAT12_1440_DATA_START) * FAT12_1440_BPS


def _set_fat12_entry(fat: bytearray, n: int, value: int) -> None:
    off = (n * 3) // 2
    if n % 2 == 0:
        fat[off] = value & 0xFF
        fat[off + 1] = (fat[off + 1] & 0xF0) | ((value >> 8) & 0x0F)
    else:
        fat[off] = (fat[off] & 0x0F) | ((value & 0x0F) << 4)
        fat[off + 1] = (value >> 4) & 0xFF


def _dos_83_name(filename: str) -> tuple[bytes, bytes]:
    if "." in filename:
        name, ext = filename.rsplit(".", 1)
    else:
        name, ext = filename, ""
    name_b = name.upper()[:8].ljust(8).encode("ascii", "replace")
    ext_b = ext.upper()[:3].ljust(3).encode("ascii", "replace")
    return name_b, ext_b


# ---------------------------------------------------------------------------
# Creación de disquetes MSX vacíos (720 KB, FAT12)
# ---------------------------------------------------------------------------
# Formato estándar de disco MSX de doble cara y doble densidad: 80 pistas,
# 9 sectores por pista, 2 caras = 1440 sectores de 512 bytes = 720 KB.
# Estos son los parámetros que espera MSX-DOS y que usan las imágenes .dsk
# habituales.

@dataclass(frozen=True)
class MsxDiskFormat:
    key: str
    label: str
    bps: int
    spc: int
    reserved: int
    nfat: int
    root_entries: int
    total_sectors: int
    media: int
    spf: int
    spt: int
    heads: int

    @property
    def size(self) -> int:
        return self.total_sectors * self.bps

    @property
    def data_start_sector(self) -> int:
        root_sectors = -(-(self.root_entries * 32) // self.bps)
        return self.reserved + self.nfat * self.spf + root_sectors

    @property
    def free_bytes(self) -> int:
        return (self.total_sectors - self.data_start_sector) * self.bps


# Formatos estándar de disquete MSX.
#
#  - 720 KB: doble cara / doble densidad, 80 pistas x 9 sectores x 2 caras.
#    Es el formato más extendido en MSX2.
#  - 360 KB: UNA sola cara, 80 pistas x 9 sectores. Lo usan las unidades de
#    cara simple de varios modelos, como el Philips VG-8235.
#
# La diferencia relevante, más allá del número de caras y sectores totales,
# es el descriptor de medio (0xF9 para doble cara, 0xF8 para cara simple) y
# el número de sectores por FAT.

MSX_DISK_FORMATS: dict[str, MsxDiskFormat] = {
    "720": MsxDiskFormat("720", '720 KB (doble cara, 3.5" DS/DD)',
                          bps=512, spc=2, reserved=1, nfat=2, root_entries=112,
                          total_sectors=1440, media=0xF9, spf=3, spt=9, heads=2),
    "360": MsxDiskFormat("360", '360 KB (cara simple — p. ej. Philips VG-8235)',
                          bps=512, spc=2, reserved=1, nfat=2, root_entries=112,
                          total_sectors=720, media=0xF8, spf=2, spt=9, heads=1),
}

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Formatos de disco del Super Magic Drive (copiador de Mega Drive/Genesis)
# ---------------------------------------------------------------------------
# Geometría extraída directamente del firmware del propio copiador: se
# localizó y verificó una tabla de parámetros de disco compacta (equivalente
# a un BPB de FAT12) presente, byte a byte, en DOS versiones distintas de
# la BIOS (v3.3 y v4.1A) — la coincidencia exacta entre dos firmwares
# independientes, sumada a que los cuatro tamaños resultan en un número
# entero exacto de sectores por pista (20, 18, 10 y 9, asumiendo 80 pistas
# y 2 caras, la geometría física estándar de un disquete de 3.5"), da alta
# confianza en que la interpretación es correcta.
#
# El formato de 1600 KB es el que hace único al Super Magic Drive frente a
# un disquete estándar: es un disco de alta densidad "superformateado" a
# 20 sectores por pista en vez de los 18 habituales — el mismo principio
# que ya se usa con COPIA720 para MSX, pero en la dirección de más
# capacidad en vez de menos.
#
# spc=1, nfat=2: confirmado contra dos discos de 1600 KB REALES, grabados
# por un Super Wild Card físico ("Momotaro", 2 partes) — antes se asumía
# spc=2, nfat=1 (una única FAT y clústeres de 2 sectores), una estimación
# razonable pero nunca verificada, y resultó ser incorrecta: el SWC
# físico usa exactamente el estándar FAT12 más común (1 sector/clúster,
# dos copias redundantes de la FAT), no una variante propia. La discre-
# pancia probablemente pasaba desapercibida en discos de 1440/720 KB
# (formatos estándar, donde el lector FAT12 del propio SWC es más
# tolerante y sí respeta lo que declara el BPB del disco), pero rompía la
# lectura del directorio en el formato "superformateado" propio de 1600
# KB, donde el firmware muy probablemente asume ciegamente su propia
# geometría real en vez de leerla del disco.
SMD_DISK_FORMATS: dict[str, MsxDiskFormat] = {
    "1600": MsxDiskFormat("1600", "1600 KB (formato especial del Super Magic Drive)",
                          bps=512, spc=1, reserved=1, nfat=2, root_entries=224,
                          total_sectors=3200, media=0xF0, spf=10, spt=20, heads=2),
    "1440": MsxDiskFormat("1440", "1440 KB (alta densidad estándar)",
                          bps=512, spc=1, reserved=1, nfat=2, root_entries=224,
                          total_sectors=2880, media=0xF0, spf=9, spt=18, heads=2),
    "800": MsxDiskFormat("800", "800 KB (doble densidad superformateada)",
                         bps=512, spc=1, reserved=2, nfat=2, root_entries=112,
                         total_sectors=1600, media=0xF9, spf=3, spt=10, heads=2),
    "720": MsxDiskFormat("720", "720 KB (doble densidad estándar)",
                         bps=512, spc=1, reserved=2, nfat=2, root_entries=112,
                         total_sectors=1440, media=0xF9, spf=3, spt=9, heads=2),
}

# Constantes del formato de 720 KB, mantenidas por compatibilidad
_F720 = MSX_DISK_FORMATS["720"]
MSX_DSK_BPS = _F720.bps
MSX_DSK_SPC = _F720.spc
MSX_DSK_RESERVED = _F720.reserved
MSX_DSK_NFAT = _F720.nfat
MSX_DSK_ROOT_ENTRIES = _F720.root_entries
MSX_DSK_TOTAL_SECTORS = _F720.total_sectors
MSX_DSK_MEDIA = _F720.media
MSX_DSK_SPF = _F720.spf
MSX_DSK_SPT = _F720.spt
MSX_DSK_HEADS = _F720.heads
MSX_DSK_SIZE = _F720.size


# ---------------------------------------------------------------------------
# Imágenes de cara simple volcadas con COPIA720
# ---------------------------------------------------------------------------
# COPIA720 (F. J. Martos, 1995) vuelca disquetes pista a pista con la BIOS.
# Con la opción /1, para discos de CARA SIMPLE, sigue recorriendo las dos
# caras y rellena la cara inexistente con 0xE5 (el byte de relleno de un
# disco formateado). El resultado es que un disco de 360 KB acaba en un
# archivo de 737.280 bytes, del que la mitad es relleno.
#
# Aquí se detecta ese caso y se recorta a los 368.640 bytes reales, que es
# el formato que esperan emuladores y el resto de la aplicación.

COPIA720_TRACK_BYTES = 9 * 512          # 9 sectores por pista
COPIA720_TRACKS = 160                   # 80 cilindros x 2 caras
COPIA720_SIZE = COPIA720_TRACK_BYTES * COPIA720_TRACKS   # 737280
FILLER_BYTE = 0xE5


def detect_copia720_single_sided(data: bytes, tolerance: float = 0.98) -> bool:
    """¿Es una imagen de 720 KB cuya segunda cara es solo relleno?

    Se comprueba que las pistas impares (cara 1) estén formadas casi por
    completo por el byte de relleno 0xE5. Se admite un pequeño margen por si
    algún sector conserva restos de un uso anterior del disquete.
    """
    if len(data) != COPIA720_SIZE:
        return False

    total = 0
    relleno = 0
    for pista in range(1, COPIA720_TRACKS, 2):      # caras impares
        ini = pista * COPIA720_TRACK_BYTES
        trozo = data[ini:ini + COPIA720_TRACK_BYTES]
        total += len(trozo)
        relleno += trozo.count(FILLER_BYTE)
    if total == 0:
        return False
    return (relleno / total) >= tolerance


def copia720_to_single_sided(data: bytes) -> bytes:
    """Recorta una imagen de COPIA720 /1 a su tamaño real de 360 KB,
    quedándose solo con las pistas de la cara 0."""
    if len(data) != COPIA720_SIZE:
        raise ValueError(
            f"no tiene el tamaño de una imagen COPIA720 de 720 KB "
            f"({len(data)} bytes en vez de {COPIA720_SIZE})"
        )
    salida = bytearray()
    for pista in range(0, COPIA720_TRACKS, 2):      # solo cara 0
        ini = pista * COPIA720_TRACK_BYTES
        salida += data[ini:ini + COPIA720_TRACK_BYTES]
    return bytes(salida)


def single_sided_to_copia720(data: bytes) -> bytes:
    """Operación inversa: expande una imagen real de 360 KB al formato de
    720 KB con la cara 1 rellena de 0xE5, que es lo que COPIA720 espera al
    grabar de vuelta con la opción /1."""
    esperado = COPIA720_TRACK_BYTES * (COPIA720_TRACKS // 2)
    if len(data) != esperado:
        raise ValueError(
            f"no tiene el tamaño de un disco de cara simple "
            f"({len(data)} bytes en vez de {esperado})"
        )
    relleno = bytes([FILLER_BYTE]) * COPIA720_TRACK_BYTES
    salida = bytearray()
    for i in range(COPIA720_TRACKS // 2):
        ini = i * COPIA720_TRACK_BYTES
        salida += data[ini:ini + COPIA720_TRACK_BYTES]   # cara 0
        salida += relleno                                 # cara 1 simulada
    return bytes(salida)


# ---------------------------------------------------------------------------
# Validación del sistema de archivos de una imagen de disco
# ---------------------------------------------------------------------------
# No todos los .dsk contienen un sistema de archivos MSX-DOS. Muchos juegos
# de la época usan CARGADORES PROPIOS: el sector de arranque es código puro y
# el juego lee sus datos por sectores, sin FAT ni directorio. En esas
# imágenes no hay archivos que extraer, y conviene decirlo claramente en vez
# de crear una carpeta vacía.

def _texto_legible(datos: bytes, minimo: int = 5) -> str:
    """Cadena de texto más larga dentro de un bloque de bytes.

    Sirve para reconocer el disco: los cargadores propios suelen llevar el
    nombre del juego en el sector de arranque.
    """
    mejor, actual = "", ""
    for b in datos:
        if 32 <= b < 127:
            actual += chr(b)
        else:
            if len(actual) > len(mejor):
                mejor = actual
            actual = ""
    if len(actual) > len(mejor):
        mejor = actual
    mejor = mejor.strip()
    return mejor if len(mejor) >= minimo else ""


def validate_dsk(data: bytes) -> tuple[bool, str]:
    """Comprueba si la imagen tiene un sistema de archivos legible.

    Devuelve (es_válido, motivo). El motivo explica en lenguaje llano por qué
    no se puede leer, para poder mostrárselo al usuario.
    """
    if len(data) < 1024:
        return False, "el archivo es demasiado pequeño para ser una imagen de disco"

    primer_byte = data[0]
    if primer_byte not in (0xEB, 0xE9):
        return False, (
            f"el sector de arranque no empieza por EB ni E9 (empieza por "
            f"{primer_byte:02X}): no parece una imagen de disco MSX"
        )

    try:
        bps = struct.unpack_from("<H", data, 0x0B)[0]
        spc = data[0x0D]
        reserved = struct.unpack_from("<H", data, 0x0E)[0]
        nfat = data[0x10]
        root_entries = struct.unpack_from("<H", data, 0x11)[0]
        total_sectors = struct.unpack_from("<H", data, 0x13)[0]
        spf = struct.unpack_from("<H", data, 0x16)[0]
    except struct.error:
        return False, "no se pudo leer la tabla de parámetros del disco (BPB)"

    # "Bytes por sector = 0" es imposible en cualquier disco real: significa
    # que ahí no hay una tabla de parámetros, sino código. Es la firma de los
    # discos con CARGADOR PROPIO, muy comunes en juegos japoneses: el sector 0
    # arranca el juego, que luego lee sus datos por sectores sin usar FAT.
    if bps == 0 or bps not in (128, 256, 512, 1024):
        etiqueta = _texto_legible(data[:64])
        detalle = f" (en el sector de arranque se lee «{etiqueta}»)" if etiqueta else ""
        return False, (
            "este disco NO tiene sistema de archivos: su sector de arranque es "
            f"código de un cargador propio del juego{detalle}.\n\n"
            "Los juegos así leen sus datos directamente por sectores, sin FAT ni "
            "directorio, así que no hay archivos sueltos que extraer. La imagen es "
            "correcta y funcionará en el MSX o en un emulador; simplemente no se "
            "puede abrir su contenido como si fuera un disco de MSX-DOS."
        )

    problemas = []
    if bps not in (128, 256, 512, 1024):
        problemas.append(f"bytes por sector no válido ({bps})")
    if spc == 0 or spc > 64:
        problemas.append(f"sectores por clúster no válido ({spc})")
    if reserved == 0:
        problemas.append("sectores reservados = 0")
    if nfat == 0 or nfat > 4:
        problemas.append(f"número de copias de FAT no válido ({nfat})")
    if root_entries == 0 or root_entries > 1024:
        problemas.append(f"entradas de directorio raíz no válidas ({root_entries})")

    # Coherencia con el tamaño real del archivo
    if bps and total_sectors:
        declarado = bps * total_sectors
        if declarado > len(data) * 1.02:
            problemas.append(
                f"declara {total_sectors} sectores ({fmt_bytes(declarado)}) pero el "
                f"archivo solo tiene {fmt_bytes(len(data))}")
    if spf and bps and spf * bps > len(data):
        problemas.append(f"la FAT declarada ({spf} sectores) no cabe en el archivo")

    if problemas:
        return False, (
            "la tabla de parámetros del disco (BPB) contiene valores imposibles: "
            + "; ".join(problemas)
            + ". Es habitual en discos con protección o con cargador propio, que "
              "no usan un sistema de archivos estándar"
        )

    return True, ""


def make_blank_msx_dsk(volume_label: str = "", fmt: str | MsxDiskFormat = "720") -> bytes:
    """Crea la imagen de un disquete MSX recién formateado y vacío.

    `fmt` puede ser "720" (doble cara) o "360" (cara simple, para unidades
    como la del Philips VG-8235), o un MsxDiskFormat concreto.

    Genera el sector de arranque con el BPB correcto, las dos copias de la
    FAT inicializadas (con el descriptor de medio en la primera entrada) y
    el directorio raíz y el área de datos a cero, tal y como quedaría un
    disco tras un FORMAT en MSX-DOS.
    """
    f = fmt if isinstance(fmt, MsxDiskFormat) else MSX_DISK_FORMATS[str(fmt)]
    img = bytearray(f.size)

    # --- sector de arranque (BPB) ---
    img[0:3] = bytes([0xEB, 0xFE, 0x90])           # salto corto (bucle) + NOP
    img[3:11] = b"ROMINSPT"                        # identificador del creador (OEM)
    struct.pack_into("<H", img, 0x0B, f.bps)
    img[0x0D] = f.spc
    struct.pack_into("<H", img, 0x0E, f.reserved)
    img[0x10] = f.nfat
    struct.pack_into("<H", img, 0x11, f.root_entries)
    struct.pack_into("<H", img, 0x13, f.total_sectors)
    img[0x15] = f.media
    struct.pack_into("<H", img, 0x16, f.spf)
    struct.pack_into("<H", img, 0x18, f.spt)
    struct.pack_into("<H", img, 0x1A, f.heads)
    struct.pack_into("<I", img, 0x1C, 0)           # sectores ocultos

    # --- FAT: primera entrada = descriptor de medio, segunda = fin de cadena ---
    # Se escriben f.nfat copias, no siempre 2: con una sola copia (como los
    # formatos del Super Magic Drive), asumir 2 fijas sobreescribía el
    # directorio raíz con una "segunda copia" que en realidad no existe en
    # ese formato.
    fat = bytearray(f.spf * f.bps)
    fat[0] = f.media
    fat[1] = 0xFF
    fat[2] = 0xFF
    for copia in range(f.nfat):
        fat_off = (f.reserved + copia * f.spf) * f.bps
        img[fat_off:fat_off + len(fat)] = fat

    # --- directorio raíz: vacío, salvo etiqueta de volumen si se pide ---
    if volume_label:
        root_start = (f.reserved + f.nfat * f.spf) * f.bps
        entrada = bytearray(32)
        etiqueta = volume_label.upper()[:11].ljust(11)
        entrada[0:11] = etiqueta.encode("ascii", "replace")
        entrada[11] = 0x08                          # atributo: etiqueta de volumen
        img[root_start:root_start + 32] = entrada

    return bytes(img)


class DiskFullError(ValueError):
    """El conjunto de archivos no cabe en el disquete elegido."""


def msx_disk_capacity(fmt) -> tuple[int, int]:
    """Devuelve (bytes libres, entradas de directorio disponibles)."""
    f = fmt if isinstance(fmt, MsxDiskFormat) else MSX_DISK_FORMATS[str(fmt)]
    return f.free_bytes, f.root_entries


def plan_msx_disk(files: list[tuple[str, bytes]], fmt="720",
                  volume_label: str = "") -> tuple[int, int, int]:
    """Calcula el espacio que ocuparían `files` en un disquete del formato
    dado. Devuelve (bytes usados, bytes libres del disco, nº de entradas).

    Importante: el espacio se consume por clústeres completos, así que un
    archivo de 1 byte ocupa un clúster entero (1 KB en formato MSX). Por eso
    no basta con sumar los tamaños de los archivos.
    """
    f = fmt if isinstance(fmt, MsxDiskFormat) else MSX_DISK_FORMATS[str(fmt)]
    cluster_bytes = f.spc * f.bps
    usados = 0
    for _nombre, datos in files:
        clusters = max(1, -(-len(datos) // cluster_bytes))
        usados += clusters * cluster_bytes
    entradas = len(files) + (1 if volume_label else 0)
    return usados, f.free_bytes, entradas


def write_files_to_msx_dsk(files: list[tuple[str, bytes]], fmt="720",
                            volume_label: str = "",
                            boot_sector: bytes | None = None,
                            system_attr_for: tuple[str, ...] = ()) -> bytes:
    """Crea una imagen de disquete MSX con los archivos indicados dentro.

    `files` es una lista de (nombre, datos) en el orden en que deben quedar
    en el directorio. El orden importa para los discos de sistema: MSX-DOS
    espera encontrar sus archivos al principio del directorio.

    `boot_sector`, si se indica, sustituye el sector 0 generado (manteniendo
    el BPB propio del formato elegido, que se reescribe encima). Es lo que
    permite crear discos arrancables reutilizando el código de arranque de
    un disco de sistema que ya se posea.

    `system_attr_for` son los nombres a los que marcar con los atributos de
    sistema y oculto, como corresponde a los archivos del sistema operativo.
    """
    f = fmt if isinstance(fmt, MsxDiskFormat) else MSX_DISK_FORMATS[str(fmt)]

    usados, libres, entradas = plan_msx_disk(files, f, volume_label)
    if usados > libres:
        raise DiskFullError(
            f"no caben: se necesitan {fmt_bytes(usados)} y el disco de "
            f"{f.label} solo tiene {fmt_bytes(libres)} libres"
        )
    if entradas > f.root_entries:
        raise DiskFullError(
            f"demasiados archivos: {entradas} entradas para un máximo de {f.root_entries}"
        )

    img = bytearray(make_blank_msx_dsk(volume_label, f))

    if boot_sector:
        # Se conserva el código de arranque ajeno, pero el BPB se reescribe
        # con los parámetros del formato elegido: si no, un sector de
        # arranque de 720 KB dejaría inservible un disco de 360 KB.
        nuevo = bytearray(boot_sector[:f.bps].ljust(f.bps, b"\x00"))
        nuevo[0x0B:0x0B + 2] = struct.pack("<H", f.bps)
        nuevo[0x0D] = f.spc
        struct.pack_into("<H", nuevo, 0x0E, f.reserved)
        nuevo[0x10] = f.nfat
        struct.pack_into("<H", nuevo, 0x11, f.root_entries)
        struct.pack_into("<H", nuevo, 0x13, f.total_sectors)
        nuevo[0x15] = f.media
        struct.pack_into("<H", nuevo, 0x16, f.spf)
        struct.pack_into("<H", nuevo, 0x18, f.spt)
        struct.pack_into("<H", nuevo, 0x1A, f.heads)
        img[0:f.bps] = nuevo

    fat = bytearray(f.spf * f.bps)
    fat[0] = f.media
    fat[1] = 0xFF
    fat[2] = 0xFF

    root_start = (f.reserved + f.nfat * f.spf) * f.bps
    root_sectors = -(-(f.root_entries * 32) // f.bps)
    data_start = (f.reserved + f.nfat * f.spf + root_sectors) * f.bps
    cluster_bytes = f.spc * f.bps

    # Si hay etiqueta de volumen, ya ocupa la entrada 0
    entrada_idx = 1 if volume_label else 0
    cluster = 2

    for nombre, datos in files:
        n_clusters = max(1, -(-len(datos) // cluster_bytes))
        primer_cluster = cluster

        # Escribir los datos y encadenar los clústeres en la FAT
        for i in range(n_clusters):
            off_datos = data_start + (cluster - 2) * cluster_bytes
            trozo = datos[i * cluster_bytes:(i + 1) * cluster_bytes]
            img[off_datos:off_datos + len(trozo)] = trozo
            siguiente = 0xFFF if i == n_clusters - 1 else cluster + 1
            _set_fat12_entry(fat, cluster, siguiente)
            cluster += 1

        # Entrada de directorio
        name83, ext83 = _dos_83_name(nombre)
        entrada = bytearray(32)
        entrada[0:8] = name83
        entrada[8:11] = ext83
        entrada[11] = 0x07 if nombre.upper() in system_attr_for else 0x00
        struct.pack_into("<H", entrada, 26, primer_cluster)
        struct.pack_into("<I", entrada, 28, len(datos))
        off_entrada = root_start + entrada_idx * 32
        img[off_entrada:off_entrada + 32] = entrada
        entrada_idx += 1

    # Igual que en make_blank_msx_dsk: se escriben f.nfat copias, no 2 fijas.
    for copia in range(f.nfat):
        fat_off = (f.reserved + copia * f.spf) * f.bps
        img[fat_off:fat_off + len(fat)] = fat

    return bytes(img)


def make_blank_smd_disk(volume_label: str = "", fmt: str = "1600") -> bytes:
    """Crea un disquete vacío recién formateado, con la geometría del Super
    Magic Drive. `fmt` es una clave de SMD_DISK_FORMATS ("1600", "1440",
    "800" o "720"). Reutiliza make_blank_msx_dsk: la estructura FAT12 es la
    misma con independencia del sistema, solo cambia la geometría (que
    MsxDiskFormat ya describe por completo).
    """
    return make_blank_msx_dsk(volume_label, SMD_DISK_FORMATS[str(fmt)])


def write_files_to_smd_disk(files: list[tuple[str, bytes]], fmt: str = "1600",
                            volume_label: str = "") -> bytes:
    """Crea un disquete con la geometría del Super Magic Drive y estos
    archivos dentro. Ver make_blank_smd_disk: misma FAT12, solo cambia la
    geometría según `fmt`.
    """
    return write_files_to_msx_dsk(files, SMD_DISK_FORMATS[str(fmt)], volume_label)


def make_fat12_floppy_image(filename: str, file_data: bytes) -> bytes:
    """Genera una imagen de disquete de 1.44 MB con sistema de archivos
    FAT12 conteniendo un único archivo `file_data` con nombre `filename`
    (se convierte a 8.3 automáticamente), replicando el formato exacto
    (WinImage 6.50) de las imágenes reales que usa la Super Wild Card.
    """
    if len(file_data) > FAT12_1440_MAX_FILE_BYTES:
        raise ValueError(
            f"el archivo ({len(file_data)} bytes) no cabe en un disquete de 1.44 MB "
            f"(máximo utilizable: {FAT12_1440_MAX_FILE_BYTES} bytes)"
        )

    num_clusters = max(1, -(-len(file_data) // FAT12_1440_BPS))  # ceil, mínimo 1

    fat = bytearray(FAT12_1440_SPF * FAT12_1440_BPS)
    _set_fat12_entry(fat, 0, 0xF00 | FAT12_1440_MEDIA)
    _set_fat12_entry(fat, 1, 0xFFF)
    for i in range(num_clusters):
        cluster = 2 + i
        _set_fat12_entry(fat, cluster, 0xFFF if i == num_clusters - 1 else cluster + 1)

    name83, ext83 = _dos_83_name(filename)
    entry = bytearray(32)
    entry[0:8] = name83
    entry[8:11] = ext83
    entry[11] = 0x00  # sin atributos, igual que en las imágenes SWC reales de referencia
    struct.pack_into("<H", entry, 26, 2)
    struct.pack_into("<I", entry, 28, len(file_data))
    root = bytearray(_FAT12_1440_ROOT_SECTORS * FAT12_1440_BPS)
    root[0:32] = entry

    data_area = bytearray(num_clusters * FAT12_1440_BPS)
    data_area[0:len(file_data)] = file_data

    image = bytearray(FAT12_1440_TOTAL_SECTORS * FAT12_1440_BPS)
    image[0:512] = _FAT12_1440_BOOT_SECTOR
    fat_off1 = FAT12_1440_RESERVED * FAT12_1440_BPS
    fat_off2 = fat_off1 + FAT12_1440_SPF * FAT12_1440_BPS
    image[fat_off1:fat_off1 + len(fat)] = fat
    image[fat_off2:fat_off2 + len(fat)] = fat
    root_off = fat_off2 + FAT12_1440_SPF * FAT12_1440_BPS
    image[root_off:root_off + len(root)] = root
    data_off = _FAT12_1440_DATA_START * FAT12_1440_BPS
    image[data_off:data_off + len(data_area)] = data_area

    return bytes(image)


# ---------------------------------------------------------------------------
# Detección de mapper MSX (MegaROM)
# ---------------------------------------------------------------------------
# Fuentes: MSX Wiki "MegaROM Mappers" (msx.org/wiki/MegaROM_Mappers),
# bifi.msxnet.org/msxnet/tech/megaroms (documentación técnica clásica y
# ampliamente contrastada de la escena MSX) y, para NEO-8/NEO-16, la
# especificación oficial de MSXgl (aoineko.org/msxgl, "NEO mapper").
#
# Los mappers clásicos (Konami, Konami SCC, ASCII8, ASCII16) NO se
# autodeclaran en ningún campo del ROM: la única forma de reconocerlos sin
# una base de datos de juegos conocidos es buscar en el código el patrón de
# escrituras a las direcciones de conmutación de banco propias de cada uno
# (instrucción Z80 "LD (nn),A", opcode 0x32). Es una heurística -igual que
# hacen emuladores como blueMSX u openMSX cuando la ROM no está en su base
# de datos-, no una certeza absoluta.
#
# NEO-8/NEO-16 sí llevan una firma de texto explícita y documentada
# ("ROM_NEO8"/"ROM_NE16" en el offset 0x10), así que esos dos se detectan
# de forma determinista, no heurística.

NEO8_SIGNATURE = b"ROM_NEO8"
NEO16_SIGNATURE = b"ROM_NE16"
_MAPPER_HEURISTIC_SCAN_CAP = 1_048_576  # 1 MB: de sobra para el código de arranque/bank-switch


@dataclass
class MapperGuess:
    name: str
    confidence: str   # "alta" | "media" | "baja"
    detail: str
    sram: bool = False


def guess_msx_mapper(data: bytes) -> MapperGuess:
    if len(data) <= 0x8000:
        return MapperGuess(
            "Sin mapper (ROM simple ≤32 KB)", "alta",
            "Tamaño típico de ROM sin mecanismo de bancos.",
        )

    sig = data[16:24]
    if sig == NEO8_SIGNATURE:
        return MapperGuess("NEO-8", "alta", 'Firma "ROM_NEO8" detectada en offset 0x10 (determinista).')
    if sig == NEO16_SIGNATURE:
        return MapperGuess("NEO-16", "alta", 'Firma "ROM_NE16" detectada en offset 0x10 (determinista).')

    scan = data[:_MAPPER_HEURISTIC_SCAN_CAP]
    counts: dict[int, int] = {}
    for i in range(len(scan) - 2):
        if scan[i] == 0x32:  # opcode Z80 "LD (nn),A"
            addr = scan[i + 1] | (scan[i + 2] << 8)
            counts[addr] = counts.get(addr, 0) + 1

    def c(addr: int) -> int:
        return counts.get(addr, 0)

    scores = {
        "Konami (sin SCC)": c(0x8000) + c(0xA000) + 0.3 * c(0x6000),
        "Konami SCC": c(0x5000) + c(0x9000) + c(0xB000) + 0.3 * c(0x7000),
        "ASCII8": c(0x6800) + c(0x7800) + 0.3 * c(0x6000) + 0.3 * c(0x7000),
        "ASCII16": 0.5 * c(0x6000) + 0.5 * c(0x7000),
    }
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_name, best_score = ordered[0]
    runner_up = ordered[1][1] if len(ordered) > 1 else 0
    sram = (c(0x7FFE) + c(0x7FFF)) >= 1

    if best_score < 2 or best_score < runner_up * 1.3:
        return MapperGuess(
            "No determinado", "baja",
            "El patrón de escrituras no distingue con claridad un mapper clásico "
            "(o usa un mapper moderno no cubierto por esta heurística: Yamanooto, "
            "ASCII16-X, Zemina, etc. — ver lista de mappers conocidos).",
            sram=sram,
        )

    confidence = "alta" if best_score >= runner_up * 2 else "media"
    detail = f"Heurística por direcciones de escritura (puntuación {best_name}: {best_score:.1f})"
    if sram:
        detail += " · posible SRAM (ESE-RAM): escritura detectada en 0x7FFE/0x7FFF"
    return MapperGuess(best_name, confidence, detail, sram=sram)


@dataclass
class MapperInfo:
    name: str
    category: str      # "clásico" | "moderno"
    detected: bool      # si esta herramienta lo detecta activamente
    description: str


KNOWN_MSX_MAPPERS: list[MapperInfo] = [
    MapperInfo("Sin mapper (16K/32K)", "clásico", True,
               "ROM simple, sin mecanismo de bancos."),
    MapperInfo("Konami (sin SCC / Konami4)", "clásico", True,
               "4 páginas de 8 KB, conmutadas en 6000h/8000h/A000h. Usado por "
               "Nemesis, Metal Gear, Penguin Adventure, Usas, etc."),
    MapperInfo("Konami SCC (Konami5)", "clásico", True,
               "Como el anterior más el chip de sonido SCC, conmutado en "
               "5000h/7000h/9000h/B000h. Usado por Salamander, Gradius 2, etc."),
    MapperInfo("ASCII8", "clásico", True,
               "4 páginas de 8 KB, conmutadas en 6000h/6800h/7000h/7800h."),
    MapperInfo("ASCII16", "clásico", True,
               "2 páginas de 16 KB, conmutadas en 6000h/7000h. Usado también por "
               "algunos cartuchos MSX-DOS2."),
    MapperInfo("+ SRAM (ESE-RAM: ASC8/ASC16/KonamiSCC)", "clásico", True,
               "Variantes con SRAM de guardado; registro de control de escritura "
               "en 7FFEh/7FFFh (detectado como aviso adicional junto al mapper base)."),
    MapperInfo("Zemina 8K / Zemina 16K", "clásico", False,
               "Variantes coreanas próximas a Konami4/ASCII16 respectivamente. No "
               "hay direcciones publicadas de forma independiente que permitan "
               "distinguirlas con fiabilidad de esas dos; no se autodetectan."),
    MapperInfo("NEO-8 / NEO-16", "moderno", True,
               'Mapper moderno con registro de 16 bits; firma "ROM_NEO8"/"ROM_NE16" '
               "en offset 0x10 (detección determinista, especificación oficial MSXgl)."),
    MapperInfo("Yamanooto", "moderno", False,
               "Mapper moderno de hasta 8 MB (4 páginas de 8 KB). Sin direcciones de "
               "conmutación publicadas que permitan una detección fiable; no se autodetecta."),
    MapperInfo("ASCII16-X", "moderno", False,
               "Mapper moderno de hasta 64 MB para cartuchos flash (p. ej. ASCII-X "
               "FlashROM). Sin direcciones de conmutación publicadas para detección "
               "fiable; no se autodetecta."),
]


def build_preview(name: str, data: bytes, max_bytes: int = 32) -> str:
    """Texto corto (para tooltip) con el tipo detectado y un vistazo en
    hexadecimal/ASCII de los primeros bytes."""
    lines = [f"{name}  ·  {fmt_bytes(len(data))}"]
    kind, payload = classify_msx(name, data)
    if kind == "rom":
        h: MSXRomHeader = payload
        guess = guess_msx_mapper(data)
        lines.append(
            f"ROM de cartucho (firma AB) · INIT={hexn(h.init, 4)} "
            f"STATEMENT={hexn(h.statement, 4)} DEVICE={hexn(h.device, 4)}"
        )
        lines.append(f"Mapper: {guess.name} (confianza: {guess.confidence})")
    elif kind == "bin":
        h: MSXBinHeader = payload
        lines.append(
            f"Binario BLOAD · inicio={hexn(h.start, 4)} fin={hexn(h.end, 4)} "
            f"exec={hexn(h.exec_addr, 4)}"
        )
    elif kind == "dsk":
        if isinstance(payload, DskImage):
            lines.append(f"Disco MSX-DOS · {len(payload.entries)} elemento(s) en la raíz")
        else:
            lines.append(f"Disco MSX-DOS (no se pudo leer: {payload})")
    elif kind == "error":
        lines.append(f"Error al analizar: {payload}")
    else:
        lines.append("Sin cabecera reconocida")

    if kind != "dsk":
        chunk = data[:max_bytes]
        if chunk:
            hex_line = " ".join(f"{b:02X}" for b in chunk)
            ascii_line = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(hex_line)
            lines.append(ascii_line + ("…" if len(data) > max_bytes else ""))
    return "\n".join(lines)


def classify_msx(name: str, data: bytes):
    """Devuelve (kind, payload) donde kind es 'rom' | 'bin' | 'dsk' | 'raw' | 'error'."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "dsk":
        try:
            return "dsk", parse_dsk(data)
        except Exception as e:  # noqa: BLE001
            return "error", str(e)
    if len(data) >= 10 and data[0:2] == b"AB":
        return "rom", parse_msx_rom_header(data)
    if len(data) >= 7 and data[0] == 0xFE:
        return "bin", parse_msx_bin_header(data)
    return "raw", None


# ---------------------------------------------------------------------------
# Sega Mega Drive / Genesis
# ---------------------------------------------------------------------------

@dataclass
class GenesisHeader:
    console_name: str
    copyright: str
    domestic: str
    overseas: str
    serial: str
    checksum: int
    io_support: str
    rom_start: int
    rom_end: int
    ram_start: int
    ram_end: int
    sram: str
    region: str


def parse_genesis(data: bytes):
    if len(data) < 0x200:
        return None, "archivo demasiado pequeño"
    console_name = ascii_str(data, 0x100, 16)
    if "SEGA" not in console_name.upper():
        return None, 'no se encontró la firma "SEGA" en el offset 0x100'

    checksum = struct.unpack_from(">H", data, 0x18E)[0]
    rom_start, rom_end, ram_start, ram_end = struct.unpack_from(">IIII", data, 0x1A0)

    header = GenesisHeader(
        console_name=console_name,
        copyright=ascii_str(data, 0x110, 16),
        domestic=ascii_str(data, 0x120, 48),
        overseas=ascii_str(data, 0x150, 48),
        serial=ascii_str(data, 0x180, 14),
        checksum=checksum,
        io_support=ascii_str(data, 0x190, 16),
        rom_start=rom_start, rom_end=rom_end,
        ram_start=ram_start, ram_end=ram_end,
        sram=ascii_str(data, 0x1B0, 12),
        region=ascii_str(data, 0x1F0, 16),
    )
    return header, None


# ---------------------------------------------------------------------------
# Super Nintendo / SFC
# ---------------------------------------------------------------------------

SNES_REGIONS = {
    0: "Japón", 1: "EE. UU. / Canadá", 2: "Europa", 3: "Suecia", 4: "Finlandia",
    5: "Dinamarca", 6: "Francia", 7: "Holanda", 8: "España", 9: "Alemania / Austria",
    10: "Italia", 11: "China", 12: "Indonesia", 13: "Corea", 14: "Común",
    15: "Canadá", 16: "Brasil", 17: "Australia",
}


@dataclass
class SnesHeader:
    base: int
    title: str
    map_mode: int
    rom_type: int
    rom_size_n: int
    ram_size_n: int
    dest_code: int
    version: int
    ccomp: int
    csum: int
    valid: bool
    kind: str
    copier: bool


def _try_snes_header(data: bytes, base: int):
    if base < 0 or base + 32 > len(data):
        return None
    title = ascii_str(data, base, 21)
    map_mode = data[base + 21]
    rom_type = data[base + 22]
    rom_size_n = data[base + 23]
    ram_size_n = data[base + 24]
    dest_code = data[base + 25]
    version = data[base + 27]
    ccomp = struct.unpack_from("<H", data, base + 28)[0]
    csum = struct.unpack_from("<H", data, base + 30)[0]
    valid = (ccomp ^ csum) == 0xFFFF
    return dict(
        base=base, title=title, map_mode=map_mode, rom_type=rom_type,
        rom_size_n=rom_size_n, ram_size_n=ram_size_n, dest_code=dest_code,
        version=version, ccomp=ccomp, csum=csum, valid=valid,
    )


def _printable(s: str) -> bool:
    return len(s.strip()) > 2 and all(32 <= ord(c) < 127 or c == "·" for c in s)


def parse_snes(data: bytes):
    copier = 512 if len(data) % 0x8000 == 512 else 0
    lo = _try_snes_header(data, copier + 0x7FC0)
    hi = _try_snes_header(data, copier + 0xFFC0)

    chosen, kind = None, ""
    if lo and lo["valid"] and not (hi and hi["valid"]):
        chosen, kind = lo, "LoROM"
    elif hi and hi["valid"] and not (lo and lo["valid"]):
        chosen, kind = hi, "HiROM"
    elif lo or hi:
        lo_ok = bool(lo and _printable(lo["title"]))
        hi_ok = bool(hi and _printable(hi["title"]))
        if lo_ok and not hi_ok:
            chosen, kind = lo, "LoROM (checksum no verificado)"
        elif hi_ok and not lo_ok:
            chosen, kind = hi, "HiROM (checksum no verificado)"
        elif lo:
            chosen, kind = lo, "LoROM (sin confirmar)"
        else:
            chosen, kind = hi, "HiROM (sin confirmar)"

    if not chosen:
        return None, "no se localizó una cabecera reconocible"

    header = SnesHeader(
        base=chosen["base"], title=chosen["title"], map_mode=chosen["map_mode"],
        rom_type=chosen["rom_type"], rom_size_n=chosen["rom_size_n"],
        ram_size_n=chosen["ram_size_n"], dest_code=chosen["dest_code"],
        version=chosen["version"], ccomp=chosen["ccomp"], csum=chosen["csum"],
        valid=chosen["valid"], kind=kind, copier=bool(copier),
    )
    return header, None


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Nombres de archivo estilo FAT 8.3 (--r83 de uCON64)
# ---------------------------------------------------------------------------
# Útil al preparar archivos para sistemas de la época que exigen nombres
# cortos: MSX-DOS (FAT12, igual que el DOS de PC), o cualquier copión que
# lea el nombre del archivo desde un disquete con ese límite. Replica el
# algoritmo real de la opción --r83 de uCON64 (src/ucon64_misc.c, case
# UCON64_R83), verificado contra su código fuente:
#
#   - La extensión (con el punto) se recorta a 4 caracteres como máximo.
#   - Si el nombre base (sin extensión) mide 8 caracteres o menos, se deja
#     tal cual: no hace falta tocar nada.
#   - Si mide más de 8, se trunca a 5 caracteres y se le añaden 3 dígitos
#     hexadecimales tomados del CRC32 del nombre base ORIGINAL completo.
#     Es el mismo principio que usa Windows al generar nombres cortos del
#     tipo "MIARCHI~1.TXT", pero con un hash en vez de un contador
#     secuencial: dos archivos distintos que truncarían al mismo prefijo de
#     5 caracteres acaban, con muchísima probabilidad, en sufijos hex
#     distintos, en vez de chocar entre sí.

import zlib


def rename_to_8_3(nombre_archivo: str) -> str:
    """Genera un nombre de archivo válido para FAT 8.3 a partir de uno largo.

    Ejemplo: "Adventures_Batman_y_Ronin.swc" -> "ADVEN1a2.swc" (el sufijo
    hexadecimal exacto depende del CRC32 del nombre original).
    """
    import os as _os
    base, ext = _os.path.splitext(nombre_archivo)
    ext = ext[:4]   # el punto cuenta como parte de la extensión
    if len(base) <= 8:
        return base + ext
    crc = zlib.crc32(base.encode("utf-8", errors="replace")) & 0xFFFFFFFF
    sufijo_hex = format(crc, "x")[:3].rjust(3, "0")
    return base[:5] + sufijo_hex + ext


def generar_flashfloppy_img_cfg() -> str:
    """Genera un archivo IMG.CFG para FlashFloppy/HxC, con las entradas
    necesarias para que reconozcan los discos "superformateados" del Super
    Magic Drive / Super Wild Card (1600 y 800 KB) directamente en formato
    de imagen en bruto (.dsk/.img), SIN necesidad de convertirlos a HFE.

    Los formatos estándar (720 KB, 1.44 MB) NO llevan entrada aquí a
    propósito: su geometría física (9 y 18 sectores por pista) es la
    habitual de cualquier disquete de 3.5", así que FlashFloppy la reconoce
    sola. Solo los dos tamaños "superformateados" (20 y 10 sectores por
    pista) necesitan decírselo explícitamente.

    Sintaxis verificada contra examples/IMG.CFG del propio proyecto
    FlashFloppy (github.com/keirf/flashfloppy): cada bloque etiqueta por
    tamaño exacto de archivo, y basta con cyls/heads/secs/bps/rate — el
    resto de parámetros (gaps, interleave...) los calcula el propio
    firmware ("auto") a partir de estos.
    """
    cabecera = (
        "## IMG.CFG para FlashFloppy / HxC\n"
        "## Formatos \"superformateados\" del Super Magic Drive / Super Wild Card,\n"
        "## generados por ASTURCONSOLE.\n"
        "##\n"
        "## Copia este archivo a la memoria USB del Gotek: a la carpeta FF/ si\n"
        "## existe, o si no a la raiz. Los formatos estandar (720 KB, 1.44 MB)\n"
        "## no necesitan entrada aqui: FlashFloppy los reconoce solo.\n"
        "##\n"
        "## Sintaxis verificada contra examples/IMG.CFG del propio proyecto\n"
        "## FlashFloppy (github.com/keirf/flashfloppy). No probado contra\n"
        "## hardware real: revisa el resultado con cuidado la primera vez.\n\n"
    )
    bloques = []
    for clave in ("1600", "800"):   # solo los NO estándar; ver docstring
        f = SMD_DISK_FORMATS[clave]
        rate = 500 if clave == "1600" else 250   # HD vs DD, kbit/s
        tamano = f.total_sectors * f.bps
        bloques.append(
            f"[smd{clave}::{tamano}]\n"
            f"cyls = 80\n"
            f"heads = 2\n"
            f"secs = {f.spt}\n"
            f"bps = {f.bps}\n"
            f"rate = {rate}\n"
        )
    return cabecera + "\n".join(bloques)


# ---------------------------------------------------------------------------
# Discos con cabecera de copiador dividida en varias partes (Super Wild
# Card / Super Magic Drive): reconstruir el archivo original a partir de
# los discos, de forma genérica — sirve igual para SNES que para Genesis,
# y para discos generados por ESTA aplicación o por cualquier otra.
# ---------------------------------------------------------------------------
# La firma de cabecera (AA BB 04 en offsets 8-10) la comparten el Super
# Wild Card y el Super Magic Drive —mismo fabricante de firmware, JSI/
# Front Far East—, así que un disco con esta cabecera puede contener tanto
# una ROM de SNES como una de Genesis: no se puede saber cuál sin mirar el
# contenido real. Ver system_detect._detectar_disquete_copiador, que hace
# exactamente esa comprobación para identificar el sistema.
COPIER_HEADER_SIGNATURE_OFFSET = 8  # AA BB 04 empieza aquí


@dataclass
class DiskSeriesPart:
    numero: int
    es_ultima: bool
    header: bytes
    datos: bytes
    nombre_base_interno: str
    origen: str  # nombre del archivo .img/.dsk, para mensajes de error

    def clave_serie(self) -> tuple[str, bytes]:
        """Identifica de forma fiable a qué serie pertenece esta parte:
        el nombre base interno por sí solo NO basta, porque dos juegos
        DISTINTOS pueden truncar a 8.3 al mismo nombre corto (FAT12 solo
        permite 8 caracteres) y por pura coincidencia acabar compartiendo
        el mismo "DONKEY~1" o similar, aunque no tengan nada que ver.

        Se combina con el resto de la cabecera de 512 bytes, EXCLUYENDO
        los tres bytes que cambian por diseño entre partes de una misma
        serie real (el campo de páginas de 8 KB, bytes 0-1, y el bit
        "quedan más partes" del byte 2): todo lo demás lo copia tal cual
        split_swc_disks desde la cabecera original, así que si dos discos
        con el mismo nombre truncado difieren en esos bytes "constantes",
        son de series distintas por mucho que compartan nombre.
        """
        h = bytearray(self.header)
        h[0] = 0
        h[1] = 0
        h[2] &= ~0x40
        return (self.nombre_base_interno, bytes(h))


def leer_partes_de_disco(path: str) -> list[DiskSeriesPart]:
    """Abre un disco (.img/.dsk) con FAT12 y extrae TODAS las partes de
    juego dividido que contenga en su directorio raíz.

    Normalmente es una sola, pero algunas herramientas de terceros (como
    WinImage, usada para crear discos de "Donkey Kong Country 2") meten
    DOS partes en el mismo disco físico cuando cada una por separado deja
    demasiado espacio libre — aprovechan el resto del disco para la
    siguiente parte en vez de desperdiciarlo. Por eso esto no asume "un
    disco, una parte": mira TODOS los archivos de la raíz y se queda con
    los que tengan la cabecera de copiador válida.

    El número de cada parte se lee del nombre INTERNO del archivo (el que
    lleva dentro del propio disco, como "AEROTH~2.1" o "DONKEY~1.5"), no
    del nombre externo del .img: así funciona igual con los discos que
    genera esta aplicación que con los de cualquier otra herramienta.
    """
    nombre_visible = os.path.basename(path)
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise ValueError(f"{nombre_visible}: no se pudo leer ({e})")

    dsk = parse_dsk(data)
    archivos = [e for e in dsk.entries if not e.is_dir]
    if not archivos:
        raise ValueError(f"{nombre_visible}: el disco no contiene ningún archivo")

    partes: list[DiskSeriesPart] = []
    for entry in archivos:
        try:
            contenido = reconstruct_dsk_file(dsk, entry)
        except Exception:  # noqa: BLE001
            continue
        if len(contenido) < 512:
            continue
        header = contenido[:512]
        if not (header[8] == 0xAA and header[9] == 0xBB and header[10] == 0x04):
            continue  # este archivo del disco no es una parte de copiador válida
        m = re.search(r"\.(\d+)$", entry.name)
        if not m:
            continue
        numero = int(m.group(1))
        nombre_base = entry.name.rsplit(".", 1)[0]
        es_ultima = not (header[2] & 0x40)
        partes.append(DiskSeriesPart(numero, es_ultima, header, contenido[512:],
                                      nombre_base, nombre_visible))

    if not partes:
        raise ValueError(
            f"{nombre_visible}: ningún archivo dentro del disco tiene la cabecera "
            f"de copiador esperada (Super Wild Card / Super Magic Drive)")
    return partes


def find_disk_series(path: str) -> list[DiskSeriesPart]:
    """Dado UN disco de una serie dividida (cualquiera de ellos, aunque
    contenga una o varias partes), localiza en la misma carpeta el resto
    de partes de esa misma serie — estén en discos distintos o compartan
    disco con otra parte, como hacen algunas herramientas.

    A diferencia de reconocer un patrón en el nombre de archivo EXTERNO
    (que dependería de qué convención use la herramienta que generó los
    discos, y fallaría con cualquier otra), esto abre cada .img/.dsk de
    la carpeta y compara la cabecera real de cada parte encontrada.
    """
    partes_ref = leer_partes_de_disco(path)
    clave_ref = partes_ref[0].clave_serie()
    carpeta = os.path.dirname(path) or "."

    encontrados: dict[int, DiskSeriesPart] = {
        p.numero: p for p in partes_ref if p.clave_serie() == clave_ref}

    try:
        nombres_carpeta = os.listdir(carpeta)
    except OSError as e:
        raise ValueError(f"no se pudo leer la carpeta {carpeta}: {e}")

    for nombre in nombres_carpeta:
        ruta = os.path.join(carpeta, nombre)
        if ruta == path or os.path.splitext(nombre)[1].lower() not in (".img", ".dsk"):
            continue
        try:
            otras_partes = leer_partes_de_disco(ruta)
        except ValueError:
            continue  # no es un disco de esta serie (u otro tipo de disco cualquiera)
        for p in otras_partes:
            if p.clave_serie() == clave_ref:
                encontrados[p.numero] = p

    numeros = sorted(encontrados)
    faltantes = [n for n in range(1, numeros[-1] + 1) if n not in encontrados]
    if faltantes:
        detalle = ", ".join(f"{n}→{encontrados[n].origen}" for n in numeros)
        raise ValueError(
            f"faltan las partes número {', '.join(map(str, faltantes))} de la serie "
            f"«{partes_ref[0].nombre_base_interno}» — deben estar en la misma carpeta "
            f"que el resto.\nPartes encontradas con esa misma cabecera: {detalle}\n"
            "Si tienes más de un juego cuyo nombre largo se trunca al mismo nombre "
            "8.3 (algo posible: FAT12 solo permite 8 caracteres), podrían estarse "
            "mezclando partes de series distintas — revisa que todos esos números "
            "pertenezcan de verdad al mismo juego."
        )
    return [encontrados[n] for n in numeros]


def rebuild_from_disk_series(partes: list[DiskSeriesPart]) -> tuple[bytes, str]:
    """Reconstruye el archivo original con cabecera de copiador a partir
    de una lista de partes ya leídas (ver leer_partes_de_disco /
    find_disk_series) — uno o varios discos, cada uno pudiendo aportar
    una o varias partes; se reordenan por su número, así que da igual en
    qué orden se pasen.

    Verifica que las partes son consecutivas sin huecos y que la última
    tiene desactivado el bit "quedan más partes" de la cabecera, y
    recalcula el campo de páginas de 8 KB para que refleje el tamaño
    TOTAL reconstruido, no el de una sola parte.

    Devuelve (datos_reconstruidos, nombre_base_interno) — el nombre puede
    servir para nombrar el archivo de salida.
    """
    if not partes:
        raise ValueError("no se ha indicado ninguna parte")

    partes = sorted(partes, key=lambda p: p.numero)

    numeros = [p.numero for p in partes]
    if numeros != list(range(1, len(numeros) + 1)):
        faltantes = sorted(set(range(1, numeros[-1] + 1)) - set(numeros))
        raise ValueError(
            f"faltan partes de la serie (número {', '.join(map(str, faltantes))}); "
            "no se puede reconstruir el archivo completo con las partes indicadas")
    if not partes[-1].es_ultima:
        raise ValueError(
            "la última parte de las indicadas todavía tiene activado el bit "
            "\"quedan más partes\" de su cabecera: falta al menos una parte más "
            "de la serie para completar la reconstrucción")
    intermedias_mal = [p.origen for p in partes[:-1] if p.es_ultima]
    if intermedias_mal:
        raise ValueError(
            "una parte intermedia (" + ", ".join(intermedias_mal) + ") tiene "
            "desactivado el bit \"quedan más partes\": no parece pertenecer a "
            "esta misma serie dividida")

    header_final = bytearray(partes[0].header)
    datos_totales = b"".join(p.datos for p in partes)
    paginas = len(datos_totales) // 0x2000
    header_final[0] = paginas & 0xFF
    header_final[1] = (paginas >> 8) & 0xFF
    header_final[2] &= ~0x40  # reconstruido completo: sin más partes pendientes

    return bytes(header_final) + datos_totales, partes[0].nombre_base_interno
