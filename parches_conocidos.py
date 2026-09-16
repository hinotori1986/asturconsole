"""Base de datos de parches conocidos, por juego — para decidir qué
casillas de "parches al vuelo" pre-marcar en la ventana de transferencia
SIN depender de ejecutar los patrones de búsqueda binaria sobre el ROM
para ver si "coinciden" (eso puede dar falsos positivos: por ejemplo, un
patrón de 3 bytes de detección de SlowROM que coincidió por pura
casualidad en un punto cualquiera de un ROM de varios megabytes, sin que
el juego tuviera relación real con esa protección).

En su lugar, este módulo identifica el juego de forma fiable (por su
CRC32, el mismo que ya se calcula en otras partes de la aplicación) y
consulta una lista curada de qué parches le hacen falta de verdad,
verificados uno a uno — no una heurística genérica aplicada a ciegas.

Mientras la lista de abajo esté vacía (o no contenga el juego en
cuestión), TODAS las casillas de parches empiezan desmarcadas por
defecto: es preferible no marcar nada a marcar algo por una coincidencia
casual — el usuario conserva siempre el control manual completo.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParchesConocidos:
    crack: bool = False       # SNES: -k, quitar protección anti-copia
    pal: bool = False         # SNES: -f, corregir NTSC/PAL
    slowrom: bool = False     # SNES: -l, quitar comprobación SlowROM
    checksum: bool = False    # SNES y Genesis: --chk, corregir checksum
    region: bool = False      # Genesis: -f, quitar protección regional (NTSC/PAL)
    notas: str = ""


# Clave: CRC32 del ROM en hexadecimal, minúsculas, sin "0x" — se calcula
# sobre el cuerpo del ROM sin cabecera de copiador (el mismo criterio que
# usa el resto de la aplicación al analizar ROMs). Se indexa por CRC32 y
# no por nombre de archivo porque el nombre no es fiable (puede venir
# renombrado, con o sin región/idioma indicados, etc.) — el CRC32 del
# contenido sí identifica el volcado exacto de forma inequívoca.
SNES: dict[str, ParchesConocidos] = {
    # "a1b2c3d4": ParchesConocidos(crack=True, pal=True,
    #                               notas="Donkey Kong Country (Europe)"),
}

GENESIS: dict[str, ParchesConocidos] = {
    # "a1b2c3d4": ParchesConocidos(region=True, checksum=True,
    #                               notas="Ejemplo"),
}


def buscar(sistema: str, crc32_hex: str) -> ParchesConocidos:
    """Devuelve los parches conocidos para este CRC32 exacto, o una
    entrada vacía (todo desmarcado) si el juego no está en la lista."""
    tabla = SNES if sistema == "snes" else GENESIS if sistema == "genesis" else {}
    return tabla.get(crc32_hex.lower(), ParchesConocidos())
