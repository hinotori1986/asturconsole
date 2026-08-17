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
        self._finished_emitted = False
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
        self._finished_emitted = False
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

        # Comprobación por tiempo, además de la señal de Qt: la notificación
        # de "búfer agotado" no siempre llega según el motor de audio del
        # sistema, y sin esta red de seguridad la reproducción parecía no
        # terminar nunca (las bobinas seguían girando indefinidamente).
        if self._duration > 0 and elapsed >= self._duration - 0.05:
            self._finish()

    def _on_sink_state(self, state):
        # QAudio.IdleState = se acabaron los datos del búfer -> fin natural
        from PySide6.QtMultimedia import QAudio
        if state == QAudio.IdleState:
            self._finish()

    def _finish(self):
        """Cierra la reproducción una sola vez, avise quien avise."""
        if self._finished_emitted:
            return
        self._finished_emitted = True
        self._timer.stop()
        self.progress.emit(self._duration, self._duration)
        # El aviso de fin se emite ANTES de detener: así quien lo escuche
        # puede marcar el estado "terminado" antes de que el cambio a
        # "detenido" reinicie los indicadores a cero.
        self.finished.emit()
        self.stop()


def available_output_devices():
    """Lista de dispositivos de salida de audio disponibles."""
    return QMediaDevices.audioOutputs()


# Frecuencias de muestreo ofrecidas al grabar. Se incluye 43200 Hz porque es
# la que usan varias grabaciones de referencia de la escena MSX: es múltiplo
# exacto de 1200 (36 x 1200), así que cada ciclo del tono cae en un número
# entero de muestras y la onda sale sin deriva.
RECORD_SAMPLE_RATES = (22050, 43200, 44100, 48000, 96000)

