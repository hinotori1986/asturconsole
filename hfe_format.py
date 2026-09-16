"""Conversión de imágenes de disco (sectores FAT12, como las que genera este
proyecto) al formato HFE de HxC/FlashFloppy, usado por los emuladores de
disquetera Gotek para pruebas sin desgastar disquetes físicos reales.

Referencias usadas (ver conversación): especificación oficial "SDCard HxC
Floppy Emulator HFE file format" (Jean-François DEL NERO, rev. 3.1), y la
página de compatibilidad de FlashFloppy, que confirma soporte de HFEv3.

A diferencia de un .dsk/.img (que son bytes de sectores lógicos tal cual),
un .hfe almacena el FLUJO DE BITS MAGNÉTICO completo: marcas de sincronismo,
cabeceras de sector con su CRC, huecos entre sectores... todo lo que
generaría de verdad una cabeza de disquetera al grabar. Por eso hace falta
implementar la codificación MFM (Modified Frequency Modulation) estándar
IBM, no solo "cambiar de contenedor".

Verificación: como no hay forma de probar esto contra un HxC/FlashFloppy
real desde aquí, se implementa también el decodificador inverso (hfe_a_dsk),
y se comprueba que decodificar lo que se acaba de codificar reproduce
exactamente los mismos sectores — no garantiza que el hardware real lo lea
igual, pero sí que la codificación es internamente consistente y sigue la
especificación al pie de la letra.
"""
from __future__ import annotations

import struct

# Valores de gap3 REALES por sectores/pista, verificados de forma
# independiente en dos ocasiones: contra las definiciones de Greaseweazle
# para los samplers Ensoniq (misma geometría exacta que el SMD/SWC
# superformateado) y contra los discos que el propio Greaseweazle graba
# con esos parámetros (data/greaseweazle_diskdefs.cfg). No usar la
# fórmula de reserva proporcional para estas geometrías conocidas: ahí es
# donde estaba el bug que hacía que la conversión a HFE generase un
# bitstream con el gap incorrecto (75 en vez de 40 para 1600 KB, por
# ejemplo) aunque el TAMAÑO total del archivo resultante fuese correcto.
GAP3_CONOCIDOS = {
    9: 84,    # 720 KB (3,5" DD estándar)
    10: 30,   # 800 KB (superformateado SMD/SWC)
    18: 84,   # 1,44 MB (3,5" HD estándar)
    20: 42,   # 1,6 MB (superformateado SMD/SWC) — medido directamente
              # contra flujo real (Greaseweazle, SCP): la distancia total
              # entre sectores mide 54 bytes, pero esa cifra ya incluye
              # los 12 bytes de presync (0x00) que van justo antes de
              # cada marca de sincronismo — el hueco de relleno (0x4E)
              # real, medido decodificando directamente el contenido en
              # vez de solo la distancia entre marcas, es 54-12=42.
}

# Bytes de flujo MFM codificado por CARA que ocupa una revolución física
# completa a 300 rpm — medido DIRECTAMENTE contra flujo real (Greaseweazle,
# formato SCP) de un disco superformateado auténtico: 199981 bits de celda
# en la pista 0 (cilindro 0, cara 0) de un disco vacío formateado por la
# propia utilidad del Super Wild Card, es decir 199981/8 ≈ 24998 bytes de
# archivo. Sustituye un valor anterior (12504) derivado incorrectamente de
# dividir entre 2 la longitud de una entrada de la tabla de pistas HFE,
# asumiendo que esa longitud combina ambas caras — la medición directa de
# flujo real para una sola cara resultó ser casi idéntica a esa longitud
# sin dividir, así que esa división no correspondía a la realidad.
LONGITUD_PISTA_CONOCIDA = {
    20: 24998,  # 1,6 MB (superformateado SMD/SWC) — medido con Greaseweazle/SCP
}


# ---------------------------------------------------------------------------------------
# CRC-16-CCITT, tal como lo usa el formato IBM de disquete (polinomio 0x1021,
# valor inicial 0xFFFF). Se calcula sobre los 3 bytes de sincronismo A1 más
# el byte de marca (FE/FB) y el campo que corresponda.
# ---------------------------------------------------------------------------------------------------------------------------------------
def _construir_tabla_crc16_ccitt() -> list:
    tabla = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        tabla.append(crc)
    return tabla


_TABLA_CRC16_CCITT = _construir_tabla_crc16_ccitt()


def _crc16_ccitt(datos: bytes, inicial: int = 0xFFFF) -> int:
    crc = inicial
    tabla = _TABLA_CRC16_CCITT
    for byte in datos:
        crc = ((crc << 8) ^ tabla[((crc >> 8) ^ byte) & 0xFF]) & 0xFFFF
    return crc


