"""Herramientas de conversión para ROMs de Sega Mega Drive / Genesis:
conversión entre el formato plano (.bin/.gen/.md) y el formato entrelazado
del Super Magic Drive (.smd).

El formato SMD
---------------
Un archivo .smd consta de una cabecera de 512 bytes seguida de los datos
del ROM organizados en bloques de 16 KB. Dentro de cada bloque, los bytes
NO van en orden: la primera mitad (8 KB) contiene los bytes de una paridad
y la segunda mitad los de la otra. Este entrelazado viene de que la BIOS
del Super Magic Drive funciona en modo de compatibilidad con Master
System, que limita el tamaño de los accesos a memoria.

Nota sobre las fuentes
-----------------------
Las descripciones publicadas se contradicen entre sí sobre QUÉ paridad va
primero: unas dicen "primero los pares, después los impares" y otras
justo lo contrario. El origen de la discrepancia es que "par/impar" se usa
a veces contando desde 0 y a veces desde 1.

Para no depender de esa ambigüedad, aquí se implementan las dos variantes
y se elige la correcta COMPROBANDO EL RESULTADO: un ROM de Mega Drive
válido tiene la cadena "SEGA" en el offset 0x100. `smd_to_bin()` prueba la
conversión y verifica ese marcador, de modo que el acierto no depende de
qué fuente tuviera razón. La variante que produce una cabecera válida es,
por definición, la correcta para ese archivo.
"""
from __future__ import annotations

from dataclasses import dataclass

SMD_HEADER_SIZE = 512
SMD_BLOCK_SIZE = 0x4000      # 16 KB
SMD_HALF_BLOCK = 0x2000      # 8 KB

GENESIS_SIGNATURE_OFFSET = 0x100
GENESIS_SIGNATURES = (b"SEGA", b"\x20SEG")  # "SEGA MEGA DRIVE", " SEGA GENESIS"...


@dataclass
class SmdHeaderInfo:
    present: bool
    size: int
    block_count: int | None = None
    notes: str = ""


def has_genesis_signature(data: bytes) -> bool:
    """Comprueba la firma SEGA en el offset 0x100 de un ROM plano."""
    if len(data) < GENESIS_SIGNATURE_OFFSET + 16:
        return False
    chunk = data[GENESIS_SIGNATURE_OFFSET:GENESIS_SIGNATURE_OFFSET + 16].upper()
    return b"SEGA" in chunk


def detect_smd_header(data: bytes) -> SmdHeaderInfo:
    """Detecta la cabecera de 512 bytes propia del Super Magic Drive.

    Señales usadas (las dos primeras son las documentadas para SMD):
      - byte 0: número de bloques de 16 KB
      - byte 1: 0x03 en los volcados habituales
      - bytes 8-9: 0xAA 0xBB (marca de identificación)
    """
    if len(data) < SMD_HEADER_SIZE + SMD_BLOCK_SIZE:
        return SmdHeaderInfo(False, 0)

    resto = len(data) - SMD_HEADER_SIZE
    tamano_encaja = resto % SMD_BLOCK_SIZE == 0

    h = data[:SMD_HEADER_SIZE]
    marca = h[8] == 0xAA and h[9] == 0xBB

    if marca:
        return SmdHeaderInfo(True, SMD_HEADER_SIZE, block_count=h[0],
                              notes="marca 0xAA 0xBB detectada en offsets 8-9")

    # Sin la marca, se recurre a la heurística: tamaño coherente con bloques
    # de 16 KB más cabecera, y ausencia de firma SEGA al principio (si la
    # tuviera en 0x100 sería un ROM plano, no un SMD con cabecera).
    if tamano_encaja and not has_genesis_signature(data):
        return SmdHeaderInfo(True, SMD_HEADER_SIZE,
                              notes="sin marca 0xAA 0xBB; deducida por tamaño")

    return SmdHeaderInfo(False, 0)


def _deinterleave_block(block: bytes, first_half_is_odd: bool) -> bytes:
    """Desentrelaza un bloque de 16 KB."""
    mitad = len(block) // 2
    primera = block[:mitad]
    segunda = block[mitad:]
    out = bytearray(len(block))
    for i in range(mitad):
        if first_half_is_odd:
            out[i * 2 + 1] = primera[i]
            out[i * 2] = segunda[i]
        else:
            out[i * 2] = primera[i]
            out[i * 2 + 1] = segunda[i]
    return bytes(out)


def _interleave_block(block: bytes, first_half_is_odd: bool) -> bytes:
    """Entrelaza un bloque de 16 KB (operación inversa de la anterior)."""
    mitad = len(block) // 2
    primera = bytearray(mitad)
    segunda = bytearray(mitad)
    for i in range(mitad):
        if first_half_is_odd:
            primera[i] = block[i * 2 + 1]
            segunda[i] = block[i * 2]
        else:
            primera[i] = block[i * 2]
            segunda[i] = block[i * 2 + 1]
    return bytes(primera) + bytes(segunda)


