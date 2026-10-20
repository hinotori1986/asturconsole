"""Decodificador de cintas MSX (audio -> CAS) pensado para grabaciones reales.

Sustituye, para el grabador, al decodificador sencillo de ``cas_tape`` (que
sigue sirviendo para el audio limpio generado por la propia aplicación).
Trabaja con numpy y está pensado para una señal que viene de un casete o de
la salida de un MSX por la entrada de línea de un ordenador:

- Elimina la componente continua (DC) y mide el nivel local, de modo que un
  volumen bajo o una cinta que sube y baja de nivel no rompe la lectura.
- Usa un disparador con histéresis (Schmitt) para ignorar el ruido cercano a
  cero, y mide ciclos completos de flanco de subida a flanco de subida. Esa
  medida NO depende de la polaridad de la señal: una cinta con la onda
  invertida se lee igual.
- Mide la velocidad (baudios) en el tono piloto de CADA bloque y sigue sus
  variaciones (wow & flutter) mientras lee los datos, de modo que admite
  cintas con cambios de velocidad dentro de una misma grabación.
- Cuenta los errores de trama (bits de parada incorrectos, ciclos huérfanos)
  y los asocia a cada bloque, para que se vea la calidad de la lectura.
- Procesa por trozos: una cinta de media hora no necesita cientos de MB.

Formato FSK "Kansas City" del MSX: un bit 0 es 1 ciclo a la frecuencia
baja (= baudios) y un bit 1 son 2 ciclos a la frecuencia doble. Cada byte son
11 bits: arranque 0, 8 de datos (LSB primero), dos de parada 1.
"""
from __future__ import annotations

import io
import wave
from dataclasses import dataclass, field

import numpy as np

CAS_SYNC = bytes.fromhex("1FA6DEBACC137D74")

# Racha mínima de bits 1 (tono piloto) para considerar que empieza un bloque.
PILOT_MIN_BITS = 256

# Rango de velocidades que se aceptan al medir el piloto.
MIN_BAUD = 900.0
MAX_BAUD = 4500.0

# Un hueco sin ciclos más largo que esto (segundos) es una pausa entre bloques.
GAP_SECONDS = 0.010

# Ciclos mínimos para considerar que un tramo de señal es algo más que ruido.
MIN_SEGMENT_CYCLES = 200

# Umbral del disparador de histéresis, relativo al nivel local de la señal.
EDGE_REL = 0.18


# ---------------------------------------------------------------------------
# Lectura de audio
# ---------------------------------------------------------------------------

