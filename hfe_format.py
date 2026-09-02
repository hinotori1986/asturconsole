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
    20: 40,   # 1,6 MB (superformateado SMD/SWC)
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

def _construir_tabla_mfm() -> list:
    tabla = [None] * 512  # índice: bit_anterior * 256 + byte
    for bit_anterior in (0, 1):
        for byte in range(256):
            anterior = bit_anterior
            valor16 = 0
            for i in range(7, -1, -1):
                bit = (byte >> i) & 1
                reloj = 0 if (anterior or bit) else 1
                valor16 = (valor16 << 2) | (reloj << 1) | bit
                anterior = bit
            tabla[bit_anterior * 256 + byte] = (bytes(((valor16 >> 8) & 0xFF, valor16 & 0xFF)), anterior)
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
        # Siempre caen alineados a byte: cada emisión anterior añade un
        # número par de bytes (2 por cada byte de entrada), así que el
        # total acumulado hasta aquí es siempre múltiplo de 8 bits.
        nonlocal ultimo_bit
        flujo.extend(struct.pack(">H", patron))
        ultimo_bit = patron & 1

    # GAP4A + IAM (marca de índice de pista)
    emitir_bytes(bytes([0x4E] * 80))
    emitir_bytes(bytes([0x00] * 12))
    for _ in range(3):
        emitir_sync(_MFM_SYNC_C2)
    emitir_bytes(bytes([0xFC]))
    # GAP1
    emitir_bytes(bytes([0x4E] * 50))

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
        # GAP2
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
        emitir_bytes(bytes([0x4E] * gap3))

    # GAP4B: relleno hasta completar la pista con el tamaño EXACTO de una
    # revolución física completa (ver docstring), redondeado hacia arriba
    # al siguiente múltiplo de 256 bytes: así el redondeo por bloques que
    # hace dsk_a_hfe para el entrelazado de caras nunca tiene que rellenar
    # con ceros crudos sin codificar (que representan un patrón magnético
    # inválido) — todo el sobrante siempre es gap MFM válido.
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


def dsk_a_hfe(datos_dsk: bytes, bytes_por_sector: int, sectores_por_pista: int,
              caras: int, pistas: int, gap3: int | None = None) -> bytes:
    """Convierte una imagen de disco lógica (sectores FAT12 tal cual, como
    las que genera este proyecto) a formato HFEv3.

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
    bitrate_kbps = 250 if sectores_por_pista <= 10 else 500

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

    # --- cabecera (512 bytes) ---
    cabecera = bytearray(HFE_BLOCK)
    cabecera[0:8] = b"HXCHFEV3"
    cabecera[8] = 0                                    # formatrevision (reseteado en v3)
    cabecera[9] = pistas
    cabecera[10] = caras
    cabecera[11] = _ENC_ISOIBM_MFM
    struct.pack_into("<H", cabecera, 12, bitrate_kbps)
    struct.pack_into("<H", cabecera, 14, 300)           # floppyRPM, no usado por el emulador
    modo_interfaz = _IFM_IBMPC_HD if bitrate_kbps == 500 else _IFM_GENERIC_SHUGART_DD
    cabecera[16] = modo_interfaz
    cabecera[17] = 0xFF                                 # dnu / reservado
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

_TABLA_BYTE_A_BITS = [tuple((b >> i) & 1 for i in range(7, -1, -1)) for b in range(256)]


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
    (los de dato, descartando los de reloj intercalados)."""
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
            while True:
                pos_id = _buscar_patron(bits, _PATRON_A1, pos)
                if pos_id == -1:
                    break
                # Tres marcas A1 consecutivas (48 bits) antes del byte FE/FB
                fin_sync = pos_id + 16 * 3
                if fin_sync + 16 > len(bits):
                    break
                marca = _mfm_decodificar(bits, fin_sync, 1)[0]
                if marca == 0xFE:
                    campo = _mfm_decodificar(bits, fin_sync, 5)
                    _cil, _cab, n_sector, codigo_tam = campo[1], campo[2], campo[3], campo[4]
                    tam = 128 << codigo_tam
                    pos = fin_sync + 5 * 16
                elif marca == 0xFB:
                    datos_sector = _mfm_decodificar(bits, fin_sync, 1 + tam)[1:]
                    sectores_pista[n_sector] = datos_sector
                    pos = fin_sync + (1 + tam + 2) * 16
                else:
                    pos = pos_id + 16
            for n in sorted(sectores_pista):
                sectores_totales.append(sectores_pista[n])

    info = {"pistas": pistas, "caras": caras, "sectores_leidos": len(sectores_totales)}
    return b"".join(sectores_totales), info
