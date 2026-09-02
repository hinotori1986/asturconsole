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
FORMATOS = {
    "360":  "asturconsole.360",
    "720":  "asturconsole.720",
    "800":  "asturconsole.800",
    "1440": "asturconsole.1440",
    "1600": "asturconsole.1600",
}

NOMBRE_FORMATO = {
    "360":  "360 KB (cara simple MSX)",
    "720":  "720 KB (3,5\" DD, estándar)",
    "800":  "800 KB (superformateado, SMD/SWC)",
    "1440": "1,44 MB (3,5\" HD, estándar)",
    "1600": "1,6 MB (superformateado, SMD/SWC)",
}

# Qué formatos tiene sentido ofrecer según el sistema desde el que se
# abre el diálogo: mostrar aquí "1,6 MB (SMD/SWC)" para MSX, o "360 KB
# (MSX)" para SNES/Genesis, solo confundiría sin aportar nada, ya que
# esos formatos nunca se usan en el sistema contrario.
FORMATOS_POR_SISTEMA = {
    "msx":     ["360", "720"],
    "snes":    ["720", "800", "1440", "1600"],
    "genesis": ["720", "800", "1440", "1600"],
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