def wav_to_float(wav_bytes: bytes, channel: int | None = None) -> tuple[int, np.ndarray]:
    """Lee un WAV (8, 16, 24 o 32 bits, mono o estéreo) como float32 en
    [-1, 1]. En estéreo, ``channel=None`` elige el canal con más señal."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        nch = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    return rate, pcm_to_float(raw, nch, width, rate, channel)[1]


def pcm_to_float(raw: bytes, n_channels: int, sample_width: int, rate: int,
                 channel: int | None = None) -> tuple[int, np.ndarray]:
    if sample_width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        n = len(raw) // 2
        data = np.frombuffer(raw[:n * 2], dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 3:
        n = len(raw) // 3
        b = np.frombuffer(raw[:n * 3], dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v & 0x800000, v - 0x1000000, v)
        data = v.astype(np.float32) / 8388608.0
    elif sample_width == 4:
        n = len(raw) // 4
        data = np.frombuffer(raw[:n * 4], dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"profundidad de bits no soportada: {sample_width * 8}")
    if n_channels > 1:
        frames = len(data) // n_channels
        data = data[:frames * n_channels].reshape(frames, n_channels)
        if channel is None:
            channel = best_channel(data)
        data = np.ascontiguousarray(data[:, channel])
    return rate, data


def best_channel(frames: np.ndarray) -> int:
    """Índice del canal con más señal (el que de verdad lleva la cinta)."""
    if frames.ndim == 1 or frames.shape[1] == 1:
        return 0
    step = max(1, len(frames) // 400000)
    sub = frames[::step]
    energy = [float(np.sqrt(np.mean((sub[:, c] - sub[:, c].mean()) ** 2)))
              for c in range(sub.shape[1])]
    return int(np.argmax(energy))


# ---------------------------------------------------------------------------
# Flancos
# ---------------------------------------------------------------------------

def _signal_gate(x: np.ndarray, sr: int) -> tuple[float, float]:
    """(umbral de silencio, ruido de fondo). Se calcula una vez para toda la
    grabación, para que todos los trozos usen los mismos valores. El ruido de
    fondo es 0 si en la grabación no hay silencios que medir."""
    block = max(1, sr // 200)
    n = (len(x) // block) * block
    if n == 0:
        return 1.0, 0.0
    v = x[:n].reshape(-1, block)
    amp = (v.max(axis=1) - v.min(axis=1)) * 0.5
    typical = float(np.percentile(amp, 98))
    floor = float(np.percentile(amp, 1.5))
    if floor >= 0.35 * typical:
        floor = 0.0
    gate = max(0.25 * typical, 2.0 * floor)
    gate = min(max(gate, 0.012), max(0.6 * typical, 0.012))
    return gate, floor


def _edges_chunk(seg: np.ndarray, sr: int, gate: float, floor: float):
    """Posiciones (muestras, con decimales) de los flancos de subida y de bajada."""
    n = len(seg)
    win = max(3, int(sr * 0.010)) | 1
    half = win // 2
    padded = np.pad(seg.astype(np.float64), (half, half), mode="edge")
    cs = np.concatenate(([0.0], np.cumsum(padded)))
    mean = (cs[win:] - cs[:-win]) / win
    y = seg - mean[:n].astype(np.float32)

    block = max(2, sr // 200)
    nb = -(-n // block)
    ypad = np.pad(np.abs(y), (0, nb * block - n))
    peaks = ypad.reshape(nb, block).max(axis=1)
    env = peaks.copy()
    if nb > 2:
        env[1:-1] = np.maximum(np.maximum(peaks[:-2], peaks[1:-1]), peaks[2:])
        env[0] = max(peaks[0], peaks[1])
        env[-1] = max(peaks[-1], peaks[-2])
    th_b = np.where(env >= gate, np.maximum(np.maximum(EDGE_REL * env, 1.2 * floor), 0.003), np.inf)
    th = np.repeat(th_b, block)[:n]

    state = np.zeros(n, dtype=np.int8)
    state[y > th] = 1
    state[y < -th] = -1
    idx = np.where(state != 0, np.arange(n), 0)
    np.maximum.accumulate(idx, out=idx)
    s = state[idx]
    rise = np.flatnonzero((s[:-1] == -1) & (s[1:] == 1)) + 1
    fall = np.flatnonzero((s[:-1] == 1) & (s[1:] == -1)) + 1
    return (_refine(y, rise, True, block), _refine(y, fall, False, block))


def _refine(y: np.ndarray, trig: np.ndarray, rising: bool, block: int) -> np.ndarray:
    """Afina cada disparo al cruce por cero real (interpolación lineal)."""
    if len(trig) == 0:
        return np.empty(0, dtype=np.float64)
    if rising:
        z = np.flatnonzero((y[:-1] <= 0) & (y[1:] > 0))
    else:
        z = np.flatnonzero((y[:-1] >= 0) & (y[1:] < 0))
    if len(z) == 0:
        return trig.astype(np.float64)
    k = np.clip(np.searchsorted(z, trig, side="left") - 1, 0, len(z) - 1)
    zi = z[k]
    y0 = y[zi].astype(np.float64)
    y1 = y[zi + 1].astype(np.float64)
    frac = np.where(y1 != y0, -y0 / (y1 - y0), 0.0)
    pos = zi + np.clip(frac, 0.0, 1.0)
    # Si el cruce asignado quedó muy lejos del disparo, usa el disparo.
    return np.where(trig - pos > 3 * block, trig.astype(np.float64), pos)


def find_edges(x: np.ndarray, sr: int, chunk: int = 1 << 20,
               progress=None) -> tuple[np.ndarray, np.ndarray]:
    """(flancos de subida, flancos de bajada) de toda la señal, por trozos
    para acotar la memoria."""
    gate, floor = _signal_gate(x, sr)
    pad = max(2048, int(sr * 0.05))
    rises, falls = [], []
    n = len(x)
    start = 0
    while start < n:
        end = min(n, start + chunk)
        a = max(0, start - pad)
        b = min(n, end + pad)
        r, f = _edges_chunk(x[a:b], sr, gate, floor)
        r = r + a
        f = f + a
        rises.append(r[(r >= start) & (r < end)])
        falls.append(f[(f >= start) & (f < end)])
        start = end
        if progress:
            progress(start / n)
    empty = np.empty(0, dtype=np.float64)
    return (np.concatenate(rises) if rises else empty,
            np.concatenate(falls) if falls else empty)


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class TapeBlock:
    """Un bloque de cinta: lo que sigue a un tono piloto."""
    cas_offset: int           # posición de la marca de sincronismo en el CAS
    length: int               # bytes decodificados (sin la marca)
    start_s: float            # segundo de la grabación en que empieza el piloto
    end_s: float
    baud: float
    framing_errors: int = 0
    orphan_cycles: int = 0

    @property
    def clean(self) -> bool:
        return self.framing_errors == 0 and self.orphan_cycles == 0


@dataclass
class DecodeResult:
    cas: bytes
    sample_rate: int
    duration_s: float
    blocks: list[TapeBlock] = field(default_factory=list)
    segments: int = 0
    framing_errors: int = 0
    orphan_cycles: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def baud(self) -> float:
        """Velocidad predominante (ponderada por bytes)."""
        if not self.blocks:
            return 0.0
        total = sum(max(1, b.length) for b in self.blocks)
        return sum(b.baud * max(1, b.length) for b in self.blocks) / total

    @property
    def standard_baud(self) -> int:
        return snap_baud(self.baud)


def snap_baud(baud: float) -> int:
    """Velocidad estándar más cercana (1200/2400) si está a menos de un 12 %;
    si no, el valor medido redondeado a la centena."""
    for std in (1200, 2400):
        if abs(baud - std) / std <= 0.12:
            return std
    return int(round(baud / 100.0) * 100) if baud else 0


# ---------------------------------------------------------------------------
# Decodificación
# ---------------------------------------------------------------------------

def _find_pilot_period(p: np.ndarray, lo: float, hi: float) -> float | None:
    """Periodo de ciclo del piloto (mediana de la primera ventana estable)."""
    w = 96
    m = len(p)
    if m < w:
        return None
    for start in range(0, min(m - w, 6000) + 1, 48):
        win = p[start:start + w]
        med = float(np.median(win))
        if med < lo or med > hi:
            continue
        if np.mean(np.abs(win - med) < 0.18 * med) >= 0.92:
            return med
    return None


def _tracked_short_period(p: np.ndarray, short: np.ndarray, s0: float,
                          window: int = 192) -> np.ndarray:
    """Periodo corto local (media móvil sobre los ciclos cortos)."""
    vals = np.where(short, p, 0.0)
    cnt = short.astype(np.float64)
    cv = np.concatenate(([0.0], np.cumsum(vals)))
    cc = np.concatenate(([0.0], np.cumsum(cnt)))
    n = len(p)
    i = np.arange(n)
    a = np.clip(i - window, 0, n)
    b = np.clip(i + window + 1, 0, n)
    num = cv[b] - cv[a]
    den = cc[b] - cc[a]
    return np.where(den >= 8, num / np.maximum(den, 1), s0)


def _classify(p: np.ndarray, s0: float) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (largo, s_local): ciclo largo = bit 0, corto = mitad de un 1."""
    s_loc = np.full(len(p), s0)
    long_ = p > 1.5 * s_loc
    for _ in range(2):
        s_loc = _tracked_short_period(p, ~long_ & (p > 0.5 * s0), s0)
        long_ = p > 1.5 * s_loc
    return long_, s_loc


