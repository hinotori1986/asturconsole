"""Conversión de audio (MP3, WAV, FLAC, OGG) a WAV mono de 16 bits, para las
cintas MSX.

Por qué existe: los dispositivos modernos que sustituyen al casete guardan la
cinta como MP3 ESTÉREO, pero el MSX (y las herramientas de esta aplicación,
como WAV → CAS) trabajan con un WAV MONO: el casete es una única línea de
señal FSK, de modo que el segundo canal no aporta nada.

La conversión es solo de formato: la forma de onda no se modifica más allá de
decodificar el MP3 y reducirlo a un canal. Los datos del MSX viajan en la
FRECUENCIA de la señal (1200/2400 Hz a 1200 baudios), no en su volumen.

--- Decodificadores (en este orden de preferencia) ---------------------------

1. `miniaudio` (pip install miniaudio cffi): decodifica dentro del propio
   proceso, sin depender de nada instalado en el sistema, igual en Linux y
   Windows. IMPORTANTE: hay que instalar también `cffi` explícitamente. El
   modo "máquina antigua" de build_linux.sh instala con `--no-deps`, y sin
   cffi `import miniaudio` falla con «No module named '_cffi_backend'»
   (comprobado).
2. `ffmpeg` (si está en el PATH): respaldo para cuando miniaudio no esté
   disponible.

Ambos mezclan a mono con (L+R)/2 y dan el mismo resultado con audio de nivel
normal (comprobado: misma longitud y diferencia máxima de 1 LSB en todas las
muestras donde ningún canal llega a saturar). La única diferencia, medida y
explicada, aparece con audio SATURADO a fondo de escala: miniaudio recorta
cada canal a 16 bits y después mezcla, mientras que ffmpeg mezcla en coma
flotante y recorta al final, conservando el sobreimpulso que el MP3 produce
sobre una onda a fondo de escala. En una señal de cinta con nivel razonable
no se da; y, aun dándose, la información FSK está en los cruces por cero,
no en la amplitud.

Ambos entregan los datos como trozos de enteros de 16 bits intercalados, y
TODO lo demás (elección de canal, medición de nivel, escritura del WAV) es
código común: así el resultado no depende de qué decodificador se use.

--- Memoria -------------------------------------------------------------------

Se lee y escribe POR TROZOS. Una cara de casete son 30-45 minutos: como WAV
mono de 16 bits a 44100 Hz serían 160-240 MB, que no hace falta tener nunca a
la vez en memoria. Solo el MP3 de entrada (unas decenas de MB) se carga entero,
y a propósito: así los nombres de archivo con acentos o ñ no dependen de cómo
la biblioteca nativa trate la ruta en Windows.

--- El problema del canal -----------------------------------------------------

Mezclar L y R promediándolos funciona cuando ambos canales llevan lo mismo
(lo habitual). Pero si uno de los canales está en CONTRAFASE respecto al otro,
el promedio se cancela y sale un WAV MUDO (se ha comprobado con un MP3 real
de prueba: cada canal con señal a fondo de escala y la mezcla con pico 3 sobre
32767). Y si la señal está solo en un canal y el otro lleva ruido o está
vacío, la mezcla baja el volumen a la mitad y suma ese ruido. Por eso el modo
por defecto (CANAL_AUTO) mira el principio del audio y elige.
"""
from __future__ import annotations

import array
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from typing import Callable, Iterator

EXTENSIONES_AUDIO = (".mp3", ".wav", ".flac", ".ogg")

CANAL_AUTO = "auto"
CANAL_MEZCLA = "mezcla"
CANAL_IZQ = "izquierdo"
CANAL_DER = "derecho"
CANALES = (CANAL_AUTO, CANAL_MEZCLA, CANAL_IZQ, CANAL_DER)

