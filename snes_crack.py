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
import zlib
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
     b"\xea\xea", -1, [_S89, _SCD], ""),
    (bytes([ESCAPE, WILDCARD, WILDCARD, 0x70, ESCAPE, WILDCARD, WILDCARD, 0x70, 0xF0]),
     b"\x80", -1, [_S89, _SCD], "Kirby's Dream Course, Lufia II - Rise of the Sinistrals"),
    (bytes([ESCAPE, WILDCARD, WILDCARD, ESCAPE, ESCAPE, WILDCARD, WILDCARD, ESCAPE, 0xF0]),
     b"\x80", -1, [_S89, _BANCOS, _SCD, _BANCOS], ""),
]
PATRONES_SEGUN_SRAM_OTRO = [
    (bytes([ESCAPE, WILDCARD, WILDCARD, 0x70, ESCAPE, WILDCARD, WILDCARD, 0x70, 0xD0]),
     b"\x80", -1, [_S89, _SCD], ""),
    (bytes([ESCAPE, WILDCARD, WILDCARD, 0x70, ESCAPE, WILDCARD, WILDCARD, 0x70, 0xF0]),
     b"\xea\xea", -1, [_S89, _SCD], "Mega Man X"),
    (bytes([ESCAPE, WILDCARD, WILDCARD, ESCAPE, ESCAPE, WILDCARD, WILDCARD, ESCAPE, 0xF0]),
     b"\xea\xea", -1, [_S89, _BANCOS, _SCD, _BANCOS], ""),
]

