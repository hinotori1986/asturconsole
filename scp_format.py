"""Parser mínimo del formato SCP (SuperCard Pro), siguiendo al detalle la
especificación oficial v2.5 (Jim Drew, cbmstuff.com) — usado aquí solo
como herramienta de investigación para medir directamente, contra
volcados de flujo magnético reales, los parámetros exactos (duración de
pista, huecos entre sectores) que necesita nuestro propio codificador
HFE, en vez de seguir dependiendo de ingeniería inversa sobre el
codificador de un tercero.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass
class RevolucionSCP:
    duracion_25ns: int   # tiempo de índice a índice, en unidades de 25ns
    n_bitcells: int      # cuántas transiciones de flujo hay
    duraciones: list      # lista de duraciones (en unidades de 25ns) entre transiciones consecutivas


def leer_cabecera(datos: bytes) -> dict:
    assert datos[0:3] == b"SCP", f"firma inválida: {datos[0:3]!r}"
    return dict(
        version=datos[3], disk_type=datos[4], n_revs=datos[5],
        start_track=datos[6], end_track=datos[7], flags=datos[8],
        encoding_bits=datos[9], heads=datos[10], resolution=datos[11],
        checksum=struct.unpack_from("<I", datos, 0x0C)[0],
    )


def leer_pista(datos: bytes, n_pista: int) -> list[RevolucionSCP] | None:
    """Lee todas las revoluciones capturadas para la pista SCP n_pista
    (0-167; para un disco de doble cara, pista_fisica = n_pista//2,
    cara = n_pista%2). Devuelve None si esa pista no se capturó."""
    offset_tabla = 0x10 + n_pista * 4
    offset_tdh = struct.unpack_from("<I", datos, offset_tabla)[0]
    if offset_tdh == 0:
        return None
    assert datos[offset_tdh:offset_tdh + 3] == b"TRK", \
        f"TDH inválido en pista {n_pista}: {datos[offset_tdh:offset_tdh+3]!r}"
    cabecera = leer_cabecera(datos)
    revoluciones = []
    for r in range(cabecera["n_revs"]):
        base = offset_tdh + 4 + r * 12
        duracion, longitud, offset_flujo = struct.unpack_from("<III", datos, base)
        inicio_flujo = offset_tdh + offset_flujo
        crudo = datos[inicio_flujo: inicio_flujo + longitud * 2]
        duraciones = []
        acumulado = 0
        for i in range(0, len(crudo), 2):
            valor = struct.unpack_from(">H", crudo, i)[0]  # big-endian, según especificación
            if valor == 0:
                acumulado += 65536
                continue
            duraciones.append(acumulado + valor)
            acumulado = 0
        revoluciones.append(RevolucionSCP(duracion, longitud, duraciones))
    return revoluciones


# --- Herramientas de decodificación MFM directamente desde flujo físico ---
# (para investigación: no hay "bytes" agrupados aquí, así que el patrón de
# sincronismo se usa en su forma temporal directa MSB, distinta de la
# usada en hfe_format.py para archivos HFE ya agrupados en bytes)

_PATRON_A1_FLUJO = [int(b) for b in format(0x4489, "016b")]
T_MEDIA_CELDA_25NS = 1000 / 25  # media celda a 2000ns de cell time (250 kbps de cabecera, superformato SMD/SWC)


def flujo_a_bits(duraciones: list[int], t_media_celda: float = T_MEDIA_CELDA_25NS) -> list[int]:
    bits = []
    for d in duraciones:
        n = max(1, round(d / t_media_celda))
        bits.extend([0] * (n - 1))
        bits.append(1)
    return bits


def _buscar(bits: list[int], patron: list[int], desde: int = 0) -> int:
    n = len(patron)
    for i in range(desde, len(bits) - n + 1):
        if bits[i:i + n] == patron:
            return i
    return -1


def _mfm_decodificar_directo(bits: list[int], inicio: int, n_bytes: int) -> bytes:
    salida = bytearray(n_bytes)
    pos = inicio
    for i in range(n_bytes):
        valor = 0
        for _ in range(8):
            pos += 1
            valor = (valor << 1) | bits[pos]
            pos += 1
        salida[i] = valor
    return bytes(salida)


def decodificar_pista_a_sectores(bits: list[int]) -> dict[int, bytes]:
    """A partir del bitstream de celda de una pista (ver flujo_a_bits),
    localiza todas las marcas de sincronismo reales (verificando que las
    3 sean consecutivas) y devuelve {numero_sector: datos_512_bytes}."""
    sectores: dict[int, bytes] = {}
    pos = 0
    tam = None
    while True:
        p = _buscar(bits, _PATRON_A1_FLUJO, pos)
        if p == -1:
            break
        if bits[p:p + 48] != _PATRON_A1_FLUJO * 3:
            pos = p + 1
            continue
        fin_sync = p + 48
        if fin_sync + 8 > len(bits):
            break
        marca = _mfm_decodificar_directo(bits, fin_sync, 1)
        if marca == b"\xfe":
            campo = _mfm_decodificar_directo(bits, fin_sync, 5)
            tam = 128 << campo[4]
            n_sector = campo[3]
            pos = fin_sync + 5 * 16
        elif marca == b"\xfb" and tam is not None:
            datos = _mfm_decodificar_directo(bits, fin_sync, 1 + tam)[1:]
            sectores[n_sector] = datos
            pos = fin_sync + (1 + tam + 2) * 16
        else:
            pos = p + 1
    return sectores


def leer_pista_logica(datos_scp: bytes, n_pista: int) -> dict[int, bytes] | None:
    """Combina leer_pista + flujo_a_bits + decodificar_pista_a_sectores para
    la 1a revolución capturada de la pista SCP n_pista."""
    revs = leer_pista(datos_scp, n_pista)
    if not revs:
        return None
    bits = flujo_a_bits(revs[0].duraciones)
    return decodificar_pista_a_sectores(bits)