# Análisis de canales (modo automático)
SEGUNDOS_ANALISIS = 60        # cuánto del principio se examina
UMBRAL_SILENCIO = 330         # pico (de 32768) por debajo del cual "casi no suena" (~1 %)
RATIO_CANAL_DEBIL = 0.25      # un canal con menos de esto del pico del otro se considera vacío/ruido
RATIO_CANCELACION = 0.70      # si la mezcla queda por debajo de esto del pico del mejor canal, se cancela

# Aviso de nivel bajo en el resultado
NIVEL_BAJO_PCT = 10.0

# El nivel "típico" (y el de cada canal al analizarlos) NO es el máximo absoluto
# sino el percentil de los picos POR TROZO. Con el máximo, unas pocas muestras
# aisladas bastan para enmascarar un audio entero casi mudo: se comprobó con un
# MP3 en contrafase, mudo durante 90 s salvo las 21 últimas muestras, donde el
# final del flujo MP3 no cancela (L=-32768, R=-28369): el máximo marcaba 93 % y
# el aviso de «nivel muy bajo» no saltaba. Con el percentil, un artefacto
# aislado en un borde o un chasquido suelto no cuentan.
PERCENTIL_NIVEL = 0.90

FRAMES_POR_TROZO = 16384
_FONDO_ESCALA = 32768


class AudioError(Exception):
    """Error con un mensaje listo para enseñar al usuario."""


class ConversionCancelada(Exception):
    """El usuario canceló desde la barra de progreso."""


@dataclass
class ResultadoConversion:
    ruta_salida: str
    sample_rate: int
    duracion_s: float
    canales_origen: int
    canal_usado: str        # CANAL_MEZCLA | CANAL_IZQ | CANAL_DER
    motivo_canal: str       # explicación legible de por qué ese canal
    pico_pct: float         # nivel máximo del resultado, en % del fondo de escala
    nivel_tipico_pct: float  # nivel típico (percentil de los picos por trozo), en %
    decodificador: str      # "miniaudio" | "ffmpeg"

    def aviso_nivel(self) -> str:
        """Texto de advertencia si la señal resultante es muy débil, o ''.
        Se juzga por el nivel TÍPICO, no por el máximo (ver PERCENTIL_NIVEL)."""
        if self.nivel_tipico_pct >= NIVEL_BAJO_PCT:
            return ""
        return (
            f"AVISO: el nivel de la señal es muy bajo ({self.nivel_tipico_pct:.1f} % del máximo). "
            "Si el audio está vacío o casi mudo, prueba a elegir un canal concreto "
            "(izquierdo o derecho) en vez de la mezcla, o el modo automático: "
            "puede que los dos canales estén en contrafase y se cancelen al mezclarlos."
        )

    def descripcion(self) -> str:
        m, s = divmod(int(round(self.duracion_s)), 60)
        etiqueta = {CANAL_MEZCLA: "mezcla de ambos canales", CANAL_IZQ: "canal izquierdo",
                    CANAL_DER: "canal derecho"}[self.canal_usado]
        lineas = [
            f"Convertido a WAV mono ({self.sample_rate} Hz, 16 bit).",
            f"Duración: {m}:{s:02d}",
            f"Canal: {etiqueta} — {self.motivo_canal}",
            f"Nivel: máximo {self.pico_pct:.0f} %, típico {self.nivel_tipico_pct:.0f} % del fondo de escala",
        ]
        aviso = self.aviso_nivel()
        if aviso:
            lineas += ["", aviso]
        return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Decisión de canal (pura: se prueba sin audio)
# ---------------------------------------------------------------------------

