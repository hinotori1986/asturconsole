"""Catálogo de parches «de fábrica» en la carpeta de trabajo, SIN pisar el del usuario.

Dos archivos en  ~/ASTURCONSOLE/Parches/  para que nadie se pise:

  * mis-parches-{sistema}.json            -> el del USUARIO.
        Lo escribe la aplicación solo cuando el usuario marca o desmarca
        casillas (cada marca lleva  "usuario": true).  Esta rutina NUNCA lo
        modifica, lo mueve ni lo borra: el usuario puede estar probando
        cosas sin conexión y no se pierde nada, pase lo que pase con las
        versiones de la aplicación.

  * parches-{sistema}-asturconsole.json   -> el de la APLICACIÓN.
        Lo genera esta rutina en cada arranque a partir de:
          1. el catálogo de fábrica incluido en la aplicación
             (data/semillas/mis-parches-{sistema}.json), y
          2. las entradas del archivo del usuario que ese catálogo NO tenga
             (juegos nuevos probados por el usuario): se añaden.
        Si un juego está en las dos partes con datos distintos, mandan los
        parámetros de la aplicación (están revisados con trazas reales);
        la única excepción son las MARCAS A MANO del usuario (las que
        llevan "usuario": true), que no se copian aquí y siguen ganando en
        tiempo de ejecución: el usuario siempre puede marcar o desmarcar
        casillas y lo suyo se respeta (ver parches_conocidos.buscar_destino).

Es un archivo derivado: se puede borrar o regenerar sin perder nada, y por
eso no hace falta guardar copias de versiones anteriores. Solo se vuelve a
escribir si su contenido cambia. Nada de aquí lanza excepciones hacia
fuera: un fallo de permisos o un JSON corrupto se anotan en el informe y
la aplicación arranca igual.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass

# sistema -> nombre del archivo del USUARIO (el mismo que usa la semilla)
ARCHIVOS = {
    "snes": "mis-parches-snes.json",
    "genesis": "mis-parches-genesis.json",
}
# sistema -> nombre del archivo GENERADO por la aplicación
ARCHIVOS_APP = {
    "snes": "parches-snes-asturconsole.json",
    "genesis": "parches-genesis-asturconsole.json",
}

CARPETA_PARCHES = "Parches"


@dataclass
class Resultado:
    sistema: str
    accion: str                    # "primera_vez" | "actualizado" | "sin_cambios" | "sin_semilla" | "error"
    entradas_semilla: int = 0
    entradas_propias_conservadas: int = 0   # del usuario, añadidas al de la app
    entradas_reemplazadas: int = 0  # mismo CRC con datos distintos: manda la app
    entradas_marcadas: int = 0      # marcas a mano del usuario (se respetan)
    detalle: str = ""

    def resumen(self) -> str:
        if self.accion in ("primera_vez", "actualizado"):
            txt = (f"{self.sistema.upper()}: catálogo de parches de la aplicación "
                   f"{'instalado' if self.accion == 'primera_vez' else 'actualizado'} "
                   f"({self.entradas_semilla} de fábrica")
            if self.entradas_propias_conservadas:
                txt += f" + {self.entradas_propias_conservadas} tuyas añadidas"
            txt += ")."
            return txt
        if self.accion == "error":
            return f"{self.sistema.upper()}: {self.detalle}"
        return self.detalle


# --------------------------------------------------------------- rutas

def _base_app() -> str:
    meipass = getattr(sys, "_MEIPASS", None)
    return meipass or os.path.dirname(os.path.abspath(__file__))


def ruta_semilla(sistema: str, base_app: str | None = None) -> str:
    return os.path.join(base_app or _base_app(), "data", "semillas", ARCHIVOS[sistema])


def carpeta_parches(base_trabajo: str) -> str:
    return os.path.join(base_trabajo, CARPETA_PARCHES)


def ruta_usuario(sistema: str, base_trabajo: str) -> str:
    return os.path.join(carpeta_parches(base_trabajo), ARCHIVOS[sistema])


def ruta_app(sistema: str, base_trabajo: str) -> str:
    return os.path.join(carpeta_parches(base_trabajo), ARCHIVOS_APP[sistema])


# ------------------------------------------------------------- utilidades

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


def _tarjetas(entrada: dict) -> dict:
    d = entrada.get("destinos")
    return d if isinstance(d, dict) else {}


def _entrada_marcada(entrada: dict) -> bool:
    """¿Esta entrada del archivo del usuario lleva alguna marca a mano?"""
    if entrada.get("usuario") is True:
        return True
    return any(isinstance(c, dict) and c.get("usuario") is True
               for c in _tarjetas(entrada).values())


def _sin_marcas(entrada: dict) -> dict | None:
    """La parte de la entrada que NO es una marca a mano del usuario (la que
    puede copiarse al catálogo de la aplicación), o None si no queda nada."""
    tarjetas = _tarjetas(entrada)
    if not tarjetas:
        return None if entrada.get("usuario") is True else dict(entrada)
    libres = {d: dict(c) for d, c in tarjetas.items()
              if isinstance(c, dict) and c.get("usuario") is not True}
    if not libres:
        return None
    nueva = dict(entrada)
    nueva.pop("usuario", None)
    nueva["destinos"] = libres
    # los campos planos son la unión de las fichas: recalcularla con las que quedan
    for k in ("crack", "pal", "slowrom", "checksum"):
        nueva[k] = any(c.get(k) for c in libres.values())
    estados = [c.get("estado") for c in libres.values()]
    for cand in ("necesita_parche", "incompatible", "compatible"):
        if cand in estados:
            nueva["estado"] = cand
            break
    else:
        nueva["estado"] = "desconocido"
    return nueva


def fusionar(semilla: dict, usuario: dict | None) -> tuple[dict, int, int, int]:
    """Catálogo de la aplicación = fábrica + lo del usuario que la fábrica no
    tiene. Devuelve (resultado, añadidas, en_conflicto, marcadas).

    * CRC solo en el archivo del usuario  -> se añade (salvo sus marcas a
      mano, que no se duplican aquí: ya mandan desde su propio archivo).
    * CRC en los dos con datos distintos  -> manda la fábrica.
    """
    resultado = dict(semilla)
    anadidas = conflicto = marcadas = 0
    for crc, entrada in (usuario or {}).items():
        if not isinstance(entrada, dict):
            continue
        crc = str(crc).lower()
        marcada = _entrada_marcada(entrada)
        if marcada:
            marcadas += 1
        if crc in semilla:
            if entrada != semilla[crc] and not marcada:
                conflicto += 1          # sin marca a mano: manda la aplicación
            continue
        libre = _sin_marcas(entrada)
        if libre is not None:
            resultado[crc] = libre
            anadidas += 1
    return resultado, anadidas, conflicto, marcadas


# ---------------------------------------------------------------- núcleo

def sincronizar_sistema(sistema: str, version: str, base_trabajo: str,
                        base_app: str | None = None) -> Resultado:
    """`version` ya no decide nada (el archivo de la aplicación se compara
    por contenido); se conserva en la firma por compatibilidad."""
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

        # Archivo del usuario: SOLO se lee. Si está corrupto se ignora
        # (y no se toca: que lo arregle o lo recupere él).
        usuario = None
        ruta_usr = ruta_usuario(sistema, base_trabajo)
        if os.path.isfile(ruta_usr):
            with open(ruta_usr, "rb") as fh:
                usuario = _leer_json_dict(fh.read())
            if usuario is None:
                res.detalle = (f"{sistema.upper()}: tu archivo de parches no se pudo leer; "
                               "se ha ignorado (no se ha modificado)")

        fusion, res.entradas_propias_conservadas, res.entradas_reemplazadas, \
            res.entradas_marcadas = fusionar(semilla, usuario)
        # sin nada que añadir: byte a byte como viene en la aplicación
        nuevo = bytes_semilla if fusion == semilla else \
            json.dumps(fusion, ensure_ascii=False, indent=2).encode("utf-8")

        destino = ruta_app(sistema, base_trabajo)
        actual = None
        if os.path.isfile(destino):
            with open(destino, "rb") as fh:
                actual = fh.read()
        if actual == nuevo:
            return res
        res.accion = "primera_vez" if actual is None else "actualizado"
        _escribir_atomico(destino, nuevo)
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
    # si los catálogos ya se habían cargado en memoria, que se relean
    try:
        import parches_conocidos as pc
        for db in (pc.SNES_USER_DB, pc.GENESIS_USER_DB,
                   pc.SNES_APP_DB, pc.GENESIS_APP_DB):
            db._indice = None
    except Exception:  # noqa: BLE001
        pass
    return [r for r in resultados
            if r.accion not in ("sin_semilla", "sin_cambios") or r.detalle]
