"""Captura de una cinta MSX desde la entrada de audio (sin dependencias de Qt).

Recibe los bloques de audio crudo que entrega la tarjeta de sonido y se
encarga de todo lo demás, para que la interfaz sea fina y esto se pueda
probar sin hardware:

- Convierte cualquier formato de muestra (8/16/32 bits, coma flotante) y
  admite entrada estéreo: se captura estéreo y se elige el canal que lleva la
  cinta (Automático detecta cuál tiene señal; algunas tarjetas conectan un
  jack mono solo a un canal y mezclar los dos a mono perdería 6 dB).
- Armado automático: espera a oír una señal con pinta de cinta MSX y empieza
  a grabar justo antes (conserva 1,5 s previos), de modo que no se corta el
  principio del tono piloto.
- Parada automática tras un silencio configurable, cuando ya se ha oído
  algo.
- Mide el nivel (con aviso de saturación) y, en vivo, si lo que llega es un
  piloto o datos y a qué velocidad.
- Cuando termina un bloque lo decodifica en segundo plano, de modo que la
  lista de programas se va llenando mientras se graba.
"""
from __future__ import annotations

import io
import wave
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

import tape_catalog as tc
import tape_decoder as td

WINDOW_S = 0.05            # ventana de análisis
PREROLL_S = 1.5            # audio que se conserva antes del disparo
TRIGGER_WINDOWS = 6        # ventanas de tono seguidas para disparar (0,3 s)
SEGMENT_END_S = 0.35       # silencio que cierra un bloque
SEGMENT_MIN_S = 0.8        # un bloque más corto se ignora
RMS_TONE_MIN = 0.012       # nivel mínimo para considerar que hay señal
LOCK_ACTIVE_S = 1.0        # señal necesaria para fijar el canal automático

CHANNEL_MODES = ("auto", "left", "right", "mix")


def frames_from_bytes(raw: bytes, channels: int, fmt: str) -> np.ndarray:
    """Bytes crudos -> float32 (n, canales) en [-1, 1]. ``raw`` debe contener
    un número entero de tramas."""
    if fmt == "i16":
        a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif fmt == "u8":
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif fmt == "i32":
        a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif fmt == "f32":
        a = np.frombuffer(raw, dtype="<f4").astype(np.float32)
        a = np.clip(a, -1.0, 1.0)
    else:
        raise ValueError(f"formato de muestra no soportado: {fmt}")
    return a.reshape(-1, channels)


BYTES_PER_SAMPLE = {"u8": 1, "i16": 2, "i32": 4, "f32": 4}


@dataclass
class LiveStatus:
    state: str = "armed"            # armed | recording | stopped
    elapsed: float = 0.0
    peak: float = 0.0               # pico del último bloque de audio (0..1)
    clipped: bool = False           # hubo saturación en el último segundo
    signal: str = "silence"         # silence | data | pilot
    baud_guess: int = 0
    silence_s: float = 0.0
    segments: int = 0               # bloques cerrados
    channel: str = "—"
    auto_stopped: bool = False
    entries: list[tc.TapeEntry] = field(default_factory=list)
    live_errors: int = 0