def decidir_canal(pico_izq: int, pico_der: int, pico_mezcla: int) -> tuple[str, str]:
    """Elige entre mezcla, canal izquierdo o derecho a partir de los picos
    medidos al principio del audio. Devuelve (canal, motivo)."""
    mayor = max(pico_izq, pico_der)
    if mayor < UMBRAL_SILENCIO:
        return CANAL_MEZCLA, ("al principio del audio casi no hay señal, no se pudo comparar "
                              "los canales; se mezclaron")
    fuerte = CANAL_IZQ if pico_izq >= pico_der else CANAL_DER
    nombre_fuerte = "izquierdo" if fuerte == CANAL_IZQ else "derecho"
    nombre_debil = "derecho" if fuerte == CANAL_IZQ else "izquierdo"
    if min(pico_izq, pico_der) < RATIO_CANAL_DEBIL * mayor:
        return fuerte, f"el canal {nombre_debil} está casi vacío o solo lleva ruido"
    if pico_mezcla < RATIO_CANCELACION * mayor:
        return fuerte, ("los dos canales parecen estar en contrafase: al mezclarlos se "
                        f"cancelarían; se usó el {nombre_fuerte}")
    return CANAL_MEZCLA, "ambos canales llevan la misma señal"


# ---------------------------------------------------------------------------
# Decodificadores
# ---------------------------------------------------------------------------

@dataclass
class _Info:
    sample_rate: int
    canales: int
    frames: int | None      # None si no se conoce de antemano


# stream(nch, rate, max_frames) -> iterador de array('h') intercalado
_Stream = Callable[[int, int, "int | None"], Iterator[array.array]]


def _importar_miniaudio():
    try:
        import miniaudio  # noqa: PLC0415
        return miniaudio
    except Exception:  # noqa: BLE001 - ImportError, o fallo al cargar la parte nativa
        return None


def _buscar_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def decodificador_disponible() -> str | None:
    """'miniaudio', 'ffmpeg' o None si no hay ninguno."""
    if _importar_miniaudio() is not None:
        return "miniaudio"
    if _buscar_ffmpeg():
        return "ffmpeg"
    return None


_MENSAJE_SIN_DECODIFICADOR = (
    "No hay ningún decodificador de audio disponible.\n\n"
    "Instala uno de estos dos:\n"
    "  • El módulo de Python 'miniaudio' (recomendado):\n"
    "        pip install miniaudio cffi\n"
    "  • O ffmpeg (https://ffmpeg.org), accesible desde el PATH del sistema."
)


def _al_orden_nativo_a_le(chunk: array.array) -> array.array:
    """array('h') está en el orden de bytes de la máquina; el WAV es little-endian."""
    if sys.byteorder == "big":
        chunk = array.array("h", chunk)
        chunk.byteswap()
    return chunk


def _abrir_miniaudio(ma, datos: bytes, ext: str) -> tuple[_Info, _Stream]:
    informar = {".mp3": ma.mp3_get_info, ".wav": ma.wav_get_info,
                ".flac": ma.flac_get_info, ".ogg": ma.vorbis_get_info}[ext]
    try:
        info = informar(datos)
    except Exception as e:  # noqa: BLE001 - DecodeError y similares
        raise AudioError(
            f"no se pudo leer como {ext[1:].upper()}: el archivo está dañado o no es "
            f"realmente de ese formato ({e})") from e
    formato = ma.SampleFormat.SIGNED16

    def stream(nch: int, rate: int, max_frames: int | None):
        leidos = 0
        gen = ma.stream_memory(datos, output_format=formato, nchannels=nch,
                               sample_rate=rate, frames_to_read=FRAMES_POR_TROZO)
        try:
            for chunk in gen:
                yield chunk
                leidos += len(chunk) // nch
                if max_frames is not None and leidos >= max_frames:
                    break
        except AudioError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AudioError(f"error al decodificar el audio: {e}") from e
        finally:
            gen.close()

    return _Info(info.sample_rate, info.nchannels, info.num_frames), stream


_RE_AUDIO = re.compile(r"Audio:.*?,\s*(\d+)\s*Hz,\s*([^,\n]+)")
_RE_DURACION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def _canales_de_layout(layout: str) -> int:
    layout = layout.strip().lower()
    if layout == "mono":
        return 1
    if layout == "stereo":
        return 2
    m = re.match(r"(\d+)\s*channels?", layout)
    if m:
        return int(m.group(1))
    m = re.match(r"(\d+)\.(\d+)", layout)          # 5.1, 7.1...
    if m:
        return int(m.group(1)) + int(m.group(2))
    return 2