def _periods_to_bits(long_: np.ndarray) -> tuple[np.ndarray, int]:
    """Convierte la clasificación corto/largo en bits (0 = largo, 1 = 2 cortos)
    y cuenta los ciclos cortos huérfanos (rachas impares)."""
    m = len(long_)
    li = np.flatnonzero(long_)
    if len(li) == 0:
        k = m // 2
        return np.ones(k, dtype=np.uint8), m % 2
    gaps = np.empty(len(li) + 1, dtype=np.int64)
    gaps[0] = li[0]
    gaps[1:-1] = np.diff(li) - 1
    gaps[-1] = m - 1 - li[-1]
    ones = gaps // 2
    orphans = int(np.sum(gaps % 2))
    total = len(li) + int(ones.sum())
    bits = np.ones(total, dtype=np.uint8)
    zero_pos = np.cumsum(ones)[:len(li)] + np.arange(len(li))
    bits[zero_pos] = 0
    return bits, orphans


def _heal_pilot(bits: np.ndarray) -> np.ndarray:
    """Quita los 0 sueltos dentro de un tono piloto (un 'pinchazo' de ruido que
    parte el piloto en dos). Un 0 entre dos rachas largas de 1 no es dato."""
    for _ in range(3):
        z = np.flatnonzero(bits == 0)
        if len(z) < 3:
            return bits
        ones_between = np.diff(z) - 1            # unos entre ceros consecutivos
        # cero j (1..len-2) con rachas largas a ambos lados
        cand = np.flatnonzero((ones_between[:-1] >= PILOT_MIN_BITS) &
                              (ones_between[1:] >= PILOT_MIN_BITS)) + 1
        # pareja de ceros pegados con rachas largas fuera
        pair = np.flatnonzero((ones_between[:-2] >= PILOT_MIN_BITS) &
                              (ones_between[1:-1] <= 1) &
                              (ones_between[2:] >= PILOT_MIN_BITS)) + 1
        if len(cand) == 0 and len(pair) == 0:
            return bits
        bits = bits.copy()
        bits[z[cand]] = 1
        if len(pair):
            bits[z[pair]] = 1
            bits[z[pair + 1]] = 1
    return bits