class CaptureSession:
    def __init__(self, sample_rate: int, channels: int = 1, sample_format: str = "i16",
                 channel_mode: str = "auto", armed: bool = True,
                 autostop_s: float | None = 10.0, max_seconds: float = 3600.0,
                 live_decode: bool = True, monitor_only: bool = False):
        if channel_mode not in CHANNEL_MODES:
            raise ValueError("modo de canal desconocido")
        self.sr = int(sample_rate)
        self.channels = max(1, int(channels))
        self.fmt = sample_format
        self.bps = BYTES_PER_SAMPLE[sample_format]
        self.channel_mode = channel_mode
        self.autostop_s = autostop_s
        self.max_seconds = max_seconds
        self.live_decode = live_decode
        self.monitor_only = monitor_only

        self._carry = b""
        self._state = "armed" if armed else "recording"
        self._win = max(64, int(self.sr * WINDOW_S))
        self._pending = np.empty(0, dtype=np.float32)       # para ventanas de análisis
        self._chunks: list[np.ndarray] = []                 # int16 (n,) o (n,2)
        self._chunk_frames = 0
        self._preroll: deque = deque()
        self._preroll_frames = 0
        self._locked: int | str | None = None               # 0, 1, 'mix'
        if self.channels == 1:
            self._locked = 0
        elif channel_mode == "left":
            self._locked = 0
        elif channel_mode == "right":
            self._locked = min(1, self.channels - 1)
        elif channel_mode == "mix":
            self._locked = "mix"
        self._energy = np.zeros(self.channels, dtype=np.float64)
        self._energy_frames = 0
        self._auto_pending = np.empty((0, self.channels), dtype=np.float32)

        # análisis
        self._tone_run = 0
        self._silence_frames = 0
        self._heard_signal = False
        self._in_segment = False
        self._seg_start_frame = 0
        self._seg_quiet = 0
        self._status = LiveStatus(state=self._state)
        self._recent_pilot_hz: deque = deque(maxlen=6)
        self._clip_hist: deque = deque(maxlen=int(1.0 / WINDOW_S))

        # decodificación en vivo
        self._pool = ThreadPoolExecutor(max_workers=1) if live_decode else None
        self._jobs: list[tuple[int, Future]] = []
        self._live_parts: list[tuple[int, td.DecodeResult]] = []
        self._status.channel = self._channel_label()

    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    def status(self) -> LiveStatus:
        self._poll_jobs()
        s = self._status
        s.state = self._state
        s.elapsed = self._chunk_frames / self.sr
        s.channel = self._channel_label()
        return s

    def duration(self) -> float:
        return self._chunk_frames / self.sr

    def _channel_label(self) -> str:
        if self.channels == 1:
            return "mono"
        if self._locked == "mix":
            return "L+R"
        if self._locked is None:
            return "auto…"
        return "izquierdo" if self._locked == 0 else "derecho"

    # ------------------------------------------------------------------
    def start_now(self):
        """Empieza a grabar sin esperar a oír señal."""
        if self._state == "armed":
            self._begin_recording()

    def stop(self):
        if self._state != "stopped":
            self._finish_segment_if_open()
            self._state = "stopped"
        return self

    def feed(self, raw: bytes):
        """Procesa un bloque de audio crudo de la tarjeta."""
        if self._state == "stopped" or not raw:
            return
        data = self._carry + raw
        frame = self.bps * self.channels
        usable = (len(data) // frame) * frame
        self._carry = data[usable:]
        if usable == 0:
            return
        fr = frames_from_bytes(data[:usable], self.channels, self.fmt)
        self._process(fr)
        self._poll_jobs()

    # ------------------------------------------------------------------
    def _process(self, fr: np.ndarray):
        st = self._status
        st.peak = float(np.max(np.abs(fr)))

        # Canal automático: se decide con la primera señal clara.
        if self._locked is None:
            self._feed_auto(fr)
        active = self._active_mono(fr)

        # almacén: estéreo mientras no se haya decidido el canal, mono después
        store = fr if self._locked is None else active
        i16 = (np.clip(store, -1.0, 1.0) * 32767.0).astype(np.int16)
        if self._state == "armed":
            self._preroll.append(i16)
            self._preroll_frames += len(i16)
            keep = int(PREROLL_S * self.sr)
            while len(self._preroll) > 1 and self._preroll_frames - len(self._preroll[0]) >= keep:
                self._preroll_frames -= len(self._preroll.popleft())
        else:
            self._chunks.append(i16)
            self._chunk_frames += len(i16)

        # análisis por ventanas (sobre el canal activo)
        self._pending = np.concatenate((self._pending, active.astype(np.float32)))
        while len(self._pending) >= self._win:
            w = self._pending[:self._win]
            self._pending = self._pending[self._win:]
            self._analyze_window(w)

        if self._state == "recording" and self._chunk_frames / self.sr >= self.max_seconds:
            self.stop()

    def _active_mono(self, fr: np.ndarray) -> np.ndarray:
        if self.channels == 1:
            return fr[:, 0]
        if self._locked is None:
            # Aún sin decidir: el canal más fuerte de cada bloque
            e = np.sum(fr * fr, axis=0)
            return fr[:, int(np.argmax(e))]
        if self._locked == "mix":
            return fr.mean(axis=1)
        return fr[:, self._locked]

    def _feed_auto(self, fr: np.ndarray):
        """Acumula energía por canal; fija el canal cuando hay señal de sobra."""
        self._energy += np.sum(fr.astype(np.float64) ** 2, axis=0)
        self._energy_frames += len(fr)
        # Un instante de señal clara en alguno de los canales
        rms = np.sqrt(self._energy / max(1, self._energy_frames))
        if self._energy_frames >= LOCK_ACTIVE_S * self.sr and float(np.max(rms)) > RMS_TONE_MIN:
            self._locked = int(np.argmax(self._energy))
            # Los trozos ya guardados (estéreo) pasan a mono
            def to_mono(a):
                return a[:, self._locked] if a.ndim == 2 else a
            self._chunks = [to_mono(a) for a in self._chunks]
            self._preroll = deque(to_mono(a) for a in self._preroll)
        elif self._energy_frames >= 12 * self.sr:
            # Mucho tiempo sin señal clara: se queda con el canal más fuerte
            self._locked = int(np.argmax(self._energy))
            def to_mono2(a):
                return a[:, self._locked] if a.ndim == 2 else a
            self._chunks = [to_mono2(a) for a in self._chunks]
            self._preroll = deque(to_mono2(a) for a in self._preroll)

    # ------------------------------------------------------------------
    def _analyze_window(self, w: np.ndarray):
        st = self._status
        n = len(w)
        c = w - float(np.mean(w))
        rms = float(np.sqrt(np.mean(c * c)))
        peak = float(np.max(np.abs(w)))
        self._clip_hist.append(float(np.mean(np.abs(w) >= 0.99)) > 0.002)
        st.clipped = any(self._clip_hist)

        freq = 0.0
        if rms > RMS_TONE_MIN and peak > 0:
            th = 0.2 * float(np.max(np.abs(c)))
            s = np.where(c > th, 1, np.where(c < -th, -1, 0))
            nz = s[s != 0]
            flips = int(np.count_nonzero(nz[1:] != nz[:-1])) if len(nz) > 1 else 0
            freq = flips / 2.0 / (n / self.sr)
        tone = rms > RMS_TONE_MIN and 800.0 <= freq <= 6200.0
        pilot = tone and any(abs(freq - f) / f < 0.10 for f in (2400.0, 4800.0))

        if pilot:
            self._recent_pilot_hz.append(freq)
        elif not tone:
            self._recent_pilot_hz.clear()

        if tone:
            st.signal = "pilot" if pilot and len(self._recent_pilot_hz) >= 4 else "data"
            if st.signal == "pilot":
                hz = float(np.median(self._recent_pilot_hz))
                st.baud_guess = 2400 if abs(hz - 4800) < abs(hz - 2400) else 1200
            self._tone_run += 1
            self._silence_frames = 0
            self._heard_signal = True
        else:
            st.signal = "silence"
            self._tone_run = 0
            self._silence_frames += n
        st.silence_s = self._silence_frames / self.sr

        if self._state == "armed":
            if self._tone_run >= TRIGGER_WINDOWS and not self.monitor_only:
                self._begin_recording()
            return

        # --- grabando: seguimiento de bloques ---
        if tone and not self._in_segment:
            self._in_segment = True
            self._seg_start_frame = max(0, self._chunk_frames - int(0.4 * self.sr))
            self._seg_quiet = 0
        elif self._in_segment:
            if tone:
                self._seg_quiet = 0
            else:
                self._seg_quiet += n
                if self._seg_quiet >= SEGMENT_END_S * self.sr:
                    self._close_segment(self._chunk_frames - self._seg_quiet + int(0.1 * self.sr))
        if self.autostop_s and self._heard_signal and st.silence_s >= self.autostop_s \
                and self._state == "recording":
            st.auto_stopped = True
            self.stop()

    def _begin_recording(self):
        self._state = "recording"
        self._chunks = list(self._preroll)
        self._chunk_frames = sum(len(a) for a in self._chunks)
        self._preroll.clear()
        self._preroll_frames = 0
        self._silence_frames = 0
        # el disparo ocurrió TRIGGER_WINDOWS ventanas atrás
        self._in_segment = True
        self._seg_start_frame = max(0, self._chunk_frames - int((TRIGGER_WINDOWS * WINDOW_S + 0.4) * self.sr))
        self._seg_quiet = 0

    # ------------------------------------------------------------------
    def _finish_segment_if_open(self):
        if self._in_segment and self._state == "recording":
            self._close_segment(self._chunk_frames - self._seg_quiet)

    def _close_segment(self, end_frame: int):
        self._in_segment = False
        self._status.segments += 1
        start = self._seg_start_frame
        end = min(end_frame, self._chunk_frames)
        if (end - start) / self.sr < SEGMENT_MIN_S or self._pool is None:
            return
        if self._locked is None:
            return    # sin canal fijado aún: se decodificará al final
        x = self._slice(start, end)
        self._jobs.append((start, self._pool.submit(_decode_job, x, self.sr)))

    def _slice(self, start: int, end: int) -> np.ndarray:
        """Muestras [start, end) del almacén, como float32 mono."""
        out = []
        pos = 0
        for a in self._chunks:
            n = len(a)
            if pos + n > start and pos < end:
                lo = max(0, start - pos)
                hi = min(n, end - pos)
                out.append(a[lo:hi] if a.ndim == 1 else a[lo:hi, 0])
            pos += n
            if pos >= end:
                break
        if not out:
            return np.empty(0, dtype=np.float32)
        return np.concatenate(out).astype(np.float32) / 32768.0

    def _poll_jobs(self):
        done = [(s, f) for s, f in self._jobs if f.done()]
        if not done:
            return
        self._jobs = [(s, f) for s, f in self._jobs if not f.done()]
        for start, fut in done:
            try:
                res = fut.result()
            except Exception:           # noqa: BLE001 - un fallo en vivo no debe parar la grabación
                continue
            if res.cas:
                self._live_parts.append((start, res))
        if done:
            self._rebuild_live()

    def _rebuild_live(self):
        parts = sorted(self._live_parts, key=lambda p: p[0])
        cas = bytearray()
        errors = 0
        for _s, res in parts:
            if len(cas) % 8:
                cas += bytes(8 - len(cas) % 8)
            cas += res.cas
            errors += res.framing_errors
        self._status.entries = tc.parse_tape(bytes(cas))
        self._status.live_errors = errors

    # ------------------------------------------------------------------
    # Resultado
    # ------------------------------------------------------------------
    def mono_int16(self) -> np.ndarray:
        if not self._chunks:
            return np.empty(0, dtype=np.int16)
        if self._locked is None:
            # nunca llegó a decidirse: el canal más fuerte
            self._locked = int(np.argmax(self._energy)) if self._energy.any() else 0
            self._chunks = [a[:, self._locked] if a.ndim == 2 else a for a in self._chunks]
        return np.concatenate([a if a.ndim == 1 else a[:, 0] for a in self._chunks])

    def mono_float(self) -> np.ndarray:
        return self.mono_int16().astype(np.float32) / 32768.0

    def wav_bytes(self) -> bytes:
        pcm = self.mono_int16()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sr)
            wf.writeframes(pcm.astype("<i2").tobytes())
        return buf.getvalue()

    def level_report(self) -> td.LevelReport:
        return td.analyze_level(self.mono_float())

    def decode(self, progress=None) -> td.DecodeResult:
        """Decodificación definitiva de toda la grabación."""
        return td.decode_samples(self.mono_float(), self.sr, progress)

    def close(self):
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None


def _decode_job(x: np.ndarray, sr: int) -> td.DecodeResult:
    return td.decode_samples(x, sr)
