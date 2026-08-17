"""Conversor de cintas MSX entre formato CAS y TSX (TZX 1.21 con el bloque
KCS #4B para datos Kansas City Standard).

Especificación usada, verificada de dos formas independientes:

1. Documentación de la propia herramienta de referencia, escrita por el
   creador del formato: comentarios de cabecera de la clase `Block4B` en
   `tsx.php` (proyecto TSXphpclass de NataliaPC,
   github.com/nataliapc/MSX_devs/blob/master/TSXphpclass/tsx.php) y el
   tutorial "How to generate TSX files"
   (github.com/nataliapc/makeTSX/wiki).
2. Diseccionado byte a byte contra tres archivos .tsx reales (ripeos de
   cintas comerciales MSX de la escena de preservación), confirmando que
   cada campo cae exactamente donde la documentación dice y con valores
   físicamente coherentes (p. ej. duración de pulso piloto ≈ 707-729
   T-states a 1200 baudios, patrón de bits 2 pulsos/cero y 4 pulsos/uno,
   etc.).

Layout del bloque #4B (cabecera TZX, "T-states" = ciclos de reloj a 3.5 MHz,
la unidad de tiempo que usa todo el formato TZX/TSX heredada del Z80 del
ZX Spectrum, aunque el bloque describa datos de un MSX):

    0x00  ID del bloque = 0x4B
    0x01  DWORD  Longitud del bloque SIN contar estos 4 bytes (= 12+N)
    0x05  WORD   Pausa tras el bloque (ms)
    0x07  WORD   Duración del pulso PILOTO (T-states) — igual que pulso ONE
    0x09  WORD   Nº de pulsos del tono piloto
    0x0B  WORD   Duración del pulso ZERO (T-states)
    0x0D  WORD   Duración del pulso ONE (T-states)
    0x0F  BYTE   Config. de bits: nibble alto = pulsos por bit 0 (MSX: 2)
                                    nibble bajo = pulsos por bit 1 (MSX: 4)
    0x10  BYTE   Config. de bytes (MSX: 0x54 = 1 start bit a 0,
                  2 stop bits a 1, LSB primero)
    0x11  BYTE[N]  Datos: la misma secuencia de bytes que llevaría un
                    archivo .CAS para ese bloque (incluida la marca de
                    sincronismo si es un bloque de cabecera/datos CAS).

Simplificación deliberada y documentada, igual que en el conversor CAS↔WAV:
se antepone un tono piloto "largo" (30720 pulsos a 1200 baudios) a CADA
segmento delimitado por marca de sincronismo, en vez de alternar entre
piloto largo (cabecera) y corto (datos). Un piloto más largo de lo
necesario nunca causa fallos de carga.

El resto de bloques TZX que puedan aparecer en un .tsx real (texto,
información de archivo, pausas, etc.) se reconocen lo justo para poder
saltarlos correctamente al leer; el contenido relevante para MSX está
siempre en los bloques #4B.
"""
from __future__ import annotations

import struct

TSX_MAGIC = b"ZXTape!\x1a"
TSX_HEADER = TSX_MAGIC + bytes([1, 21])  # versión 1.21

CAS_SYNC = bytes.fromhex("1FA6DEBACC137D74")

T_STATE_HZ = 3_500_000  # reloj de referencia de TZX/TSX (3.5 MHz, heredado del Z80)

# (frecuencia "space" = bit 0, frecuencia "mark" = bit 1) por baudios
BAUD_TONES = {
    1200: (1200, 2400),
    2400: (2400, 4800),
}
# nº de pulsos del tono piloto largo, por baudios (BIOS del MSX)
BAUD_PILOT_LONG = {
    1200: 30720,
    2400: 63488,
}

MSX_BIT_CONFIG = 0x24   # 2 pulsos para bit 0, 4 pulsos para bit 1
MSX_BYTE_CONFIG = 0x54  # 1 start bit(0), 2 stop bits(1), LSB primero


