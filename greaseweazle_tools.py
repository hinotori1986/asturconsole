"""Integración con Greaseweazle: dispositivo USB que permite leer y
escribir disquetes físicos reales a nivel de flujo magnético, con
cualquier geometría, cableado directamente al conector de 34 pines de
una disquetera tradicional de 3.5".

Pensado para equipos modernos sin puerto paralelo ni controladora de
disquetera integrada — las dos vías que hasta ahora ofrecía ASTURCONSOLE
para trabajar con discos físicos reales (disquetera real vía FDSETPRM, o
enviar por puerto paralelo con uCON64), y que sencillamente no existen en
places recientes. A diferencia de una disquetera USB genérica (limitada a
los formatos de fábrica, 720 KB / 1.44 MB), Greaseweazle trabaja al nivel
de flujo magnético: puede leer y escribir CUALQUIER geometría, incluidos
los formatos "superformateados" propios del Super Magic Drive / Super
Wild Card (800 y 1600 KB) — exactamente igual que lo haría una disquetera
física tradicional.

Se invoca como proceso externo (el ejecutable "gw"), igual que uCON64
para el puerto paralelo: es software libre (dominio público, licencia
Unlicense) mantenido activamente por su autor, así que no tiene sentido
reescribirlo — solo orquestarlo desde aquí.

Greaseweazle no viene incluido con ASTURCONSOLE: hay que instalarlo aparte
(https://github.com/keirf/greaseweazle/wiki) y tener el dispositivo físico
conectado. El propio "gw" detecta el puerto solo (por VID/PID USB), así
que a diferencia de uCON64 con el puerto paralelo, aquí no hace falta que
el usuario indique nada de eso.
"""
from __future__ import annotations

import os
import shutil

# Los formatos de disco de MSX y del Super Magic Drive / Super Wild Card.
# El nombre debe coincidir exactamente con los definidos en
# data/greaseweazle_diskdefs.cfg (ver ese archivo para el porqué de cada
# parámetro: los de 360/720/1440 son el estándar de PC/MSX de siempre, y
# los de 800/1600 son los "superformateados", con la geometría confirmada
# contra el firmware real de tres BIOS distintas del SMD/SWC, y el gap3
# tomado de las definiciones —verificadas por años de uso real— que trae
# la propia Greaseweazle para los samplers Ensoniq, que usan la misma
# geometría exacta).
#
# Además de estos formatos propios, se ofrecen también los perfiles
# MSX oficiales de la propia Greaseweazle (msx.1d/1dd/2d/2dd) y el
# formato "raw" (captura de flujo crudo sin decodificar), disponibles
# porque nuestro greaseweazle_diskdefs.cfg los importa explícitamente
# (import msx./import raw. al principio del archivo) — necesario porque
# --diskdefs=archivo REEMPLAZA POR COMPLETO la configuración incorporada
# de gw en vez de añadirse a ella (confirmado en el código fuente de
# Greaseweazle: codec.py, clase DiskDef_File — cuando se indica un
# nombre de archivo, carga ÚNICAMENTE ese archivo, nunca el paquete de
# datos interno además). Sin este import, esos perfiles no aparecerían
# en absoluto al usar nuestro propio archivo.
#
# Los perfiles "msx.1d" y "msx.2d" son discos MSX de 40 cilindros (180 y
# 360 KB) menos comunes que los estándar de 80 cilindros; "msx.1dd" y
# "msx.2dd" son geométricamente equivalentes a nuestros "360" y "720" de
# siempre, pero se ofrecen con su nombre oficial porque así es como
# vienen documentados en cualquier guía de Greaseweazle, y porque son
# los que ya se sabe con certeza que funcionan con hardware MSX real.
FORMATOS = {
    "360":         "asturconsole.360",
    "720":         "asturconsole.720",
    "800":         "asturconsole.800",
    "1440":        "asturconsole.1440",
    "1600":        "asturconsole.1600",
    "msx_1d":      "msx.1d",
    "msx_1dd":     "msx.1dd",
    "msx_2d":      "msx.2d",
    "msx_2dd":     "msx.2dd",
    "ibm_720":     "ibm.720",
    "ibm_1440":    "ibm.1440",
    "amstrad_cpc": "ibm.180",
    "amiga_dd":    "amiga.amigados",
    "c64":         "commodore.1541",
    "atarist":     "atarist.720",
    "zx_plus3":    "zx.3dos.ss40",
    "ibm_scan":    "ibm.scan",
    "raw_125":     "raw.125",
    "raw_250":     "raw.250",
    "raw_500":     "raw.500",
}