def _flags_sin_ventana() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _abrir_ffmpeg(ffmpeg: str, ruta: str) -> tuple[_Info, _Stream]:
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", ruta],
                       capture_output=True, text=True, errors="replace",
                       creationflags=_flags_sin_ventana())
    texto = r.stderr or ""
    m = _RE_AUDIO.search(texto)
    if not m:
        raise AudioError("ffmpeg no reconoce el archivo como audio (¿está dañado?)")
    rate, canales = int(m.group(1)), _canales_de_layout(m.group(2))
    frames = None
    d = _RE_DURACION.search(texto)
    if d:
        frames = int((int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))) * rate)

    def stream(nch: int, rate_out: int, max_frames: int | None):
        cmd = [ffmpeg, "-v", "error", "-nostdin", "-i", ruta, "-vn",
               "-ac", str(nch), "-ar", str(rate_out)]
        if max_frames is not None:
            cmd += ["-t", f"{max_frames / rate_out:.3f}"]
        cmd += ["-f", "s16le", "-"]
        bytes_trozo = FRAMES_POR_TROZO * nch * 2
        with tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err,
                                    creationflags=_flags_sin_ventana())
            terminado = False
            try:
                while True:
                    buf = proc.stdout.read(bytes_trozo)
                    if not buf:
                        terminado = True
                        break
                    buf = buf[: len(buf) - (len(buf) % (2 * nch))]   # nunca un frame a medias
                    if buf:
                        chunk = array.array("h")
                        chunk.frombytes(buf)
                        if sys.byteorder == "big":
                            chunk.byteswap()
                        yield chunk
            finally:
                if not terminado:
                    proc.kill()
                proc.stdout.close()
                codigo = proc.wait()
            if terminado and codigo != 0:
                err.seek(0)
                detalle = err.read().decode("utf-8", "replace").strip()
                raise AudioError(f"ffmpeg falló al decodificar: {detalle or codigo}")

    return _Info(rate, canales, frames), stream


# ---------------------------------------------------------------------------
# Conversión
# ---------------------------------------------------------------------------

def _pico(chunk: array.array) -> int:
    return max(max(chunk), -min(chunk)) if len(chunk) else 0


def _percentil(valores: list[int], fraccion: float) -> int:
    """Valor en la posición `fraccion` (0..1) de la lista ordenada; 0 si está vacía."""
    if not valores:
        return 0
    orden = sorted(valores)
    return orden[int(fraccion * (len(orden) - 1))]


def _analizar_canales(stream: _Stream, rate: int) -> tuple[int, int, int]:
    """Nivel de izquierdo, derecho y mezcla en los primeros SEGUNDOS_ANALISIS
    (percentil de los picos por trozo, ver PERCENTIL_NIVEL)."""
    maximo = SEGUNDOS_ANALISIS * rate
    picos_l, picos_r, picos_m = [], [], []
    for chunk in stream(2, rate, maximo):
        picos_l.append(_pico(chunk[0::2]))
        picos_r.append(_pico(chunk[1::2]))
    for chunk in stream(1, rate, maximo):
        picos_m.append(_pico(chunk))
    return (_percentil(picos_l, PERCENTIL_NIVEL), _percentil(picos_r, PERCENTIL_NIVEL),
            _percentil(picos_m, PERCENTIL_NIVEL))