# El resto se aplica siempre, sin depender del tamaño de SRAM.
# CONVENCIÓN DE OFFSET (ojo): el reemplazo se escribe en
#     posición_de_la_coincidencia + len(búsqueda) + offset
# y el offset de cada entrada está medido EXACTAMENTE como lo hace uCON64
# (0 = justo después del último byte de la búsqueda; -1 = sobre el propio último byte).
# Las entradas de abajo estuvieron un byte desplazadas (+1) respecto a uCON64 -k
# hasta la v1.9.8: el reemplazo caía sobre el operando en vez de sobre el
# opcode (p. ej. Super Bases Loaded 3: «BNE +0C» quedaba como «BNE -22» en
# lugar de neutralizarse, y la comprobación de SRAM seguía activa en el
# Super Wild Card). Corregido comparando, entrada por entrada, con uCON64 -k
# sobre ROMs sintéticas y reales. (Las dos de «Donkey Kong Country» ya se
# habían corregido a mano antes y se dejan como estaban.)
PATRONES_BASE = [
    (bytes([0x8F, WILDCARD, WILDCARD, 0x77, 0xE2, WILDCARD, 0xAF, WILDCARD, WILDCARD,
            0x77, 0xC9, WILDCARD, 0xF0]),
     b"\x80", -1, [], "Uniracers/Unirally"),
    # ADVERTENCIA: mismo bug de base que ya corregimos varias veces esta
    # sesión (Art of Fighting, GP-1, GP-1 Part II) -- offset=0 aquí deja
    # el opcode D0 intacto y el reemplazo "EA EA" cae sobre el operando y
    # el byte siguiente, sin neutralizar el BNE en absoluto (solo lo
    # convierte en un salto con desplazamiento fijo -22, un destino
    # arbitrario no verificado). Confirmado con Donkey Kong Country (E)
    # Rev1: el test de SRAM seguía activo tras "aplicar" este parche.
    # Corregido a offset=-1, para que el reemplazo caiga sobre el propio
    # D0 y su operando, neutralizando el BNE por completo.
    (bytes([ESCAPE] * 6 + [0x60, ESCAPE, 0xD0]),
     b"\xea\xea", -1, [_S89, b"\x57\x59", b"\x60\x68", _BANCOS, _SCD, b"\x57\x59", _BANCOS],
     "Donkey Kong Country (8f, 30, cf, 30)"),
    # ADVERTENCIA: coincide con la misma zona que el patrón específico de
    # "Donkey Kong Country" de arriba (ambos terminan en D0, con sets
    # compatibles) -- antes tenía reemplazo "80" con offset=0, que solo
    # toca el OPERANDO del BNE dejando el opcode D0 intacto (0x80 no es
    # cero, es un salto real de -128). Al aplicarse los dos patrones en
    # secuencia sobre el mismo sitio, el resultado quedaba a medias (el
    # opcode ya convertido a NOP por el específico, pero el operando
    # sobrescrito de nuevo por este). Corregido a la misma técnica segura
    # usada arriba: reemplazo "EA EA" con offset=-1, que cae sobre el
    # propio D0 y su operando, neutralizando el BNE por completo sea cual
    # sea el desplazamiento original -- confirmado con Donkey Kong
    # Country (E) Rev1, sin depender ya del orden de aplicación entre
    # los dos patrones.
    (bytes([ESCAPE, WILDCARD, WILDCARD, ESCAPE, ESCAPE, WILDCARD, WILDCARD, ESCAPE, 0xD0]),
     b"\xea\xea", -1, [_S89, _BANCOS, _SCD, _BANCOS], ""),
    (bytes([ESCAPE, WILDCARD, WILDCARD, 0xB0, 0xCF, WILDCARD, WILDCARD, 0xB1, 0xD0]),
     b"\xea\xea", -1, [b"\x8f\xaf"], "Mario no Super Picross"),
    (bytes([ESCAPE, WILDCARD, WILDCARD, ESCAPE, 0xAF, WILDCARD, WILDCARD, ESCAPE, 0xC9,
            WILDCARD, WILDCARD, 0xD0]),
     b"\x80", -1, [_S89, _BANCOS, _BANCOS], ""),
    (b"\xa9\x00\x00\xa2\xfe\x1f\xdf\x00\x00\x70\xd0",
     b"\xea\xea", -1, [], "Super Metroid"),
    (bytes([0x8F, WILDCARD, WILDCARD, 0x70, 0xAF, WILDCARD, WILDCARD, 0x70, 0xC9,
            WILDCARD, WILDCARD, 0xD0]),
     b"\x80", -1, [], "Tetris Attack (genérico)"),
    (bytes([ESCAPE, WILDCARD, WILDCARD, ESCAPE, ESCAPE, WILDCARD, WILDCARD, ESCAPE, 0xF0]),
     b"\x80", -1, [_SAB, _BANCOS, _SCD, _BANCOS], "Breath of Fire II (bf, 30, df, 31)"),
    (bytes([ESCAPE, WILDCARD, 0x80, 0x00, ESCAPE, WILDCARD, 0x80, 0x40, 0xF0]),
     b"\x80", -1, [_SAB, _SCD], "Mega Man X (mirroring)"),
    (bytes([ESCAPE, WILDCARD, 0xFF, ESCAPE, ESCAPE, WILDCARD, 0xFF, 0x40, 0xF0]),
     b"\x80", -1, [_SAB, b"\x80\xc0", _SCD], "Demon's Crest / Breath of Fire II"),
    (b"\x5c\x7f\xd0\x83\x18\xfb\x78\xc2\x30",
     b"\xea" * 9, -9, [], "Killer Instinct"),
    (b"KONG\x00\xf8\xf7",
     b"\xf8", -1, [], "Diddy's Kong Quest"),
    (b"\x26\x38\xe9\x48\x12\xc9\xaf\x71\xf0",
     b"\x80", -1, [], "Diddy's Kong Quest"),
    (b"\xa0\x5c\x2f\x77\x32\xe9\xc7\x04\xf0",
     b"\x80", -1, [], "Diddy's Kong Quest"),
    (b"\x22\x08\x5c\x10\xb0\x28",
     b"\xea" * 6, -6, [], "BS The Legend of Zelda Remix"),
    (b"\xda\xe2\x30\xc9\x01\xf0\x18\xc9\x02",
     b"\x09\xf0\x18\xc9\x07", -5, [], "BS The Legend of Zelda Remix (música)"),
    (b"\x29\xff\x00\xc9\x07\x00\x90\x16",
     b"\x00", -4, [], "BS The Legend of Zelda Remix (música)"),
    (b"\xca\x10\xf8\x38\xef\x1a\x80\x81\x8d",
     b"\x9c", -1, [], "Kirby's Dream Course"),
    (b"\x81\xca\x10\xf8\xcf\x39\x80\x87\xf0",
     b"\x80", -1, [], "Kirby's Dream Course"),
    (b"\x84\x26\xad\x39\xb5\xd0\x1a",
     b"\xea\xea", -2, [], "Earthbound"),
    (b"\x10\xf8\x38\xef\xef\xff\xc1",
     b"\xea\xa9\x00\x00", -4, [], "Earthbound"),
    (b"\x10\xf8\x38\xef\xf2\xfd\xc3\xf0",
     b"\xea\xa9\x00\x00\x80", -5, [], "Earthbound"),
    (b"\xc2\x30\xad\xfc\x1f\xc9\x50\x44\xd0",
     b"\x4c\xd1\x80", -7, [], "Tetris Attack"),
    (b"\xa9\xc3\x80\xdd\xff\xff\xf0\x6c",
     b"\xf0\xcc\xff\xff\x80\x7d", -6, [], "Dixie Kong's Double Trouble (E)"),
    (b"\xd0\xf4\xab\xcf\xae\xff\x00\xd0\x01",
     b"\x00", -1, [], "Front Mission - Gun Hazard"),
    # Samurai Shodown (Europe): DETECTOR DE COPIADORES en $DF:483A (y una copia
    # idéntica en $C2:0000 que el juego compara con la primera en $C2:0039 para
    # detectar manipulaciones). Escribe en $C0:1AC3, $FA:5678 y $33:6000
    # (en HiROM, SRAM) y relee: si el valor se guarda -- lo que pasa en un
    # Super Wild Card, que siempre tiene SRAM y ROM escribible -- la rutina se
    # repite sin fin (pantalla negra). En el emulador la escritura no hace
    # nada. Se corta la rutina con RTL (C2 -> 6B) EN LAS DOS COPIAS: si solo se
    # tocara una, la comparación posterior bloquearía el juego igualmente.
    # CONFIRMADO por el usuario en hardware real. uCON64 -k no lo detecta.
    (bytes([0xC2, 0x20, 0xA9, 0x12, 0xFF, 0x8F, 0xC3, 0x1A, 0xC0, 0xAF, 0xC3, 0x1A,
            0xC0, 0xC9, 0x12, 0xFF, 0xAF, 0x78, 0x56, 0xFA]),
     b"\x6b", -20, [], "Samurai Shodown (detector de copiadores)"),
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
    # Nigel Mansell's World Championship Racing (U): detecta PAL de DOS formas
    # a la vez y muestra el aviso de región si CUALQUIERA delata PAL
    # (comparando trazas reales de MesenCE, rutina en $1F:FD89):
    #     LDX #$FFFF ; STX $F8                 ($F8/$F9 = $FF si NTSC)
    #     (espera VBlank y cuenta líneas -> X)
    #     LDA $213F ; AND #$10 ; BEQ +2 ; STZ $F8      <- 1.ª: bit PAL de STAT78 ($1FFDAD)
    #     CPX #$0400 ; BCC +2 ; STZ $F9                <- 2.ª: duración del cuadro ($1FFDB4)
    # y después ($1F:A1EE): LDA $F8 ; INC ; BEQ ok  -> si no vale $FFFF, aviso.
    # uCON64 -f solo neutraliza la 1.ª (y otras lecturas de $213F); con la 2.ª
    # activa en consola PAL el aviso seguía saliendo. Se cambia BCC (90) -> BRA
    # (80), 1 byte, para que nunca se ejecute el STZ $F9.
    (bytes([0xE0, 0x00, 0x04, 0x90, 0x02, 0x64, 0xF9, 0xC2, 0x20, 0x60]),
     b"\x80", -7, [], 0xEE, 0xEF, "Nigel Mansell's World Championship Racing (U)"),
    # Claymates (U): lectura directa del flag PAL en $CC:834C (único acceso a
    # $213F del ROM; encontrado comparando trazas PAL/NTSC de MesenCE):
    #     LDA.L $00213F ; BIT #$0010 ; BEQ $CC8378 ; (aviso: estado $0B + puntero a su pantalla)
    # Si es PAL no salta y cae en la rama que dibuja «This Game Pak Is Not
    # Designed For Your Super Famicom Or Super NES». Se cambia el BEQ por BRA
    # (F0 -> 80, 1 byte). El patrón de BIT (89 10 00) es de 16 bits, por eso
    # no lo cubrían los patrones de 8 bits ni el de Ardy Lightfoot (AND).
    # Wildcard/escape 0xEE/0xEF (no aparecen en la búsqueda). Offset -2: el
    # F0 es el 8.º byte de una búsqueda de 9. Verificado en el ROM real:
    # aparece 1 sola vez y los bytes siguientes coinciden con la traza.
    (bytes([0xAF, 0x3F, 0x21, 0x00, 0x89, 0x10, 0x00, 0xF0, 0x23]),
     b"\x80", -2, [], 0xEE, 0xEF, "Claymates (U)"),
    # Clay Fighter 2 - Judgment Clay (U): detección de región por MEDICIÓN DE
    # LÍNEAS, sin leer el flag PAL de $213F (por eso ninguna búsqueda de ese
    # registro la encontraba). Rutina en $C0:0100 (una sola vez en el ROM):
    #     LDA $2137 ; LDA $213D ; XBA ; LDA $213D ; AND #$01 ; XBA   (A = línea V, 9 bits)
    #     CMP #$001E ; BNE +6 ; INX ; CPX #$0004 ; BCS ok            (cuenta 4 muestras en la línea 30)
    #     CMP #$010E ; BCC bucle                                      (si V < 270 sigue sondeando)
    #     JSL $C140B9                                                 (V >= 270: AVISO)
    #     bucle: BRA $C00100
    # Una NTSC solo tiene 262 líneas y nunca llega a 270; una PAL llega a 311,
    # así que a la primera muestra con V >= 270 sale la pantalla «This Game
    # Pak Is Not Designed For Your Super Famicom Or Super NES. -Interplay-».
    # Encontrado comparando trazas de MesenCE PAL/NTSC con la RAM en ceros
    # (la primera divergencia del hilo principal, ya sin la NMI, estaba aquí).
    # Se cambia el BCC por BRA (90 -> 80, 1 byte): una línea >= 270 ya no
    # dispara el aviso y el bucle espera igualmente a las 4 muestras de la
    # línea 30, que existe en PAL. OJO: la versión Europa NO tiene esta rutina.
    # Wildcard/escape 0xEE/0xEF (no aparecen en la búsqueda). Offset -8: el
    # byte 0x90 es el 4.º de una búsqueda de 11.
    (bytes([0xC9, 0x0E, 0x01, 0x90, 0x04, 0x22, 0xB9, 0x40, 0xC1, 0x80, 0xD9]),
     b"\x80", -8, [], 0xEE, 0xEF, "Clay Fighter 2 - Judgment Clay (U)"),
    # Clay Fighter (U) y Clay Fighter - Tournament Edition (U): detección de
    # región INDIRECTA, por eso ninguna búsqueda de «3F 21» la encontraba:
    #     LDX #$20F9 ; LDA $45,X ; AND #$1000 ; CMP #$1000 ; JSR ...
    # con D=0, $45 + $20F9 = $213E: es una lectura de 16 bits de STAT77 y
    # STAT78 a la vez, y el AND #$1000 aísla el bit 4 de $213F (PAL). El
    # resultado vuelve en los flags (Z/C) y acaba cambiando el estado de un
    # objeto del motor del juego, que dibuja con sprites la pantalla «This
    # Game Pak Is Not Designed For Your Super Famicom Or Super NES. -Interplay-».
    # Encontrado comparando dos trazas de MesenCE (PAL vs NTSC) del mismo ROM.
    # Se cambia el 0x10 del inmediato (AND #$1000 -> AND #$0000): A=0, y el
    # CMP #$1000 deja exactamente los mismos flags que la traza NTSC
    # (NvmxdIzc). Un solo byte. OJO: la búsqueda no contiene 0xEE/0xEF, por
    # eso van como comodín/escape. Offset -5: el byte es el 8.º de 12.
    (bytes([0xA2, 0xF9, 0x20, 0xB5, 0x45, 0x29, 0x00, 0x10, 0xC9, 0x00, 0x10, 0x20]),
     b"\x00", -5, [], 0xEE, 0xEF, "Clay Fighter (U)"),
    # ADVERTENCIA (mismo tipo de hallazgo): el patrón de "Terranigma" de
    # abajo pone el desplazamiento del BNE a un valor fijo ("0x80" = -128,
    # salto hacia atrás), específico de dónde cae ese salto en la propia
    # estructura de Terranigma. Coincidió también con GP-1 (U) y Mighty
    # Max (U), misma búsqueda de 6 bytes -- en ambos ese mismo destino no
    # es el camino correcto (en GP-1 cae en medio de una reinicialización
    # ya ejecutada; en Mighty Max cae directamente en datos/basura, ya
    # que el flujo real es BNE+1 hacia un JSL de aviso, y NO saltar cae
    # en un RTL inmediato -- el camino bueno).
    #
    # BUG REAL ENCONTRADO Y CORREGIDO (el parche que se llegó a entregar
    # al usuario para GP-1 seguía dando pantalla negra, igual en copión
    # que en emulador -- pista clave de que no era detección de copión):
    # la primera versión de este patrón sí tenía contexto único para no
    # colisionar en la BÚSQUEDA, pero su REEMPLAZO era solo 1 byte ("00"
    # con offset=0), dejando el propio D0 intacto. Con el D0 todavía ahí,
    # "Terranigma" (bytes idénticos salvo el contexto) seguía coincidiendo
    # DESPUÉS y sobrescribía ese "00" con su "80" -- confirmado con una
    # prueba directa: el resultado real que salía era "D0 80", no "D0 00".
    # Corregido con la misma técnica que ya se usó en Head-On Soccer y
    # Kirby's Avalanche: reemplazo de 2 bytes "80 00" con offset=-1, que
    # cae sobre el propio opcode y su operando a la vez -- convierte D0 en
    # BRA con desplazamiento 0, Y ya no queda ningún D0 que el patrón de
    # abajo pueda encontrar.
    (bytes([0x22, 0x1d, 0xf5, 0x00, 0xe2, 0x20, 0xad, 0x3f, 0x21, 0x89, 0x10, 0xd0]),
     b"\x80\x00", -1, [], _W1, _E2, "GP-1 (U)"),
    (bytes([0xE2, 0x20, 0xAD, 0x3F, 0x21, 0x89, 0x10, 0xD0]),
     b"\x80\x00", -1, [], _W1, _E2, "Mighty Max (U)"),
    (bytes([0xAF, 0x3F, 0x21, 0x00, 0xC2, 0x20, 0x29, 0x10, 0x00, 0xF0]),
     b"\x80", -1, [], _W1, _E2, "Pac-In-Time (U)"),
    # NOTA APARTE, bug encontrado al construir este patrón: el contexto
    # previo elegido para diferenciarlo ("9C 02 03", parte de "STA
    # $0302") contiene un byte 0x02 -- si wildcard/escape usan por
    # descuido ESE mismo valor (o cualquier otro byte que la propia
    # búsqueda ya contenga como dato literal), el motor lo trata como
    # comodín en esa posición en vez de como literal, y con sets=[] eso
    # nunca coincide con nada (silenciosamente, sin error). Hay que
    # elegir wildcard/escape que no aparezcan en ningún byte de la propia
    # búsqueda -- aquí se usó 0xFE/0xFC en vez de los 0x2A/0x21 por
    # defecto, que sí colisionaban con el "21" de la propia dirección
    # $213F. Va ANTES que "Terranigma" a propósito: misma razón de
    # siempre, para consumir la coincidencia antes de que el patrón
    # corto (y su destino "0x80" incorrecto para este ROM) se aplique.
    (bytes([0x20, 0x3A, 0xFF, 0x9C, 0x02, 0x03, 0xAD, 0x3F, 0x21, 0x89, 0x10, 0xD0]),
     b"\x80\x00", -1, [], 0xFE, 0xFC, "Kirby's Avalanche (U)"),
    (b"\xad\x3f\x21\x89\x10\xd0", b"\x80", 0, [], _W1, _E2, "Terranigma"),
    # ADVERTENCIA (mismo tipo de hallazgo, tercera vez con este patrón):
    # coincide también con Kirby's Avalanche (U), misma búsqueda de 6
    # bytes -- ahí el destino "0x80" cae en mitad de una cadena de texto
    # ASCII ("START :"), no código. Contexto único para no colisionar.
    # ADVERTENCIA (hallazgo real, no solo teórico) sobre el patrón de
    # Super Metroid (E) que viene justo debajo: es un parche ESPECÍFICO
    # para la estructura de código exacta de ese juego — su reemplazo
    # cambia el desplazamiento del BEQ a un valor fijo ("EA"), que solo
    # tiene sentido si en Super Metroid ese desplazamiento concreto lleva
    # a un sitio válido. Coincidió también con BioMetal (U), que tiene la
    # misma búsqueda de 6 bytes pero un desplazamiento y contenido
    # posterior completamente distintos — aplicado ahí, el BEQ saltaba a
    # un punto arbitrario del código cuando es NTSC, causando pantalla
    # negra en hardware real (detectado solo después de que el usuario
    # probara la copia parcheada en MesenCE con "todos funcionan menos
    # BioMetal"). Mismo tipo de riesgo ya documentado para los patrones
    # SlowROM: una búsqueda corta puede coincidir con juegos distintos
    # cuyo contexto exacto no es el mismo para el que se verificó el
    # reemplazo.
    #
    # Para BioMetal se necesitó un patrón aparte, con más contexto previo
    # ("08 E2 20", PHP; SEP #$20, que antecede a la lectura en su rutina
    # concreta) para no coincidir también con el caso genérico de abajo,
    # y con la técnica segura ya usada en el resto de patrones nuevos de
    # esta sesión: tocar solo el opcode del salto (F0->80), dejando su
    # desplazamiento original intacto. Confirmado antes de aplicar que
    # ese destino original es "PLP; RTS" — retorno normal, sin nada más.
    #
    # IMPORTANTE: este patrón va ANTES que el de Super Metroid (E) a
    # propósito, no por casualidad de orden — aplicar_fix_pal prueba la
    # lista en orden, cada patrón sobre el resultado ya modificado por
    # los anteriores. Si el de Super Metroid (búsqueda más corta, 6
    # bytes) se probara primero, ya habría estropeado el desplazamiento
    # de BioMetal antes de que este patrón (que necesita el "F0" intacto
    # para reconocer el caso) tuviera ocasión de coincidir — confirmado
    # así de primeras, con un resultado híbrido roto (opcode correcto,
    # desplazamiento aún corrompido) hasta reordenar los dos.
    (bytes([0x08, 0xe2, 0x20, 0xad, 0x3f, 0x21, 0x89, 0x10, 0xf0]),
     b"\x80", -1, [], _W1, _E2, "BioMetal (U)"),
    # ADVERTENCIA (mismo tipo de hallazgo, cuarta vez con este patrón):
    # el reemplazo "EA EA" con offset=0 de "Super Metroid (E)" de abajo
    # deja el opcode F0 intacto y solo toca operando+byte siguiente --
    # coincide 2 veces con Mega Man X (U) Rev1, con desplazamientos
    # originales de 30 y 4 respectivamente, ambos confirmados como código
    # de continuación válido. El reemplazo "EA EA" da un nuevo destino
    # ANTES del propio inicio de la comprobación en ambos casos (claramente
    # incorrecto). Dos patrones aparte con contexto único, técnica segura
    # de siempre para BEQ: offset=-1, reemplazo "80" sobre el propio
    # opcode, manteniendo intacto el desplazamiento original ya validado.
    (bytes([0x20, 0x45, 0x8A, 0x20, 0x00, 0x81, 0xAD, 0x3F, 0x21, 0x89, 0x10, 0xF0]),
     b"\x80", -1, [], _W1, _E2, "Mega Man X (U) Rev1 - zona 1"),
    (bytes([0xAD, 0x23, 0x1F, 0x10, 0x11, 0xAD, 0x3F, 0x21, 0x89, 0x10, 0xF0]),
     b"\x80", -1, [], _W1, _E2, "Mega Man X (U) Rev1 - zona 2"),
    (bytes([0x8B, 0x08, 0x4B, 0xAB, 0xE2, 0x30, 0xAD, 0x3F, 0x21, 0x89, 0x10, 0xF0]),
     b"\x80", -1, [], _W1, _E2, "The Peace Keepers (U)"),
    # The Pirates of Dark Water (U): dos comprobaciones encadenadas con
    # LÓGICA INVERTIDA entre sí -- un "switch" en RAM ($80FFD9, valores 0
    # o 1) salta directamente a la SEGUNDA (BNE, lógica normal: salta =
    # PAL = malo). Solo si esa variable tiene otro valor se ejecuta la
    # PRIMERA (BEQ), cuyo destino "malo" es justo cuando SÍ salta (NTSC) —
    # lo contrario de la técnica BEQ habitual. Para evitar tener que
    # razonar "hacia qué lado forzar" en cada una, se neutraliza la
    # instrucción de salto completa en ambas (opcode+operando -> EA EA),
    # que siempre continúa a la instrucción siguiente sin importar el
    # resultado de la comprobación -- funciona igual de bien lo salte el
    # "malo" o el "bueno", ya que en ambos casos lo que sigue justo
    # después (PLP;RTL) es el camino correcto.
    (bytes([0xC9, 0x01, 0xF0, 0x09, 0xAD, 0x3F, 0x21, 0x29, 0x10, 0xF0]),
     b"\xea\xea", -1, [], _W1, _E2, "The Pirates of Dark Water (U) - 1ª"),
    (bytes([0x28, 0x6B, 0xAD, 0x3F, 0x21, 0x29, 0x10, 0xD0]),
     b"\xea\xea", -1, [], _W1, _E2, "The Pirates of Dark Water (U) - 2ª"),
    (bytes([0xAD, 0x3F, 0x21, 0x29, 0x10, 0xC9, 0x00, 0xD0]),
     b"\x00", 0, [], _W1, _E2, "Plok (U)"),
    (bytes([0xAD, 0x3F, 0x21, 0x89, 0x10, 0xC2, 0x20, 0xD0]),
     b"\x00", 0, [], _W1, _E2, "Robotrek (U)"),
    # Prehistorik Man (U): lectura INDIRECTA de STAT78 vía absoluto
    # indexado (LDX #$3F; LDA $2100,X = $2100+$3F = $213F) -- otra técnica
    # de ofuscación distinta a la de Donkey Kong Country (esa usaba
    # direct-page indexado, $2027,X con X=$118); misma idea, dirección
    # base e índice distintos. Aparece justo después de un bucle que
    # limpia los registros $2100-$212F. Destino confirmado: si PAL,
    # configura $2133 (SETINI) y punteros -- la rutina de aviso.
    (bytes([0xA2, 0x3F, 0xBD, 0x00, 0x21, 0x89, 0x10, 0xD0]),
     b"\x00", 0, [], _W1, _E2, "Prehistorik Man (U)"),
    (bytes([0xA9, 0x00, 0x48, 0xAB, 0xAD, 0x3F, 0x21, 0x89, 0x10, 0xF0]),
     b"\x80", -1, [], _W1, _E2, "Super Mario All-Stars (U)"),
    (b"\xad\x3f\x21\x89\x10\xf0", b"\xea\xea", 0, [], _W1, _E2, "Super Metroid (E)"),
    # ADVERTENCIA: mismo error que el patrón de Art of Fighting (ver más
    # abajo) -- el reemplazo "80" no pone el desplazamiento a cero (0x80
    # es -128 con signo). Confirmado con GP-1 - Part II (U): ese destino
    # caía en una zona de puros ceros (relleno, no código). Corregido a
    # "00" antes de aplicarse a ningún archivo real de usuario.
    (b"\xad\x3f\x21\x29\x10\x00\xd0", b"\x00", 0, [], _W1, _E2, ""),
    # ADVERTENCIA (mismo tipo de hallazgo real que con Super Metroid/
    # BioMetal): el patrón de "Eric Cantona Football?" de abajo tiene un
    # reemplazo específico para la estructura de código exacta de ESE
    # juego ("A9 10 00" con offset=-6) — coincidió también con Head-On
    # Soccer (U), que tiene la misma búsqueda de 7 bytes pero contenido
    # posterior distinto. Aplicado ahí, el reemplazo caía sobre "3F 21
    # 89" en vez de sobre el opcode del salto, dejando instrucciones sin
    # sentido ("AD A9 10 00 10 00 D0...") — confirmado con una prueba
    # directa antes de dar nada por bueno. Para Head-On Soccer se
    # necesitó un patrón aparte con más contexto previo único (para no
    # coincidir con el genérico de abajo), y aquí SÍ hubo que tocar el
    # opcode del propio BNE (D0->80, offset=-1) EN VEZ DE solo su
    # desplazamiento como en otros casos BNE: dejar el D0 intacto (solo
    # cambiando su desplazamiento a 0, la técnica habitual) habría hecho
    # que el patrón de "Eric Cantona Football?" siguiera coincidiendo
    # DESPUÉS sobre el mismo sitio (misma búsqueda de 7 bytes, ninguno
    # tocado), corrompiéndolo igualmente en un segundo paso — confirmado
    # así de primeras. Reemplazo de 2 bytes "80 00": convierte el opcode
    # en BRA y fuerza el desplazamiento a 0 a la vez, resolviendo ambos
    # problemas (lógica correcta + ya no queda ningún D0 que el otro
    # patrón pueda encontrar).
    (bytes([0xc2, 0x20, 0x58, 0x60, 0x78, 0x60, 0xad, 0x3f, 0x21, 0x89, 0x10, 0x00, 0xd0]),
     b"\x80\x00", -1, [], _W1, _E2, "Head-On Soccer (U)"),
    (b"\xad\x3f\x21\x89\x10\x00\xd0", b"\xa9\x10\x00", -6, [], _W1, _E2, "Eric Cantona Football?"),
    (bytes([0xad, 0x3f, 0x21, 0x89, 0x10, 0xc2, _W1, 0xf0]),
     b"\xea\xea", 0, [], _W1, _E2, "Soul Blazer (F/G)"),
    # ADVERTENCIA (mismo tipo de hallazgo): el reemplazo "80" con offset=0
    # de "Pop'n Twinbee (E)" de abajo deja el opcode F0 intacto y solo
    # toca el operando -- coincide también con Lethal Enforcers (U), cuyo
    # destino con ese reemplazo no se pudo verificar como código válido.
    # El propio ROM tiene además 2 lecturas de STAT78 con BIT #$40 (bit 6,
    # no el bit 4 de región) que no tienen nada que ver con esto --
    # descartadas tras revisar contexto, probablemente relacionadas con
    # el periférico de pistola del juego. Patrón aparte, sin wildcard en
    # el banco (BD FF 80 exacto), con la técnica segura: offset=-1 sobre
    # el propio F0, manteniendo su desplazamiento original ya confirmado
    # como código de continuación normal (REP #$20; RTL). Va ANTES que
    # "Pop'n Twinbee (E)" a propósito, para consumir la coincidencia
    # primero (confirmado con una prueba directa: en el orden contrario,
    # ambos patrones se aplicaban en secuencia sobre el mismo sitio,
    # dejando 3 bytes "80" en vez de 2).
    (bytes([0xad, 0x3f, 0x21, 0x29, 0x10, 0xcf, 0xbd, 0xff, 0x80, 0xf0]),
     b"\x80", -1, [], _W1, _E2, "Lethal Enforcers (U)"),
    # Sparkster (U): mismo sitio de coincidencia que "Pop'n Twinbee (E)"
    # de más abajo (esa lleva wildcard en el byte alto de la dirección
    # comparada; aquí es literal "00") -- va ANTES a propósito, misma
    # razón que Lethal Enforcers: consumir la coincidencia con la técnica
    # segura antes de que el patrón genérico (offset=0, solo toca el
    # operando) llegue a tocarla. Confirmado con prueba directa: en el
    # orden contrario, Sparkster salía con AMBOS patrones aplicados en
    # secuencia sobre el mismo sitio. Destino BEQ confirmado: RTL si
    # salta (NTSC).
    (bytes([0xAD, 0x3F, 0x21, 0x29, 0x10, 0xCF, 0xBD, 0xFF, 0x00, 0xF0]),
     b"\x80", -1, [], _W1, _E2, "Sparkster (U)"),
    (bytes([0xAD, 0x3F, 0x21, 0xC2, 0x20, 0x29, 0x10, 0x00, 0xF0]),
     b"\x80", -1, [], _W1, _E2, "Zombies Ate My Neighbors (U)"),
    (bytes([0xad, 0x3f, 0x21, 0x29, 0x10, 0xcf, 0xbd, 0xff, _W1, 0xf0]),
     b"\x80", 0, [], _W1, _E2, "Pop'n Twinbee (E)"),
    # ADVERTENCIA: el reemplazo original de este patrón era "80" (0x80),
    # que NO pone el desplazamiento a cero -- 0x80 es -128 en complemento
    # a 2, un salto real hacia atrás. Confirmado con Art of Fighting (U):
    # ese destino cae 1 byte antes del inicio real de la siguiente
    # instrucción (a mitad de un "INC $95EF" anterior), desalineando por
    # completo el flujo desde ahí -- el propio archivo que se entregó al
    # usuario en una sesión anterior estaba roto por este motivo. Para
    # BNE, la técnica de "desplazamiento a 0" (como en ABC Monday Night
    # Football) necesita el byte 0x00, no 0x80 -- error de trascripción
    # original, corregido aquí.
    (b"\xaf\x3f\x21\x00\x29\x10\xd0", b"\x00", 0, [], _W1, _E2,
     "LDA.L $00213F; AND #$10; BNE -> desplazamiento 0 (Art of Fighting)"),
    # LDA $213F; AND #$10; BNE +5 -- variante de 6 bytes (AND directamente
    # seguido de BNE, sin el byte "00" intermedio del patrón de arriba con
    # 7 bytes) encontrada en ABC Monday Night Football (U). El reemplazo
    # pone a 0 el desplazamiento del propio BNE en vez de copiar un valor
    # fijo de otro juego (como sí hacen la mayoría de patrones de esta
    # lista): un desplazamiento 0 hace que el salto, se tome o no, caiga
    # siempre en la misma instrucción siguiente — fuerza la rama NTSC sin
    # tener que conocer ni depender de qué código haya más adelante, así
    # que en principio debería generalizar a cualquier otro juego con esta
    # misma estructura exacta de 6 bytes, no solo a este.
    (b"\xad\x3f\x21\x29\x10\xd0", b"\x00", 0, [], _W1, _E2,
     "ABC Monday Night Football (U)"),
    # LDA $213F; AND #$10; CMP $80FFAD (variable en RAM con el valor
    # esperado en NTSC, 0x00 en este ROM); BEQ +offset -- estructura
    # distinta a los patrones de arriba (compara contra una variable en
    # vez de comprobar el resultado del AND directamente), encontrada en
    # The Adventures of Batman & Robin (U). Aquí sí se puede convertir el
    # propio opcode del salto (F0=BEQ -> 80=BRA) en vez de tocar su
    # desplazamiento, porque el destino original YA es el camino válido
    # que el juego toma en NTSC (saltar el código que sigue, que escribe
    # en los registros de paleta $2121/$2122 -- casi seguro la pantalla
    # de aviso de región) — forzar ese mismo salto siempre es más seguro
    # que en un caso donde no se conociera el destino de antemano.
    (bytes([0xad, 0x3f, 0x21, 0x29, 0x10, 0xcf, 0xad, 0xff, 0x80]),
     b"\x80", 0, [], _W1, _E2, "The Adventures of Batman & Robin (U)"),
    # Misma comprobación de 7 bytes que el patrón de arriba ("00 D0", sin
    # nombre) pero con BEQ (F0) en vez de BNE (D0) al final -- encontrada
    # en The Adventures of Dr. Franken (U). Con BEQ la lógica se invierte
    # (salta cuando ES NTSC, no cuando es PAL), así que NO vale la técnica
    # de "desplazamiento a 0" (eso forzaría aquí la rama PAL, justo al
    # revés de lo que hace falta) — hay que forzar que el salto se tome
    # siempre. Se confirmó primero el destino real de este BEQ: cae en un
    # RTL inmediato (retorna sin hacer nada) en el caso NTSC, mientras que
    # la rama "no salta" configura registros y llama a un par de
    # subrutinas -- casi seguro la pantalla de aviso de región. Al llevar
    # el opcode F0 dentro de la propia búsqueda (para no coincidir también
    # con el caso D0 de arriba, que necesita el efecto contrario), el
    # offset se pone en -1 para que el reemplazo caiga sobre ese mismo
    # byte en vez de después de él -- misma técnica que ya usa el patrón
    # de "Eric Cantona Football?" con offset=-6.
    (bytes([0xad, 0x3f, 0x21, 0x29, 0x10, 0x00, 0xf0]),
     b"\x80", -1, [], _W1, _E2, "The Adventures of Dr. Franken (U)"),
    # LDA $213F; AND #$10; BEQ +offset -- variante de 6 bytes (sin el "00"
    # extra del patrón de arriba) encontrada en Bonkers (U), en dos
    # sitios: uno donde la rama PAL hace JSL a la rutina de aviso seguido
    # de un BRA -2 (bucle infinito, cuelga el juego ahí mismo), y otro
    # similar sin el bucle. Mismo razonamiento que con Dr. Franken:
    # BEQ salta cuando ES NTSC, así que hay que forzar que el salto se
    # tome siempre (opcode F0->80 con offset=-1), no poner el
    # desplazamiento a 0 (eso forzaría la rama PAL, la contraria).
    # Confirmados ambos destinos como código de continuación normal antes
    # de aplicar el cambio.
    (bytes([0xad, 0x3f, 0x21, 0x29, 0x10, 0xf0]),
     b"\x80", -1, [], _W1, _E2, "Bonkers (U) / Captain Commando (U)"),
    # Variante con un CMP #$00 redundante entre el AND y el BEQ (el AND ya
    # deja el flag Z correcto por sí solo; el propio compilador del juego
    # generó esta comprobación de más) -- encontrada en Dennis the Menace
    # (U). Mismo caso BEQ de siempre: se fuerza el salto siempre (F0->80,
    # offset=-1) en vez de tocar el desplazamiento. Destino confirmado
    # como código de continuación normal.
    (bytes([0xad, 0x3f, 0x21, 0x29, 0x10, 0xc9, 0x00, 0xf0]),
     b"\x80", -1, [], _W1, _E2, "Dennis the Menace (U)"),
    # Variante "long" con BIT #$10 en vez de AND, y REP #$20 (16 bits)
    # ANTES del BEQ en vez de después -- la rama PAL usa un truco de pila
    # (PEA direccion; RTS) para saltar indirectamente a la rutina de
    # aviso, en vez de un JSL/JML directo, encontrada 2 veces en Dragon:
    # The Bruce Lee Story (U). Mismo caso BEQ de siempre: offset=-1 sobre
    # F0->80. Una tercera lectura de STAT78 en este mismo ROM usa AND
    # #$0F (bits de versión de CPU, no el bit 4 de región) y no tiene
    # nada que ver con esto; se descartó tras revisar el contexto.
    (bytes([0xaf, 0x3f, 0x21, 0x00, 0x89, 0x10, 0xc2, 0x20, 0xf0]),
     b"\x80", -1, [], _W1, _E2, "Dragon: The Bruce Lee Story (U)"),
    # Variante "BIT de 16 bits sin REP intermedio": BIT #$0010 justo
    # después del LDA (a diferencia de Dragon, aquí no hay ningún REP
    # entre medias) -- encontrada en Elite Soccer (U). Destino confirmado
    # como RTS normal.
    (bytes([0xad, 0x3f, 0x21, 0x89, 0x10, 0x00, 0xf0]),
     b"\x80", -1, [], _W1, _E2, "Elite Soccer (U)"),
    # Función que devuelve el resultado en el flag Carry (RTL con CLC si
    # NTSC, con SEC si PAL) en vez de saltar directamente a una rutina de
    # aviso -- el llamador decide qué hacer con ese Carry. Encontrada en
    # Fatal Fury Special (U); el mismo ROM tiene otras 2 lecturas de
    # STAT78 que forman parte de una espera VSYNC (comparación contra
    # OPVCT 0xD0-0xD2), sin relación con esto. BNE de siempre:
    # desplazamiento a 0.
    (bytes([0xaf, 0x3f, 0x21, 0x00, 0xc2, 0x20, 0x29, 0x10, 0x00, 0xd0]),
     b"\x00", 0, [], _W1, _E2, "Fatal Fury Special (U)"),
    # BIT #$10 (8 bits, sin REP/16 bits) seguido de BNE directo -- variante
    # "long" mas simple, encontrada en Final Fight Guy (U). El mismo ROM
    # tiene otras 2 lecturas (formato abs, no long) que son parte de una
    # espera VSYNC (SLHV/OPVCT), sin relación con esto. BNE: desplazamiento
    # a 0, destino de la rama PAL confirmado como JSL a una subrutina.
    (bytes([0xaf, 0x3f, 0x21, 0x00, 0x89, 0x10, 0xd0]),
     b"\x00", 0, [], _W1, _E2, "Final Fight Guy (U)"),
    # AND (no BIT) de 8 bits + BEQ directo -- variante "long" simple,
    # encontrada en EarthBound (U). Destino confirmado como RTL normal.
    # Este mismo ROM también coincide con varios patrones -k (crack) ya
    # existentes -- protección distinta (anti-copia), sin relación con
    # el aviso de región que muestra la captura del usuario.
    (bytes([0xaf, 0x3f, 0x21, 0x00, 0x29, 0x10, 0xf0]),
     b"\x80", -1, [], _W1, _E2, "EarthBound (U)"),
    # Variante "long" (AF, no AD) de 8 bytes con BEQ al final, en vez de
    # BNE (como el patrón "AF 3F 21 00 29 10 D0" de más arriba) --
    # encontrada literalmente en el arranque de Ardy Lightfoot (U),
    # offset 0x8 del ROM. Mismo caso que Dr. Franken/Bonkers: BEQ salta
    # cuando ES NTSC, así que se fuerza el salto siempre (F0->80,
    # offset=-1) en vez de poner el desplazamiento a 0. Destino
    # confirmado como código de continuación normal antes de aplicar.
    (bytes([0xaf, 0x3f, 0x21, 0x00, 0x29, 0x10, 0x00, 0xf0]),
     b"\x80", -1, [], _W1, _E2, "Ardy Lightfoot (U)"),
    # ADVERTENCIA: mismo bug de base que ya se corrigió varias veces esta
    # sesión (Art of Fighting, GP-1 Part II, Donkey Kong Country SRAM) --
    # offset=0 deja el opcode D0 intacto, dejando el BNE con un
    # desplazamiento fijo -22 en vez de neutralizarlo. Confirmado con
    # International Tennis Tour (U) y Jim Power (U), ambos con la misma
    # búsqueda exacta: "D0 03"->"D0 EA" y "D0 01"->"D0 EA" respectivamente,
    # ninguno neutralizado. Corregido a offset=-1, para que "EA EA" caiga
    # sobre el propio D0 y su operando.
    (b"\xaf\x3f\x21\x00\x29\x10\x00\xd0", b"\xea\xea", -1, [], _W1, _E2, ""),
    (bytes([0x7A, 0xFA, 0x68, 0x28, 0x40, 0xAF, 0x3F, 0x21, 0x00, 0x29, 0x10, 0xC9, 0x00, 0xF0]),
     b"\x80", -1, [], _W1, _E2, "Trials of Mana (fan translation, Seiken Densetsu 3)"),
    # CORREGIDO: con offset 0 el "80" caía sobre el operando del BEQ (un salto
    # de -128 bytes) y no sobre el propio F0. Con -1 coincide byte a byte con
    # uCON64 -f (CONFIRMADO en hardware real con Secret of Mana (Europe) Rev 1).
    (bytes([0xaf, 0x3f, 0x21, 0x00, 0x29, _W1, 0xc9, _W1, 0xf0]),
     b"\x80", -1, [], _W1, _E2, "Secret of Mana (E)"),
    (b"\xa2\x18\x01\xbd\x27\x20\x89\x10\x00\xf0\x01",
     b"\xea\xea", -1, [], WILDCARD, ESCAPE, "Donkey Kong Country (E)"),
]