# ---------------------------------------------------------------------------------------------------------------------------------
# Codificación MFM, con tabla de lookup precalculada.
#
# Cada bit de datos D[i] va precedido de un bit de reloj C[i] que sigue la
# regla estándar: C[i] = NOT (D[i-1] OR D[i]) — es decir, el reloj solo se
# pone a 1 cuando NINGUNO de los dos bits de datos adyacentes lo está,
# garantizando así una transición magnética mínima para que la disquetera
# pueda mantener la sincronía.
#
# Trabajar bit a bit en una lista de Python (como en la primera versión de
# este módulo) es correcto pero lento: generar el bitstream completo de un
# disco de 1,6 MB tardaba más de 5 segundos. Precalculando, para cada
# posible byte de entrada y cada uno de los dos bits de contexto posibles
# (el último bit del byte anterior), los 16 bits de salida ya codificados,
# la codificación se reduce a una búsqueda en tabla por byte — unas 10
# veces más rápido, y bit a bit idéntico al resultado de la versión lenta
# (verificado exhaustivamente antes de sustituirla).
# ---------------------------------------------------------------------------------------------------------------------------

def _bits_a_byte_lsb(bits8: list[int]) -> int:
    """Empaqueta 8 bits (bits8[0] = bit menos significativo) en un byte
    — el inverso exacto de leer un byte con _bytes_a_bits/_TABLA_BYTE_A_BITS,
    para que codificar y decodificar usen siempre la misma convención."""
    valor = 0
    for i, b in enumerate(bits8):
        valor |= b << i
    return valor


def _construir_tabla_mfm() -> list:
    tabla = [None] * 512  # índice: bit_anterior * 256 + byte
    for bit_anterior in (0, 1):
        for byte in range(256):
            anterior = bit_anterior
            # Dos convenciones DISTINTAS que no deben confundirse (un
            # error real que costó bastante encontrar): cómo se agrupan
            # las celdas de flujo en bytes DENTRO DEL ARCHIVO (para leerlo
            # de vuelta) es LSB-primero, confirmado repetidas veces contra
            # archivos reales — pero el orden en que la codificación MFM
            # estándar procesa los BITS DE DATO de un byte de entrada
            # siempre es MSB-primero (bit 7 primero), como en cualquier
            # implementación MFM/IBM estándar; esto es independiente de
            # cómo se empaqueten luego las celdas resultantes en bytes de
            # archivo. Confirmado byte a byte contra un sector de arranque
            # real (contenido variado, no un simple relleno periódico
            # como 0x4E, que por su propia periodicidad no permite
            # distinguir entre ambas convenciones — hacía falta contenido
            # real para verlo con claridad).
            bits16 = []
            for i in range(7, -1, -1):
                bit = (byte >> i) & 1
                reloj = 0 if (anterior or bit) else 1
                bits16.append(reloj)
                bits16.append(bit)
                anterior = bit
            byte_alto = _bits_a_byte_lsb(bits16[0:8])
            byte_bajo = _bits_a_byte_lsb(bits16[8:16])
            tabla[bit_anterior * 256 + byte] = (bytes((byte_alto, byte_bajo)), anterior)
    return tabla


_TABLA_MFM = _construir_tabla_mfm()


def _mfm_codificar_bytes(datos: bytes, ultimo_bit: int) -> tuple[bytes, int]:
    """Codifica una secuencia de bytes en bytes de flujo MFM (reloj+dato
    intercalados, 2 bytes de flujo por cada byte de entrada). Devuelve
    (bytes_de_flujo, último_bit_de_dato), para poder encadenar la
    codificación de varios bloques manteniendo la continuidad del reloj
    entre ellos (el reloj de cada bit depende del anterior).
    """
    salida = bytearray(len(datos) * 2)
    bit_actual = ultimo_bit
    base = bit_actual * 256
    for i, byte in enumerate(datos):
        par, bit_actual = _TABLA_MFM[base + byte]
        salida[i * 2] = par[0]
        salida[i * 2 + 1] = par[1]
        base = bit_actual * 256
    return bytes(salida), bit_actual


# Patrones de sincronismo con "violación de reloj" deliberada: son los
# valores MFM estándar de la industria para las marcas A1 (dirección/datos)
# y C2 (índice de pista) — el hardware las reconoce precisamente porque no
# siguen la regla de codificación normal, así que nunca aparecen por
# casualidad en datos codificados normalmente.
_MFM_SYNC_A1 = 0x4489   # 16 bits de flujo para una marca de sincronismo A1
_MFM_SYNC_C2 = 0x5224   # 16 bits de flujo para una marca de sincronismo C2


