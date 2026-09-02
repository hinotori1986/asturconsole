"""Identificación del sistema al que pertenece un archivo.

No se fía de la extensión ni del nombre: mira DENTRO del archivo. Hace falta
porque las extensiones mienten a menudo (.bin puede ser Mega Drive o
cualquier otra cosa, .img puede ser un disquete de Super Wild Card o una
imagen de disco MSX) y porque al seleccionar ROMs mezcladas hay que saber a
cuál aplicar cada herramienta.

Cómo se reconoce cada sistema:

  MEGA DRIVE  La cadena "SEGA" en el offset 0x100. Se comprueba también
              sobre el archivo con los bytes intercambiados (aparecería como
              "ESAG") y sobre el resultado de deshacer el entrelazado SMD,
              así que se reconocen igual los volcados en esos formatos.

  SNES        La cabecera interna, que puede estar en cuatro sitios según
              sea LoROM o HiROM y lleve o no cabecera de copiador. Se valida
              con el complemento del checksum: dos palabras de 16 bits que
              deben sumar 0xFFFF. Es una comprobación fuerte, difícil de
              cumplir por casualidad.

  MSX         Firma "AB" de un ROM de cartucho, tabla de parámetros de un
              disquete, o marca de sincronismo de una cinta CAS.
"""
from __future__ import annotations

import os
import struct

CONFIANZA_ALTA = "alta"
CONFIANZA_MEDIA = "media"
CONFIANZA_BAJA = "baja"

NOMBRES = {
    "snes": "Super Nintendo",
    "genesis": "Mega Drive",
    "msx": "MSX",
}


class Deteccion:
    def __init__(self, sistema: str | None, confianza: str, motivo: str,
                 formato: str = ""):
        self.sistema = sistema
        self.confianza = confianza
        self.motivo = motivo
        self.formato = formato          # detalle: "byte swap", "SMD", "HiROM"...

    def __repr__(self):
        return (f"Deteccion({self.sistema}, {self.confianza}, "
                f"{self.formato!r}, {self.motivo!r})")


# --- Mega Drive -------------------------------------------------------------

def _tiene_firma_sega(datos: bytes) -> bool:
    if len(datos) < 0x110:
        return False
    return b"SEGA" in datos[0x100:0x110].upper()


def _byteswap(datos: bytes) -> bytes:
    n = len(datos) - (len(datos) % 2)
    out = bytearray(datos)
    out[0:n:2] = datos[1:n:2]
    out[1:n:2] = datos[0:n:2]
    return bytes(out)


def _desentrelazar_smd(datos: bytes) -> bytes:
    """Deshace el entrelazado SMD del primer bloque, que basta para la firma."""
    bloque = 0x4000
    if len(datos) < bloque:
        return b""
    trozo = datos[:bloque]
    mitad = bloque // 2
    primera, segunda = trozo[:mitad], trozo[mitad:]
    out = bytearray(bloque)
    for i in range(mitad):
        out[i * 2 + 1] = primera[i]
        out[i * 2] = segunda[i]
    return bytes(out)


def _detectar_genesis(datos: bytes) -> Deteccion | None:
    if _tiene_firma_sega(datos):
        return Deteccion("genesis", CONFIANZA_ALTA,
                         "firma SEGA en el offset 0x100", "plano")

    if _tiene_firma_sega(_byteswap(datos)):
        return Deteccion("genesis", CONFIANZA_ALTA,
                         "firma SEGA tras intercambiar los bytes: el volcado "
                         "tiene los bytes cambiados de orden", "byte swap")

    # Con cabecera SMD de 512 bytes, o sin ella
    for desplazamiento, etiqueta in ((512, "SMD con cabecera"), (0, "SMD")):
        cuerpo = datos[desplazamiento:]
        if len(cuerpo) < 0x4000:
            continue
        if _tiene_firma_sega(_desentrelazar_smd(cuerpo)):
            return Deteccion("genesis", CONFIANZA_ALTA,
                             "firma SEGA tras deshacer el entrelazado SMD",
                             etiqueta)
    return None