# Patrones GENÉRICOS de PATRONES_PAL que casan por casualidad en un ROM
# concreto y NO deben aplicársele: CRC32 del cuerpo (sin cabecera de copiador)
# -> descripciones de patrón a saltar. Un patrón de 8 bytes como
# «LDA.L $00213F; AND #$10; BEQ» (el de Ardy Lightfoot) aparece en cualquier
# juego que lea ese registro por cualquier motivo.
EXCLUSIONES_FIX_PAL = {
    # Clay Fighter (USA): ahí ese patrón cae sobre la CORRECCIÓN DE VELOCIDAD
    # PAL del juego (si es PAL decrementa dos contadores y ejecuta una rutina
    # extra, a 0x1B0B95), no sobre un aviso. Convertir su BEQ en BRA no quita
    # el aviso real (que está en otro sitio, ver "Clay Fighter (U)") y además
    # desactivaba la compensación de 50 Hz. Era el motivo de que este juego
    # pareciera «parcheado pero sin efecto».
    "c814e3c2": {"Ardy Lightfoot (U)"},
    # Yoshi's Safari (Europe): el patrón «Monday Night Football» coincide por
    # casualidad con una lectura de $213F que NO es de región. Su aviso se
    # trata solo como variante dual (ver PATRONES_INVERSION_REGION).
    "9a8178bf": {"ABC Monday Night Football (U)"},
    # Super Pinball: Behind the Mask (Europe): "ABC Monday Night Football (U)" y
    # "Bonkers (U) / Captain Commando (U)" coinciden por casualidad (2 bytes
    # sin relación con la región). Se trata solo como variante dual.
    # R-Type III (Europe): el genérico "Art of Fighting" cae en el mismo sitio;
    # se trata solo como variante dual.
    "5a183e62": {"LDA.L $00213F; AND #$10; BNE -> desplazamiento 0 (Art of Fighting)"},
    "3bcb5d70": {"ABC Monday Night Football (U)", "Bonkers (U) / Captain Commando (U)"},
    # Art of Fighting (Europe): el genérico "EarthBound (U)" coincide en el BEQ
    # de la rutina de región ($C0:1599) y lo convierte en BRA, que SIEMPRE cae
    # en SEC (= "región incorrecta"): rompería también la consola PAL. Se
    # trata solo como variante dual (ver PATRONES_INVERSION_REGION).
    "143051a5": {"EarthBound (U)"},
    # Terranigma (Europe): "Mighty Max (U)" coincide por casualidad y pone BRA +0
    # (cae en el aviso). Se trata solo como variante dual.
    "974523ff": {"Mighty Max (U)"},
}


