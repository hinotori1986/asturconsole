"""Motor de "cracks" de protección anti-copia para ROMs SNES.

Reimplementa en Python el mecanismo que usa la opción -k de uCON64
(console/snes.c:snes_k — GPL, dbjh y colaboradores, ver license.html de
esa distribución): busca patrones de bytes conocidos —secuencias de
código que comprueban cuánta SRAM tiene la consola como protección
anti-copia— y los sustituye por una versión que no hace esa comprobación.

Los patrones de abajo (PATRONES_BASE, más los dos grupos que dependen de
si la SRAM del juego es de 8 KB) son una traducción literal, patrón a
patrón, de los que trae el código fuente de uCON64: NO vienen del archivo
data/snescopy.txt, que por defecto trae casi todos comentados (son ahí
solo referencia/documentación de estos mismos patrones, para quien quiera
además añadir otros propios sin tocar código — ver cargar_patrones_extra).

- Un byte de la búsqueda marcado como *wildcard* (0x2A, '*') coincide con
  CUALQUIER byte.
- Un byte marcado como *escape* (0x21, '!') coincide solo si el byte real
  está en el "set" correspondiente (los sets se consumen en el orden en
  que aparecen las apariciones de escape en la búsqueda).
- El reemplazo se escribe en (fin_de_la_búsqueda + offset); offset puede
  ser negativo.

IMPORTANTE — por qué esto suele ser innecesario ahora: en la mayoría de
los casos el problema de fondo no es el código del juego en sí, sino que
la cabecera del copión declaraba siempre 32 KB de SRAM (ver
snes_tools.make_swc_header): con el tamaño real ya corregido ahí, muchos
juegos que antes "necesitaban crack" funcionan sin tocarles ni un byte —
confirmado con hardware real (Breath of Fire II). Este motor sigue siendo
útil para los casos que de verdad lo requieran, o para quien prefiera
aplicarlo de todas formas.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

WILDCARD = 0x2A  # '*'
ESCAPE = 0x21    # '!'

_S89 = b"\x8f\x9f"      # sta $70YYXX / sta $70YYXX,x
_SCD = b"\xcf\xdf"      # cmp $70YYXX / cmp $70YYXX,x
_SAB = b"\xaf\xbf"      # lda absoluto / absoluto,x
_BANCOS = b"\x30\x31\x32\x33"  # bancos de SRAM habituales 30-33

# Los tres primeros dependen de si el juego usa 8 KB de SRAM o no — mismo
# patrón de búsqueda, reemplazo distinto según el caso.
PATRONES_SEGUN_SRAM_8KB = [
    (bytes([ESCAPE, WILDCARD, WILDCARD, 0x70, ESCAPE, WILDCARD, WILDCARD, 0x70, 0xD0]),
     b"\xea\xea", 0, [_S89, _SCD], ""),
    (bytes([ESCAPE, WILDCARD, WILDCARD, 0x70, ESCAPE, WILDCARD, WILDCARD, 0x70, 0xF0]),
     b"\x80", 0, [_S89, _SCD], "Kirby's Dream Course, Lufia II - Rise of the Sinistrals"),
    (bytes([ESCAPE, WILDCARD, WILDCARD, ESCAPE, ESCAPE, WILDCARD, WILDCARD, ESCAPE, 0xF0]),
     b"\x80", 0, [_S89, _BANCOS, _SCD, _BANCOS], ""),
]
PATRONES_SEGUN_SRAM_OTRO = [
    (bytes([ESCAPE, WILDCARD, WILDCARD, 0x70, ESCAPE, WILDCARD, WILDCARD, 0x70, 0xD0]),
     b"\x80", 0, [_S89, _SCD], ""),
    (bytes([ESCAPE, WILDCARD, WILDCARD, 0x70, ESCAPE, WILDCARD, WILDCARD, 0x70, 0xF0]),
     b"\xea\xea", 0, [_S89, _SCD], "Mega Man X"),
    (bytes([ESCAPE, WILDCARD, WILDCARD, ESCAPE, ESCAPE, WILDCARD, WILDCARD, ESCAPE, 0xF0]),
     b"\xea\xea", 0, [_S89, _BANCOS, _SCD, _BANCOS], ""),
]

# El resto se aplica siempre, sin depender del tamaño de SRAM.
PATRONES_BASE = [
    (bytes([0x8F, WILDCARD, WILDCARD, 0x77, 0xE2, WILDCARD, 0xAF, WILDCARD, WILDCARD,
            0x77, 0xC9, WILDCARD, 0xF0]),
     b"\x80", 0, [], "Uniracers/Unirally"),
    (bytes([ESCAPE] * 6 + [0x60, ESCAPE, 0xD0]),
     b"\xea\xea", 0, [_S89, b"\x57\x59", b"\x60\x68", _BANCOS, _SCD, b"\x57\x59", _BANCOS],
     "Donkey Kong Country (8f, 30, cf, 30)"),
    (bytes([ESCAPE, WILDCARD, WILDCARD, ESCAPE, ESCAPE, WILDCARD, WILDCARD, ESCAPE, 0xD0]),
     b"\x80", 0, [_S89, _BANCOS, _SCD, _BANCOS], ""),
    (bytes([ESCAPE, WILDCARD, WILDCARD, 0xB0, 0xCF, WILDCARD, WILDCARD, 0xB1, 0xD0]),
     b"\xea\xea", 0, [b"\x8f\xaf"], "Mario no Super Picross"),
    (bytes([ESCAPE, WILDCARD, WILDCARD, ESCAPE, 0xAF, WILDCARD, WILDCARD, ESCAPE, 0xC9,
            WILDCARD, WILDCARD, 0xD0]),
     b"\x80", 0, [_S89, _BANCOS, _BANCOS], ""),
    (b"\xa9\x00\x00\xa2\xfe\x1f\xdf\x00\x00\x70\xd0",
     b"\xea\xea", 0, [], "Super Metroid"),
    (bytes([0x8F, WILDCARD, WILDCARD, 0x70, 0xAF, WILDCARD, WILDCARD, 0x70, 0xC9,
            WILDCARD, WILDCARD, 0xD0]),
     b"\x80", 0, [], "Tetris Attack (genérico)"),
    (bytes([ESCAPE, WILDCARD, WILDCARD, ESCAPE, ESCAPE, WILDCARD, WILDCARD, ESCAPE, 0xF0]),
     b"\x80", 0, [_SAB, _BANCOS, _SCD, _BANCOS], "Breath of Fire II (bf, 30, df, 31)"),
    (bytes([ESCAPE, WILDCARD, 0x80, 0x00, ESCAPE, WILDCARD, 0x80, 0x40, 0xF0]),
     b"\x80", 0, [_SAB, _SCD], "Mega Man X (mirroring)"),
    (bytes([ESCAPE, WILDCARD, 0xFF, ESCAPE, ESCAPE, WILDCARD, 0xFF, 0x40, 0xF0]),
     b"\x80", 0, [_SAB, b"\x80\xc0", _SCD], "Demon's Crest / Breath of Fire II"),
    (b"\x5c\x7f\xd0\x83\x18\xfb\x78\xc2\x30",
     b"\xea" * 9, -8, [], "Killer Instinct"),
    (b"KONG\x00\xf8\xf7",
     b"\xf8", 0, [], "Diddy's Kong Quest"),
    (b"\x26\x38\xe9\x48\x12\xc9\xaf\x71\xf0",
     b"\x80", 0, [], "Diddy's Kong Quest"),
    (b"\xa0\x5c\x2f\x77\x32\xe9\xc7\x04\xf0",
     b"\x80", 0, [], "Diddy's Kong Quest"),
    (b"\x22\x08\x5c\x10\xb0\x28",
     b"\xea" * 6, -5, [], "BS The Legend of Zelda Remix"),
    (b"\xda\xe2\x30\xc9\x01\xf0\x18\xc9\x02",
     b"\x09\xf0\x18\xc9\x07", -4, [], "BS The Legend of Zelda Remix (música)"),
    (b"\x29\xff\x00\xc9\x07\x00\x90\x16",
     b"\x00", -3, [], "BS The Legend of Zelda Remix (música)"),
    (b"\xca\x10\xf8\x38\xef\x1a\x80\x81\x8d",
     b"\x9c", 0, [], "Kirby's Dream Course"),
    (b"\x81\xca\x10\xf8\xcf\x39\x80\x87\xf0",
     b"\x80", 0, [], "Kirby's Dream Course"),
    (b"\x84\x26\xad\x39\xb5\xd0\x1a",
     b"\xea\xea", -1, [], "Earthbound"),
    (b"\x10\xf8\x38\xef\xef\xff\xc1",
     b"\xea\xa9\x00\x00", -3, [], "Earthbound"),
    (b"\x10\xf8\x38\xef\xf2\xfd\xc3\xf0",
     b"\xea\xa9\x00\x00\x80", -4, [], "Earthbound"),
    (b"\xc2\x30\xad\xfc\x1f\xc9\x50\x44\xd0",
     b"\x4c\xd1\x80", -6, [], "Tetris Attack"),
    (b"\xa9\xc3\x80\xdd\xff\xff\xf0\x6c",
     b"\xf0\xcc\xff\xff\x80\x7d", -5, [], "Dixie Kong's Double Trouble (E)"),
    (b"\xd0\xf4\xab\xcf\xae\xff\x00\xd0\x01",
     b"\x00", 0, [], "Front Mission - Gun Hazard"),
]


@dataclass
class Patron:
    search: bytes
    replace: bytes
    offset: int
    sets: list = field(default_factory=list)
    descripcion: str = ""
    wildcard: int = WILDCARD
    escape: int = ESCAPE


def patrones_para(sram_size: int) -> list:
    """Los patrones aplicables para un juego con este tamaño de SRAM (en
    bytes) — los tres primeros varían según sea 8 KB o no, el resto es
    siempre igual."""
    base = PATRONES_SEGUN_SRAM_8KB if sram_size == 8 * 1024 else PATRONES_SEGUN_SRAM_OTRO
    todos = base + PATRONES_BASE
    return [Patron(s, r, o, sets, desc) for s, r, o, sets, desc in todos]


def _base_dir() -> str:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


def _bytes_de_campo(campo: str) -> bytes:
    return bytes(int(tok, 16) for tok in campo.split())


def _parsear_linea_extra(cuerpo: str) -> "Patron | None":
    campos = cuerpo.split(":")
    if len(campos) < 5:
        return None
    try:
        search = _bytes_de_campo(campos[0])
        wildcard = int(campos[1].strip(), 16)
        escape = int(campos[2].strip(), 16)
        replace = _bytes_de_campo(campos[3])
        offset = int(campos[4].strip())
        sets = [_bytes_de_campo(c) for c in campos[5:] if c.strip()]
    except ValueError:
        return None
    if not search:
        return None
    return Patron(search, replace, offset, sets, wildcard=wildcard, escape=escape)


def cargar_patrones_extra(ruta: "str | None" = None) -> list:
    """Patrones ADICIONALES desde data/snescopy.txt, más allá de los ya
    incluidos en PATRONES_BASE: por defecto ese archivo trae casi todo
    comentado (es la copia de referencia de uCON64, pensada para que se
    descomente o se añadan patrones propios sin tocar código Python) —
    esta función solo recoge lo que esté activo de verdad.
    """
    if ruta is None:
        ruta = os.path.join(_base_dir(), "data", "snescopy.txt")
    patrones = []
    descripcion_actual = ""
    try:
        with open(ruta, encoding="utf-8", errors="replace") as fh:
            for linea_bruta in fh:
                linea = linea_bruta.rstrip("\n\r")
                cuerpo = linea.split("#", 1)[0]
                if not cuerpo.strip():
                    comentario = linea.strip().lstrip("#").strip()
                    if comentario and not comentario[:1].isdigit():
                        descripcion_actual = comentario
                    continue
                patron = _parsear_linea_extra(cuerpo)
                if patron is not None:
                    patron.descripcion = patron.descripcion or descripcion_actual
                    patrones.append(patron)
    except OSError:
        pass
    return patrones


def _coincide_en(datos, pos: int, patron: Patron) -> bool:
    """¿Coincide el patrón completo empezando en la posición `pos`?"""
    n = len(patron.search)
    if pos + n > len(datos):
        return False
    indice_set = 0
    for i in range(n):
        b_patron = patron.search[i]
        b_real = datos[pos + i]
        if b_patron == patron.wildcard:
            continue  # cualquier byte vale aquí
        if b_patron == patron.escape:
            conjunto = patron.sets[indice_set] if indice_set < len(patron.sets) else b""
            indice_set += 1
            if b_real not in conjunto:
                return False
            continue
        if b_real != b_patron:
            return False
    return True


def aplicar_patron(datos: bytearray, patron: Patron) -> int:
    """Aplica un único patrón sobre `datos`, EN EL SITIO (in-place).
    Devuelve cuántas veces se encontró y aplicó.

    Antes esto recorría el archivo posición a posición con un bucle en
    Python puro — para un ROM de varios MB, multiplicado por los ~38
    patrones que se prueban en cada archivo, se notaba claramente como
    lentitud en la interfaz (mucho más que dividir el mismo ROM en
    varios discos, que no pasa por aquí). Ahora se usa bytearray.find()
    —implementado en C, mucho más rápido— para saltar directamente a las
    posiciones donde coincide el primer byte FIJO del patrón (el primero
    que no sea comodín ni escape), y solo ahí se comprueba el patrón
    completo con _coincide_en(), en vez de probarlo en cada posición del
    archivo. El resultado es exactamente el mismo, byte a byte — se
    verificó comparando ambas implementaciones sobre los patrones reales
    del proyecto antes de sustituir la anterior.
    """
    n = len(patron.search)
    limite = len(datos) - n
    if limite < 0:
        return 0

    ancla_offset = None
    for i, b_patron in enumerate(patron.search):
        if b_patron != patron.wildcard and b_patron != patron.escape:
            ancla_offset = i
            break

    aplicados = 0
    if ancla_offset is None:
        # patrón sin ningún byte fijo (caso raro: todo comodines/escapes):
        # no hay nada con lo que anclar find(), recurre al barrido de siempre
        pos = 0
        while pos <= limite:
            if _coincide_en(datos, pos, patron):
                destino = pos + n + patron.offset
                fin = destino + len(patron.replace)
                if 0 <= destino and fin <= len(datos):
                    datos[destino:fin] = patron.replace
                    aplicados += 1
                pos += n
            else:
                pos += 1
        return aplicados

    ancla_byte = patron.search[ancla_offset]
    pos = 0
    while pos <= limite:
        idx = datos.find(ancla_byte, pos + ancla_offset, limite + ancla_offset + 1)
        if idx == -1:
            break
        candidato = idx - ancla_offset
        if _coincide_en(datos, candidato, patron):
            destino = candidato + n + patron.offset
            fin = destino + len(patron.replace)
            if 0 <= destino and fin <= len(datos):
                datos[destino:fin] = patron.replace
                aplicados += 1
            pos = candidato + n  # seguir buscando después de esta coincidencia
        else:
            pos = candidato + 1
    return aplicados


def aplicar_crack(datos: bytes, sram_size: int = 32 * 1024,
                  incluir_extra: bool = False) -> tuple:
    """Aplica todos los patrones conocidos de -k sobre `datos` (trabaja
    sobre una copia; el original no se modifica).

    `incluir_extra`: si se activa, añade también los patrones de
    data/snescopy.txt que estén descomentados — por defecto False porque
    el único que trae activo de fábrica ese archivo es, según su propio
    comentario, "para Super Flash, no para Super Wild Card... mejor
    aplicarlo con --pattern, no con -k" — incluirlo sin que el usuario lo
    pida podría interferir sin aportar nada, si el copión es un SWC.

    Devuelve (datos_parcheados, lista_de_cambios) — la lista describe qué
    patrones se llegaron a aplicar y cuántas veces cada uno; vacía si no
    se encontró ninguna coincidencia (nada que "crackear" en este ROM).
    """
    patrones = patrones_para(sram_size)
    if incluir_extra:
        patrones = cargar_patrones_extra() + patrones  # mayor precedencia, como en uCON64
    buf = bytearray(datos)
    cambios = []
    for patron in patrones:
        n = aplicar_patron(buf, patron)
        if n:
            desc = patron.descripcion or f"patrón sin descripción ({patron.search.hex()})"
            cambios.append(f"{desc}  (×{n})" if n > 1 else desc)
    return bytes(buf), cambios


# ---------------------------------------------------------------------------
# Corrección de protección NTSC/PAL (equivalente a la opción -f de uCON64,
# console/snes.c:snes_fix_pal_protection): algunos juegos PAL comprueban el
# estándar de vídeo de la consola y se detienen si no es el que esperan —
# el copión, al no imitar exactamente una consola PAL real, dispara esa
# comprobación. Son patrones de código totalmente distintos de los de -k
# (protección de SRAM): un mismo juego puede necesitar uno, otro, o ambos
# — es el caso real de Donkey Kong Country (E), confirmado con hardware:
# la lista de compatibilidad solo documentaba "needs crack", pero el
# patrón de esta función también coincide en el ROM real.
_W1, _E2 = 0x01, 0x02  # wildcard/escape propios de estos patrones (distintos de -k)

PATRONES_PAL = [
    (b"\xad\x3f\x21\x89\x10\xd0", b"\x80", 0, [], _W1, _E2, "Terranigma"),
    (b"\xad\x3f\x21\x89\x10\xf0", b"\xea\xea", 0, [], _W1, _E2, "Super Metroid (E)"),
    (b"\xad\x3f\x21\x29\x10\x00\xd0", b"\x80", 0, [], _W1, _E2, ""),
    (b"\xad\x3f\x21\x89\x10\x00\xd0", b"\xa9\x10\x00", -6, [], _W1, _E2, "Eric Cantona Football?"),
    (bytes([0xad, 0x3f, 0x21, 0x89, 0x10, 0xc2, _W1, 0xf0]),
     b"\xea\xea", 0, [], _W1, _E2, "Soul Blazer (F/G)"),
    (bytes([0xad, 0x3f, 0x21, 0x29, 0x10, 0xcf, 0xbd, 0xff, _W1, 0xf0]),
     b"\x80", 0, [], _W1, _E2, "Pop'n Twinbee (E)"),
    (b"\xaf\x3f\x21\x00\x29\x10\xd0", b"\x80", 0, [], _W1, _E2, ""),
    (b"\xaf\x3f\x21\x00\x29\x10\x00\xd0", b"\xea\xea", 0, [], _W1, _E2, ""),
    (bytes([0xaf, 0x3f, 0x21, 0x00, 0x29, _W1, 0xc9, _W1, 0xf0]),
     b"\x80", 0, [], _W1, _E2, "Secret of Mana (E)"),
    (b"\xa2\x18\x01\xbd\x27\x20\x89\x10\x00\xf0\x01",
     b"\xea\xea", -1, [], WILDCARD, ESCAPE, "Donkey Kong Country (E)"),
]


def aplicar_fix_pal(datos: bytes) -> tuple:
    """Aplica los patrones de corrección NTSC/PAL (-f de uCON64) sobre
    `datos` (trabaja sobre una copia; el original no se modifica).

    Devuelve (datos_parcheados, lista_de_cambios), igual que aplicar_crack.
    """
    buf = bytearray(datos)
    cambios = []
    for search, replace, offset, sets, wildcard, escape, desc in PATRONES_PAL:
        patron = Patron(search, replace, offset, sets, desc, wildcard, escape)
        n = aplicar_patron(buf, patron)
        if n:
            texto = desc or f"patrón sin descripción ({search.hex()})"
            cambios.append(f"{texto}  (×{n})" if n > 1 else texto)
    return bytes(buf), cambios