def _segments(data: bytes) -> list[tuple[int, int]]:
    """Igual que en cas_tape.py: delimita el CAS en tramos por marca de
    sincronismo, para poder envolver cada tramo en su propio Block4B."""
    positions = []
    for off in range(0, len(data) - 8 + 1, 8):
        if data[off:off + 8] == CAS_SYNC:
            positions.append(off)
    if not positions:
        return [(0, len(data))] if data else []
    segments = []
    if positions[0] != 0:
        segments.append((0, positions[0]))
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(data)
        segments.append((pos, end))
    return segments


def _make_block4b(data: bytes, baud: int, pause_ms: int = 500) -> bytes:
    if baud not in BAUD_TONES:
        raise ValueError("baud debe ser 1200 o 2400")
    space_hz, mark_hz = BAUD_TONES[baud]

    pilot_dur = round(T_STATE_HZ / mark_hz / 2)
    one_dur = pilot_dur  # mismo valor, por definición (nota de la spec)
    zero_dur = round(T_STATE_HZ / space_hz / 2)
    pilot_num = BAUD_PILOT_LONG[baud]

    header = struct.pack(
        "<IHHHHHBB",
        12 + len(data),   # longitud del bloque tras este campo
        pause_ms,
        pilot_dur,
        pilot_num,
        zero_dur,
        one_dur,
        MSX_BIT_CONFIG,
        MSX_BYTE_CONFIG,
    )
    return bytes([0x4B]) + header + data


def _make_block35(identifier: str, text: str) -> bytes:
    ident = identifier.upper()[:16].ljust(16).encode("ascii", "replace")
    payload = text.encode("ascii", "replace")
    return bytes([0x35]) + ident + struct.pack("<I", len(payload)) + payload


def cas_to_tsx(data: bytes, baud: int = 1200, pause_ms: int = 500) -> bytes:
    """Convierte el contenido de un .CAS a .TSX (bloques #4B).

    La marca de sincronismo de 8 bytes de cada segmento NO se guarda en los
    datos del bloque #4B: es implícita (la representa el propio bloque,
    con su tono piloto), tal y como se comprobó dedisecionando archivos
    .tsx reales. Se reconstruye automáticamente al volver a CAS.
    """
    if not data:
        raise ValueError("el archivo CAS está vacío")

    out = bytearray()
    out += TSX_HEADER
    out += _make_block35("TSX.RIPPER", "ROM Inspector CAS2TSX")
    for start, end in _segments(data):
        chunk = data[start:end]
        if chunk[:8] == CAS_SYNC:
            chunk = chunk[8:]
        out += _make_block4b(chunk, baud=baud, pause_ms=pause_ms)
    return bytes(out)


def _skip_block(data: bytes, pos: int) -> tuple[int, bytes | None]:
    """Devuelve (siguiente_posición, datos_extraídos_o_None) para el bloque
    que empieza en `pos`. `datos_extraídos` solo tiene valor para #4B."""
    if pos >= len(data):
        return len(data), None
    bid = data[pos]

    if bid == 0x4B:
        blocklen = struct.unpack_from("<I", data, pos + 1)[0]
        payload_len = blocklen - 12
        payload_start = pos + 1 + 4 + 12
        payload = data[payload_start:payload_start + payload_len]
        return payload_start + payload_len, payload

    if bid == 0x10:  # Standard speed data block (ZX)
        length = struct.unpack_from("<H", data, pos + 3)[0]
        return pos + 5 + length, None
    if bid == 0x11:  # Turbo speed data block (ZX)
        len16, len8 = struct.unpack_from("<HB", data, pos + 0x10)
        length = len16 | (len8 << 16)
        return pos + 0x13 + length, None
    if bid == 0x12:  # Pure tone
        return pos + 5, None
    if bid == 0x13:  # Sequence of pulses
        num = data[pos + 1]
        return pos + 2 + num * 2, None
    if bid == 0x14:  # Pure data block
        len16, len8 = struct.unpack_from("<HB", data, pos + 7)
        length = len16 | (len8 << 16)
        return pos + 0x0B + length, None
    if bid == 0x15:  # Direct recording
        len16, len8 = struct.unpack_from("<HB", data, pos + 5)
        length = len16 | (len8 << 16)
        return pos + 9 + length, None
    if bid == 0x18:  # CSW recording block
        blocklen = struct.unpack_from("<I", data, pos + 1)[0]
        return pos + 5 + blocklen, None
    if bid == 0x20:  # Pause / stop the tape
        return pos + 3, None
    if bid == 0x21:  # Group start
        length = data[pos + 1]
        return pos + 2 + length, None
    if bid == 0x22:  # Group end
        return pos + 1, None
    if bid == 0x30:  # Text description
        length = data[pos + 1]
        return pos + 2 + length, None
    if bid == 0x31:  # Message block
        length = data[pos + 2]
        return pos + 3 + length, None
    if bid == 0x32:  # Archive info
        length = struct.unpack_from("<H", data, pos + 1)[0]
        return pos + 3 + length, None
    if bid == 0x35:  # Custom (general extension) info
        length = struct.unpack_from("<I", data, pos + 17)[0]
        return pos + 1 + 16 + 4 + length, None
    if bid == 0x5A:  # Glue block
        return pos + 10, None

    raise ValueError(
        f"bloque TZX/TSX desconocido (ID 0x{bid:02X}) en offset {pos:#x}; "
        "no se puede seguir leyendo con seguridad"
    )