def aplicar_fix_pal(datos: bytes) -> tuple:
    """Aplica los patrones de corrección NTSC/PAL (-f de uCON64) sobre
    `datos` (trabaja sobre una copia; el original no se modifica).

    Devuelve (datos_parcheados, lista_de_cambios), igual que aplicar_crack.
    """
    buf = bytearray(datos)
    cambios = []
    cuerpo = datos[512:] if len(datos) % 0x8000 == 512 else datos
    excluidos = EXCLUSIONES_FIX_PAL.get(f"{zlib.crc32(cuerpo) & 0xFFFFFFFF:08x}", ())
    region_rom = region_nativa_rom(cuerpo)
    for search, replace, offset, sets, wildcard, escape, desc in PATRONES_PAL:
        if desc in excluidos:
            continue
        if desc in GENERICOS_POR_REGION:
            # Patrón corto genérico: el parche correcto depende de la región
            # nativa de la ROM (igual que uCON64 -f), ver GENERICOS_POR_REGION.
            replace, offset = GENERICOS_POR_REGION[desc][region_rom]
        patron = Patron(search, replace, offset, sets, desc, wildcard, escape)
        n = aplicar_patron(buf, patron)
        if n:
            texto = desc or f"patrón sin descripción ({search.hex()})"
            cambios.append(f"{texto}  (×{n})" if n > 1 else texto)
    return bytes(buf), cambios