def convertir_a_wav_mono(
    ruta_entrada: str,
    ruta_salida: str,
    canal: str = CANAL_AUTO,
    sample_rate: int | None = None,
    progreso: Callable[[float | None], bool] | None = None,
) -> ResultadoConversion:
    """Convierte `ruta_entrada` (MP3/WAV/FLAC/OGG) a un WAV mono de 16 bits.

    canal        CANAL_AUTO (por defecto), CANAL_MEZCLA, CANAL_IZQ o CANAL_DER.
                 Se ignora si el audio ya es mono.
    sample_rate  None = conservar la frecuencia original; si no, remuestrea.
    progreso     callback(fraccion 0..1, o None si no se conoce la duración);
                 si devuelve False se cancela (ConversionCancelada).

    Lanza AudioError (mensaje para el usuario) o ConversionCancelada. Si algo
    falla, no deja un WAV a medias en `ruta_salida`.
    """
    if canal not in CANALES:
        raise ValueError(f"canal desconocido: {canal!r}")
    ext = os.path.splitext(ruta_entrada)[1].lower()
    if ext not in EXTENSIONES_AUDIO:
        raise AudioError(
            f"no es un archivo de audio compatible (se esperaba "
            f"{', '.join(EXTENSIONES_AUDIO)}; este es «{ext or 'sin extensión'}»)")

    ma = _importar_miniaudio()
    ffmpeg = None if ma else _buscar_ffmpeg()
    if ma is None and ffmpeg is None:
        raise AudioError(_MENSAJE_SIN_DECODIFICADOR)

    if ma is not None:
        with open(ruta_entrada, "rb") as fh:
            datos = fh.read()
        info, stream = _abrir_miniaudio(ma, datos, ext)
        nombre_dec = "miniaudio"
    else:
        info, stream = _abrir_ffmpeg(ffmpeg, ruta_entrada)
        nombre_dec = "ffmpeg"

    if info.canales < 1 or info.sample_rate < 1:
        raise AudioError("el archivo no contiene audio utilizable")

    rate_salida = sample_rate or info.sample_rate
    total = None
    if info.frames:
        total = int(info.frames * rate_salida / info.sample_rate)

    # --- qué canal ---
    if info.canales == 1:
        canal_usado, motivo, nch = CANAL_MEZCLA, "el archivo ya es mono", 1
    else:
        if canal == CANAL_AUTO:
            pl, pr, pm = _analizar_canales(stream, rate_salida)
            canal_usado, motivo = decidir_canal(pl, pr, pm)
        else:
            canal_usado, motivo = canal, "elegido por ti"
        nch = 1 if canal_usado == CANAL_MEZCLA else 2

    # --- conversión, por trozos, directamente a disco ---
    escritos = 0
    pico = 0
    picos_trozos: list[int] = []
    ok = False
    try:
        with wave.open(ruta_salida, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate_salida)
            for chunk in stream(nch, rate_salida, None):
                if nch == 2:
                    chunk = chunk[0::2] if canal_usado == CANAL_IZQ else chunk[1::2]
                if not len(chunk):
                    continue
                p_trozo = _pico(chunk)
                picos_trozos.append(p_trozo)
                pico = max(pico, p_trozo)
                wf.writeframes(_al_orden_nativo_a_le(chunk).tobytes())
                escritos += len(chunk)
                if progreso is not None:
                    fraccion = min(1.0, escritos / total) if total else None
                    if progreso(fraccion) is False:
                        raise ConversionCancelada()
        if escritos == 0:
            raise AudioError("el archivo no contiene muestras de audio")
        ok = True
    finally:
        if not ok:
            try:
                os.remove(ruta_salida)
            except OSError:
                pass

    return ResultadoConversion(
        ruta_salida=ruta_salida, sample_rate=rate_salida,
        duracion_s=escritos / rate_salida, canales_origen=info.canales,
        canal_usado=canal_usado, motivo_canal=motivo,
        pico_pct=100.0 * pico / _FONDO_ESCALA,
        nivel_tipico_pct=100.0 * _percentil(picos_trozos, PERCENTIL_NIVEL) / _FONDO_ESCALA,
        decodificador=nombre_dec)