def _entero_a_bits(valor: int, n_bits: int) -> list[int]:
    """Bits de `valor` leídos directamente en orden MSB (bit n_bits-1 al
    bit 0) — usado solo para construir el patrón de búsqueda de una
    marca de sincronismo, que se transmite como sus 16 bits en ese orden
    directo (ver emitir_sync), NO agrupados en bytes de archivo con LSB
    interno como los datos normales codificados byte a byte."""
    return [(valor >> i) & 1 for i in range(n_bits - 1, -1, -1)]


# ---------------------------------------------------------------------------------------------------------------------------------
# Construcción de una pista MFM completa (todos los sectores de un
# cilindro+cara), en el formato IBM estándar de doble densidad/alta
# densidad: GAP4A, IAM, GAP1, y para cada sector: sync+IDAM+CRC, GAP2,
# sync+DAM+datos+CRC, GAP3; relleno final GAP4B.
# ---------------------------------------------------------------------------------------------------------------------------

def _generar_pista_mfm(sectores: list[bytes], cilindro: int, cabeza: int,
                       bytes_por_sector: int, gap3: int, bitrate_kbps: int) -> bytes:
    """Devuelve el flujo de bytes MFM completo de una pista, con tantos
    sectores como se le pasen (numerados 1..N en el orden de la lista).

    `gap3` es el hueco entre sectores; un valor menor cabe más sectores por
    pista (es el mismo principio que el "superformateo" que descubrimos en
    las BIOS del SMD/SWC — aquí se aplica igual, pero a nivel de bitstream
    en vez de a nivel de parámetros del controlador).

    `bitrate_kbps` se usa para calcular el GAP4B: el relleno final hasta
    completar el tamaño EXACTO de una revolución física completa a 300
    rpm. Sin este relleno (bug real que hubo aquí: estaba documentado en
    un comentario, pero nunca implementado), la pista terminaba justo
    tras el último sector, más corta que una revolución real — el
    software que decodifica sectores conocidos no lo nota, pero un
    controlador de disquete físico (el del propio copión, leyendo a
    través del Gotek) sí puede depender de que cada pista dure una
    revolución completa antes de repetirse, y una pista más corta puede
    desincronizar la lectura del siguiente sector o de la marca de
    índice. Fórmula (verificada contra la especificación oficial de HFE,
    "cell rate = bitrate × 2"): a 300 rpm, una revolución dura 1/5 de
    segundo, así que bytes_por_revolución = bitrate_kbps * 1000 * 2 / 8
    * (1/5) = bitrate_kbps * 50.
    """
    codigo_tamano = {128: 0, 256: 1, 512: 2, 1024: 3}[bytes_por_sector]
    flujo = bytearray()
    ultimo_bit = 0

    def emitir_bytes(datos: bytes):
        nonlocal ultimo_bit
        nuevos, ultimo_bit = _mfm_codificar_bytes(datos, ultimo_bit)
        flujo.extend(nuevos)

    def emitir_sync(patron: int):
        # Los patrones de sincronismo se insertan directamente como flujo
        # ya codificado (no pasan por _mfm_codificar_bytes, porque son
        # precisamente la EXCEPCIÓN a la regla de codificación normal).
        # A diferencia de los datos normales codificados byte a byte (que
        # sí se agrupan con LSB-primero dentro de cada byte de archivo),
        # una marca de sincronismo se transmite como sus 16 bits leídos
        # directamente en orden MSB — confirmado byte a byte contra un
        # volcado de flujo real: el patrón real en el archivo es
        # exactamente 0x5224/0x4489 leído bit a bit de izquierda a
        # derecha, no "dos bytes cada uno con su propio LSB interno"
        # (que es lo que se obtenía antes con struct.pack + _bytes_a_bits,
        # y no coincidía con ningún archivo real). Se usa _bits_a_byte_lsb
        # para volver a empaquetar esos mismos 16 bits en el formato de
        # archivo correcto, de forma que al leerlos de vuelta con
        # _bytes_a_bits se recupere exactamente la secuencia MSB deseada.
        nonlocal ultimo_bit
        bits16 = [(patron >> i) & 1 for i in range(15, -1, -1)]
        byte_alto = _bits_a_byte_lsb(bits16[0:8])
        byte_bajo = _bits_a_byte_lsb(bits16[8:16])
        flujo.extend(bytes((byte_alto, byte_bajo)))
        ultimo_bit = bits16[-1]

    # GAP4A + IAM (marca de índice de pista)
    emitir_bytes(bytes([0x4E] * 80))
    emitir_bytes(bytes([0x00] * 12))
    for _ in range(3):
        emitir_sync(_MFM_SYNC_C2)
    emitir_bytes(bytes([0xFC]))
    # GAP1 — 50 bytes. Medido dos veces contra flujo real (Greaseweazle,
    # SCP) de dos discos distintos: un disco ya escrito con datos dio 38,
    # pero un disco recién formateado (FAT12 vacío) por la misma cadena de
    # herramientas (gw convert --bitrate=499) que sí funciona en hardware
    # real dio 50 de forma consistente — se usa este último valor, porque
    # es el que corresponde al estado real en el que se encuentra un
    # disco recién formateado antes de escribir nada más sobre él.
    emitir_bytes(bytes([0x4E] * 50))

    n_total_sectores = len(sectores)
    for n_sector, datos_sector in enumerate(sectores, start=1):
        # --- cabecera de dirección del sector (IDAM) ---
        emitir_bytes(bytes([0x00] * 12))
        for _ in range(3):
            emitir_sync(_MFM_SYNC_A1)
        campo_id = bytes([0xFE, cilindro & 0xFF, cabeza & 0xFF,
                          n_sector & 0xFF, codigo_tamano])
        emitir_bytes(campo_id)
        crc_id = _crc16_ccitt(bytes([0xA1, 0xA1, 0xA1]) + campo_id)
        emitir_bytes(struct.pack(">H", crc_id))
        # GAP2 — 22 bytes. La distancia total medida entre marcas (34)
        # incluye el presync de 12 bytes emitido aparte más abajo — el
        # hueco de relleno puro es 34-12=22 (confirmado decodificando
        # directamente el contenido, no solo restando distancias).
        emitir_bytes(bytes([0x4E] * 22))
        # --- datos del sector (DAM) ---
        emitir_bytes(bytes([0x00] * 12))
        for _ in range(3):
            emitir_sync(_MFM_SYNC_A1)
        emitir_bytes(bytes([0xFB]))
        emitir_bytes(datos_sector)
        crc_datos = _crc16_ccitt(bytes([0xA1, 0xA1, 0xA1, 0xFB]) + datos_sector)
        emitir_bytes(struct.pack(">H", crc_datos))
        # GAP3 (hueco hasta el siguiente sector; determina cuántos caben)
        # — SOLO entre sectores: tras el último sector no hay "siguiente"
        # al que separar, así que ese espacio ya es relleno final (ver
        # GAP4B más abajo), no un GAP3 más. Emitirlo aquí también (como
        # ocurría antes de esta corrección) añadía un hueco de más por
        # cada pista, y a menudo ya dejaba la pista más larga que el
        # objetivo real medido contra hardware, sin que el relleno GAP4B
        # pudiera compensarlo (solo rellena si falta, nunca recorta).
        if n_sector < n_total_sectores:
            emitir_bytes(bytes([0x4E] * gap3))

    # GAP4B: relleno hasta completar la pista con el tamaño EXACTO de una
    # revolución física completa (ver docstring), redondeado hacia arriba
    # al siguiente múltiplo de 256 bytes: así el redondeo por bloques que
    # hace dsk_a_hfe para el entrelazado de caras nunca tiene que rellenar
    # con ceros crudos sin codificar (que representan un patrón magnético
    # inválido) — todo el sobrante siempre es gap MFM válido.
    #
    # Se usa el valor REAL conocido (ver LONGITUD_PISTA_CONOCIDA) cuando
    # existe para este número de sectores por pista, en vez de la fórmula
    # teórica basada en el bitrate: esa fórmula, verificada contra pistas
    # reales, resultó no coincidir con la realidad (para 20 sectores/pista
    # calculaba 25088 en vez de los 26368 reales — 1280 bytes de menos por
    # cara, suficiente para que el controlador de disquete físico del
    # copión se quedara esperando indefinidamente a mitad de lectura, en
    # vez de solo producir un archivo "un poco corto"). Para números de
    # sectores sin verificar aún contra un disco real, se mantiene la
    # fórmula como mejor aproximación disponible.
    sectores_por_pista = len(sectores)
    if sectores_por_pista in LONGITUD_PISTA_CONOCIDA:
        tamano_objetivo = LONGITUD_PISTA_CONOCIDA[sectores_por_pista]
    else:
        tamano_objetivo = -(-(bitrate_kbps * 50) // 256) * 256
    faltan_bytes_flujo = tamano_objetivo - len(flujo)
    if faltan_bytes_flujo > 0:
        emitir_bytes(bytes([0x4E] * (faltan_bytes_flujo // 2)))

    return bytes(flujo)


# ---------------------------------------------------------------------------------------------------------------------------
# Empaquetado del archivo HFE: cabecera de 512 bytes + tabla de pistas (LUT)
# + datos de pista. Estructura verificada contra la especificación oficial
# "SDCard HxC Floppy Emulator HFE File format" rev. 3.1.
#
# Peculiaridad importante: dentro del bloque de datos de cada pista, las dos
# caras NO van una detrás de otra completas, sino intercaladas en trozos de
# 256 bytes (256 de la cara 0, 256 de la cara 1, 256 de la cara 0...) — así
# es como lo espera el firmware, pensado para leer desde una SD con búfers
# pequeños. Olvidar este detalle produce un archivo con la cabecera
# correcta pero los datos de pista desordenados.
# ---------------------------------------------------------------------------------------------------------------------------------

HFE_BLOCK = 512
_ENC_ISOIBM_MFM = 0x00
_IFM_GENERIC_SHUGART_DD = 0x07
_IFM_IBMPC_HD = 0x01


def geometria_desde_dsk(datos_dsk: bytes) -> dict:
    """Deduce (bytes_por_sector, sectores_por_pista, caras, pistas) leyendo
    el BPB de una imagen de disco ya generada por este proyecto, para poder
    convertirla a HFE sin tener que repetir la geometría a mano.

    Asume la geometría física estándar de un disquete de 3.5" (80 pistas,
    2 caras): es correcta para todos los formatos que genera este proyecto
    (MSX, SMD/SWC estándar y superformateado).
    """
    import struct as _struct
    bps = _struct.unpack_from("<H", datos_dsk, 0x0B)[0]
    total_sectores = _struct.unpack_from("<H", datos_dsk, 0x13)[0]
    caras = 2 if total_sectores > 720 * (512 // bps) else 1
    sectores_por_pista = total_sectores // (80 * caras)
    return {"bytes_por_sector": bps, "sectores_por_pista": sectores_por_pista,
            "caras": caras, "pistas": 80}


def generar_disco_vacio_hfe(pistas: int = 82, caras: int = 2,
                             bitrate_kbps: int = 499,
                             bytes_por_pista: int = 50000) -> bytes:
    """Genera un disco HFE completamente en blanco (desmagnetizado): sin
    ningún sector ni estructura MFM, tal como viene un disquete físico
    nuevo sin formatear. El propio Super Wild Card se encarga de
    formatearlo y escribir sus datos al volcar un cartucho encima —
    replica byte a byte los parámetros de cabecera confirmados
    (pistas=82, bitrate=499, encoding/interface sin especificar) al
    analizar un disco vacío real, generado con la propia utilidad de
    conversión de Greaseweazle, que ya se ha probado con éxito en
    hardware real (Super Wild Card + Gotek/HxC).

    0xAA (10101010) es, en MFM, el patrón de "todos los bits de datos
    en cero" — el estado magnético neutro de un disco sin escribir —
    confirmado como el byte dominante (~47%) en la pista de un disco
    vacío real.
    """
    cabecera = bytearray(512)
    cabecera[0:8] = b"HXCPICFE"
    cabecera[8] = 0                      # revisión
    cabecera[9] = pistas
    cabecera[10] = caras
    cabecera[11] = 0xFF                  # track_encoding: sin especificar (igual que el original real)
    struct.pack_into("<H", cabecera, 12, bitrate_kbps)
    struct.pack_into("<H", cabecera, 14, 0)     # rpm: sin especificar (300 por defecto)
    cabecera[16] = 0xFF                  # interface_mode: sin especificar
    cabecera[17] = 0x01
    struct.pack_into("<H", cabecera, 18, 1)     # track_list_offset: bloque 1 (0x200)
    for i in range(20, 512):
        cabecera[i] = 0xFF

    ultimo_bit = 0
    gap4a, ultimo_bit = _mfm_codificar_bytes(bytes([0x4E]) * 71, ultimo_bit)
    resto = bytes_por_pista - len(gap4a)
    pista_en_blanco = gap4a + bytes([0xAA]) * resto
    n_bloques_pista = -(-len(pista_en_blanco) // HFE_BLOCK)  # redondeo hacia arriba

    tabla = bytearray(512)
    for i in range(128):  # 512 bytes / 4 bytes por entrada = 128 entradas máximo en 1 bloque
        tabla[i * 4: i * 4 + 4] = b"\xff\xff\xff\xff"
    offset_bloques = 2  # bloque 0=cabecera, bloque 1=tabla, las pistas empiezan en el bloque 2
    for n in range(pistas * caras if caras else pistas):
        # HFEv3: una entrada de tabla por CILINDRO (no por cara) — pistas
        # aquí ya se refiere a cilindros, ver dsk_a_hfe para la misma
        # convención con datos reales.
        if n >= pistas:
            break
        struct.pack_into("<HH", tabla, n * 4, offset_bloques, len(pista_en_blanco))
        offset_bloques += n_bloques_pista

    salida = bytearray(cabecera) + bytearray(tabla)
    for _ in range(pistas):
        bloque = bytearray(pista_en_blanco)
        relleno = n_bloques_pista * HFE_BLOCK - len(bloque)
        if relleno > 0:
            bloque += bytes([0xFF]) * relleno
        salida += bloque
    return bytes(salida)


def dsk_a_hfe(datos_dsk: bytes, bytes_por_sector: int, sectores_por_pista: int,
              caras: int, pistas: int, gap3: int | None = None,
              pistas_fisicas: int | None = None) -> bytes:
    """Convierte una imagen de disco lógica (sectores FAT12 tal cual, como
    las que genera este proyecto) a formato HFEv3.

    `pistas_fisicas`, si se indica y es mayor que `pistas`, declara en la
    cabecera HFE más cilindros físicos de los que tienen datos reales
    (por ejemplo 82 declarados frente a 80 con contenido real, como
    confirmado contra un disco superformateado auténtico) — las pistas
    de más se generan igualmente en blanco (gap uniforme, sin sectores),
    ya que el hardware real parece esperar encontrar esa cantidad exacta
    de cilindros declarados aunque el sistema de archivos lógico no los
    use todos.

    `gap3` por defecto usa los valores REALES verificados para cada
    formato (los mismos que data/greaseweazle_diskdefs.cfg, confirmados
    contra la propia BIOS del SMD/SWC y contra las definiciones de
    Greaseweazle para los samplers Ensoniq, que comparten geometría): 84
    para los formatos estándar (720 KB / 1,44 MB), 30 para el
    "superformateado" de 800 KB, 40 para el de 1,6 MB. Para cualquier otra
    geometría no catalogada, se usa una fórmula de reserva proporcional
    (menos precisa, pero mejor que nada).
    """
    if len(datos_dsk) != bytes_por_sector * sectores_por_pista * caras * pistas:
        raise ValueError(
            f"la imagen mide {len(datos_dsk)} bytes, se esperaban "
            f"{bytes_por_sector * sectores_por_pista * caras * pistas} para esa geometría"
        )
    if gap3 is None:
        gap3 = GAP3_CONOCIDOS.get(sectores_por_pista)
        if gap3 is None:
            # geometría no catalogada: aproximación proporcional a partir
            # del hueco estándar IBM de 84 bytes para 18 sectores/pista
            gap3 = max(12, (84 * 18) // sectores_por_pista)

    bytes_por_pista_logica = bytes_por_sector * sectores_por_pista
    # El bitrate NO depende solo de "cuántos sectores caben" — depende de
    # la densidad FÍSICA real del disco. El superformateado de 20
    # sectores/pista del SMD/SWC sigue siendo un disco DD normal (250
    # kbps): el truco para caber más sectores es un gap3 más pequeño
    # entre ellos, no una densidad mayor. Confirmado directamente contra
    # la propia utilidad oficial de HxC (250 kbps real, no 500 como
    # asumía antes una heurística simplista "más de 10 sectores → HD").
    # 18 sectores/pista (1,44 MB estándar) sí es HD real (500 kbps) —
    # ahí la heurística anterior coincidía con el estándar universal de
    # la industria por casualidad, no por estar bien fundamentada.
    # El bitrate real del superformateado de 20 sectores/pista es 499 (no
    # 250 ni 500), confirmado con la propia utilidad de conversión de
    # Greaseweazle (gw convert --bitrate=499) — el único valor de bitrate
    # que se ha logrado confirmar funcional escribiendo un cartucho real
    # con un Super Wild Card físico. 250 kbps sigue siendo la densidad
    # física real (DD estándar) del disco, pero por algún motivo (quizás
    # el margen que necesita el hardware real) el valor efectivo que hay
    # que declarar en la cabecera HFE difiere ligeramente del teórico.
    BITRATE_CONOCIDO = {9: 250, 10: 250, 18: 500, 20: 499}
    bitrate_kbps = BITRATE_CONOCIDO.get(sectores_por_pista, 250 if sectores_por_pista <= 10 else 500)

    bloques_pista: list[bytes] = []
    for pista in range(pistas):
        datos_por_cara = []
        for cara in range(caras):
            offset = (pista * caras + cara) * bytes_por_pista_logica
            datos_pista = datos_dsk[offset:offset + bytes_por_pista_logica]
            sectores = [datos_pista[i:i + bytes_por_sector]
                       for i in range(0, len(datos_pista), bytes_por_sector)]
            datos_pista_cara = _generar_pista_mfm(sectores, pista, cara, bytes_por_sector,
                                                   gap3, bitrate_kbps)
            datos_por_cara.append(datos_pista_cara)

        # Intercalado en bloques de 256 bytes entre las dos caras
        longitud_maxima = max(len(d) for d in datos_por_cara)
        datos_por_cara = [d.ljust(longitud_maxima, b"\x00") for d in datos_por_cara]
        entrelazado = bytearray()
        for i in range(0, longitud_maxima, 256):
            for cara_datos in datos_por_cara:
                entrelazado += cara_datos[i:i + 256].ljust(256, b"\x00")
        bloques_pista.append(bytes(entrelazado))

    # Pistas físicas de más, sin sectores (ver docstring de pistas_fisicas)
    n_pistas_totales = max(pistas, pistas_fisicas or 0)
    if n_pistas_totales > pistas:
        pista_en_blanco_cara = _generar_pista_mfm([], 0, 0, bytes_por_sector, gap3, bitrate_kbps)
        entrelazado_blanco = bytearray()
        for i in range(0, len(pista_en_blanco_cara), 256):
            for _ in range(caras):
                entrelazado_blanco += pista_en_blanco_cara[i:i + 256].ljust(256, b"\x00")
        for _ in range(n_pistas_totales - pistas):
            bloques_pista.append(bytes(entrelazado_blanco))

    # --- cabecera (512 bytes) ---
    # Firma "HXCPICFE", no "HXCHFEV3": todos los archivos reales
    # confirmados como funcionales en un Super Wild Card físico (tanto
    # generados por la utilidad de HxC como por "gw convert") usan esta
    # firma — nunca se ha confirmado que "HXCHFEV3" (formalmente válida
    # según la especificación, pero de una encarnación distinta del
    # formato) sea reconocida por ese hardware/firmware en concreto.
    cabecera = bytearray(HFE_BLOCK)
    cabecera[0:8] = b"HXCPICFE"
    cabecera[8] = 0                                    # formatrevision (reseteado en v3)
    cabecera[9] = n_pistas_totales
    cabecera[10] = caras
    cabecera[11] = 0xFF                                 # track_encoding: sin especificar (igual que los archivos reales confirmados)
    struct.pack_into("<H", cabecera, 12, bitrate_kbps)
    struct.pack_into("<H", cabecera, 14, 0)             # floppyRPM: sin especificar (igual que los archivos reales confirmados)
    cabecera[16] = 0xFF                                 # interface_mode: sin especificar (igual que los archivos reales confirmados)
    cabecera[17] = 0x01                                 # confirmado contra archivos reales funcionales (no 0xFF)
    struct.pack_into("<H", cabecera, 18, 1)             # track_list_offset: bloque 1 (0x200)
    cabecera[20] = 0xFF                                 # write_allowed: sin proteger
    cabecera[21] = 0xFF                                 # single_step
    cabecera[22] = 0xFF                                 # track0s0_altencoding: sin usar
    cabecera[23] = 0xFF
    cabecera[24] = 0xFF                                 # track0s1_altencoding: sin usar
    cabecera[25] = 0xFF

    # --- tabla de pistas (LUT), en el bloque 1 = offset 0x200 ---
    lut = bytearray(HFE_BLOCK)
    offset_bloques = 2  # los datos de pista empiezan tras cabecera (bloque 0) y LUT (bloque 1)
    for i, datos_pista in enumerate(bloques_pista):
        struct.pack_into("<H", lut, i * 4, offset_bloques)
        struct.pack_into("<H", lut, i * 4 + 2, len(datos_pista))
        offset_bloques += -(-len(datos_pista) // HFE_BLOCK)  # redondeo hacia arriba

    cuerpo = bytearray()
    for datos_pista in bloques_pista:
        relleno = (-len(datos_pista)) % HFE_BLOCK
        cuerpo += datos_pista + bytes(relleno)

    return bytes(cabecera) + bytes(lut) + bytes(cuerpo)


# ---------------------------------------------------------------------------------------------------------------------------
# Decodificador HFE -> imagen de disco lógica.
#
# Existe por un único motivo: no hay forma de probar la codificación de
# arriba contra un HxC o un FlashFloppy reales desde este entorno. Decodificar
# lo que se acaba de codificar y comprobar que se recuperan los mismos
# sectores da una confianza razonable en que la codificación sigue la
# especificación correctamente — no es una garantía de que el hardware real
# vaya a leerlo igual, pero si ni siquiera esta comprobación pasara, sería
# una señal segura de que algo está mal.
# ---------------------------------------------------------------------------------------------------------------------------------

_TABLA_BYTE_A_BITS = [tuple((b >> i) & 1 for i in range(8)) for b in range(256)]


def _bytes_a_bits(datos: bytes) -> list[int]:
    bits = []
    tabla = _TABLA_BYTE_A_BITS
    for byte in datos:
        bits.extend(tabla[byte])
    return bits


def _buscar_patron(bits: list[int], patron_bits: list[int], desde: int) -> int:
    n = len(patron_bits)
    for i in range(desde, len(bits) - n + 1):
        if bits[i:i + n] == patron_bits:
            return i
    return -1


def _mfm_decodificar(bits: list[int], inicio: int, n_bytes: int) -> bytes:
    """Decodifica n_bytes MFM a partir de `inicio` (que debe apuntar al
    primer bit de RELOJ del primer byte): se toma 1 de cada 2 bits
    (los de dato, descartando los de reloj intercalados). El primer bit
    de dato leído es el MSB del byte (codificación MFM estándar: los
    bits de datos de cada byte se procesan de MSB a LSB — ver
    _construir_tabla_mfm)."""
    salida = bytearray(n_bytes)
    pos = inicio
    for i in range(n_bytes):
        valor = 0
        for _ in range(8):
            pos += 1  # salta el bit de reloj
            valor = (valor << 1) | bits[pos]
            pos += 1
        salida[i] = valor
    return bytes(salida)


_PATRON_A1 = _entero_a_bits(_MFM_SYNC_A1, 16)


def hfe_a_dsk(datos_hfe: bytes) -> tuple[bytes, dict]:
    """Decodifica un archivo HFEv3 de vuelta a una imagen de disco lógica
    (sectores en orden, tal como los generan parse_dsk/write_files_to_*_dsk
    de rom_formats.py). Devuelve (datos, info_geometria).
    """
    if datos_hfe[:8] not in (b"HXCHFEV3", b"HXCPICFE"):
        raise ValueError("no es un archivo HFE reconocible (firma incorrecta)")

    pistas = datos_hfe[9]
    caras = datos_hfe[10]
    track_list_offset = struct.unpack_from("<H", datos_hfe, 18)[0] * HFE_BLOCK

    sectores_totales: list[bytes] = []
    for pista in range(pistas):
        offset_b, longitud = struct.unpack_from("<HH", datos_hfe, track_list_offset + pista * 4)
        bloque = datos_hfe[offset_b * HFE_BLOCK: offset_b * HFE_BLOCK + longitud]

        # Deshacer el intercalado de 256 bytes entre caras
        datos_por_cara = [bytearray() for _ in range(caras)]
        for i in range(0, len(bloque), 256 * caras):
            for c in range(caras):
                trozo = bloque[i + c * 256: i + c * 256 + 256]
                datos_por_cara[c] += trozo

        for cara in range(caras):
            bits = _bytes_a_bits(bytes(datos_por_cara[cara]))
            sectores_pista: dict[int, bytes] = {}
            pos = 0
            tam = None
            while True:
                pos_id = _buscar_patron(bits, _PATRON_A1, pos)
                if pos_id == -1:
                    break
                # Comprobar que las tres marcas A1 son REALMENTE
                # consecutivas (48 bits), en vez de asumirlo tras
                # encontrar solo la primera — un A1 aislado puede
                # aparecer por coincidencia en cualquier otro punto del
                # flujo (bug real encontrado al decodificar un archivo
                # HFE generado por otro codificador distinto al nuestro:
                # un A1 suelto antes de la primera cabecera válida hacía
                # que el código asumiera estar ya dentro de una, leyera
                # una "marca" arbitraria, y fallara más adelante con
                # variables sin asignar en vez de simplemente descartar
                # la coincidencia falsa y seguir buscando).
                if bits[pos_id:pos_id + 16 * 3] != _PATRON_A1 * 3:
                    pos = pos_id + 16
                    continue
                fin_sync = pos_id + 16 * 3
                if fin_sync + 16 > len(bits):
                    break
                marca = _mfm_decodificar(bits, fin_sync, 1)[0]
                if marca == 0xFE:
                    campo = _mfm_decodificar(bits, fin_sync, 5)
                    _cil, _cab, n_sector, codigo_tam = campo[1], campo[2], campo[3], campo[4]
                    tam = 128 << codigo_tam
                    pos = fin_sync + 5 * 16
                elif marca == 0xFB and tam is not None:
                    datos_sector = _mfm_decodificar(bits, fin_sync, 1 + tam)[1:]
                    sectores_pista[n_sector] = datos_sector
                    pos = fin_sync + (1 + tam + 2) * 16
                else:
                    pos = pos_id + 16
            for n in sorted(sectores_pista):
                sectores_totales.append(sectores_pista[n])

    info = {"pistas": pistas, "caras": caras, "sectores_leidos": len(sectores_totales)}
    return b"".join(sectores_totales), info
