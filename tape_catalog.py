"""Catálogo de programas de una cinta MSX (formato CAS).

Interpreta los bloques de un CAS y los agrupa en programas con su nombre,
tipo y, si son binarios, las direcciones de inicio, final y ejecución.

Estructura de una cinta MSX estándar:

- Bloque de CABECERA: diez bytes de tipo repetidos y un nombre de 6
  caracteres. Tipo D0 = binario (BSAVE), D3 = BASIC tokenizado (CSAVE),
  EA = BASIC en ASCII (SAVE"CAS:").
- Bloques de DATOS:
    * Binario: un bloque que empieza con dirección de inicio, final y de
      ejecución (6 bytes, 16 bits little endian) seguido del código. En la
      cinta NO lleva el byte FE que sí tiene el archivo en disco.
    * BASIC tokenizado: un bloque con el programa en tokens.
    * ASCII: bloques de 256 bytes hasta un byte 1A (fin de archivo).
- Las cintas con cargador propio (juegos) añaden bloques de datos SIN
  cabecera que lee el propio programa; se listan como «datos».
"""
from __future__ import annotations

from dataclasses import dataclass, field

CAS_SYNC = bytes.fromhex("1FA6DEBACC137D74")

HEADER_BIN = 0xD0
HEADER_BASIC = 0xD3
HEADER_ASCII = 0xEA
HEADER_TYPES = (HEADER_BIN, HEADER_BASIC, HEADER_ASCII)

KIND_LABEL = {
    "bin": "Binario (BSAVE)",
    "basic": "BASIC",
    "ascii": "BASIC ASCII",
    "data": "Datos sin cabecera",
}
KIND_EXT = {"bin": ".BIN", "basic": ".BAS", "ascii": ".ASC", "data": ".DAT"}


@dataclass
class TapeEntry:
    index: int
    kind: str                      # bin | basic | ascii | data
    name: str
    cas_start: int                 # inicio (en el CAS) de la marca de su cabecera
    cas_end: int
    body: bytes = b""              # contenido útil (sin cabeceras de cinta)
    start: int | None = None
    end: int | None = None
    exec_addr: int | None = None
    blocks: int = 1
    notes: list[str] = field(default_factory=list)

    @property
    def kind_label(self) -> str:
        return KIND_LABEL.get(self.kind, self.kind)

    @property
    def size(self) -> int:
        return len(self.body)

    @property
    def display_name(self) -> str:
        return self.name or "(sin nombre)"


def _sync_positions(cas: bytes) -> list[int]:
    return [o for o in range(0, len(cas) - 7, 8) if cas[o:o + 8] == CAS_SYNC]


def header_info(content: bytes) -> tuple[int, str] | None:
    """(tipo, nombre) si el bloque es una cabecera de archivo; si no, None."""
    if len(content) >= 16 and content[0] in HEADER_TYPES and \
            content[:10] == bytes([content[0]]) * 10:
        raw = content[10:16]
        name = "".join(chr(b) if 32 <= b < 127 else "?" for b in raw).rstrip()
        return content[0], name
    return None


def _u16(b: bytes, i: int) -> int:
    return b[i] | (b[i + 1] << 8)


def parse_tape(cas: bytes) -> list[TapeEntry]:
    """Lista de programas (y bloques de datos sueltos) de un CAS."""
    pos = _sync_positions(cas)
    if not pos:
        return []
    bounds = pos + [len(cas)]
    blocks = [(a, cas[a + 8:b]) for a, b in zip(bounds, bounds[1:])]

    entries: list[TapeEntry] = []
    cur: TapeEntry | None = None
    raw_data: list[bytes] = []

    def finish():
        nonlocal cur, raw_data
        if cur is not None:
            _fill_entry(cur, raw_data)
        cur = None
        raw_data = []

    for off, content in blocks:
        h = header_info(content)
        if h is not None:
            finish()
            kind = {HEADER_BIN: "bin", HEADER_BASIC: "basic", HEADER_ASCII: "ascii"}[h[0]]
            cur = TapeEntry(len(entries), kind, h[1], off, off + 8 + len(content))
            entries.append(cur)
            continue
        # bloque de datos
        accepts = False
        if cur is not None:
            if cur.kind in ("bin", "basic"):
                accepts = not raw_data
            elif cur.kind == "ascii":
                accepts = not any(0x1A in d for d in raw_data)
        if accepts:
            raw_data.append(content)
            cur.cas_end = off + 8 + len(content)
            cur.blocks += 1
        else:
            finish()
            cur = TapeEntry(len(entries), "data", "", off, off + 8 + len(content))
            entries.append(cur)
            raw_data.append(content)
    finish()
    return entries


def _fill_entry(e: TapeEntry, data: list[bytes]):
    joined = b"".join(data)
    if e.kind == "bin":
        if len(joined) < 6:
            e.notes.append("Sin datos tras la cabecera")
            return
        e.start, e.end, e.exec_addr = _u16(joined, 0), _u16(joined, 2), _u16(joined, 4)
        payload = joined[6:]
        want = e.end - e.start + 1
        if e.end >= e.start and want <= len(payload):
            e.body = payload[:want]
        else:
            e.body = payload.rstrip(b"\x00")
            e.notes.append("Las direcciones no cuadran con el tamaño del bloque")
    elif e.kind == "basic":
        e.body = joined.rstrip(b"\x00")
    elif e.kind == "ascii":
        cut = joined.find(b"\x1a")
        e.body = joined if cut < 0 else joined[:cut]
        if cut < 0:
            e.notes.append("Falta el marcador de fin de archivo (1A)")
    else:
        e.body = joined.rstrip(b"\x00")
        if joined and len(joined) >= 2 and not e.name:
            e.name = ""


def entry_cas(cas: bytes, entry: TapeEntry) -> bytes:
    """El trozo de CAS (cabecera + bloques) de un programa, listo para guardar."""
    return cas[entry.cas_start:entry.cas_end]


def entry_file(entry: TapeEntry) -> bytes:
    """Contenido como archivo de disco MSX: BIN con su cabecera FE, BAS con FF."""
    if entry.kind == "bin" and entry.start is not None:
        hdr = bytes([0xFE, entry.start & 0xFF, entry.start >> 8,
                     entry.end & 0xFF, entry.end >> 8,
                     (entry.exec_addr or 0) & 0xFF, (entry.exec_addr or 0) >> 8])
        return hdr + entry.body
    if entry.kind == "basic":
        return b"\xff" + entry.body
    return entry.body


def suggested_filename(entry: TapeEntry, taken: set[str] | None = None) -> str:
    """Nombre de archivo MSX-DOS (8.3) sugerido para exportar un programa."""
    base = "".join(c for c in entry.name.upper() if c.isalnum() or c in "_-") or f"PROG{entry.index + 1}"
    base = base[:8]
    name = base + KIND_EXT.get(entry.kind, ".DAT")
    if taken is not None:
        n = 2
        while name in taken:
            suf = str(n)
            name = base[:8 - len(suf)] + suf + KIND_EXT.get(entry.kind, ".DAT")
            n += 1
        taken.add(name)
    return name


def hex16(v: int | None) -> str:
    return "—" if v is None else f"&H{v:04X}"