def region_nativa_rom(cuerpo: bytes) -> str:
    """"NTSC" (Japón/USA) o "PAL" según el código de país de la cabecera
    interna de la ROM (sin cabecera de copiador). Mismo criterio que uCON64
    -f: países 0 y 1 son NTSC, cualquier otro código es PAL. Si no se
    encuentra una cabecera creíble se asume NTSC (el caso más común, y el
    que ya cubrían los patrones de este módulo)."""
    mejor = None
    for base in (0x7FC0, 0xFFC0, 0x40FFC0):
        if len(cuerpo) < base + 0x20:
            continue
        cab = cuerpo[base:base + 0x20]
        comp = cab[0x1C] | (cab[0x1D] << 8)
        chk = cab[0x1E] | (cab[0x1F] << 8)
        puntos = (2 if (comp ^ chk) == 0xFFFF else 0)
        puntos += 1 if all(32 <= b < 127 for b in cab[:21]) else 0
        puntos += 1 if cab[0x15] & 0x0F in (0, 1, 2, 3, 5) else 0
        if mejor is None or puntos > mejor[0]:
            mejor = (puntos, cab[0x19])
    if mejor is None or mejor[0] < 2:
        return "NTSC"
    return "NTSC" if mejor[1] in (0, 1) else "PAL"


# Patrones CORTOS genéricos de PATRONES_PAL (la lectura de $213F y el salto,
# sin más contexto) cuyo parche correcto depende de la región nativa de la
# ROM. Comprobado contra uCON64 -f con ROMs reales y con ROMs sintéticas
# cambiando solo el código de país de la cabecera:
#     ROM NTSC:  BEQ (F0 xx) -> BRA (80 xx)      BNE (D0 xx) -> NOP NOP (EA EA)
#     ROM PAL:   BEQ (F0 xx) -> NOP NOP (EA EA)  BNE (D0 xx) -> BRA (80 xx)
# Antes estos dos patrones llevaban un único reemplazo escrito sobre el
# OPERANDO y el byte siguiente (offset 0) en vez de sobre el opcode
# (offset -1): corrompía código (p. ej. Speedy Gonzales, Super Bases Loaded 3,
# Tetris 2, Nigel Mansell's: BEQ -22 en vez de BRA) y no coincidía con -f.
# Valor: {región_de_la_ROM: (reemplazo, offset)}.
GENERICOS_POR_REGION = {
    # "LDA.L $00213F; AND #$10; BNE": en una ROM NTSC (el caso de Art of
    # Fighting) el BNE se anula con desplazamiento 0; en una ROM PAL ese
    # mismo cambio deja las dos ramas iguales y el aviso sigue ahí, así que
    # hay que forzar el salto (BNE -> BRA). Es lo que hace uCON64 -f según el
    # país de la cabecera. CONFIRMADO en hardware real con R-Type III (Europe).
    "LDA.L $00213F; AND #$10; BNE -> desplazamiento 0 (Art of Fighting)":
        {"NTSC": (b"\x00", 0), "PAL": (b"\x80", -1)},
    "Super Metroid (E)": {"NTSC": (b"\x80", -1), "PAL": (b"\xea\xea", -1)},
    "Terranigma":        {"NTSC": (b"\xea\xea", -1), "PAL": (b"\x80", -1)},
}