NOMBRE_FORMATO = {
    "360":         "360 KB (cara simple MSX, 80 cilindros)",
    "720":         "720 KB (3,5\" DD, estándar)",
    "800":         "800 KB (superformateado, SMD/SWC)",
    "1440":        "1,44 MB (3,5\" HD, estándar)",
    "1600":        "1,6 MB (superformateado, SMD/SWC)",
    "msx_1d":      "MSX 1D — 180 KB, cara simple, 40 cilindros (perfil oficial gw)",
    "msx_1dd":     "MSX 1DD — 360 KB, cara simple, 80 cilindros (perfil oficial gw)",
    "msx_2d":      "MSX 2D — 360 KB, doble cara, 40 cilindros (perfil oficial gw)",
    "msx_2dd":     "MSX 2DD — 720 KB, doble cara, 80 cilindros (perfil oficial gw, el más habitual)",
    "ibm_720":     "IBM PC/MS-DOS — 720 KB, 3,5\" DD",
    "ibm_1440":    "IBM PC/MS-DOS — 1,44 MB, 3,5\" HD",
    "amstrad_cpc": "Amstrad CPC — 180 KB, disquete de 3\" (formato CP/M estándar)",
    "amiga_dd":    "Commodore Amiga — 880 KB, AmigaDOS",
    "c64":         "Commodore 64 — disquetera 1541 (170 KB, GCR)",
    "atarist":     "Atari ST — 720 KB, doble cara",
    "zx_plus3":    "ZX Spectrum +3 — disquete de 3\", +3DOS",
    "ibm_scan":    "Escaneo automático (ibm.scan) — detecta FM/MFM sin indicar formato",
    "raw_125":     "Flujo crudo (raw), 125 kbps — sin decodificar, para discos SD de 5,25\"",
    "raw_250":     "Flujo crudo (raw), 250 kbps — sin decodificar, para discos DD de 3,5\"/5,25\"",
    "raw_500":     "Flujo crudo (raw), 500 kbps — sin decodificar, para discos HD de 3,5\"",
}

# Extensión de archivo que tiene sentido sugerir para cada formato: .dsk
# para discos MSX (así los reconoce el resto de ASTURCONSOLE — ver
# file_workbench.py, donde la propia estructura del disco decide si es
# MSX o SMD/SWC solo para archivos .dsk); .img para los superformateados
# de SMD/SWC (mismo criterio que ya se usaba); .raw para el flujo crudo,
# que no es un disco decodificado en absoluto.
# Extensiones que gw reconoce como tipo de imagen válido (lista completa
# confirmada en su propio código fuente, tools/util.py: image_types) —
# sin una de estas, gw se niega en seco con "Unrecognised file suffix"
# ANTES de intentar nada con el hardware, incluso para leer. Se usa para
# corregir automáticamente el nombre de archivo si el usuario ha escrito
# o editado uno sin extensión, o con una que gw no reconoce — no hay
# forma de garantizar que el usuario siempre teclee una extensión
# válida a mano, así que se comprueba y corrige antes de lanzar el
# proceso en vez de confiar en ello.
EXTENSIONES_VALIDAS_GW = frozenset((
    ".2d", ".a2r", ".adf", ".ads", ".adm", ".adl", ".ctr", ".d1m", ".d2m",
    ".d4m", ".d64", ".d71", ".d81", ".d88", ".dcp", ".dim", ".dmk", ".do",
    ".dsd", ".dsk", ".edsk", ".fd", ".fdi", ".hdm", ".hfe", ".ima", ".img",
    ".imd", ".ipf", ".mgt", ".msa", ".nfd", ".nsi", ".po", ".raw", ".sf7",
    ".scp", ".ssd", ".st", ".td0", ".xdf",
))

