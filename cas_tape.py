"""Conversor de cintas MSX entre formato CAS (lógico, por bytes) y WAV
(forma de onda de audio real, tal como sonaría en un casete).

Especificación usada (contrastada en varias fuentes técnicas de la escena
MSX: MSX Wiki, foros de msx.org, documentación de castools/MCP):

- Un archivo .CAS es una captura "decodificada": una secuencia de bytes en
  la que cada bloque va precedido por la marca de sincronismo de 8 bytes
  1F A6 DE BA CC 13 7D 74, siempre alineada a un múltiplo de 8 dentro del
  archivo. No contiene información de temporización (duración de los tonos
  piloto); eso lo decide quien genera el audio.
- La codificación de audio es FSK "Kansas City" tal como la usa la BIOS del
  MSX:
    - A 1200 baudios: bit 0 = 1 ciclo a 1200 Hz, bit 1 = 2 ciclos a 2400 Hz.
    - A 2400 baudios (turbo): bit 0 = 1 ciclo a 2400 Hz, bit 1 = 2 ciclos a
      4800 Hz.
  Ambas codificaciones de bit duran lo mismo, lo cual es la base de este
  esquema FSK de baudios fijos.
- Cada byte se transmite como: 1 bit de arranque (0) + 8 bits de datos
  (LSB primero) + 2 bits de parada (1,1) = 11 bits por byte.

Simplificación deliberada y documentada: esta implementación antepone un
tono piloto de la MISMA duración ("larga") antes de cada marca de
sincronismo, en vez de alternar entre piloto largo (antes del bloque de
cabecera) y corto (antes del bloque de datos) como hacen algunas
grabaciones de referencia. Esto es más simple y nunca causa fallos de
carga (un piloto más largo de lo necesario no es un problema, uno más
corto sí podría serlo) a cambio de un archivo WAV algo más largo de lo
estrictamente necesario.

El decodificador WAV→CAS está pensado principalmente para audio limpio
generado digitalmente (por esta misma herramienta, por un emulador, etc.),
pero incorpora una mejora de precisión tomada de makeTSX (la herramienta de
referencia de Natalia Pujol, autora del formato TSX, cuyas fuentes se
revisaron para contrastar este decodificador): la velocidad de la cinta se
mide promediando sobre el propio tramo de tono piloto detectado, en vez de
tomar el valor más frecuente de todo el archivo. Un promedio sobre cientos
de ciclos consecutivos tolera mucho mejor el "wow and flutter" (deriva
lenta de velocidad del motor) que una grabación de cinta real siempre
tiene en mayor o menor medida.

Lo que NO se ha incorporado de makeTSX, por ser de una complejidad y un
alcance distintos a los de esta herramienta: su modo predictivo (cuando un
bit es ambiguo, prueba ambos valores y comprueba cuál permite decodificar
el resto del byte con coherencia) y su modo interactivo, que llega a
preguntar al usuario byte a byte ante una duda irresoluble. Para cintas
muy degradadas, con ruido real de casete más allá de la deriva de
velocidad, herramientas especializadas como makeTSX o castools siguen
siendo la referencia más robusta.
"""
from __future__ import annotations

import io
import struct
import wave

CAS_SYNC = bytes.fromhex("1FA6DEBACC137D74")

# (frecuencia "space" = bit 0, frecuencia "mark" = bit 1) por baudios.
#
# La relación es siempre space=baud y mark=2*baud: un bit 0 es un ciclo a la
# frecuencia baja y un bit 1 son dos ciclos a la frecuencia doble, de forma
# que ambos bits duran exactamente lo mismo (base del esquema FSK de
# baudios fijos que usa la BIOS del MSX).
#
# 1200 y 2400 son las dos velocidades soportadas por la ROM estándar. Las
# velocidades superiores (3000, 3600) NO son estándar: requieren que en el
# MSX se haya fijado antes la velocidad de lectura correspondiente (p. ej.
# con el POKE adecuado a la variable de sistema), igual que hacen otras
# herramientas del ecosistema que ofrecen estas mismas opciones. Si el MSX
# está en su configuración por defecto, solo cargarán 1200 y 2400.
STANDARD_BAUDS = (1200, 2400)
EXTENDED_BAUDS = (3000, 3600)
SUPPORTED_BAUDS = STANDARD_BAUDS + EXTENDED_BAUDS