# Patrones de INVERSIÓN de región: para el puñado de juegos donde la propia
# ROM tiene código genuinamente distinto según la región (velocidad,
# timing de animación/música — no solo un aviso de "región incorrecta"),
# de forma que "neutralizar siempre hacia el mismo lado" (como hace
# PATRONES_PAL de arriba, para el resto del catálogo) sería incorrecto: el
# dump ya funciona en su región nativa tal cual, y adaptarlo a la región
# CONTRARIA exige invertir esa comprobación, no anularla.
#
# Cada entrada aquí solo tiene sentido acompañada de una VarianteDual en
# parches_conocidos.py (que dice cuál es la región nativa del dump y qué
# parches base hacen falta siempre) — ver aplicar_variante_dual() más abajo
# y el diálogo DualRegionCopyDialog en main.py, que es donde el usuario
# elige a qué consola de destino quiere generar la copia.
#
# Mismo formato que PATRONES_PAL: (search, reemplazo, offset, sets,
# wildcard, escape, descripcion). El reemplazo aquí siempre invierte el
# opcode del salto (BEQ<->BNE) manteniendo su desplazamiento/operando
# original intacto — igual que la técnica segura para BEQ en PATRONES_PAL,
# pero sin necesidad de que ese destino sea "el camino bueno": aquí SIEMPRE
# es la rama de aviso de región del propio juego, y lo que cambia es cuál
# de las dos regiones la activa.
PATRONES_INVERSION_REGION = [
    # Claymates (Europe): región nativa PAL. Mismo código que Claymates (U)
    # en la misma posición ($CC:834C) con la polaridad invertida:
    #     LDA.L $00213F ; BIT #$0010 ; BNE $CC8378   (aviso si es NTSC)
    # Se cambia el BNE por BRA (D0 -> 80, 1 byte), solo para destino NTSC.
    # Verificado con trazas reales de las dos versiones y con el ROM.
    (bytes([0xAF, 0x3F, 0x21, 0x00, 0x89, 0x10, 0x00, 0xD0, 0x23]),
     b"\x80", -2, [], 0xEE, 0xEF, "Claymates (Europe)"),
    # Clay Fighter (Europe): región nativa PAL. MISMO motor que Clay Fighter
    # (U) y Tournament Edition (U) (ver el patrón "Clay Fighter (U)" en
    # PATRONES_PAL), con la polaridad del test INVERTIDA:
    #     USA   : LDX #$20F9 ; LDA $45,X ; AND #$1000 ; CMP #$1000        (C=1 si PAL)
    #     EUROPA: LDX #$20F9 ; LDA $45,X ; AND #$1FFF ; EOR #$FFFF ; CMP #$EFFF
    #             -> C = ((valor & $1FFF) <= $1000), es decir C=1 si NTSC
    # La rutina que consume el resultado (PHP ... PLP ; LDA $30 ; ADC $30 ;
    # STA $30) es la misma en las dos versiones, así que en Europa el acarreo
    # 1 (= NTSC) activa la pantalla «This Game Pak Is Not Designed For Your
    # Super Famicom Or Super NES». Se cambia AND #$1FFF por LDA #$1FFF (29 ->
    # A9, 1 byte): A=$1FFF -> EOR -> $E000 -> CMP #$EFFF deja Nzc, idéntico al
    # resultado de una consola PAL real (comprobado por simulación con todos
    # los valores realistas de STAT77/STAT78).
    # AVISO: INFERIDO POR ANÁLISIS ESTÁTICO, sin traza de esta ROM. La
    # polaridad del consumidor se dio por idéntica a la de TE (verificada con
    # trazas reales de MesenCE), y la rutina es la misma salvo destinos de JSR
    # relocalizados. Pendiente de confirmar en emulador/SWC. Offset -10: el 29
    # es el 6.º byte de una búsqueda de 15.
    (bytes([0xA2, 0xF9, 0x20, 0xB5, 0x45, 0x29, 0xFF, 0x1F, 0x49, 0xFF, 0xFF, 0xC9, 0xFF, 0xEF, 0x20]),
     b"\xa9", -10, [], 0x01, 0x02, "Clay Fighter (Europe)"),
    # Pinocchio (Europe): región nativa PAL. Mismo código que la versión USA
    # (un único acceso directo a $213F en todo el ROM, sin lecturas
    # indirectas) pero con la polaridad del salto invertida:
    #     LDA $213F ; BIT #$10 ; BEQ +1 ; RTL ; JSL $8192BE
    # Si es NTSC (bit 4 = 0) el BEQ salta el RTL y cae en la rutina de aviso,
    # que prepara la pantalla y muestra «THIS VERSION OF PINOCCHIO IS
    # DESIGNED TO RUN ON A PAL MACHINE ONLY» (texto presente en el ROM, 2
    # copias). Se anula el BEQ entero (F0 01 -> EA EA) para que siempre
    # continúe en el RTL, solo para destino NTSC. OJO: la búsqueda contiene
    # el byte 0x01, que coincidiría con el comodín por defecto de otros
    # patrones (0x01) -- por eso aquí wildcard/escape son 0xEE/0xEF, que no
    # aparecen en ella. Offset -4: el F0 es el 6.º byte de una búsqueda de 9.
    (bytes([0xAD, 0x3F, 0x21, 0x89, 0x10, 0xF0, 0x01, 0x6B, 0x22]),
     b"\xea\xea", -4, [], 0xEE, 0xEF, "Pinocchio (Europe)"),
    # The Adventures of Dr. Franken (Europe, En/Fr/De/Es/It/Nl/Sv): región
    # nativa PAL. Comprobación con la misma estructura de bytes que la
    # versión USA de este mismo juego (AD 3F 21 29 10 00 D0), pero
    # compilada por separado -- el destino relativo del BNE (+0x71) lleva
    # aquí a RTL directo (el camino bueno), justo al revés de lo que ese
    # mismo desplazamiento significaba en la versión USA. Confirmado con
    # captura real del usuario (aviso clásico "THIS GAME PAK IS NOT
    # DESIGNED FOR YOUR SUPER FAMICOM OR SUPER NES. ELITE SYSTEMS LTD.")
    # -- el texto en sí no se pudo localizar por búsqueda directa (no es
    # ASCII plano ni un offset/XOR simple, probablemente tabla de tiles
    # propia), así que la confirmación fue por el patrón de código: el
    # camino contrario a RTL inicializa sistemáticamente casi todos los
    # registros de vídeo PPU desde cero ($2101, $2105, $2107-210D,
    # $212C-2133), consistente con las rutinas de aviso del resto de la
    # sesión aunque esta en concreto no revelara su texto.
    (bytes([0x00, 0x00, 0x00, 0x00, 0xAD, 0x3F, 0x21, 0x29, 0x10, 0x00, 0xD0]),
     b"\x80", -1, [], 0x01, 0x02, "The Adventures of Dr. Franken (Europe)"),
    # 90 Minutes - European Prime Goal (Europe): región nativa PAL.
    # Comprobación directa de STAT78 -- confirmada su relación real con el
    # aviso de región (no un simple ajuste de timing como se pensó en un
    # primer análisis): la rama que toma cuando detecta NTSC llama, a
    # través de 2 subrutinas encadenadas, a una que escribe literalmente
    # el texto "THIS GAME PAK IS NOT DESIGINED FOR YOUR SUPER FAMICOM OR
    # SUPER NES. NAMCO LTD. BY SIMA SIMA" (errata "DESIGINED" original del
    # juego) sobre una zona de pantalla previamente rellenada de espacios.
    # Se neutraliza el BEQ por completo (opcode+operando -> EA EA) para
    # que SIEMPRE tome el camino bueno (PLP;RTL) sin importar el
    # resultado real de STAT78 -- solo se aplica para destino NTSC, nunca
    # para PAL (su región nativa, donde ya funciona sin tocar nada).
    (bytes([0xE2, 0x20, 0xAF, 0x3F, 0x21, 0x00, 0xC2, 0x20, 0x29, 0x10, 0x00, 0xF0]),
     b"\xea\xea", -1, [], 0x01, 0x02, "90 Minutes - European Prime Goal (Europe)"),
    # Donkey Kong Country (E) Rev1: lectura INDIRECTA de STAT78 vía
    # direct-page indexado, para evitar que "3F 21" aparezca literal en el
    # código (LDX #$0118; LDA $2027,X = $2027+$118 = $213F). Región nativa
    # PAL: BEQ salta a la rutina de aviso compartida si detecta NTSC.
    # Invertir a destino NTSC: BEQ(F0)->BNE(D0) sin tocar el operando (ya
    # confirmado como el destino correcto de esa rama de aviso) — así pasa
    # a bloquear PAL y permitir NTSC.
    (bytes([0xA2, 0x18, 0x01, 0xBD, 0x27, 0x20, 0x89, 0x10, 0x00, 0xF0]),
     b"\xD0", -1, [], 0x01, 0x02, "Donkey Kong Country (E) Rev1"),
    # RoboCop versus The Terminator (U): región nativa NTSC. Motor de
    # script propietario (no un simple salto condicional en código) --
    # una tabla de datos en ROM ($019F9F en adelante) contiene los
    # "comandos" que un intérprete genérico va leyendo y ejecutando. El
    # comando de comprobación de región lee STAT78 vía la subrutina
    # genérica de lectura de hardware, guarda el resultado (0=NTSC,
    # 1=PAL) en la variable $82, y OTRO comando del script compara $82
    # contra un valor -- ese valor de comparación (byte "01" en offset
    # $9FA1) es un DATO del script, no código, y la subrutina de
    # comparación en sí es compartida con ~158 comprobaciones no
    # relacionadas en el resto del juego (confirmado buscando el patrón
    # corto antes de aplicar nada) -- parchear el código habría sido muy
    # peligroso, y cambiar el dato a CUALQUIER valor tampoco sirve para
    # "neutralizar sin más": ese dato pasa por una máscara de 1 bit antes
    # de compararse, así que el resultado solo puede ser 0 o 1 -- los
    # mismos dos valores que puede tomar $82 -- por lo que cualquier
    # valor fijo que se ponga ahí SIEMPRE coincidirá con una de las dos
    # regiones reales. CONFIRMADO CON ERROR REAL: la primera versión de
    # este parche (byte "02") se probó como neutralización universal en
    # PATRONES_PAL y el usuario confirmó en su hardware que funcionaba en
    # PAL pero rompía NTSC (mostraba el aviso ahí, cuando antes no lo
    # hacía) -- no era una neutralización, era una INVERSIÓN exacta de a
    # qué región afecta el aviso. Por eso pertenece aquí, no en
    # PATRONES_PAL: con destino nativo (NTSC) no se toca nada (ya
    # funciona), y solo con destino PAL se aplica esta inversión.
    (bytes([0xAF, 0x00, 0x01, 0x00, 0xCA]),
     b"\x02", -3, [], _W1, _E2, "RoboCop versus The Terminator (U)"),
    # Super Metroid (Europe): región nativa PAL. Dos lecturas de $213F
    # (LDA $213F; BIT #$10; BEQ), en $80:860F y $80:8619 aprox. -- la misma
    # forma que hace uCON64 -f para una ROM PAL: BEQ + operando -> NOP NOP
    # (EA EA). CONFIRMADO por el usuario en hardware real (consola NTSC,
    # junto con -k). Solo se aplica con destino NTSC (en PAL no hace falta).
    (b"\xad\x3f\x21\x89\x10\xf0",
     b"\xea\xea", -1, [], _W1, _E2, "Super Metroid (Europe)"),
    # X-Kaliber 2097 (Europe): región nativa PAL. Única lectura real de $213F,
    # en $00:CA95 (subrutina llamada una vez al arrancar):
    #     SEP #$20 ; LDA $213F ; BIT #$10 ; BEQ +1 (salta el RTS) ; RTS
    # Con NTSC (bit 4 = 0) el BEQ se toma, se salta el RTS y cae en la pantalla
    # de aviso; con PAL retorna normal. Hallado comparando trazas reales de
    # MesenCE. BEQ + operando (F0 01) -> NOP NOP (EA EA), igual que uCON64 -f
    # para una ROM PAL. Solo se aplica con destino NTSC.
    (bytes([0xE2, 0x20, 0xAD, 0x3F, 0x21, 0x89, 0x10, 0xF0, 0x01, 0x60]),
     b"\xea\xea", -3, [], 0xEE, 0xEF, "X-Kaliber 2097 (Europe)"),
    # Wolfenstein 3D (Europe) — región nativa PAL. Única lectura de STAT78,
    # en $C0:743A (código compilado en C, con puntero largo [$05] = $00213F):
    #     LDA [$05] ; AND #$0010 ; LDX #0 ; CMP #$0010 ; BNE +1 ; INX ; TXA ;
    #     STA $09 ; LDA $09 ; BEQ aviso
    # Con NTSC el BNE se toma, X queda en 0 y el BEQ lleva a la pantalla de
    # aviso ($C028BF); con PAL se ejecuta el INX (X=1) y retorna normal.
    # BNE + operando (D0 01) -> NOP NOP: siempre se ejecuta el INX, igual que
    # en PAL. uCON64 -f no lo detecta. Hallado con trazas reales. Solo se
    # aplica con destino NTSC.
    (bytes([0xA7, 0x05, 0x29, 0x10, 0x00, 0xA2, 0x00, 0x00, 0xC9, 0x10, 0x00,
            0xD0, 0x01, 0xE8, 0x8A, 0x85, 0x09]),
     b"\xea\xea", -6, [], 0xEE, 0xEF, "Wolfenstein 3D (Europe)"),
    # Top Gear 2 (Europe) — región nativa PAL. Rutina de detección en
    # $81:F900 (llamada al arrancar). Mide la duración del vblank contando
    # iteraciones (X) y lee STAT78; deja dos banderas en $FC/$FD: $FF = NTSC,
    # $00 = PAL:
    #     LDA $213F ; AND #$10 ; BEQ +2 ; STZ $FC ; CPX #$0400 ; BCC +2 ; STZ $FD
    # Después $81:F845 hace LDA $FC con A de 16 BITS (lee $FC y $FD juntos) y
    # salta a la pantalla de aviso ($81:F4AE) si la palabra no es 0. Por eso
    # hay que anular LAS DOS condiciones: BEQ (F0 02) y BCC (90 02) -> NOP NOP,
    # de modo que se ejecuten siempre STZ $FC y STZ $FD. (Un primer intento que
    # solo anulaba el BEQ seguía mostrando el aviso.) El resto de lecturas de
    # STAT78 del juego ($9F:9D45, $9F:F85B: banderas de velocidad/tempo de
    # música PAL/NTSC) se dejan intactas. Hallado con trazas reales de MesenCE;
    # uCON64 -f no lo detecta. Solo con destino NTSC.
    (bytes([0xAD, 0x3F, 0x21, 0x29, 0x10, 0xF0, 0x02, 0x64, 0xFC, 0xE0, 0x00,
            0x04, 0x90, 0x02, 0x64, 0xFD]),
     bytes([0xEA, 0xEA, 0x64, 0xFC, 0xE0, 0x00, 0x04, 0xEA, 0xEA, 0x64, 0xFD]),
     -11, [], 0xEE, 0xEF, "Top Gear 2 (Europe)"),
    # WeaponLord (Europe) — región nativa PAL. Única comprobación real, en
    # $EA:487D (el resto de lecturas de STAT78, en $EA:6144, solo resetean el
    # latch del contador antes de leer OPVCT):
    #     LDA.L $00213F ; BIT #$0010 ; BNE $EA48A7 (RTL) ; JSL $EA6064 (aviso)
    # Con NTSC el BNE no se toma y cae en el aviso; con PAL salta al RTL. Se
    # cambia BNE (D0) -> BRA (80) para que SIEMPRE salte (igual que uCON64 -f
    # sobre una ROM PAL, que aquí no lo detecta). Solo con destino NTSC.
    (bytes([0xAF, 0x3F, 0x21, 0x00, 0x89, 0x10, 0x00, 0xD0, 0x21, 0x22, 0x64,
            0x60, 0xEA]),
     b"\x80", -6, [], 0xEE, 0xEF, "WeaponLord (Europe)"),
    # Terranigma (Europe) — región nativa PAL. Única comprobación real, en
    # $87:97C9, dentro de un script del intérprete de bytecode del juego (COP):
    #     LDA $213F ; BIT #$10 ; BNE $8797D3 ; JMP $9869 (pantalla de aviso)
    # Con NTSC el BNE no se toma y cae en el JMP; con PAL salta. Las demás
    # lecturas de STAT78 ($85:FB26) solo reinician el latch antes de leer
    # OPVCT. BNE (D0) -> BRA (80), 1 byte: es exactamente lo que hace uCON64
    # -f sobre esta ROM (país != 0/1). OJO: el patrón genérico "Mighty Max
    # (U)" de PATRONES_PAL también coincide aquí y escribe 80 00 (BRA +0), que
    # cae EN el JMP del aviso — por eso esta ROM va excluida de ese patrón
    # (EXCLUSIONES_FIX_PAL) y se trata solo como variante dual. Solo con
    # destino NTSC.
    (bytes([0xAD, 0x3F, 0x21, 0x89, 0x10, 0xD0, 0x03, 0x4C, 0x69, 0x98]),
     b"\x80", -5, [], 0xEE, 0xEF, "Terranigma (Europe)"),
    # Super Putty (Europe) — región nativa PAL (LoROM de 1 MB, sin SRAM). Única
    # lectura de STAT78, en $01:E9FC (rutina llamada al arrancar):
    #     LDA $213F ; AND #$10 ; BNE $01EA23 (RTL) ; JSL $01E134 (pantalla de aviso)
    # Con NTSC el BNE no se toma y cae en el aviso; con PAL salta al RTL. BNE
    # (D0) -> BRA (80), 1 byte (uCON64 -f no lo detecta). Hallado con trazas
    # reales de MesenCE. Solo con destino NTSC.
    (bytes([0xAD, 0x3F, 0x21, 0x29, 0x10, 0xD0, 0x20, 0x22, 0x34, 0xE1, 0x01]),
     b"\x80", -6, [], 0xEE, 0xEF, "Super Putty (Europe)"),
    # Super Street Fighter II (Europe) — región nativa PAL (HiROM de 4 MB, sin
    # SRAM). Única lectura de STAT78, en $C0:120D, tras leer el código de país
    # de su propia cabecera ($C0:FFD9):
    #     LDA.L $C0FFD9 ; CMP #$02 ; BNE aviso ; LDA $213F ; AND #$10 ;
    #     BNE $C01230 (juego) ; aviso: LDA #$17 ...
    # Con NTSC el BNE no se toma y cae en el aviso. BNE (D0) -> BRA (80),
    # 1 byte (uCON64 -f no lo detecta). Hallado con trazas reales. Solo con
    # destino NTSC.
    (bytes([0xC9, 0x02, 0xD0, 0x07, 0xAD, 0x3F, 0x21, 0x29, 0x10, 0xD0, 0x1C,
            0xA9, 0x17, 0x85, 0xBF]),
     b"\x80", -6, [], 0xEE, 0xEF, "Super Street Fighter II (Europe)"),
    # APARCADO (sin VarianteDual a propósito): con este parche la ROM pasa el
    # aviso pero en consola NTSC y en emulador con región NTSC el juego
    # parpadea — es la temporización 50 Hz del propio juego, sin arreglo simple.
    # World Cup Striker (Europe) — región nativa PAL. Única lectura de STAT78
    # en $82:B6FC: LDA $213F ; BIT #$0010 ; BNE ok. Con NTSC no salta y cae en
    # la pantalla de aviso. LDA $213F (AD 3F 21) -> LDA #$0010 (A9 10 00): el
    # BIT ve siempre bit 4 = 1. Mismo cambio que hace uCON64 -f en una ROM
    # PAL; hallado de forma independiente con trazas reales. Solo con
    # destino NTSC.
    (bytes([0xAD, 0x3F, 0x21, 0x89, 0x10, 0x00, 0xD0]),
     bytes([0xA9, 0x10, 0x00]), -7, [], 0xEE, 0xEF,
     "World Cup Striker (Europe)"),
    # Super Pinball: Behind the Mask (Europe) — región nativa PAL (LoROM
    # FastROM de 1 MB, sin SRAM). Única lectura de STAT78 en $00:F4BB, tras
    # leer el país de su cabecera ($FFD9 = 02):
    #     LDA $213F ; AND #$10 ; BEQ $F4CD (aviso) ; BRA $F4B9 (RTS)
    # Con NTSC el bit 4 vale 0 y el BEQ lleva al aviso. BEQ (F0 0B) -> NOP NOP
    # (EA EA): cae siempre en el BRA que sale. Hallado con trazas reales y
    # CONFIRMADO por el usuario en hardware real con destino NTSC. uCON64 -f
    # no lo detecta. Solo con destino NTSC.
    (bytes([0xAD, 0x3F, 0x21, 0x29, 0x10, 0xF0, 0x0B, 0x80, 0xF5]),
     bytes([0xEA, 0xEA]), -4, [], 0x01, 0x02, "Super Pinball - Behind the Mask (Europe)"),
    # Prehistorik Man (Europe): región nativa PAL (HiROM no, LoROM de 1 MB).
    # $82:86F2: LDX #$3F ; LDA $2100,X (= STAT78) ; BIT #$10 ; BEQ $8702 ;
    # LDA #$01 ; STA ($00) ; INC $00 ; DEC ; STA ($00)  -- en PAL pone a 1 el
    # word $27 (variable de región); en NTSC el BEQ se lo salta, $27 queda con
    # basura ($A11E) y más tarde el juego (rutina $82:CDE7, DEC + BEQ) sigue la
    # rama del aviso. BEQ (F0 09) -> NOP NOP (EA EA). uCON64 -f no lo detecta
    # (su patrón solo cubre la versión con BNE). CONFIRMADO por el usuario en
    # hardware real con destino NTSC.
    (bytes([0xA2, 0x3F, 0xBD, 0x00, 0x21, 0x89, 0x10, 0xF0, 0x09, 0xA9, 0x01, 0x92, 0x00]),
     bytes([0xEA, 0xEA]), -6, [], 0xEE, 0xEF, "Prehistorik Man (Europe)"),
    # Samurai Shodown (Europe): región nativa PAL (HiROM de 4 MB). $DF:46EE:
    #     LDA.L $00213F ; AND #$10 ; BNE -> SEC ; RTS   (PAL: carry = 1)
    #                                 CLC ; RTS         (NTSC: carry = 0 -> aviso)
    # BNE (D0) -> BRA (80), 1 byte, igual que uCON64 -f. Aparte, la ROM lleva un
    # detector de copiadores que cuelga el juego en un SWC: se quita con el
    # parche -k "Samurai Shodown (detector de copiadores)" (ver PATRONES_BASE),
    # que la variante dual marca siempre. CONFIRMADO por el usuario en
    # hardware real con destino NTSC.
    (bytes([0xAF, 0x3F, 0x21, 0x00, 0x29, 0x10, 0xD0, 0x04, 0xC2, 0x20, 0x18, 0x60,
            0xC2, 0x20, 0x38, 0x60]),
     b"\x80", -10, [], 0x01, 0x02, "Samurai Shodown (Europe)"),
    # Secret of Mana (Europe, Rev 1): región nativa PAL (HiROM de 2 MB). El
    # código del juego va COMPRIMIDO (LZ) y se descomprime en RAM al arrancar;
    # la comprobación (en RAM: LDA.L $00213F; AND #$10; CMP #$10; BEQ ok) cae
    # en una tirada de bytes sin comprimir, así que se parchea directamente en
    # la ROM: BEQ (F0) -> BRA (80), 1 byte. Coincide con uCON64 -f.
    # CONFIRMADO por el usuario en hardware real con destino NTSC.
    (bytes([0xAF, 0x3F, 0x21, 0x00, 0x29, 0x10, 0xC9, 0x10, 0xF0]),
     b"\x80", -1, [], 0x01, 0x02, "Secret of Mana (Europe) Rev 1"),
    # Revolution X (Europe): región nativa PAL (LoROM). $81:F08D guarda el bit 4
    # de STAT78 desplazado a bit 7 en $1A20; la rutina de arranque lo usa para
    # decidir (por el flag Z del último ASL) si muestra el aviso:
    #     JSR $922F ; BNE $8E50 (sigue) ; ... aviso "THIS GAME PAK ..."
    # BNE (D0) -> BRA (80) en $86:8E06. uCON64 -f no lo detecta. CONFIRMADO por
    # el usuario en hardware real con destino NTSC.
    (bytes([0x20, 0x2F, 0x92, 0xD0, 0x48, 0xA9, 0xC4, 0x70, 0xA0, 0x53, 0x8E]),
     b"\x80", -8, [], 0xEE, 0xEF, "Revolution X (Europe)"),
    # R-Type III (Europe): región nativa PAL (LoROM). El código se copia a RAM
    # ($7E:D96F...) y en $7E:D988 hace LDA.L $00213F; AND #$10; BNE ok; con NTSC
    # sigue por la rama que carga la rutina de aviso. BNE (D0) -> BRA (80), igual
    # que uCON64 -f. CONFIRMADO por el usuario en hardware real con destino NTSC.
    (bytes([0xAF, 0x3F, 0x21, 0x00, 0x29, 0x10, 0xD0, 0x15, 0xA2, 0xD7, 0xD9, 0x86, 0xAE]),
     b"\x80", -7, [], 0x01, 0x02, "R-Type III (Europe)"),
    # Art of Fighting (Europe): región nativa PAL (HiROM de 2 MB). Rutina en
    # $C0:1591: SEP #$20; LDA.L $00213F; AND #$10; BEQ +4; REP #$20; CLC; RTS;
    # REP #$20; SEC; RTS. El llamador ($C0:9848) hace BCS -> pantalla de aviso.
    # Con NTSC (bit 4 = 0) el BEQ SÍ se toma y devuelve Carry=1 (aviso); con PAL
    # sigue y devuelve Carry=0. Se neutraliza el BEQ (EA EA) para que siempre
    # devuelva Carry=0. Hallado comparando trazas reales (NTSC con aviso / PAL
    # sin él). OJO: aquí el BEQ lleva al aviso, al revés que en otros juegos,
    # por eso NO sirve BEQ->BRA.
    (bytes([0xAF, 0x3F, 0x21, 0x00, 0x29, 0x10, 0xF0, 0x04, 0xC2, 0x20, 0x18, 0x60]),
     b"\xea\xea", -6, [], 0x01, 0x02, "Art of Fighting (Europe)"),
    # Zombies Ate My Neighbors (Europe): región nativa PAL. Única lectura
    # de STAT78 en $80:919C (SEP #$20; LDA $213F; REP #$20; AND #$0010;
    # BNE $809202). Con NTSC (bit 4 = 0) el BNE no se toma y cae en
    # JSL $80C2E6, que prepara la pantalla de aviso; con PAL salta a un
    # RTL. Se cambia BNE (D0) -> BRA (80) para que SIEMPRE salte. Hallado
    # comparando trazas reales (NTSC con aviso / PAL sin él) y CONFIRMADO
    # en hardware real por el usuario con destino NTSC.
    (bytes([0xAD, 0x3F, 0x21, 0xC2, 0x20, 0x29, 0x10, 0x00, 0xD0]),
     b"\x80", -1, [], 0x01, 0x02, "Zombies Ate My Neighbors (Europe)"),
    # Yoshi's Safari (Europe): región nativa PAL (HiROM no, LoROM FastROM
    # de 1 MB). Comprobación en el arranque, $80:8055 (LDA $213F; AND #$10;
    # BNE $808062): con PAL salta a JSL $80C655 (carga normal) y deja
    # $26=$83; con NTSC deja $26=$81 y entra en la máquina de estados que
    # muestra el aviso. BNE (D0) -> BRA (80). Hay otra lectura de $213F
    # (AND #$40) relacionada con la pistola de luz, NO es de región y no se
    # toca. Confirmado en hardware real por el usuario con destino NTSC.
    (bytes([0x85, 0x26, 0xAD, 0x3F, 0x21, 0x29, 0x10, 0xD0]),
     b"\x80", -1, [], 0x01, 0x02, "Yoshi's Safari (Europe)"),
]


