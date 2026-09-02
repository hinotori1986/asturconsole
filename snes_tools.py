"""Herramientas de conversión para ROMs de Super Nintendo: cabeceras de
copiadora de época, checksum interno y división en disquetes multi-parte.

Nota de fiabilidad
-------------------
Los formatos de cabecera de las copiadoras SNES de los 90 (Super Wild Card,
Super UFO, Game Doctor, Pro Fighter, Professor SF...) no siguieron un
estándar único documentado de forma consistente entre fuentes. Lo que aquí
se implementa con confianza es:

  - el bloque genérico de 512 bytes que antepone la inmensa mayoría de
    copiadoras y que reconocen prácticamente todos los emuladores (se
    detecta por `tamaño_archivo % 32768 == 512`);
  - la cabecera **Super Wild Card**, verificada contra la especificación
    oficial de JSI/Front Far East (wiki.superfamicom.org/super-wild-card)
    Y contra archivos .SWC reales de dos discos que cargan correctamente en
    una Super Wild Card DX2 física: firma `AA BB 04` en los offsets **8-10**
    (no 3-5, como asumía una versión anterior de este código), con un bit
    en el byte 2 que indica si quedan más partes por cargar.

El resto de "marcas" de copiadora comparten el mismo bloque de 512 bytes
sin ninguna firma distintiva, así que no se puede diferenciar de forma
fiable cuál las generó: en esos casos se etiqueta como "genérica" en lugar
de adivinar una marca concreta.

La división en disquetes SWC genera imágenes `.img` de 1.44 MB con sistema
de archivos FAT12 real (no fragmentos de bytes en bruto): cada disco lleva
su propio archivo con su propia cabecera de 512 bytes, replicando el
formato exacto verificado contra hardware físico.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import rom_formats as rf

COPIER_HEADER_SIZE = 512


@dataclass
class CopierHeaderInfo:
    present: bool
    size: int
    brand: str                          # "Super Wild Card" | "Genérica / desconocida" | ""
    block_count: Optional[int] = None
    rom_type_hint: Optional[str] = None  # "LoROM" | "HiROM" | None
    more_parts_follow: Optional[bool] = None  # solo relevante para "Super Wild Card"


def detect_copier_header(data: bytes) -> CopierHeaderInfo:
    if len(data) < COPIER_HEADER_SIZE:
        return CopierHeaderInfo(False, 0, "")

    header = data[:COPIER_HEADER_SIZE]
    # Firma real verificada contra la especificación oficial de JSI/Front Far
    # East (wiki.superfamicom.org/super-wild-card) Y contra archivos .SWC
    # reales de una Super Wild Card DX2 funcionando en hardware: el ID va en
    # los bytes 8-9 ('AA','BB') y el byte 10 indica el tipo de archivo
    # ('04' = ROM de juego SWC/SSM). NO en los bytes 3-5 como versiones
    # anteriores de este código asumían incorrectamente.
    #
    # Esta comprobación va ANTES que la heurística de tamaño de abajo (y sin
    # depender de ella) porque los archivos partidos en varios discos no
    # cumplen la relación "tamaño % 32768 == 512" propia de un ROM completo,
    # pero siguen teniendo una cabecera SWC perfectamente válida.
    if header[8] == 0xAA and header[9] == 0xBB and header[10] == 0x04:
        block_count = header[0] | (header[1] << 8)
        flags = header[2]
        rom_type_hint = "HiROM" if (flags & 0x10) else "LoROM"
        more_parts_follow = bool(flags & 0x40)
        return CopierHeaderInfo(True, COPIER_HEADER_SIZE, "Super Wild Card",
                                 block_count, rom_type_hint, more_parts_follow)

    # Sin firma distintiva: solo queda la heurística de tamaño para el
    # bloque de 512 bytes "genérico" (asume un ROM completo, header + datos
    # cuyo tamaño es cercano a una potencia de dos).
    if len(data) % 0x8000 != COPIER_HEADER_SIZE:
        return CopierHeaderInfo(False, 0, "")

    return CopierHeaderInfo(True, COPIER_HEADER_SIZE, "Genérica / desconocida")


def strip_header(data: bytes) -> bytes:
    info = detect_copier_header(data)
    return data[info.size:] if info.present else data


def make_generic_header() -> bytes:
    return bytes(COPIER_HEADER_SIZE)


def sram_size_from_ram_size_n(ram_size_n: int) -> int:
    """Tamaño real de SRAM (en bytes) a partir del campo "RAM size" de la
    cabecera interna SNES (SnesHeader.ram_size_n, offset base+24) — mismo
    cálculo que usa uCON64: 1 << (n+10) si n no es 0, si no 0 (sin SRAM).
    """
    return (1 << (ram_size_n + 10)) if ram_size_n else 0


def make_swc_header(data_size: int, hirom: bool, more_parts_follow: bool = False,
                     sram_size: int = 32 * 1024) -> bytes:
    """Cabecera Super Wild Card para UNA parte de datos de `data_size` bytes.

    `more_parts_follow`: False si esta parte es la última (o la única) del
    juego; True si tras cargar esta parte la SWC debe pedir el siguiente
    disco. Layout verificado contra la especificación oficial (JSI/Front
    Far East), contra archivos .SWC reales de dos discos que cargan
    correctamente en una Super Wild Card DX2 física, y contra el código
    fuente de uCON64 (console/snes.c:snes_ffe, que genera esta misma
    cabecera):
      0-1   nº de páginas de 8 KB de ESTA parte (no del juego completo)
      2     flags: bits 4-5 = 0x30 si HiROM, 0x00 si LoROM;
                   bits 2-3 = tamaño de SRAM del juego (ver más abajo);
                   bit6 = 1 si quedan más partes, 0 si es la última
      3-7   reservado (0)
      8-9   'AA' 'BB' (ID)
      10    '04' (tipo: ROM de juego SWC/SSM)
      11-511 reservado (0)

    El tamaño de SRAM (bits 2-3) NO es cosmético: es la causa real,
    documentada en SWC-compatibility.txt, de que bastantes juegos SNES
    necesiten "crackearse" (opción -k de uCON64) para funcionar en un
    copión. Muchos juegos comprueban cuánta SRAM tiene conectada la
    consola como protección anti-copia: si el copión declara siempre 32
    KB (el máximo, y lo que se generaba aquí antes de este cambio) pero
    el juego usa menos, la discrepancia delata que se está ejecutando
    desde un copión y el juego se detiene. Indicando aquí el tamaño REAL
    de SRAM del juego (que se lee de su propia cabecera, ver
    sram_size_from_ram_size_n), la protección no llega ni a dispararse
    en la mayoría de los casos — sin tocar ni un byte del código del
    juego. Confirmado con hardware real: Breath of Fire II (E), que
    SWC-compatibility.txt marca con "needs crack", funciona sin ningún
    parche de código si la cabecera declara sus 8 KB de SRAM reales en
    vez de asumir 32 KB.
        32 KB (o desconocido): 00   (ya es el valor por defecto, uCON64
                                      no pone nada en este caso)
         8 KB: 04     2 KB: 08     0 KB (sin SRAM): 0C
    """
    header = bytearray(COPIER_HEADER_SIZE)
    pages = data_size // 0x2000  # páginas de 8 KB
    header[0] = pages & 0xFF
    header[1] = (pages >> 8) & 0xFF
    flags = 0x30 if hirom else 0x00
    if sram_size == 8 * 1024:
        flags |= 0x04
    elif sram_size == 2 * 1024:
        flags |= 0x08
    elif sram_size == 0:
        flags |= 0x0C
    # cualquier otro tamaño (incluido 32 KB) no necesita bits adicionales
    if more_parts_follow:
        flags |= 0x40
    header[2] = flags
    header[8] = 0xAA
    header[9] = 0xBB
    header[10] = 0x04
    return bytes(header)


def add_header(data: bytes, style: str = "generic", hirom: bool = False,
               sram_size: int = 32 * 1024) -> bytes:
    if detect_copier_header(data).present:
        raise ValueError("el archivo ya tiene una cabecera de copiador; quítala antes de añadir otra")
    prefix = (make_swc_header(len(data), hirom, sram_size=sram_size) if style == "swc"
             else make_generic_header())
    return prefix + data


def compute_snes_checksum(rom: bytes) -> tuple[int, int]:
    """Checksum interno SNES: suma de 16 bits con "espejado" para tamaños
    que no son potencia de dos. `rom` debe ser el contenido SIN cabecera
    de copiador (el cartucho real nunca la tuvo).
    """
    size = len(rom)
    if size == 0:
        return 0, 0xFFFF

    p2 = 1
    while p2 * 2 <= size:
        p2 *= 2

    total = sum(rom[:p2])
    remainder = rom[p2:]
    if remainder:
        repeats = p2 // len(remainder)
        total += sum(remainder) * repeats

    checksum = total & 0xFFFF
    complement = checksum ^ 0xFFFF
    return checksum, complement


def fix_checksum(data: bytes, header_base_absolute: int, copier_size: int):
    """Recalcula checksum/complemento y los escribe en `data` (que puede
    incluir cabecera de copiador). `header_base_absolute` es el offset de
    la cabecera SNES dentro de `data` tal cual viene (0x7FC0/0xFFC0 más el
    desplazamiento de la cabecera de copiador si la hay).

    Convención estándar: durante el cálculo los 4 bytes de
    checksum/complemento se fijan a 0xFF (para que el resultado sea
    autoconsistente y no dependa de lo que hubiera antes en esos bytes) y
    después se sobrescriben con el valor final.
    """
    out = bytearray(data)
    b = header_base_absolute
    if b + 32 > len(out):
        raise ValueError("offset de cabecera fuera de rango")

    out[b + 28] = out[b + 29] = out[b + 30] = out[b + 31] = 0xFF
    rom_no_header = bytes(out[copier_size:]) if copier_size else bytes(out)
    checksum, complement = compute_snes_checksum(rom_no_header)

    out[b + 28] = complement & 0xFF
    out[b + 29] = (complement >> 8) & 0xFF
    out[b + 30] = checksum & 0xFF
    out[b + 31] = (checksum >> 8) & 0xFF
    return bytes(out), checksum, complement


def split_floppy(data: bytes, chunk_size: int) -> list[bytes]:
    if chunk_size <= 0:
        raise ValueError("el tamaño de fragmento debe ser mayor que 0")
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]


# ---------------------------------------------------------------------------
# Entrelazado / desentrelazado de HiROM
# ---------------------------------------------------------------------------
# Según la documentación del propio proyecto uCON64: los volcados SNES
# entrelazados los producen la Game Doctor y la Super UFO (y, por error,
# alguna Super Wild Card mal configurada) al volcar un cartucho HiROM. El
# formato "más simple" de entrelazado -que es, con diferencia, el más
# habitual y el que reconocen las herramientas clásicas- coloca primero
# todas las mitades SUPERIORES (32 KB) de cada banco de 64 KB, y a
# continuación todas las mitades INFERIORES. Convertir un volcado a formato
# Super Wild Card implica desentrelazarlo primero si hace falta.
#
# Existe al menos una variante distinta de entrelazado (usada por algunos
# juegos con chip Super FX) que uCON64 trata aparte y que esta
# implementación NO reconoce ni convierte.

HIROM_BANK_SIZE = 0x10000   # 64 KB
HIROM_HALF_SIZE = 0x8000    # 32 KB


def deinterleave_hirom(data: bytes) -> bytes:
    if len(data) == 0 or len(data) % HIROM_BANK_SIZE != 0:
        raise ValueError("el tamaño no es múltiplo de 64 KB; no parece un HiROM entrelazado")
    half = len(data) // 2
    upper_region = data[:half]
    lower_region = data[half:]
    num_banks = half // HIROM_HALF_SIZE

    out = bytearray(len(data))
    for i in range(num_banks):
        lower = lower_region[i * HIROM_HALF_SIZE:(i + 1) * HIROM_HALF_SIZE]
        upper = upper_region[i * HIROM_HALF_SIZE:(i + 1) * HIROM_HALF_SIZE]
        base = i * HIROM_BANK_SIZE
        out[base:base + HIROM_HALF_SIZE] = lower
        out[base + HIROM_HALF_SIZE:base + HIROM_BANK_SIZE] = upper
    return bytes(out)


def interleave_hirom(data: bytes) -> bytes:
    if len(data) == 0 or len(data) % HIROM_BANK_SIZE != 0:
        raise ValueError("el tamaño no es múltiplo de 64 KB; no es un HiROM válido para entrelazar")
    num_banks = len(data) // HIROM_BANK_SIZE
    upper_region = bytearray(num_banks * HIROM_HALF_SIZE)
    lower_region = bytearray(num_banks * HIROM_HALF_SIZE)

    for i in range(num_banks):
        base = i * HIROM_BANK_SIZE
        lower = data[base:base + HIROM_HALF_SIZE]
        upper = data[base + HIROM_HALF_SIZE:base + HIROM_BANK_SIZE]
        lower_region[i * HIROM_HALF_SIZE:(i + 1) * HIROM_HALF_SIZE] = lower
        upper_region[i * HIROM_HALF_SIZE:(i + 1) * HIROM_HALF_SIZE] = upper

    return bytes(upper_region) + bytes(lower_region)


FLOPPY_SIZES = {
    '360 KB (5.25" DD)': 360 * 1024,
    '720 KB (3.5" DD)': 720 * 1024,
    '1.2 MB (5.25" HD)': 1200 * 1024,
    '1.44 MB (3.5" HD)': 1440 * 1024,
}


# ---------------------------------------------------------------------------
# División en varios discos Super Wild Card (imágenes .img FAT12 reales)
# ---------------------------------------------------------------------------
# Verificado contra dos archivos .img reales de una Super Wild Card DX2 que
# cargan correctamente en hardware físico (partida en 2 discos): cada disco
# es una imagen FAT12 de 1.44 MB con UN archivo dentro, y ese archivo lleva
# su PROPIA cabecera SWC de 512 bytes (no solo el primero). La única
# diferencia entre las cabeceras de cada parte es el bit "quedan más partes"
# (byte 2, bit 6) y el recuento de páginas de 8 KB, que describe el tamaño
# de ESA parte, no del juego completo.

@dataclass
class SwcDiskPart:
    filename: str        # nombre del disco (para guardar el .img)
    inner_name: str       # nombre 8.3 del archivo dentro del disco
    image: bytes           # imagen .img de 1.44 MB completa


def split_swc_disks(data: bytes, base_name: str, fmt: str = "1440",
                    max_data_per_part: Optional[int] = None) -> list[SwcDiskPart]:
    """Divide un ROM que YA tiene cabecera Super Wild Card en tantos discos
    como haga falta.

    `fmt`: "1440" (por defecto) usa un FAT12 genérico de 1.44 MB estándar
    (dos copias de FAT), el más compatible con lectores USB/FlashFloppy
    corrientes. "1600" usa el formato "superformateado" propio del Super
    Wild Card (20 sectores por pista en vez de 18, una sola copia de FAT):
    cabe algo más por disco, pero es menos universal — el propio manual del
    SWC dice que con este formato caben 12 megabits por disco frente a los
    11.5 de un disco "formateado a la IBM" (1.44 MB estándar).

    `max_data_per_part`: bytes de datos (sin contar la cabecera) por disco.
    Por defecto se usa el máximo que cabe en el formato elegido, pero se
    puede fijar a un valor concreto (p. ej. 0x100000 = 1 MB exacto, la
    convención que usan algunas herramientas clásicas como referencia).

    Importante: cada parte hereda TODOS los bytes de la cabecera original
    (incluidos los de SRAM/modo de arranque, específicos del juego, que no
    se pueden reconstruir de forma fiable desde cero) y solo se modifican
    dos campos por parte: el recuento de páginas de 8 KB (bytes 0-1, ajustado
    al tamaño de ESA parte) y el bit "quedan más partes" (byte 2, bit 6).
    Verificado byte a byte: partiendo de la cabecera real de un disco 1,
    aplicar este ajuste reproduce EXACTAMENTE la cabecera real del disco 2
    correspondiente (archivos de referencia de una Super Wild Card DX2
    física de dos discos). Esto se verificó con el formato de 1.44 MB
    estándar; el de 1.6 MB usa la misma lógica de cabecera, pero no se ha
    podido confirmar con un disco real de ese formato concreto.
    """
    info = detect_copier_header(data)
    if not info.present or info.brand != "Super Wild Card":
        raise ValueError(
            "el archivo debe tener ya una cabecera Super Wild Card antes de dividirlo "
            "(usa antes 'Añadir cabecera Super Wild Card')"
        )
    if fmt not in ("1440", "1600"):
        raise ValueError(f"formato de disco desconocido: {fmt}")

    original_header = data[:COPIER_HEADER_SIZE]
    rom_data = data[COPIER_HEADER_SIZE:]

    if max_data_per_part is None:
        if fmt == "1600":
            max_data_per_part = rf.SMD_DISK_FORMATS["1600"].free_bytes - COPIER_HEADER_SIZE
        else:
            max_data_per_part = rf.FAT12_1440_MAX_FILE_BYTES - COPIER_HEADER_SIZE
        max_data_per_part -= max_data_per_part % 0x2000  # múltiplo exacto de 8 KB
    if max_data_per_part <= 0:
        raise ValueError("tamaño de disquete insuficiente para la cabecera SWC")

    chunks = [rom_data[i:i + max_data_per_part] for i in range(0, len(rom_data), max_data_per_part)]
    if not chunks:
        chunks = [b""]

    short_base = "".join(c for c in base_name.upper() if c.isalnum())[:6] or "ROM"

    parts: list[SwcDiskPart] = []
    for i, chunk in enumerate(chunks):
        is_last = (i == len(chunks) - 1)
        header = bytearray(original_header)
        pages = len(chunk) // 0x2000
        header[0] = pages & 0xFF
        header[1] = (pages >> 8) & 0xFF
        if is_last:
            header[2] &= ~0x40
        else:
            header[2] |= 0x40
        part_data = bytes(header) + chunk
        inner_name = f"{short_base}.{i + 1}"
        if fmt == "1600":
            image = rf.write_files_to_smd_disk([(inner_name, part_data)], fmt="1600")
        else:
            image = rf.make_fat12_floppy_image(inner_name, part_data)
        parts.append(SwcDiskPart(
            filename=f"{base_name}_disco{i + 1}_{fmt}kb.img",
            inner_name=inner_name,
            image=image,
        ))
    return parts

# Nota: la operación inversa (reconstruir el archivo con cabecera SWC a
# partir de los discos ya divididos) vive ahora en rom_formats.py como
# rebuild_from_disk_series() / find_disk_series(): es genérica, no
# específica de SNES, porque la misma cabecera de copiador (firma AA BB
# 04) la comparten el Super Wild Card y el Super Magic Drive.