def baud_tones(baud: int) -> tuple[int, int]:
    """Devuelve (frecuencia_bit0, frecuencia_bit1) para una velocidad dada."""
    if baud <= 0:
        raise ValueError("la velocidad en baudios debe ser mayor que 0")
    return baud, baud * 2


# Compatibilidad con el código existente
BAUD_TONES = {b: baud_tones(b) for b in SUPPORTED_BAUDS}


def find_sync_positions(data: bytes) -> list[int]:
    """Posiciones (alineadas a 8 bytes) donde aparece la marca de sincronismo."""
    positions = []
    for off in range(0, len(data) - 8 + 1, 8):
        if data[off:off + 8] == CAS_SYNC:
            positions.append(off)
    return positions


def _segments(data: bytes) -> list[tuple[int, int]]:
    positions = find_sync_positions(data)
    if not positions:
        return [(0, len(data))] if data else []
    segments = []
    if positions[0] != 0:
        segments.append((0, positions[0]))
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(data)
        segments.append((pos, end))
    return segments


def samples_per_half_cycle(baud: int, sample_rate: int) -> float:
    """Muestras por semiciclo del tono MÁS AGUDO (bit 1) a esa velocidad.

    Es el indicador de si la frecuencia de muestreo es suficiente: por
    debajo de ~6 muestras la onda cuadrada empieza a deformarse por
    redondeo y la carga en hardware real se vuelve poco fiable.
    """
    _space_hz, mark_hz = baud_tones(baud)
    return sample_rate / mark_hz / 2


def check_sample_rate(baud: int, sample_rate: int) -> str | None:
    """Devuelve un aviso legible si la combinación velocidad/frecuencia de
    muestreo es arriesgada, o None si es holgada."""
    spc = samples_per_half_cycle(baud, sample_rate)
    if spc < 4:
        return (f"A {baud} baudios con {sample_rate} Hz solo hay {spc:.1f} muestras por "
                "semiciclo: la onda saldrá muy deformada y es muy probable que no cargue. "
                "Sube la frecuencia de muestreo (96000 Hz) o baja la velocidad.")
    if spc < 6:
        return (f"A {baud} baudios con {sample_rate} Hz hay {spc:.1f} muestras por semiciclo, "
                "un margen justo. Si falla la carga, prueba con 48000 o 96000 Hz.")
    return None


# Duraciones de las pausas entre bloques, en segundos. Los valores salen de
# medir grabaciones reales: 0,625 s tras una cabecera (para que el MSX la
# procese antes de que lleguen los datos) y 2,5 s antes de la cabecera de un
# archivo nuevo.
GAP_AFTER_HEADER = 0.625
GAP_BETWEEN_FILES = 2.5

# Bytes de tipo de una cabecera MSX, repetidos diez veces al inicio del bloque
HEADER_TYPE_BYTES = (0xD0, 0xD3, 0xEA)


def is_header_block(block: bytes) -> bool:
    """Un bloque de cabecera empieza con diez copias del byte de tipo."""
    if len(block) < 10:
        return False
    tipo = block[0]
    return tipo in HEADER_TYPE_BYTES and block[:10] == bytes([tipo]) * 10