def aplicar_inversion_region(datos: bytes, solo_descripcion: str) -> tuple:
    """Invierte la comprobación de región nativa de un ROM (ver
    PATRONES_INVERSION_REGION arriba) — para generar la variante dirigida
    a la región CONTRARIA a la nativa del dump. Nunca se llama sola: va
    siempre después de aplicar los parches base propios del juego (ver
    aplicar_variante_dual).

    `solo_descripcion` es OBLIGATORIO (no opcional): filtra para aplicar
    ÚNICAMENTE la entrada de PATRONES_INVERSION_REGION cuya descripción
    coincida exactamente, ignorando el resto. Necesario porque la lista
    crece con cada juego de doble variante que se añade, y un patrón de
    un juego puede coincidir por pura casualidad en el ROM de otro juego
    distinto (confirmado con datos reales: el patrón de RoboCop versus
    The Terminator tenía varias coincidencias casuales dentro del ROM de
    Donkey Kong Country) — aplicar "todos los patrones de la lista" sin
    filtrar corrompería cualquier otro juego dual con esas coincidencias.
    """
    buf = bytearray(datos)
    cambios = []
    for search, replace, offset, sets, wildcard, escape, desc in PATRONES_INVERSION_REGION:
        if desc != solo_descripcion:
            continue
        patron = Patron(search, replace, offset, sets, desc, wildcard, escape)
        n = aplicar_patron(buf, patron)
        if n:
            texto = desc or f"patrón sin descripción ({search.hex()})"
            cambios.append(f"{texto}  (×{n})" if n > 1 else texto)
    return bytes(buf), cambios


