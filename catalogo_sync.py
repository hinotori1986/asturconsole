"""Volcado del catálogo de parches «de fábrica» a la carpeta de trabajo.

La aplicación lleva dentro (en data/semillas/) una copia del catálogo de
parches conocidos del autor: mis-parches-snes.json, y opcionalmente
mis-parches-genesis.json. Este módulo la deja en
    ~/ASTURCONSOLE/Parches/mis-parches-{sistema}.json
que es el archivo que de verdad lee (y al que añade entradas) la
aplicación a través de parches_conocidos.UserPatchCatalog.

Reglas, comprobadas en cada arranque, ANTES de que nadie consulte el
catálogo:

  1. PRIMERA INSTALACIÓN (el archivo no existe): se copia tal cual.
  2. NUEVA VERSIÓN (la versión de la app o el contenido de la semilla
     difieren de lo anotado en la última sincronización): se hace una
     COPIA del archivo actual en  Parches/copias anteriores/  y se
     sobrescribe con el de la nueva versión.
  3. MISMA VERSIÓN y archivo intacto: no se toca nada — las entradas que
     el usuario guarde desde la app entre dos actualizaciones se conservan.
  4. Archivo borrado o ilegible con la misma versión: se restaura (el
     ilegible se guarda antes como copia).

Dos cautelas para que ninguna actualización pierda trabajo:

  * Al sobrescribir NO se descartan las entradas que el usuario tenga y la
    semilla no (CRC32 que solo existen en su archivo): se conservan
    añadidas al final. Solo pierden su valor las entradas con el MISMO
    CRC32 en las dos partes, donde manda la semilla (y el valor anterior
    queda en la copia).
  * La copia solo se crea si el contenido realmente cambia, y se guardan
    como máximo MAX_COPIAS por sistema (las más recientes).

Nada de aquí lanza excepciones hacia fuera: un fallo de permisos o un
JSON corrupto se anotan en el informe y la aplicación arranca igual.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime

# sistema -> nombre del archivo (el mismo en la semilla y en destino)
ARCHIVOS = {
    "snes": "mis-parches-snes.json",
    "genesis": "mis-parches-genesis.json",
}

CARPETA_PARCHES = "Parches"
CARPETA_COPIAS = "copias anteriores"
MARCADOR = ".sincronizacion.json"
MAX_COPIAS = 20


@dataclass
class Resultado:
    sistema: str
    accion: str                    # "primera_vez" | "actualizado" | "restaurado" | "sin_cambios" | "sin_semilla" | "error"
    entradas_semilla: int = 0
    entradas_propias_conservadas: int = 0
    entradas_reemplazadas: int = 0  # mismo CRC, contenido distinto
    copia: str | None = None
    detalle: str = ""

    def resumen(self) -> str:
        if self.accion == "primera_vez":
            return (f"{self.sistema.upper()}: catálogo de parches instalado "
                    f"({self.entradas_semilla} entradas).")
        if self.accion in ("actualizado", "restaurado"):
            txt = (f"{self.sistema.upper()}: catálogo de parches actualizado "
                   f"({self.entradas_semilla} entradas")
            if self.entradas_propias_conservadas:
                txt += f", {self.entradas_propias_conservadas} propias conservadas"
            txt += ")."
            if self.copia:
                txt += f" Copia anterior: {self.copia}"
            return txt
        if self.accion == "error":
            return f"{self.sistema.upper()}: {self.detalle}"
        return ""


# --------------------------------------------------------------- rutas

def _base_app() -> str:
    meipass = getattr(sys, "_MEIPASS", None)
    return meipass or os.path.dirname(os.path.abspath(__file__))


def ruta_semilla(sistema: str, base_app: str | None = None) -> str:
    return os.path.join(base_app or _base_app(), "data", "semillas", ARCHIVOS[sistema])


def carpeta_parches(base_trabajo: str) -> str:
    return os.path.join(base_trabajo, CARPETA_PARCHES)


def ruta_destino(sistema: str, base_trabajo: str) -> str:
    return os.path.join(carpeta_parches(base_trabajo), ARCHIVOS[sistema])


# ------------------------------------------------------------- utilidades

def _sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def _leer_json_dict(datos: bytes) -> dict | None:
    """El contenido como dict {crc: entrada}, o None si no es un catálogo válido."""
    try:
        obj = json.loads(datos.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _escribir_atomico(ruta: str, datos: bytes):
    """Escribe en un temporal del mismo directorio y lo renombra: nunca
    queda un archivo a medias si se corta la luz o el proceso."""
    carpeta = os.path.dirname(ruta)
    os.makedirs(carpeta, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=carpeta, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(datos)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _leer_marcador(base_trabajo: str) -> dict:
    ruta = os.path.join(carpeta_parches(base_trabajo), MARCADOR)
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        return obj if isinstance(obj, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _escribir_marcador(base_trabajo: str, marcador: dict):
    _escribir_atomico(
        os.path.join(carpeta_parches(base_trabajo), MARCADOR),
        json.dumps(marcador, indent=2, ensure_ascii=False).encode("utf-8"))


def _hacer_copia(destino: str, sistema: str, version_anterior: str,
                 base_trabajo: str) -> str:
    carpeta = os.path.join(carpeta_parches(base_trabajo), CARPETA_COPIAS)
    os.makedirs(carpeta, exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d-%H%M%S")
    ver = re.sub(r"[^0-9A-Za-z._-]", "_", version_anterior or "desconocida")
    stem = os.path.splitext(ARCHIVOS[sistema])[0]
    ruta = os.path.join(carpeta, f"{stem}_v{ver}_{sello}.json")
    n = 1
    while os.path.exists(ruta):          # dos copias en el mismo segundo
        n += 1
        ruta = os.path.join(carpeta, f"{stem}_v{ver}_{sello}_{n}.json")
    shutil.copy2(destino, ruta)
    _limitar_copias(carpeta, stem)
    return ruta


def _limitar_copias(carpeta: str, stem: str):
    try:
        copias = sorted(
            (f for f in os.listdir(carpeta)
             if f.startswith(stem + "_v") and f.endswith(".json")),
            key=lambda f: os.path.getmtime(os.path.join(carpeta, f)))
        for viejo in copias[:-MAX_COPIAS]:
            os.remove(os.path.join(carpeta, viejo))
    except OSError:
        pass


def _fusionar(semilla: dict, actual: dict | None) -> tuple[dict, int, int]:
    """Semilla + entradas propias del usuario. Devuelve (resultado,
    n_propias_conservadas, n_reemplazadas)."""
    resultado = dict(semilla)
    propias = reemplazadas = 0
    for crc, entrada in (actual or {}).items():
        if crc not in semilla:
            resultado[crc] = entrada
            propias += 1
        elif entrada != semilla[crc]:
            reemplazadas += 1
    return resultado, propias, reemplazadas


# ---------------------------------------------------------------- núcleo

def sincronizar_sistema(sistema: str, version: str, base_trabajo: str,
                        base_app: str | None = None) -> Resultado:
    res = Resultado(sistema=sistema, accion="sin_cambios")
    try:
        ruta_sem = ruta_semilla(sistema, base_app)
        if not os.path.isfile(ruta_sem):
            res.accion = "sin_semilla"
            return res
        with open(ruta_sem, "rb") as fh:
            bytes_semilla = fh.read()
        semilla = _leer_json_dict(bytes_semilla)
        if semilla is None:
            res.accion, res.detalle = "error", "la semilla incluida en la aplicación no es un JSON válido"
            return res
        res.entradas_semilla = len(semilla)
        hash_semilla = _sha256(bytes_semilla)

        destino = ruta_destino(sistema, base_trabajo)
        marcador = _leer_marcador(base_trabajo)
        anotado = marcador.get(sistema, {}) if isinstance(marcador.get(sistema), dict) else {}
        misma_version = (anotado.get("version") == version
                         and anotado.get("sha256") == hash_semilla)

        bytes_actual = None
        actual = None
        if os.path.isfile(destino):
            with open(destino, "rb") as fh:
                bytes_actual = fh.read()
            actual = _leer_json_dict(bytes_actual)

        # 3. todo al día y archivo sano: no tocar
        if bytes_actual is not None and actual is not None and misma_version:
            return res

        # decidir la acción
        if bytes_actual is None:
            res.accion = "restaurado" if anotado else "primera_vez"
        else:
            res.accion = "actualizado" if actual is not None else "restaurado"

        # sin archivo previo: copia directa, byte a byte (formato del autor)
        if bytes_actual is None:
            _escribir_atomico(destino, bytes_semilla)
        else:
            fusion, res.entradas_propias_conservadas, res.entradas_reemplazadas = \
                _fusionar(semilla, actual)
            if fusion == semilla:
                nuevo = bytes_semilla        # nada propio que conservar
            else:
                nuevo = json.dumps(fusion, ensure_ascii=False, indent=2).encode("utf-8")
            # copia de seguridad solo si el contenido va a cambiar de verdad
            if nuevo != bytes_actual:
                res.copia = _hacer_copia(destino, sistema,
                                         str(anotado.get("version", "")), base_trabajo)
                _escribir_atomico(destino, nuevo)
            else:
                res.accion = "sin_cambios"

        marcador[sistema] = {"version": version, "sha256": hash_semilla,
                             "fecha": datetime.now().isoformat(timespec="seconds")}
        _escribir_marcador(base_trabajo, marcador)
    except OSError as e:
        res.accion, res.detalle = "error", f"no se pudo sincronizar el catálogo ({e})"
    return res


def sincronizar(version: str, base_trabajo: str | None = None,
                base_app: str | None = None) -> list[Resultado]:
    """Sincroniza todos los sistemas que tengan semilla. Pensado para
    llamarse una vez al arrancar, justo tras crear el espacio de trabajo."""
    if base_trabajo is None:
        import workspace as ws
        base_trabajo = ws.base_dir()
    resultados = [sincronizar_sistema(s, version, base_trabajo, base_app)
                  for s in ARCHIVOS]
    # si el catálogo de usuario ya se había cargado en memoria, que lo relea
    try:
        import parches_conocidos as pc
        pc.SNES_USER_DB._indice = None
        pc.GENESIS_USER_DB._indice = None
    except Exception:  # noqa: BLE001
        pass
    return [r for r in resultados if r.accion != "sin_semilla"]