# --- Super Nintendo ---------------------------------------------------------

def _checksum_valido(datos: bytes, base: int) -> bool:
    """La cabecera SNES lleva checksum y su complemento; deben sumar 0xFFFF."""
    if base + 0x20 > len(datos):
        return False
    try:
        complemento = struct.unpack_from("<H", datos, base + 0x1C)[0]
        checksum = struct.unpack_from("<H", datos, base + 0x1E)[0]
    except struct.error:
        return False
    if checksum == 0 and complemento == 0:
        return False
    return (checksum ^ complemento) == 0xFFFF


def _detectar_snes(datos: bytes) -> Deteccion | None:
    # (posición de la cabecera, tiene cabecera de copiador, tipo)
    candidatos = (
        (0x7FC0, False, "LoROM"),
        (0xFFC0, False, "HiROM"),
        (0x7FC0 + 512, True, "LoROM con cabecera de copiador"),
        (0xFFC0 + 512, True, "HiROM con cabecera de copiador"),
    )
    for base, _con_cabecera, tipo in candidatos:
        if _checksum_valido(datos, base):
            return Deteccion("snes", CONFIANZA_ALTA,
                             f"cabecera SNES válida en {hex(base)} "
                             "(checksum y complemento suman 0xFFFF)", tipo)

    # Sin checksum válido, se admite una pista más débil: nombre imprimible
    # en la posición de la cabecera y tamaño coherente con un cartucho.
    for base, _c, tipo in candidatos:
        if base + 21 > len(datos):
            continue
        titulo = datos[base:base + 21]
        imprimibles = sum(1 for b in titulo if 32 <= b < 127)
        if imprimibles >= 18 and len(datos) % (32 * 1024) in (0, 512):
            return Deteccion("snes", CONFIANZA_MEDIA,
                             f"título legible en la posición de cabecera {hex(base)}, "
                             "pero el checksum no cuadra", tipo)
    return None


# --- MSX --------------------------------------------------------------------

CAS_SYNC = bytes.fromhex("1FA6DEBACC137D74")


def _detectar_msx(datos: bytes, nombre: str = "") -> Deteccion | None:
    # Cinta
    if datos[:8] == CAS_SYNC:
        return Deteccion("msx", CONFIANZA_ALTA, "marca de sincronismo de cinta CAS", "CAS")
    if datos[:8] == b"ZXTape!\x1a":
        return Deteccion("msx", CONFIANZA_ALTA, "cabecera de cinta TZX/TSX", "TSX")
    if datos[:4] == b"RIFF" and b"WAVE" in datos[:16]:
        return Deteccion("msx", CONFIANZA_MEDIA,
                         "archivo WAV: puede ser una grabación de cinta", "WAV")

    # ROM de cartucho: firma "AB" al principio de la página
    if len(datos) >= 2 and datos[:2] == b"AB":
        return Deteccion("msx", CONFIANZA_ALTA, 'firma "AB" de ROM de cartucho MSX', "ROM")

    # Imagen de disco: tabla de parámetros coherente
    if len(datos) >= 512 and datos[0] in (0xEB, 0xE9):
        try:
            bps = struct.unpack_from("<H", datos, 0x0B)[0]
            sectores = struct.unpack_from("<H", datos, 0x13)[0]
            media = datos[0x15]
        except struct.error:
            bps = sectores = media = 0
        if bps == 512 and sectores in (720, 1440) and media in (0xF8, 0xF9):
            return Deteccion("msx", CONFIANZA_ALTA,
                             f"disquete MSX de {sectores * bps // 1024} KB", "DSK")

    # Discos con cargador propio: no tienen tabla, pero el tamaño delata
    if len(datos) in (368640, 737280):
        return Deteccion("msx", CONFIANZA_MEDIA,
                         "el tamaño coincide con un disquete MSX, aunque no tiene "
                         "tabla de parámetros (posible cargador propio)", "DSK")
    return None


# --- disquetes de copiador --------------------------------------------------