def cas_to_wav(data: bytes, baud: int = 1200, sample_rate: int = 44100,
               bit_depth: int = 8, pilot_seconds: float = 4.0,
               gaps: bool = True) -> bytes:
    if baud not in SUPPORTED_BAUDS:
        raise ValueError(f"velocidad no soportada: {baud} (admitidas: {SUPPORTED_BAUDS})")
    if bit_depth not in (8, 16):
        raise ValueError("bit_depth debe ser 8 o 16")
    if not data:
        raise ValueError("el archivo CAS está vacío")

    space_hz, mark_hz = baud_tones(baud)

    if bit_depth == 8:
        hi_block, lo_block = bytes([255]), bytes([0])
    else:
        hi_block = struct.pack("<h", 32767)
        lo_block = struct.pack("<h", -32768)

    samples = bytearray()

    def emit_cycles(freq: float, n_cycles: int):
        # El semiciclo BAJO va primero, de modo que el flanco descendente
        # coincida exactamente con el inicio de cada ciclo. Así lo hacen las
        # grabaciones reales (su senoide arranca en cero bajando), y así el
        # decodificador -que se guía por los cruces descendentes- encuentra
        # las fronteras de bit en el sitio correcto. Con el semiciclo alto
        # primero, el cruce caía a mitad de ciclo y los cambios de frecuencia
        # producían periodos intermedios que rompían la lectura.
        half = max(1, round(sample_rate / freq / 2))
        unit = lo_block * half + hi_block * half
        samples.extend(unit * n_cycles)

    def emit_pilot(seconds: float):
        n_cycles = max(1, round(seconds * mark_hz))
        emit_cycles(mark_hz, n_cycles)

    def emit_byte(b: int):
        bits = [0] + [(b >> i) & 1 for i in range(8)] + [1, 1]
        i = 0
        n = len(bits)
        while i < n:
            if bits[i] == 0:
                emit_cycles(space_hz, 1)
                i += 1
            else:
                emit_cycles(mark_hz, 2)
                i += 1

    def emit_silence(seconds: float):
        n = int(sample_rate * seconds)
        if n > 0:
            # El silencio es el punto medio de la señal, no un extremo
            samples.extend((bytes([128]) if bit_depth == 8
                            else struct.pack("<h", 0)) * n)

    primero = True
    for start, end in _segments(data):
        trozo = data[start:end]
        cuerpo = trozo[8:] if trozo[:8] == CAS_SYNC else trozo

        if gaps and not primero:
            # Pausa larga antes de un archivo nuevo (su cabecera), corta si
            # es el bloque de datos que sigue a una cabecera.
            emit_silence(GAP_BETWEEN_FILES if is_header_block(cuerpo)
                          else GAP_AFTER_HEADER)
        primero = False

        emit_pilot(pilot_seconds)
        # La marca de sincronismo NO se graba como datos: en una cinta real la
        # representa el propio tono piloto que acabamos de emitir. Grabarla
        # además como bytes produciría una marca duplicada al volver a leer.
        for b in cuerpo:
            emit_byte(b)

        # Cola corta de tono tras cada bloque. Sin ella, el último ciclo del
        # bloque quedaba absorbido por el silencio siguiente (el silencio no
        # produce cruces por cero, así que no cerraba el ciclo) y se perdía el
        # último bit, corrompiendo el byte final.
        emit_cycles(mark_hz, max(1, round(0.05 * mark_hz)))

    # Pequeña cola final de piloto: sin ella, el último ciclo del último bit
    # no tendría un siguiente flanco con el que medir su duración y se
    # perdería en la decodificación.
    emit_pilot(min(pilot_seconds, 0.3))

    return _wrap_wav(bytes(samples), sample_rate, bit_depth)