def _convert(data: bytes, first_half_is_odd: bool, deinterleave: bool) -> bytes:
    out = bytearray()
    for off in range(0, len(data), SMD_BLOCK_SIZE):
        block = data[off:off + SMD_BLOCK_SIZE]
        if len(block) < SMD_BLOCK_SIZE:
            # Bloque final incompleto: se rellena para poder procesarlo y
            # después se recorta al tamaño original.
            block = block + bytes(SMD_BLOCK_SIZE - len(block))
        if deinterleave:
            out += _deinterleave_block(block, first_half_is_odd)
        else:
            out += _interleave_block(block, first_half_is_odd)
    return bytes(out[:len(data)])


def byteswap(data: bytes) -> bytes:
    """Intercambia los bytes de cada pareja (byte swap de 16 bits).

    Es una operación DISTINTA del entrelazado por bloques del formato SMD:
    aquí simplemente se invierte el orden de los dos bytes de cada palabra
    de 16 bits, en todo el archivo. Corresponde a la diferencia de
    "endianness" con la que algunos volcadores guardaron las ROMs.

    Se reconoce a simple vista en la cabecera: un volcado correcto muestra
    "SEGA GENESIS" en el offset 0x100, mientras que uno con los bytes
    intercambiados muestra "ESAGG NESESI".

    La operación es su propia inversa: aplicarla dos veces devuelve el
    archivo original.

    Verificado byte a byte contra un par de archivos reales del mismo juego
    (Aero the Acro-Bat 2, versión normal y versión "Swapped Bytes").
    """
    n = len(data) - (len(data) % 2)   # última pareja completa
    out = bytearray(data)
    out[0:n:2] = data[1:n:2]
    out[1:n:2] = data[0:n:2]
    return bytes(out)


def is_byteswapped(data: bytes) -> bool | None:
    """Indica si el ROM parece tener los bytes intercambiados.

    Devuelve True/False si puede determinarlo mirando la firma en 0x100, o
    None si no reconoce ninguna de las dos formas (archivo no estándar).
    """
    if has_genesis_signature(data):
        return False
    if has_genesis_signature(byteswap(data)):
        return True
    return None


def smd_to_bin(data: bytes) -> tuple[bytes, str]:
    """Convierte .smd (entrelazado) a formato plano .bin.

    Prueba las dos convenciones de entrelazado posibles y devuelve la que
    produce un ROM con firma SEGA válida en 0x100. Devuelve (datos, nota).
    """
    info = detect_smd_header(data)
    payload = data[info.size:] if info.present else data

    if len(payload) < SMD_BLOCK_SIZE:
        raise ValueError("el archivo es demasiado pequeño para ser un SMD válido")

    candidatos = []
    for first_half_is_odd in (True, False):
        resultado = _convert(payload, first_half_is_odd, deinterleave=True)
        candidatos.append((first_half_is_odd, resultado, has_genesis_signature(resultado)))

    validos = [c for c in candidatos if c[2]]
    if len(validos) == 1:
        orden, resultado, _ = validos[0]
        nota = ("primera mitad = bytes impares" if orden else "primera mitad = bytes pares")
        return resultado, f"Verificado: firma SEGA correcta en 0x100 ({nota})."

    if len(validos) == 2:
        # Improbable, pero si ambas dieran firma válida se usa la convención
        # más extendida en las implementaciones de emuladores.
        return validos[0][1], ("Ambas convenciones producen firma válida; se usó la más "
                                "habitual (primera mitad = bytes impares). Verifica el resultado.")

    # Ninguna produce firma válida: se devuelve la convención habitual, pero
    # avisando claramente en vez de dar por bueno un resultado sin verificar.
    return candidatos[0][1], (
        "AVISO: no se encontró la firma SEGA en 0x100 tras la conversión. El archivo "
        "puede no ser un SMD válido, estar dañado, o ser un volcado poco común. "
        "Se aplicó la convención habitual (primera mitad = bytes impares), pero el "
        "resultado NO está verificado."
    )


def bin_to_smd(data: bytes, add_header: bool = True) -> bytes:
    """Convierte un ROM plano a formato .smd entrelazado.

    Usa la convención habitual (primera mitad de cada bloque = bytes
    impares), que es la que reconocen los volcados y herramientas más
    extendidas. Si `add_header`, antepone la cabecera de 512 bytes del
    Super Magic Drive.
    """
    if len(data) < SMD_BLOCK_SIZE:
        raise ValueError("el archivo es demasiado pequeño para convertirlo a SMD")

    if detect_smd_header(data).present:
        raise ValueError("el archivo ya parece estar en formato SMD")

    # Rellenar hasta múltiplo de 16 KB
    resto = len(data) % SMD_BLOCK_SIZE
    payload = data + bytes(SMD_BLOCK_SIZE - resto) if resto else data

    entrelazado = _convert(payload, first_half_is_odd=True, deinterleave=False)

    if not add_header:
        return entrelazado

    bloques = len(payload) // SMD_BLOCK_SIZE
    header = bytearray(SMD_HEADER_SIZE)
    header[0] = bloques & 0xFF      # nº de bloques de 16 KB
    header[1] = 0x03                 # valor habitual en volcados SMD
    header[8] = 0xAA                 # marca de identificación
    header[9] = 0xBB
    return bytes(header) + entrelazado