def _detectar_disco_smd(datos: bytes) -> Deteccion | None:
    """Disquete del Super Magic Drive (o Super Wild Card, que comparte la
    misma tabla de geometría): se distingue de un disco MSX por el número
    de copias de FAT (nfat=1 en estos, 2 en MSX-DOS estándar) y, para el
    formato de 1600 KB, porque ni siquiera coincide en tamaño con ningún
    disco MSX habitual.

    Sin esto, un disco SMD de 720 u 1440 KB (que coincide en tamaño y
    descriptor de medio con un disco MSX equivalente) se confundiría con
    uno de MSX, porque por fuera son indistinguibles salvo por ese detalle
    del BPB.
    """
    if len(datos) < 512 or datos[0] not in (0xEB, 0xE9):
        return None
    try:
        bps = struct.unpack_from("<H", datos, 0x0B)[0]
        nfat = datos[0x10]
        sectores = struct.unpack_from("<H", datos, 0x13)[0]
        media = datos[0x15]
    except struct.error:
        return None

    # Las cuatro geometrías conocidas del Super Magic Drive / Super Wild
    # Card, identificadas por (sectores totales, descriptor de medio):
    # ver SMD_DISK_FORMATS en rom_formats.py.
    formatos_smd = {
        (3200, 0xF0): "1600",
        (2880, 0xF0): "1440",
        (1600, 0xF9): "800",
        (1440, 0xF9): "720",
    }
    clave = formatos_smd.get((sectores, media))
    if bps == 512 and nfat == 1 and clave:
        return Deteccion("genesis", CONFIANZA_ALTA,
                         f"disquete del Super Magic Drive de {clave} KB "
                         "(BPB con una sola copia de FAT, geometría propia "
                         "del copiador)", "DSK")
    return None


def _detectar_disquete_copiador(datos: bytes) -> Deteccion | None:
    """Imagen de disquete que contiene un trozo de ROM de Super Wild Card.

    Los .img generados al dividir una ROM son disquetes FAT12 de 1.44 MB con
    un único archivo dentro: una parte del juego, con su cabecera SWC. Se
    reconocen abriendo el disquete y mirando esa cabecera, porque por fuera
    son indistinguibles de cualquier otra imagen de disco.
    """
    if len(datos) != 1474560:
        return None
    try:
        import rom_formats as rf
        dsk = rf.parse_dsk(datos)
        entradas = [e for e in dsk.entries if not e.is_dir]
        if not entradas:
            return None
        interno = rf.reconstruct_dsk_file(dsk, entradas[0])
    except Exception:  # noqa: BLE001
        return None

    # Firma de la cabecera Super Wild Card: AA BB 04 en los offsets 8, 9 y
    # 10. OJO: esta firma la comparten el Super Wild Card (SNES) y el
    # Super Magic Drive (Genesis) —mismo fabricante de firmware, JSI/Front
    # Far East— así que verla NO basta para asumir "snes" sin más: hay que
    # mirar el contenido real tras la cabecera para saber de qué sistema
    # es en realidad. Confirmado con un caso real: discos de "Aero the
    # Acro-Bat 2" (Genesis) creados con una herramienta de terceros años
    # atrás, con esta misma cabecera de 512 bytes.
    if len(interno) > 11 and interno[8] == 0xAA and interno[9] == 0xBB:
        mas_partes = bool(interno[2] & 0x40)
        detalle = "parte con continuación" if mas_partes else "última parte"
        interior = _detectar_genesis(interno[512:]) or _detectar_snes(interno[512:])
        sistema = interior.sistema if interior else "snes"
        return Deteccion(sistema, CONFIANZA_ALTA,
                         f"disquete de copiador (cabecera SWC/SMD) con «{entradas[0].name}» "
                         f"dentro ({detalle})", "disquete SWC/SMD")

    # Sin la firma AA BB 04: son los disquetes con cabecera "genérica", que
    # existen de verdad (creados con otra herramienta o una versión más
    # antigua). Se identifican analizando el contenido como ROM, probando
    # todas las posiciones posibles de cabecera.
    interior = _detectar_genesis(interno) or _detectar_snes(interno)
    if interior:
        return Deteccion(interior.sistema, CONFIANZA_MEDIA,
                         f"disquete de copiador con «{entradas[0].name}» dentro: "
                         f"{interior.motivo}",
                         "disquete de copiador (cabecera genérica)")

    # Última posibilidad: una parte de CONTINUACIÓN. El trozo de en medio de
    # una ROM dividida no tiene cabecera de juego (esa va en la primera
    # parte), así que no hay firma que buscar. Pero su estructura es
    # inconfundible: cabecera de copiador de 512 bytes más un número entero
    # de páginas de 8 KB, y un nombre terminado en .2, .3, etc.
    nombre_interno = entradas[0].name
    resto = len(interno) % 8192
    sufijo = nombre_interno.rsplit(".", 1)[-1] if "." in nombre_interno else ""
    if resto == 512 and sufijo.isdigit() and int(sufijo) >= 2:
        paginas = struct.unpack_from("<H", interno, 0)[0]
        return Deteccion("snes", CONFIANZA_MEDIA,
                         f"parte {sufijo} de una ROM dividida en disquetes "
                         f"(«{nombre_interno}», {paginas} páginas de 8 KB). Las "
                         "partes de continuación no llevan cabecera del juego, "
                         "así que se reconocen por su estructura",
                         f"disquete de copiador, parte {sufijo}")
    return None