EXTENSION_FORMATO = {
    "360": ".dsk", "720": ".dsk",
    "800": ".img", "1440": ".img", "1600": ".img",
    "msx_1d": ".dsk", "msx_1dd": ".dsk", "msx_2d": ".dsk", "msx_2dd": ".dsk",
    "ibm_720": ".img", "ibm_1440": ".img",
    "amstrad_cpc": ".dsk",
    "amiga_dd": ".adf",
    "c64": ".d64",
    "atarist": ".st",
    "zx_plus3": ".dsk",
    "ibm_scan": ".img",
    # .scp (SuperCard Pro), no .raw: en gw ".raw" está reservado al
    # formato KryoFlux (un archivo por pista) — confirmado en el propio
    # código fuente (tools/util.py, image_types) y en ejemplos reales de
    # uso ("gw read --format=raw.250 disco.scp"). .scp guarda el flujo
    # completo del disco en un solo archivo, más práctico aquí.
    "raw_125": ".scp", "raw_250": ".scp", "raw_500": ".scp",
}

# Qué formatos tiene sentido ofrecer según el sistema desde el que se
# abre el diálogo: mostrar aquí "1,6 MB (SMD/SWC)" para MSX, o "360 KB
# (MSX)" para SNES/Genesis, solo confundiría sin aportar nada, ya que
# esos formatos nunca se usan en el sistema contrario. "raw" tiene
# sentido en cualquier sistema: es la vía de último recurso para un
# disco que no encaja en ningún formato conocido.
FORMATOS_POR_SISTEMA = {
    "msx":     ["360", "720", "msx_1d", "msx_1dd", "msx_2d", "msx_2dd",
                "ibm_720", "ibm_1440", "amstrad_cpc", "amiga_dd", "c64",
                "atarist", "zx_plus3", "ibm_scan", "raw_125", "raw_250", "raw_500"],
    "snes":    ["720", "800", "1440", "1600",
                "ibm_720", "ibm_1440", "amstrad_cpc", "amiga_dd", "c64",
                "atarist", "zx_plus3", "ibm_scan", "raw_125", "raw_250", "raw_500"],
    "genesis": ["720", "800", "1440", "1600",
                "ibm_720", "ibm_1440", "amstrad_cpc", "amiga_dd", "c64",
                "atarist", "zx_plus3", "ibm_scan", "raw_125", "raw_250", "raw_500"],
}

# Formato preseleccionado al abrir el diálogo, para no obligar a
# buscarlo entre 17 opciones cada vez: el más habitual en la práctica
# para cada sistema. Para MSX, "msx.2dd" (720 KB, doble cara, doble
# densidad) es el que confirmó funcionar con hardware real durante el
# desarrollo — con diferencia el formato de disquete MSX más común.
FORMATO_POR_DEFECTO = {
    "msx": "msx_2dd",
    "snes": "1600",
    "genesis": "1600",
}