def aplicar_variante_dual(datos: bytes, base, destino_es_nativo: bool, patron_descripcion: str) -> tuple:
    """Genera la copia de un juego de \"doble variante\" (ver VarianteDual
    en parches_conocidos.py) para la región elegida por el usuario.

    `base` es la ParchesConocidos con los parches que hacen falta SIEMPRE
    (normalmente solo la protección anti-copia, vía aplicar_crack — el
    fix de región NO se marca ahí, se maneja aquí aparte). `destino_es_nativo`
    indica si la región elegida es la nativa del dump (en cuyo caso solo
    hacen falta los parches base, sin tocar la comprobación de región) o
    la contraria (en cuyo caso, además, se invierte esa comprobación).
    `patron_descripcion` identifica cuál entrada de
    PATRONES_INVERSION_REGION aplicar (ver aplicar_inversion_region) —
    obligatorio para no aplicar por error el patrón de inversión de OTRO
    juego que coincida por casualidad en este ROM.

    Devuelve (datos_parcheados, lista_de_cambios).
    """
    cuerpo, cambios = datos, []
    if base.crack:
        cuerpo, ck = aplicar_crack(cuerpo)
        cambios += ck
    if base.slowrom:
        cuerpo, cl = aplicar_fix_slowrom(cuerpo)
        cambios += cl
    if not destino_es_nativo:
        cuerpo, ci = aplicar_inversion_region(cuerpo, patron_descripcion)
        cambios += ci
    return cuerpo, cambios


# Patrones de "-l" de uCON64: elimina las comprobaciones de SlowROM que
# algunos juegos usan como protección — verifican que el cartucho responda
# con el timing de acceso de SlowROM que esperan, y si detectan algo
# distinto (como algunos copiones o flashcarts) el juego puede fallar o
# congelarse en pantalla negra. Extraídos literalmente del comentario del
# propio código fuente de uCON64 (console/snes.c, función snes_l).
#
# Los offsets aquí son los del código C MENOS 1: en cambio_mem2() (la
# función C real, misc/misc.c) la posición de referencia para el offset
# es el ÍNDICE del último byte del patrón encontrado (bufpos se mueve en
# paralelo con el propio patrón y se congela ahí), mientras que en
# aplicar_patron() la referencia es "una posición más allá" (pos + n,
# el primer byte DESPUÉS del patrón) — verificado reproduciendo a mano el
# ejemplo textual del propio comentario original ("8c/8d/8e/8f 0d 42 ->
# 9c 0d 42"): con el offset del código C tal cual (-2) el resultado salía
# desplazado un byte ("8c 9c 42"); con -3 coincide exactamente.
#
# A diferencia de -k y -f, uCON64 no documenta variantes específicas por
# juego para esta comprobación: son solo estos 8 patrones fijos.
#
# ADVERTENCIA IMPORTANTE (encontrada investigando los 3 ClayFighter, que
# activan FastROM de forma legítima con "LDA #$01; STA $420D" — un patrón
# que coincidiría aquí igual que una comprobación real, escribiendo 0 en
# vez del 1 que el juego necesita): estos patrones convierten CUALQUIER
# escritura a $420D (MEMSEL) en STZ (forzar 0/SlowROM), sin comprobar qué
# valor se estaba escribiendo en realidad. Si el valor real era ya 0
# (SlowROM), el cambio es inofensivo pero inútil — es lo que pasaba con
# "American Tail: Fievel Goes West", donde $420D forma parte de una
# cadena larga de inicialización de registros con un LDA #$00 varias
# instrucciones atrás, no justo antes; intentar exigir un LDA #$00
# inmediatamente adyacente para "arreglar" esto descarta también ese
# caso legítimo, así que no se ha hecho — un motor de bytes simple no
# puede rastrear con fiabilidad el valor real del acumulador a través de
# instrucciones intermedias. Si el valor real era 1 (FastROM, como en
# ClayFighter), el cambio SÍ altera el comportamiento real del juego.
# Conclusión práctica: antes de dar por buena una coincidencia de estos
# patrones y guardarla en el catálogo como "necesita parche", conviene
# mirar el byte cargado inmediatamente antes de la escritura para
# confirmar que de verdad es 0, no asumirlo solo porque el patrón
# coincidió. El segundo patrón de abajo (3 bytes fijos "01 0D 42", sin
# ningún wildcard) es aún más propenso a coincidir por pura casualidad
# con datos/código no relacionado en absoluto — confirmado con un caso
# real en ClayFighter 2 que no tenía nada que ver con MEMSEL.
PATRONES_SLOWROM = [
    (bytes([ESCAPE, 0x0d, 0x42]), b"\x9c", -3, [b"\x8c\x8d\x8e\x8f"], WILDCARD, ESCAPE,
     "STA/STX/STY/STZ $420D (MEMSEL) -> STZ (fuerza SlowROM)"),
    (b"\x01\x0d\x42", b"\x00", -3, [], WILDCARD, ESCAPE, ""),
    (b"\xa9\x01\x85\x0d", b"\x00", -3, [], WILDCARD, ESCAPE, ""),
    (b"\xa2\x01\x86\x0d", b"\x00", -3, [], WILDCARD, ESCAPE, ""),
    (b"\xa0\x01\x84\x0d", b"\x00", -3, [], WILDCARD, ESCAPE, ""),
    (bytes([ESCAPE, 0x01, ESCAPE, 0x0d, 0x42]), b"\x00", -4,
     [b"\xa9\xa2", b"\x8d\x8e"], WILDCARD, ESCAPE, ""),
    (b"\xa9\x01\x00\x8d\x0d\x42", b"\x00", -5, [], WILDCARD, ESCAPE, ""),
    (b"\xa9\x01\x8f\x0d\x42\x00", b"\x00", -5, [], WILDCARD, ESCAPE, ""),
]


def aplicar_fix_slowrom(datos: bytes) -> tuple:
    """Aplica los patrones de eliminación de comprobaciones SlowROM (-l de
    uCON64) sobre `datos` (trabaja sobre una copia; el original no se
    modifica).

    Devuelve (datos_parcheados, lista_de_cambios), igual que aplicar_crack
    y aplicar_fix_pal.
    """
    buf = bytearray(datos)
    cambios = []
    for search, replace, offset, sets, wildcard, escape, desc in PATRONES_SLOWROM:
        patron = Patron(search, replace, offset, sets, desc, wildcard, escape)
        n = aplicar_patron(buf, patron)
        if n:
            texto = desc or f"patrón sin descripción ({search.hex()})"
            cambios.append(f"{texto}  (×{n})" if n > 1 else texto)
    return bytes(buf), cambios