def _bits_to_bytes(bits: np.ndarray, with_pilot_flags: bool = True):
    """Interpreta bits como bytes de 11 bits. Devuelve una lista de
    (inicio_bit, valor | -1 para 'piloto' ) para que el llamador inserte la
    marca de sincronismo, más el número de errores de trama."""
    bits = _heal_pilot(bits)
    n = len(bits)
    zeros = np.flatnonzero(bits == 0)
    events: list[tuple[int, int]] = []   # (bit_index, valor) ; valor -1 = piloto
    errors = 0
    zi = 0
    pos = 0
    nz = len(zeros)
    while zi < nz:
        z = int(zeros[zi])
        if z < pos:
            zi += 1
            continue
        ones_run = z - pos
        if ones_run >= PILOT_MIN_BITS:
            events.append((pos, -1))
        if z + 11 > n:
            break
        data = bits[z + 1:z + 9]
        s1, s2 = bits[z + 9], bits[z + 10]
        if s1 == 1 and s2 == 1:
            v = int(np.dot(data, 1 << np.arange(8)))
            events.append((z, v))
            pos = z + 11
        elif s1 == 1:
            # Segunda parada dudosa: se acepta el byte pero se cuenta el fallo.
            v = int(np.dot(data, 1 << np.arange(8)))
            events.append((z, v))
            errors += 1
            pos = z + 10
        else:
            errors += 1
            pos = z + 1
        zi += 1
    return events, errors