# Formatos de muestra que sabemos interpretar: (bytes por muestra, tipo).
# Es importante tenerlos controlados: si el dispositivo entrega, por ejemplo,
# coma flotante y se leen esos bytes como enteros de 8 bits, el resultado es
# basura y el medidor de nivel marca saturación permanente aunque la señal
# sea correcta. Ese era el origen de los avisos falsos de saturación.
_SAMPLE_FORMAT_INFO = {
    QAudioFormat.UInt8: (1, "u8"),
    QAudioFormat.Int16: (2, "i16"),
    QAudioFormat.Int32: (4, "i32"),
    QAudioFormat.Float: (4, "f32"),
}


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
    rate_adjusted = Signal(int, int)    # (pedida, concedida) si difieren

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source: QAudioSource | None = None
        self._io = None
        self._buffer = bytearray()
        self._sample_rate = 44100
        self._sample_format = QAudioFormat.Int16
        self._bytes_per_sample = 2
        self._state = "stopped"
        self._peak = 0

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)

    def state(self) -> str:
        return self._state

    def start(self, device=None, sample_rate: int = 44100, bit_depth: int = 16):
        # Cortar cualquier captura previa y VACIAR el búfer antes de nada. Si
        # no, una grabación abortada dejaba restos que se concatenaban con la
        # siguiente y todo acababa en un mismo archivo.
        self.stop()
        self.reset()

        if device is None:
            device = QMediaDevices.defaultAudioInput()
        if device is None or device.isNull():
            raise ValueError(
                "no se encontró ningún dispositivo de entrada de audio. Comprueba que "
                "hay una entrada de línea o micrófono disponible en el sistema."
            )

        fmt = QAudioFormat()
        fmt.setSampleRate(sample_rate)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16 if bit_depth == 16 else QAudioFormat.UInt8)

        if not device.isFormatSupported(fmt):
            # Recurrir al formato preferido del dispositivo, pero forzando mono
            # y conservando la frecuencia pedida si la admite.
            preferido = device.preferredFormat()
            preferido.setChannelCount(1)
            candidato = QAudioFormat(preferido)
            candidato.setSampleRate(sample_rate)
            fmt = candidato if device.isFormatSupported(candidato) else preferido

        if not device.isFormatSupported(fmt):
            raise ValueError(
                "la entrada de audio elegida no admite ningún formato mono utilizable. "
                "Prueba con otro dispositivo."
            )

        self._sample_format = fmt.sampleFormat()
        if self._sample_format not in _SAMPLE_FORMAT_INFO:
            raise ValueError(
                "la entrada de audio entrega un formato de muestra no soportado "
                f"({self._sample_format}). Prueba con otro dispositivo o frecuencia."
            )

        self._sample_rate = fmt.sampleRate()
        self._bytes_per_sample = _SAMPLE_FORMAT_INFO[self._sample_format][0]
        if self._sample_rate != sample_rate:
            self.rate_adjusted.emit(sample_rate, self._sample_rate)

        self._source = QAudioSource(device, fmt, self)
        self._io = self._source.start()
        if self._io is None:
            self._source = None
            raise ValueError(
                "el sistema no permitió abrir la entrada de audio. Comprueba que no la "
                "esté usando otro programa."
            )
        self._state = "recording"
        self.state_changed.emit(self._state)
        self._timer.start()

    def reset(self):
        """Vacía lo capturado. Se llama al empezar y tras guardar."""
        self._buffer = bytearray()
        self._peak = 0

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
        if not self._sample_rate or not self._bytes_per_sample:
            return 0.0
        return len(self._buffer) / self._bytes_per_sample / self._sample_rate

    def _samples(self) -> list:
        """Muestras normalizadas a enteros de 16 bits con signo.

        Convierte desde cualquiera de los formatos que puede entregar la
        tarjeta, en vez de suponer uno: leer coma flotante como si fueran
        bytes producía ruido y saturación falsa.
        """
        import struct
        datos = bytes(self._buffer)
        tipo = _SAMPLE_FORMAT_INFO[self._sample_format][1]
        n = len(datos) // self._bytes_per_sample
        if n == 0:
            return []
        if tipo == "i16":
            return list(struct.unpack("<%dh" % n, datos[:n * 2]))
        if tipo == "u8":
            return [(b - 128) * 256 for b in datos[:n]]
        if tipo == "i32":
            return [v >> 16 for v in struct.unpack("<%di" % n, datos[:n * 4])]
        # coma flotante en el rango -1..1
        vals = struct.unpack("<%df" % n, datos[:n * 4])
        return [max(-32768, min(32767, int(v * 32767))) for v in vals]

    def wav_bytes(self) -> bytes:
        """Lo grabado, como WAV mono de 16 bits.

        Se normaliza siempre a 16 bits con signo, venga como venga de la
        tarjeta, para que el resultado sea uniforme y directamente utilizable
        por el decodificador de cintas.
        """
        import io
        import struct
        import wave
        muestras = self._samples()
        pcm = struct.pack("<%dh" % len(muestras), *muestras) if muestras else b""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            wf.writeframes(pcm)
        return buf.getvalue()

    def save_wav(self, path: str) -> str:
        with open(path, "wb") as fh:
            fh.write(self.wav_bytes())
        return path

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
        bps = self._bytes_per_sample
        # Tomar un tramo alineado al tamaño de muestra: si se corta a mitad de
        # una muestra, los bytes se interpretan desplazados y el nivel sale
        # disparatado (otra fuente de saturaciones falsas).
        n_muestras = min(2048, len(self._buffer) // bps)
        if n_muestras == 0:
            return 0
        cola = bytes(self._buffer[-n_muestras * bps:])
        tipo = _SAMPLE_FORMAT_INFO[self._sample_format][1]
        if tipo == "i16":
            valores = struct.unpack("<%dh" % n_muestras, cola)
            pico = max(abs(v) for v in valores) / 32768
        elif tipo == "u8":
            pico = max(abs(b - 128) for b in cola) / 128
        elif tipo == "i32":
            valores = struct.unpack("<%di" % n_muestras, cola)
            pico = max(abs(v) for v in valores) / 2147483648
        else:
            valores = struct.unpack("<%df" % n_muestras, cola)
            pico = min(1.0, max(abs(v) for v in valores))
        return int(min(100, pico * 100))


def end_of_tape_tone(sample_rate: int = 44100) -> bytes:
    """Genera el aviso sonoro de fin de reproducción.

    Dos pitidos descendentes cortos, suficientes para avisar sin resultar
    molestos y sin parecerse a los tonos de la propia cinta (para no
    confundir a quien esté grabando la salida).
    """
    import io
    import math
    import struct
    import wave

    muestras = []
    for freq, dur in ((880.0, 0.12), (0.0, 0.05), (620.0, 0.18)):
        n = int(sample_rate * dur)
        for i in range(n):
            if freq <= 0:
                muestras.append(0)
                continue
            # envolvente suave para evitar chasquidos al principio y al final
            env = min(1.0, min(i, n - i) / (sample_rate * 0.01))
            muestras.append(int(9000 * env * math.sin(2 * math.pi * freq * i / sample_rate)))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack("<%dh" % len(muestras), *muestras))
    return buf.getvalue()