def _wrap_wav(pcm: bytes, sample_rate: int, bit_depth: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(1 if bit_depth == 8 else 2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def read_wav_samples(wav_bytes: bytes) -> tuple[int, list[int]]:
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sampwidth == 1:
        samples = [b - 128 for b in raw]
        if n_channels > 1:
            samples = samples[0::n_channels]
    elif sampwidth == 2:
        count = len(raw) // 2
        vals = list(struct.unpack("<%dh" % count, raw))
        if n_channels > 1:
            vals = vals[0::n_channels]
        samples = vals
    else:
        raise ValueError(f"profundidad de bits de WAV no soportada: {sampwidth * 8}")

    return framerate, samples


def _falling_crossings(samples: list[int]) -> list[int]:
    """Posiciones donde la señal cruza el cero hacia abajo.

    Se usan los cruces DESCENDENTES y no los ascendentes por un motivo
    concreto, comprobado contra grabaciones reales: en una señal senoidal
    correctamente generada, cada ciclo -tanto el del tono grave como el del
    agudo- empieza justo en el cruce descendente, así que la distancia entre
    cruces descendentes da la duración exacta del ciclo.

    Con los cruces ascendentes, en cambio, la fase del cruce dentro del ciclo
    difiere entre ambas frecuencias, y en cada cambio de frecuencia aparece un
    periodo intermedio espurio (ni grave ni agudo) que rompe la
    decodificación. Medido en un archivo real: con cruces ascendentes salían
    periodos de 9, 18 y también 13 y 14 muestras; con descendentes, solo 9 y
    18, que son las dos frecuencias reales.
    """
    crossings = []
    prev = samples[0] if samples else 0
    for i in range(1, len(samples)):
        cur = samples[i]
        if prev >= 0 > cur:
            crossings.append(i)
        prev = cur
    return crossings


def _periods_to_bits(periods: list[int], sample_rate: int, space_hz: int, mark_hz: int) -> list[int]:
    """Traduce duraciones de ciclo a bits: un ciclo grave = 0, dos agudos = 1."""
    space_period = sample_rate / space_hz
    mark_period = sample_rate / mark_hz          # == space_period / 2
    threshold = (space_period + mark_period) / 2
    bits = []
    i = 0
    n = len(periods)
    while i < n:
        if periods[i] >= threshold:
            bits.append(0)
            i += 1
        elif i + 1 < n and periods[i + 1] < threshold:
            bits.append(1)
            i += 2
        else:
            # Ciclo corto suelto, sin pareja: resto de un tono piloto que
            # termina en número impar de ciclos. Se descarta en lugar de
            # emparejarlo con el siguiente y desalinear todo lo que viene.
            i += 1
    return bits


# Nº mínimo de bits '1' seguidos para considerar que es un tono piloto y no
# datos. El piloto real dura segundos (miles de bits), así que un umbral
# holgado evita confundirlo con una racha de unos dentro de los datos.
PILOT_MIN_BITS = 256

# Valor especial en el flujo de bits que representa una pausa entre bloques.
# No es un bit: marca que ahí terminó un bloque y empieza otro.
GAP_MARKER = -1


def _bits_to_cas(bits: list[int]) -> bytes:
    """Reconstruye el flujo de un archivo CAS a partir de los bits.

    Detalle esencial, comprobado contra grabaciones reales: la marca de
    sincronismo de 8 bytes de un .CAS NO está grabada en la cinta. Es una
    convención del formato de archivo que representa el TONO PILOTO. Por eso
    aquí se detectan las rachas largas de bits '1' (el piloto) y se inserta
    la marca en su lugar, con el relleno necesario para dejarla alineada a 8
    bytes como exige el formato.
    """
    out = bytearray()
    i = 0
    n = len(bits)
    unos = 0

    while i < n:
        if bits[i] == GAP_MARKER:
            # Pausa entre bloques: cierra lo que hubiera en curso y reinicia
            # la cuenta del piloto, sin aportar ningún bit.
            unos = 0
            i += 1
            continue

        if bits[i] == 1:
            unos += 1
            i += 1
            continue

        # Llega un 0: si venimos de un piloto largo, empieza un bloque nuevo
        if unos >= PILOT_MIN_BITS:
            resto = len(out) % 8
            if resto:
                out += bytes(8 - resto)
            out += CAS_SYNC
        unos = 0

        # Intentar leer un byte: arranque(0) + 8 datos (LSB primero) + 2 parada
        if i + 11 > n:
            break
        datos = bits[i + 1:i + 9]
        parada = bits[i + 9:i + 11]
        if parada == [1, 1]:
            valor = 0
            for k, b in enumerate(datos):
                valor |= (b & 1) << k
            out.append(valor)
            i += 11
        else:
            # Trama inválida: avanzar un bit y volver a intentar
            i += 1

    return bytes(out)


def detect_baud(wav_bytes: bytes) -> tuple[int, float]:
    """Deduce la velocidad de la grabación midiendo el tono agudo.

    Devuelve (baudios, confianza 0..1). Se apoya en que el ciclo más
    frecuente de toda la cinta es el del tono agudo, que por definición está
    al doble de la velocidad en baudios.
    """
    sample_rate, samples = read_wav_samples(wav_bytes)
    if not samples:
        raise ValueError("el archivo WAV no contiene muestras de audio")
    crossings = _falling_crossings(samples)
    if len(crossings) < 100:
        raise ValueError("la señal no contiene suficientes cruces por cero")
    periods = [crossings[i + 1] - crossings[i] for i in range(len(crossings) - 1)]

    from collections import Counter
    conteo = Counter(p for p in periods if 2 <= p <= sample_rate // 200)
    if not conteo:
        raise ValueError("no se pudo medir la frecuencia de la señal")
    periodo_agudo, apariciones = conteo.most_common(1)[0]
    frecuencia_aguda = sample_rate / periodo_agudo
    baud_estimado = frecuencia_aguda / 2

    mejor = min(SUPPORTED_BAUDS, key=lambda b: abs(b - baud_estimado))
    error = abs(mejor - baud_estimado) / mejor
    confianza = max(0.0, 1.0 - error * 4) * (apariciones / max(1, len(periods)))
    return mejor, confianza


def _medir_piloto_por_promedio(sample_rate: int, periods: list) -> float | None:
    """Mide la duración del ciclo agudo promediando sobre el tramo del tono
    piloto, en vez de tomar la moda de todo el archivo.

    Es el mismo principio que usa makeTSX (la herramienta de referencia de
    Natalia Pujol para el formato TSX): mide continuamente la duración media
    acumulada de los pulsos del piloto según los va recorriendo, en vez de
    una única medición puntual. Un promedio sobre cientos de ciclos consecu-
    tivos reduce el ruido de medición frente a mirar solo el más frecuente
    de todo el archivo, que puede verse contaminado si hay tramos de datos
    con una duración parecida a la del piloto.

    Devuelve None si no se encuentra una racha de piloto suficientemente
    larga (en cuyo caso el llamador debe recurrir al método de la moda).
    """
    from collections import Counter
    # Una primera estimación basta para saber qué duración de ciclo buscar
    conteo = Counter(p for p in periods if 2 <= p <= sample_rate // 100)
    if not conteo:
        return None
    estimado, _n = conteo.most_common(1)[0]

    mejor_racha, mejor_longitud = None, 0
    racha_ini = 0
    for i, p in enumerate(periods):
        # Un ciclo "parecido" al estimado, con margen amplio (25%) porque
        # aún no conocemos la duración exacta
        if estimado * 0.75 <= p <= estimado * 1.25:
            continue
        longitud = i - racha_ini
        if longitud > mejor_longitud:
            mejor_longitud, mejor_racha = longitud, (racha_ini, i)
        racha_ini = i + 1
    longitud = len(periods) - racha_ini
    if longitud > mejor_longitud:
        mejor_longitud, mejor_racha = longitud, (racha_ini, len(periods))

    # El piloto real dura miles de ciclos; con menos de 200 no merece la
    # pena fiarse del promedio, mejor usar la moda global.
    if mejor_racha is None or mejor_longitud < 200:
        return None

    ini, fin = mejor_racha
    return sum(periods[ini:fin]) / (fin - ini)


def measure_signal(wav_bytes: bytes) -> tuple[int, float, float, float]:
    """Mide la señal sin dar por hecha ninguna velocidad estándar.

    Devuelve (frecuencia_muestreo, periodo_agudo, periodo_grave, baudios).

    Es necesario porque las cintas reales NO van a velocidades redondas: los
    ripeos aportados por el usuario resultaron estar a ~1234 y ~1670 baudios,
    valores que dependen del cargador del juego y de la mecánica del casete.
    Imponer 1200/2400 hacía fallar la decodificación; midiendo la señal,
    funciona con cualquier velocidad.
    """
    from collections import Counter
    sample_rate, samples = read_wav_samples(wav_bytes)
    if not samples:
        raise ValueError("el archivo WAV no contiene muestras de audio")
    crossings = _falling_crossings(samples)
    if len(crossings) < 100:
        raise ValueError("la señal no contiene suficientes cruces por cero")
    periods = [crossings[i + 1] - crossings[i] for i in range(len(crossings) - 1)]

    # Descartar silencios y pausas larguísimas antes de medir
    utiles = [p for p in periods if 2 <= p <= sample_rate // 100]
    if not utiles:
        raise ValueError("no se pudo medir la frecuencia de la señal")

    # Medición precisa por promedio sobre el propio tono piloto; si no se
    # encuentra una racha larga y clara, se recurre a la moda del histograma
    # como respaldo (el método usado antes, que sigue siendo válido).
    periodo_agudo = _medir_piloto_por_promedio(sample_rate, periods)
    if periodo_agudo is None:
        conteo = Counter(utiles)
        periodo_agudo = float(conteo.most_common(1)[0][0])

    # El ciclo grave debería medir el doble; se busca en el histograma para
    # confirmarlo en vez de asumirlo.
    conteo = Counter(utiles)
    candidatos = [p for p, _n in conteo.most_common(6)
                  if 1.6 * periodo_agudo <= p <= 2.4 * periodo_agudo]
    periodo_grave = candidatos[0] if candidatos else periodo_agudo * 2

    baudios = sample_rate / periodo_grave
    return sample_rate, float(periodo_agudo), float(periodo_grave), baudios


def detect_baud(wav_bytes: bytes) -> tuple[int, float]:
    """Velocidad medida, redondeada a la estándar más próxima (informativo)."""
    _sr, _pa, _pg, baudios = measure_signal(wav_bytes)
    mejor = min(SUPPORTED_BAUDS, key=lambda b: abs(b - baudios))
    error = abs(mejor - baudios) / mejor
    return mejor, max(0.0, 1.0 - error * 4)


def wav_to_cas(wav_bytes: bytes, baud: int | None = None) -> bytes:
    """Convierte una grabación de cinta MSX a formato CAS.

    Si `baud` es None (recomendado), la velocidad se mide directamente de la
    señal, lo que permite leer cintas reales a velocidades no estándar. Si se
    indica un valor, se usa ese.
    """
    sample_rate, samples = read_wav_samples(wav_bytes)
    if not samples:
        raise ValueError("el archivo WAV no contiene muestras de audio")

    if baud is None:
        _sr, periodo_agudo, periodo_grave, _b = measure_signal(wav_bytes)
    else:
        if baud not in SUPPORTED_BAUDS:
            raise ValueError(f"velocidad no soportada: {baud} (admitidas: {SUPPORTED_BAUDS})")
        space_hz, mark_hz = baud_tones(baud)
        periodo_agudo = sample_rate / mark_hz
        periodo_grave = sample_rate / space_hz

    crossings = _falling_crossings(samples)
    periods = [crossings[i + 1] - crossings[i] for i in range(len(crossings) - 1)]

    umbral = (periodo_agudo + periodo_grave) / 2
    # Un hueco mucho más largo que un ciclo normal es una PAUSA entre bloques,
    # no un bit. Las cintas reales las llevan (medidas: 0,625 s tras una
    # cabecera y 2,5 s antes del archivo siguiente). Sin este corte, cada
    # silencio inyectaba un bit 0 espurio en mitad del flujo.
    umbral_pausa = periodo_grave * 4

    bits = []
    i = 0
    n = len(periods)
    while i < n:
        p = periods[i]
        if p >= umbral_pausa:
            bits.append(GAP_MARKER)
            i += 1
        elif p >= umbral:
            bits.append(0)
            i += 1
        elif i + 1 < n and periods[i + 1] < umbral:
            bits.append(1)
            i += 2
        else:
            i += 1

    result = _bits_to_cas(bits)
    if not result:
        raise ValueError(
            "no se pudo decodificar ningún byte; el WAV puede no ser una cinta MSX "
            "válida, o estar demasiado degradado"
        )
    return result