def _decode_polarity(e: np.ndarray, sr: int, hint_s: float | None):
    """Decodifica un tramo con una de las dos polaridades de flanco.
    Devuelve (puntuación, s_usado, eventos, errores, huérfanos, s_local) o None."""
    if len(e) < MIN_SEGMENT_CYCLES + 1:
        return None
    lo_s = sr / (2.0 * MAX_BAUD) * 0.8
    hi_s = sr / (2.0 * MIN_BAUD) * 1.2
    p = np.diff(e)
    s0 = _find_pilot_period(p, lo_s, hi_s)
    if s0 is None:
        s0 = hint_s
    if s0 is None:
        s0 = float(np.percentile(p, 30))
    # Ciclo final virtual: el último ciclo de la señal no tiene flanco de
    # cierre, y son justo los bits de parada del último byte.
    p = np.concatenate((p, [s0]))
    best = None
    for cand in (s0, s0 * 2.0, s0 * 0.5):
        if cand < lo_s or cand > hi_s:
            continue
        long_, s_loc = _classify(p, cand)
        bits, orphans = _periods_to_bits(long_)
        events, errors = _bits_to_bytes(bits)
        nbytes = sum(1 for _, v in events if v >= 0)
        score = errors + orphans * 0.5 - 0.0001 * nbytes
        if best is None or score < best[0]:
            best = (score, cand, events, errors, orphans, s_loc)
        if cand == s0 and errors + orphans <= max(2, 0.002 * len(bits)):
            break
    return best


def _clean_fraction(e: np.ndarray) -> float:
    """Qué parte de los ciclos tiene una duración 'limpia' (1x o 2x del
    piloto). La polaridad correcta da flancos alineados con el inicio de bit;
    la contraria da ciclos de transición de duración intermedia."""
    if len(e) < 64:
        return 0.0
    p = np.diff(e)
    s = float(np.percentile(p, 25))
    r = p / s
    ok = (np.abs(r - 1) < 0.22) | (np.abs(r - 2) < 0.3)
    return float(ok.mean())


def _block_len(out: bytearray, block: TapeBlock) -> int:
    has_sync = out[block.cas_offset:block.cas_offset + 8] == CAS_SYNC
    return max(0, len(out) - block.cas_offset - (8 if has_sync else 0))