# Cilindros y cabezas de cada formato, para poder calcular una pista
# absoluta (cilindro*cabezas + cabeza) que avanza SIEMPRE sin repetirse
# ni retroceder, con la que alimentar un contador que "progresa" de
# verdad en la interfaz — a diferencia del recuento de sectores de la
# pista actual, que puede perfectamente repetir el mismo valor durante
# varias líneas seguidas (varios reintentos de la misma pista, o varias
# pistas seguidas sin ningún problema) sin que eso sea ningún fallo.
# Valores confirmados contra el parser real de Greaseweazle
# (codec.get_diskdef) al integrar cada formato.
GEOMETRIA_FORMATO = {
    "360": (80, 1), "720": (80, 2), "800": (80, 2), "1440": (80, 2), "1600": (80, 2),
    "msx_1d": (40, 1), "msx_1dd": (80, 1), "msx_2d": (40, 2), "msx_2dd": (80, 2),
    "ibm_720": (80, 2), "ibm_1440": (80, 2), "amstrad_cpc": (40, 1),
    "amiga_dd": (80, 2), "c64": (40, 1), "atarist": (80, 2), "zx_plus3": (40, 1),
    "ibm_scan": (80, 2), "raw_125": (81, 2), "raw_250": (81, 2), "raw_500": (81, 2),
}


def find_gw(explicit_path: str | None = None) -> str | None:
    """Localiza el ejecutable de Greaseweazle (gw). Devuelve la ruta o None."""
    if explicit_path:
        if os.path.isfile(explicit_path) and os.access(explicit_path, os.X_OK):
            return explicit_path
        return None
    for name in ("gw", "gw.exe"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in ("/usr/local/bin/gw", "/usr/bin/gw",
                       os.path.expanduser("~/bin/gw"),
                       os.path.expanduser("~/.local/bin/gw")):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def diskdefs_path(app_base_dir: str) -> str:
    """Ruta al archivo de definiciones de disco propio, empaquetado con la
    app en data/ (ver asturconsole.spec: se incluye igual que assets/)."""
    return os.path.join(app_base_dir, "data", "greaseweazle_diskdefs.cfg")


def build_write_command(gw_path: str, diskdefs: str, formato: str,
                         image_path: str) -> list[str]:
    """Escribe una imagen EN el disco físico: gw write --format=... <imagen>"""
    return [gw_path, "write", f"--diskdefs={diskdefs}",
            f"--format={FORMATOS[formato]}", image_path]


def asegurar_extension_valida(ruta: str, formato: str) -> str:
    """Corrige la ruta de destino si le falta una extensión que gw
    reconozca, o si tiene una que no reconoce en absoluto — gw se niega
    en seco con "Unrecognised file suffix" antes de tocar el hardware
    para nada, incluso al leer, así que esto se comprueba y corrige
    ANTES de lanzar el proceso en vez de confiar en que el usuario
    siempre teclee (o conserve, al editar el nombre sugerido) una
    extensión válida.
    """
    _, ext = os.path.splitext(ruta)
    if ext.lower() in EXTENSIONES_VALIDAS_GW:
        return ruta
    return ruta + EXTENSION_FORMATO.get(formato, ".img")


def build_read_command(gw_path: str, diskdefs: str, formato: str,
                        image_path: str) -> list[str]:
    """Lee el disco físico A una imagen: gw read --format=... <imagen>"""
    return [gw_path, "read", f"--diskdefs={diskdefs}",
            f"--format={FORMATOS[formato]}", image_path]


HARDWARE_NOTICE = (
    "Greaseweazle es un dispositivo USB independiente (no viene incluido "
    "con ASTURCONSOLE) que se conecta, por un lado, al PC por USB, y por "
    "el otro —con un cable plano de 34 pines— a una disquetera física "
    "tradicional de 3,5\".\n"
    "\n"
    "El propio dispositivo se detecta solo por USB: no hace falta indicar "
    "ningún puerto ni configurar nada adicional, basta con tenerlo "
    "conectado y encendido antes de empezar.\n"
    "\n"
    "A diferencia de un simple lector USB de disquetes (limitado a los "
    "formatos de fábrica, 720 KB / 1,44 MB), Greaseweazle trabaja a nivel "
    "de flujo magnético: puede leer y escribir también los formatos "
    "\"superformateados\" propios del Super Magic Drive / Super Wild Card "
    "(800 KB y 1,6 MB), igual que una disquetera física tradicional.\n"
    "\n"
    "Más información y dónde conseguirlo: "
    "https://github.com/keirf/greaseweazle/wiki"
)
