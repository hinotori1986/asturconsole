"""Reproductor de cintas MSX: envía por la tarjeta de sonido el audio
generado a partir de un .CAS/.TSX, para cargarlo en un MSX real conectando
la salida de audio del PC a la entrada de casete del ordenador.

Diseño deliberadamente simple: sin lista de reproducción, sin efectos, sin
mezclador. Solo lo que hace falta para que una carga funcione y para poder
diagnosticarla si no funciona.

Notas importantes para carga en hardware real (recogidas de la experiencia
documentada de la escena MSX):

  - El audio se genera y reproduce SIEMPRE en mono: el puerto de casete del
    MSX es una única línea de señal.
  - La frecuencia de muestreo por defecto es 96000 Hz, no 44100. A 2400
    baudios y 44.1 kHz solo hay ~4.6 muestras por semiciclo del tono agudo,
    un margen muy justo que deforma la onda cuadrada; a 96 kHz hay ~10 y la
    señal es mucho más limpia. Es una causa habitual de cargas fallidas.
  - Conviene desactivar cualquier mejora/efecto/ecualizador del sistema y
    evitar el remuestreo automático del servidor de sonido.
  - Algunos equipos solo cargan con una polaridad concreta de la señal; de
    ahí la opción de invertir fase.
"""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer, Signal
from PySide6.QtMultimedia import (
    QAudioFormat, QAudioSink, QAudioSource, QMediaDevices,
)

import cas_tape as ct


class TapePlayer(QObject):
    """Encapsula la generación de audio y su reproducción por la tarjeta de
    sonido. Emite señales de progreso y de fin para que la interfaz no tenga
    que conocer los detalles de Qt Multimedia."""

    progress = Signal(float, float)   # (segundos reproducidos, duración total)
    finished = Signal()
    state_changed = Signal(str)        # "playing" | "paused" | "stopped"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sink: QAudioSink | None = None
        self._buffer: QBuffer | None = None
        self._duration = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)
        self._state = "stopped"

    # -- generación ------------------------------------------------------
    @staticmethod
    def render_pcm(cas_data: bytes, baud: int, sample_rate: int,
                   pilot_seconds: float, invert_phase: bool) -> tuple[bytes, float]:
        """Genera PCM mono de 16 bits listo para reproducir, y su duración."""
        wav_bytes = ct.cas_to_wav(
            cas_data, baud=baud, sample_rate=sample_rate,
            bit_depth=16, pilot_seconds=pilot_seconds,
        )
        # cas_to_wav devuelve un WAV completo; nos quedamos solo con el PCM.
        # La cabecera WAV canónica que genera el módulo `wave` mide 44 bytes,
        # pero se localiza el chunk 'data' explícitamente por robustez.
        idx = wav_bytes.find(b"data")
        if idx == -1:
            raise ValueError("no se pudo localizar el bloque de datos del WAV generado")
        pcm_start = idx + 8
        pcm = wav_bytes[pcm_start:]

        if invert_phase:
            arr = bytearray(pcm)
            for i in range(0, len(arr) - 1, 2):
                val = int.from_bytes(arr[i:i + 2], "little", signed=True)
                val = -val if val != -32768 else 32767
                arr[i:i + 2] = val.to_bytes(2, "little", signed=True)
            pcm = bytes(arr)

        duration = len(pcm) / 2 / sample_rate
        return pcm, duration

    # -- control ---------------------------------------------------------
    def play(self, pcm: bytes, sample_rate: int, device=None, volume: float = 1.0):
        self.stop()

        fmt = QAudioFormat()
        fmt.setSampleRate(sample_rate)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)

        if device is None:
            device = QMediaDevices.defaultAudioOutput()
        if not device.isFormatSupported(fmt):
            raise ValueError(
                f"el dispositivo de salida no admite {sample_rate} Hz mono 16 bits. "
                "Prueba con otra frecuencia de muestreo u otro dispositivo."
            )

        self._duration = len(pcm) / 2 / sample_rate
        self._buffer = QBuffer(self)
        self._buffer.setData(QByteArray(pcm))
        self._buffer.open(QIODevice.ReadOnly)

        self._sink = QAudioSink(device, fmt, self)
        self._sink.setVolume(volume)
        self._sink.stateChanged.connect(self._on_sink_state)
        self._sink.start(self._buffer)

        self._state = "playing"
        self.state_changed.emit(self._state)
        self._timer.start()

    def pause(self):
        if self._sink is not None and self._state == "playing":
            self._sink.suspend()
            self._state = "paused"
            self.state_changed.emit(self._state)

    def resume(self):
        if self._sink is not None and self._state == "paused":
            self._sink.resume()
            self._state = "playing"
            self.state_changed.emit(self._state)

    def stop(self):
        self._timer.stop()
        if self._sink is not None:
            try:
                self._sink.stateChanged.disconnect(self._on_sink_state)
            except (RuntimeError, TypeError):
                pass
            self._sink.stop()
            self._sink = None
        if self._buffer is not None:
            self._buffer.close()
            self._buffer = None
        if self._state != "stopped":
            self._state = "stopped"
            self.state_changed.emit(self._state)

    def set_volume(self, volume: float):
        if self._sink is not None:
            self._sink.setVolume(volume)

    def state(self) -> str:
        return self._state

    def duration(self) -> float:
        return self._duration

    # -- internos --------------------------------------------------------
    def _tick(self):
        if self._sink is None:
            return
        elapsed = self._sink.processedUSecs() / 1_000_000.0
        self.progress.emit(min(elapsed, self._duration), self._duration)

    def _on_sink_state(self, state):
        # QAudio.IdleState = se acabaron los datos del búfer -> fin natural
        from PySide6.QtMultimedia import QAudio
        if state == QAudio.IdleState:
            self._timer.stop()
            self.progress.emit(self._duration, self._duration)
            self.stop()
            self.finished.emit()