def decode_edges(edges: tuple[np.ndarray, np.ndarray], sr: int,
                 total_samples: int | None = None, progress=None) -> DecodeResult:
    """A partir de los flancos, reconstruye el CAS."""
    rise, fall = edges
    allp = np.sort(np.concatenate((rise, fall)))
    duration = (total_samples or (allp[-1] if len(allp) else 0)) / sr
    result = DecodeResult(cas=b"", sample_rate=sr, duration_s=duration)
    if len(allp) < 2 * MIN_SEGMENT_CYCLES:
        result.warnings.append("No se ha detectado señal de cinta.")
        return result

    cut = np.flatnonzero(np.diff(allp) > GAP_SECONDS * sr)
    t_starts = allp[np.concatenate(([0], cut + 1))]
    t_ends = allp[np.concatenate((cut, [len(allp) - 1]))]

    out = bytearray()
    last_s = None
    seg_count = 0
    n_seg = len(t_starts)
    for si in range(n_seg):
        t0, t1 = float(t_starts[si]), float(t_ends[si])
        er = rise[np.searchsorted(rise, t0, "left"):np.searchsorted(rise, t1, "right")]
        ef = fall[np.searchsorted(fall, t0, "left"):np.searchsorted(fall, t1, "right")]
        if max(len(er), len(ef)) < MIN_SEGMENT_CYCLES + 1:
            continue
        seg_count += 1
        cands = sorted(((_clean_fraction(er), 0), (_clean_fraction(ef), 1)), reverse=True)
        tried = []
        for _frac, which in cands:
            e = er if which == 0 else ef
            r = _decode_polarity(e, sr, last_s)
            if r is None:
                continue
            tried.append((r, e))
            if r[3] + r[4] <= max(2, 0.002 * len(e)):
                break
        if not tried:
            continue
        (score, s_used, events, errors, orphans, s_loc), e = min(tried, key=lambda t: t[0][0])
        last_s = s_used
        baud = sr / (2.0 * float(np.median(s_loc)))

        pilot_seen = False
        block = None
        # Unos pocos bytes antes del primer piloto son ruido de arranque.
        first_pilot = next((k for k, (_i, v) in enumerate(events) if v == -1), None)
        if first_pilot is not None and 0 < first_pilot <= 3:
            events = events[first_pilot:]
        for _bit_i, v in events:
            if v == -1:
                pilot_seen = True
                rem = len(out) % 8
                if rem:
                    out += bytes(8 - rem)
                if block is not None:
                    block.length = _block_len(out, block)
                block = TapeBlock(len(out), 0, t0 / sr, t1 / sr, baud)
                result.blocks.append(block)
                out += CAS_SYNC
            else:
                if block is None:
                    block = TapeBlock(len(out), 0, t0 / sr, t1 / sr, baud)
                    result.blocks.append(block)
                out.append(v)
        if block is not None:
            block.length = _block_len(out, block)
            block.end_s = t1 / sr
            block.framing_errors += errors
            block.orphan_cycles += orphans
        result.framing_errors += errors
        result.orphan_cycles += orphans
        if progress:
            progress((si + 1) / n_seg)

    result.cas = bytes(out)
    result.segments = seg_count
    if not result.cas:
        result.warnings.append(
            "Hay señal, pero no se ha podido decodificar ningún byte de MSX. "
            "Revisa el volumen y que la cinta sea de MSX.")
    if result.framing_errors > 0 or result.orphan_cycles > 12:
        result.warnings.append(
            f"{result.framing_errors} errores de trama y {result.orphan_cycles} ciclos "
            "dudosos: la grabación tiene ruido o el volumen no es el adecuado.")
    return result


def decode_samples(x: np.ndarray, sr: int, progress=None) -> DecodeResult:
    """Audio mono (float, -1..1) -> resultado de decodificación."""
    edges = find_edges(x, sr, progress=(lambda f: progress(f * 0.6)) if progress else None)
    return decode_edges(edges, sr, len(x),
                        progress=(lambda f: progress(0.6 + f * 0.4)) if progress else None)


def decode_wav(wav_bytes: bytes, progress=None) -> DecodeResult:
    sr, x = wav_to_float(wav_bytes)
    return decode_samples(x, sr, progress)


# ---------------------------------------------------------------------------
# Análisis de nivel (para el medidor del grabador y los avisos)
# ---------------------------------------------------------------------------

@dataclass
class LevelReport:
    peak: float            # 0..1 sobre fondo de escala
    rms: float
    clipped: float         # fracción de muestras en el tope
    dc_offset: float
    silence: bool

    def advice(self) -> str | None:
        if self.silence:
            return "No llega señal. Comprueba el cable, que el casete esté sonando y el volumen."
        if self.clipped > 0.002 or self.peak >= 0.985:
            return "La señal satura: baja el volumen de salida del casete/MSX o el nivel de entrada."
        if self.peak < 0.12:
            return "La señal es muy baja: sube el volumen del casete o el nivel de entrada."
        return None


def analyze_level(x: np.ndarray) -> LevelReport:
    if len(x) == 0:
        return LevelReport(0.0, 0.0, 0.0, 0.0, True)
    dc = float(np.mean(x))
    y = x - dc
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(y * y)))
    clipped = float(np.mean(np.abs(x) >= 0.995))
    return LevelReport(peak, rms, clipped, dc, rms < 0.003)