def tsx_to_cas(data: bytes) -> bytes:
    """Extrae los datos de todos los bloques #4B de un .TSX y reconstruye
    el flujo de bytes equivalente a un .CAS, incluida la marca de
    sincronismo de 8 bytes (implícita en el TSX, no almacenada) delante de
    cada uno, con el relleno de alineación a 8 bytes que exige el formato
    CAS entre bloques. El resto de bloques TZX (texto, información de
    archivo, pausas...) se ignoran."""
    if data[:8] != TSX_MAGIC:
        raise ValueError('no es un archivo TZX/TSX válido (falta la cabecera "ZXTape!")')

    pos = 10
    out = bytearray()
    found_4b = False
    while pos < len(data):
        pos, payload = _skip_block(data, pos)
        if payload is not None:
            found_4b = True
            rem = len(out) % 8
            if rem:
                out += bytes(8 - rem)
            out += CAS_SYNC
            out += payload

    if not found_4b:
        raise ValueError("no se encontró ningún bloque #4B (KCS/MSX) en el archivo TSX")
    return bytes(out)


# IDs de bloque TZX que representan datos reales pero NO en formato KCS/MSX
# (mayoritariamente bloques "estilo ZX Spectrum": velocidad estándar/turbo,
# datos puros, grabación directa, CSW). Si un TSX tiene una cantidad
# significativa de bytes en estos bloques, es señal de que el juego usa un
# cargador de protección/turbo con una codificación de pulsos distinta a la
# KCS estándar del MSX -algo real y relativamente común en juegos de la
# escena española de los 80 protegidos contra copia-, y el CAS resultante
# de convertir solo los bloques #4B estará incompleto: el CAS no puede
# representar esos datos en absoluto, no es un fallo de esta herramienta.
NON_KCS_DATA_BLOCK_IDS = {0x10, 0x11, 0x14, 0x15, 0x18}


def scan_tsx_blocks(data: bytes) -> dict[int, tuple[int, int]]:
    """Devuelve {id_de_bloque: (cantidad, bytes_totales)} para todo el
    archivo TSX, útil para detectar si hay contenido relevante fuera de
    los bloques #4B antes de convertir a CAS."""
    if data[:8] != TSX_MAGIC:
        raise ValueError('no es un archivo TZX/TSX válido (falta la cabecera "ZXTape!")')
    pos = 10
    counts: dict[int, tuple[int, int]] = {}
    while pos < len(data):
        start = pos
        bid = data[pos]
        pos, _payload = _skip_block(data, pos)
        n, total = counts.get(bid, (0, 0))
        counts[bid] = (n + 1, total + (pos - start))
    return counts