def available_output_devices():
    """Lista de dispositivos de salida de audio disponibles."""
    return QMediaDevices.audioOutputs()


# Frecuencias de muestreo ofrecidas al grabar. Se incluye 43200 Hz porque es
# la que usan varias grabaciones de referencia de la escena MSX: es múltiplo
# exacto de 1200 (36 x 1200), así que cada ciclo del tono cae en un número
# entero de muestras y la onda sale sin deriva.
RECORD_SAMPLE_RATES = (22050, 43200, 44100, 48000, 96000)


class TapeRecorder(QObject):
    """Graba la entrada de audio a un archivo WAV mono.

    Pensado para digitalizar cintas reales: se conecta la salida del casete a
    la entrada de línea del PC y se captura. Siempre en mono, porque el
    puerto de casete del MSX es una única línea de señal, y sin ningún
    procesado: cualquier filtro o normalización deformaría los flancos de la
    onda cuadrada y dificultaría la decodificación posterior.
    """

    progress = Signal(float, int)      # (segundos grabados, nivel de pico 0-100)
    state_changed = Signal(str)         # "recording" | "stopped"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source: QAudioSource | None = None
        self._io = None
        self._buffer = bytearray()
        self._sample_rate = 44100
        self._bit_depth = 16
        self._state = "stopped"
        self._peak = 0

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)

    def state(self) -> str:
        return self._state

    def start(self, device=None, sample_rate: int = 44100, bit_depth: int = 16):
        self.stop()

        fmt = QAudioFormat()
        fmt.setSampleRate(sample_rate)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16 if bit_depth == 16 else QAudioFormat.UInt8)

        if device is None:
            device = QMediaDevices.defaultAudioInput()
        if device is None or device.isNull():
            raise ValueError(
                "no se encontró ningún dispositivo de entrada de audio. Comprueba que "
                "hay un micrófono o una entrada de línea disponible en el sistema."
            )
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
            fmt.setChannelCount(1)
            if fmt.sampleRate() != sample_rate:
                raise ValueError(
                    f"la entrada elegida no admite {sample_rate} Hz mono. Prueba con "
                    f"{fmt.sampleRate()} Hz, que es su formato preferido."
                )

        self._sample_rate = fmt.sampleRate()
        self._bit_depth = 16 if fmt.sampleFormat() == QAudioFormat.Int16 else 8
        self._buffer = bytearray()
        self._peak = 0

        self._source = QAudioSource(device, fmt, self)
        self._io = self._source.start()
        self._state = "recording"
        self.state_changed.emit(self._state)
        self._timer.start()

    def stop(self) -> bytes:
        self._timer.stop()
        if self._source is not None:
            self._drain()
            self._source.stop()
            self._source = None
            self._io = None
        if self._state != "stopped":
            self._state = "stopped"
            self.state_changed.emit(self._state)
        return bytes(self._buffer)

    def duration(self) -> float:
        bytes_por_muestra = 2 if self._bit_depth == 16 else 1
        if not self._sample_rate:
            return 0.0
        return len(self._buffer) / bytes_por_muestra / self._sample_rate

    def save_wav(self, path: str) -> str:
        """Guarda lo grabado como WAV mono."""
        import wave
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2 if self._bit_depth == 16 else 1)
            wf.setframerate(self._sample_rate)
            wf.writeframes(bytes(self._buffer))
        return path

    def wav_bytes(self) -> bytes:
        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2 if self._bit_depth == 16 else 1)
            wf.setframerate(self._sample_rate)
            wf.writeframes(bytes(self._buffer))
        return buf.getvalue()

    # -- internos ----------------------------------------------------------
    def _drain(self):
        if self._io is None:
            return
        datos = self._io.readAll()
        if datos:
            self._buffer.extend(bytes(datos))

    def _tick(self):
        self._drain()
        self._peak = self._measure_peak()
        self.progress.emit(self.duration(), self._peak)

    def _measure_peak(self) -> int:
        """Nivel de pico del último tramo, en porcentaje, para el vúmetro."""
        import struct
        cola = self._buffer[-4096:]
        if not cola:
            return 0
        if self._bit_depth == 16:
            n = len(cola) // 2
            if n == 0:
                return 0
            valores = struct.unpack("<%dh" % n, bytes(cola[:n * 2]))
            pico = max(abs(v) for v in valores) / 32768
        else:
            pico = max(abs(b - 128) for b in cola) / 128
        return int(min(100, pico * 100))