# --- función principal ------------------------------------------------------

def detectar(datos: bytes, nombre: str = "") -> Deteccion:
    """Identifica el sistema mirando el contenido del archivo."""
    if not datos:
        return Deteccion(None, CONFIANZA_BAJA, "el archivo está vacío")

    # El orden importa: las comprobaciones más específicas primero. La de
    # Mega Drive y la de SNES son firmes; la de MSX incluye pistas más
    # débiles, así que va después.
    # El disquete de copiador se comprueba primero: por fuera es una imagen de
    # disco cualquiera, y si no se mira dentro se confundiría con una de MSX.
    resultado = _detectar_disquete_copiador(datos)
    if resultado:
        return resultado

    # Igual con los discos del Super Magic Drive: un disco de 720/1440 KB
    # coincide en tamaño y descriptor de medio con uno de MSX, así que hay
    # que mirar el BPB (nfat) antes de llegar a _detectar_msx, o se
    # confundiría con MSX por tener la misma extensión .dsk.
    resultado = _detectar_disco_smd(datos)
    if resultado:
        return resultado

    for detector in (_detectar_genesis, _detectar_snes):
        resultado = detector(datos)
        if resultado:
            return resultado

    resultado = _detectar_msx(datos, nombre)
    if resultado:
        return resultado

    # Último recurso: la extensión, avisando de que es solo una suposición
    ext = os.path.splitext(nombre)[1].lower()
    por_extension = {
        ".sfc": "snes", ".smc": "snes", ".swc": "snes", ".fig": "snes", ".ufo": "snes",
        ".smd": "genesis", ".gen": "genesis", ".md": "genesis",
        ".rom": "msx", ".mx1": "msx", ".mx2": "msx",
        ".dsk": "msx", ".cas": "msx", ".tsx": "msx",
    }
    if ext in por_extension:
        return Deteccion(por_extension[ext], CONFIANZA_BAJA,
                         f"solo por la extensión «{ext}»: el contenido no se reconoce")
    return Deteccion(None, CONFIANZA_BAJA,
                     "no se reconoce el contenido ni por la extensión")


def detectar_archivo(ruta: str, max_bytes: int = 1024 * 1024) -> Deteccion:
    """Como `detectar`, leyendo solo el principio del archivo.

    Con un megabyte basta: todas las firmas están en los primeros bloques, y
    así analizar cien ROMs de 4 MB no obliga a leerlas enteras.
    """
    try:
        with open(ruta, "rb") as fh:
            datos = fh.read(max_bytes)
    except OSError as e:
        return Deteccion(None, CONFIANZA_BAJA, f"no se pudo leer: {e}")
    return detectar(datos, os.path.basename(ruta))
