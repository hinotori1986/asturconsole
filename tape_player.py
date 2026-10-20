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
                   pilot_seconds: float, invert_phase: bool,
                   waveform: str = "sine") -> tuple[bytes, float]:
        """Genera PCM mono de 16 bits listo para reproducir, y su duración."""
        wav_bytes = ct.cas_to_wav(
            cas_data, baud=baud, sample_rate=sample_rate,
            bit_depth=16, pilot_seconds=pilot_seconds, waveform=waveform,
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
            import numpy as np
            arr = np.frombuffer(pcm, dtype="<i2").astype(np.int32)
            pcm = np.clip(-arr, -32768, 32767).astype("<i2").tobytes()

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


def available_input_devices():
    """Lista de dispositivos de entrada de audio (línea, micro, USB...)."""
    return QMediaDevices.audioInputs()


# Frecuencias de muestreo ofrecidas al grabar. Se incluye 43200 Hz porque es
# la que usan varias grabaciones de referencia de la escena MSX: es múltiplo
# exacto de 1200 (36 x 1200), así que cada ciclo del tono cae en un número
# entero de muestras y la onda sale sin deriva. A 22050 Hz, 2400 baudios solo
# deja 4,6 muestras por ciclo agudo y la lectura falla: no se ofrece.
RECORD_SAMPLE_RATES = (43200, 44100, 48000, 96000)
DEFAULT_RECORD_RATE = 48000

# Formatos de muestra que sabemos interpretar (Qt -> nombre de tape_capture).
# Es importante tenerlos controlados: si el dispositivo entrega, por ejemplo,
# coma flotante y se leen esos bytes como enteros, el resultado es basura y el
# medidor de nivel marca saturación permanente aunque la señal sea correcta.
_SAMPLE_FORMAT_NAMES = {
    QAudioFormat.UInt8: "u8",
    QAudioFormat.Int16: "i16",
    QAudioFormat.Int32: "i32",
    QAudioFormat.Float: "f32",
}


def _negotiate_format(device, sample_rate: int) -> QAudioFormat:
    """Elige el mejor formato de captura que admita el dispositivo.

    Se prefiere ESTÉREO a la frecuencia pedida: así la aplicación decide qué
    canal lleva la cinta, en vez de dejar que el controlador mezcle los dos a
    mono (con un jack mono conectado a un solo canal, eso resta 6 dB).
    """
    candidatos = []
    for canales in (2, 1):
        for formato in (QAudioFormat.Int16, QAudioFormat.Float, QAudioFormat.Int32,
                        QAudioFormat.UInt8):
            f = QAudioFormat()
            f.setSampleRate(sample_rate)
            f.setChannelCount(canales)
            f.setSampleFormat(formato)
            candidatos.append(f)
    for f in candidatos:
        if device.isFormatSupported(f):
            return f
    pref = device.preferredFormat()
    if pref.sampleFormat() in _SAMPLE_FORMAT_NAMES and pref.channelCount() >= 1:
        return pref
    raise ValueError(
        "la entrada de audio elegida no ofrece ningún formato utilizable. "
        "Prueba con otro dispositivo o con otra frecuencia de muestreo."
    )


class TapeRecorder(QObject):
    """Captura la entrada de audio y se la pasa a una ``CaptureSession``.

    Esta clase solo habla con Qt Multimedia; toda la lógica (canal, armado,
    detección de señal, decodificación en vivo) está en ``tape_capture`` y se
    puede probar sin tarjeta de sonido.
    """

    status_changed = Signal(object)    # LiveStatus, cada 80 ms
    state_changed = Signal(str)        # "monitoring" | "armed" | "recording" | "stopped"
    rate_adjusted = Signal(int, int)   # (pedida, concedida) si difieren

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source: QAudioSource | None = None
        self._io = None
        self._session = None
        self._state = "stopped"
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)

    # -- estado ----------------------------------------------------------
    def state(self) -> str:
        return self._state

    def session(self):
        return self._session

    def duration(self) -> float:
        return self._session.duration() if self._session else 0.0

    def sample_rate(self) -> int:
        return self._session.sr if self._session else 0

    # -- control ---------------------------------------------------------
    def start(self, device=None, sample_rate: int = DEFAULT_RECORD_RATE,
              channel_mode: str = "auto", armed: bool = True,
              autostop_s: float | None = 10.0, monitor_only: bool = False,
              volume: float = 1.0):
        """Abre la entrada. ``monitor_only`` solo mide el nivel (sin grabar)."""
        import tape_capture as tcap

        self._close_source()
        if self._session is not None:
            self._session.close()
            self._session = None

        if device is None:
            device = QMediaDevices.defaultAudioInput()
        if device is None or device.isNull():
            raise ValueError(
                "no se encontró ningún dispositivo de entrada de audio. Comprueba que "
                "hay una entrada de línea o micrófono disponible en el sistema."
            )
        fmt = _negotiate_format(device, sample_rate)
        nombre = _SAMPLE_FORMAT_NAMES.get(fmt.sampleFormat())
        if nombre is None:
            raise ValueError("la entrada entrega un formato de muestra no soportado")
        if fmt.sampleRate() != sample_rate:
            self.rate_adjusted.emit(sample_rate, fmt.sampleRate())

        self._session = tcap.CaptureSession(
            fmt.sampleRate(), fmt.channelCount(), nombre,
            channel_mode=channel_mode, armed=armed or monitor_only,
            autostop_s=autostop_s, monitor_only=monitor_only)
        self._source = QAudioSource(device, fmt, self)
        self._source.setVolume(max(0.0, min(1.0, volume)))
        self._io = self._source.start()
        if self._io is None:
            self._source = None
            raise ValueError(
                "el sistema no permitió abrir la entrada de audio. Comprueba que no la "
                "esté usando otro programa."
            )
        self._set_state("monitoring" if monitor_only else
                        ("armed" if armed else "recording"))
        self._timer.start()

    def set_volume(self, volume: float) -> float | None:
        """Nivel de entrada (0..1) de la fuente abierta, también en marcha.

        Devuelve el nivel que el sistema ha aplicado de verdad, o None si no
        hay entrada abierta. Algunos controladores ignoran el ajuste: si el
        valor devuelto no coincide, el nivel hay que bajarlo en el sistema.
        """
        volume = max(0.0, min(1.0, volume))
        if self._source is None:
            return None
        self._source.setVolume(volume)
        try:
            return float(self._source.volume())
        except (RuntimeError, AttributeError):
            return volume

    def start_now(self):
        """Pasa de «armado» a grabar sin esperar a oír señal."""
        if self._session is not None and self._state == "armed":
            self._session.start_now()
            self._set_state("recording")

    def stop(self):
        """Cierra la entrada. Lo capturado queda en ``session()``."""
        self._timer.stop()
        self._drain()
        self._close_source()
        if self._session is not None:
            self._session.stop()
        self._set_state("stopped")

    def close(self):
        self.stop()
        if self._session is not None:
            self._session.close()

    # -- internos --------------------------------------------------------
    def _close_source(self):
        if self._source is not None:
            try:
                self._source.stop()
            except RuntimeError:
                pass
            self._source = None
            self._io = None

    def _set_state(self, state: str):
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _drain(self):
        if self._io is None or self._session is None:
            return
        datos = self._io.readAll()
        if datos:
            self._session.feed(bytes(datos))

    def _tick(self):
        self._drain()
        if self._session is None:
            return
        status = self._session.status()
        # La sesión puede pasar sola a «grabando» (disparo) o a «parada»
        # (silencio prolongado): se refleja en la interfaz.
        if self._state == "armed" and status.state == "recording":
            self._set_state("recording")
        elif self._state in ("armed", "recording") and status.state == "stopped":
            self._timer.stop()
            self._close_source()
            self._set_state("stopped")
        self.status_changed.emit(status)


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
