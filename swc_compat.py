"""Lista de compatibilidad de juegos con la Super Wild Card.

Los datos proceden del documento "A Super Wild Card compatibility list"
(versión 1.29, 3 de noviembre de 2008) de dbjh, autor de uCON64, con ayuda
de CL (de NSRT) y The Dumper. Se probó sobre una Super Wild Card 2.8cc de
32 Mbit PAL con uCON64 2.0.0.

Sirve para avisar por adelantado de qué juegos necesitan alguna corrección
antes de transferirlos al copiador, en vez de descubrirlo cuando la partida
no arranca.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
from dataclasses import dataclass

# Significado de cada código, tal y como los define el documento original
CODIGOS = {
    0: ("Funciona sin modificaciones", "ok"),
    1: ("Necesita crack de protección anticopia (opción -k de uCON64)", "accion"),
    2: ("Necesita corrección NTSC/PAL (opción -f de uCON64)", "accion"),
    3: ("Necesita corregir la cabecera del copiador", "accion"),
    4: ("Parece funcionar, pero no del todo correctamente", "aviso"),
    5: ("La música no suena", "aviso"),
    6: ("Aparece la pantalla de protección anticopia", "problema"),
    7: ("Aparece la pantalla de estándar de televisión incorrecto", "problema"),
    8: ("Gráficos corruptos o distorsionados", "problema"),
    9: ("No funciona", "problema"),
}

# Códigos que uCON64 puede resolver, con la opción que lo hace
SOLUCIONES = {
    1: "-k",
    2: "-f",
}


@dataclass
class CompatEntry:
    nombre: str
    codigos: list
    nota: str

    @property
    def funciona(self) -> bool:
        return self.codigos == [0]

    @property
    def gravedad(self) -> str:
        """peor categoría de entre sus códigos: ok < aviso < accion < problema"""
        orden = {"ok": 0, "aviso": 1, "accion": 2, "problema": 3}
        peor = "ok"
        for c in self.codigos:
            cat = CODIGOS.get(c, ("", "aviso"))[1]
            if orden[cat] > orden[peor]:
                peor = cat
        return peor

    def descripciones(self) -> list:
        return [CODIGOS.get(c, (f"código {c} desconocido", "aviso"))[0] for c in self.codigos]

    def opciones_ucon64(self) -> list:
        """Opciones de uCON64 que corregirían los problemas conocidos."""
        return [SOLUCIONES[c] for c in self.codigos if c in SOLUCIONES]


def _base_dir() -> str:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


_datos = None


def _cargar() -> dict:
    global _datos
    if _datos is not None:
        return _datos
    ruta = os.path.join(_base_dir(), "swc_compat_data.json")
    try:
        with open(ruta, encoding="utf-8") as fh:
            _datos = json.load(fh)
    except (OSError, json.JSONDecodeError):
        _datos = {"meta": {}, "juegos": []}
    return _datos


def meta() -> dict:
    return _cargar().get("meta", {})


def total() -> int:
    return len(_cargar().get("juegos", []))


# Numerales romanos usados en títulos, para poder compararlos con los árabes
_ROMANOS = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6",
            "vii": "7", "viii": "8", "ix": "9", "x": "10"}


def _numero_secuela(texto: str) -> str:
    """Número de entrega del título, si lo hay.

    Es determinante para no confundir un juego con su secuela: sin esto,
    "Breath of Fire 2" se emparejaba con "Breath of Fire" y se informaba de
    una compatibilidad que corresponde a otro juego.
    """
    palabras = texto.split()
    for p in reversed(palabras):
        if p in _ROMANOS:
            return _ROMANOS[p]
        if p.isdigit() and len(p) <= 2:
            return p
    return ""


def _normalizar(texto: str) -> str:
    """Deja el título en una forma comparable: sin región, sin extensión,
    sin signos y en minúsculas."""
    t = texto.lower()
    t = re.sub(r"\.(sfc|smc|swc|fig|ufo|bin)$", "", t)
    # region y etiquetas entre paréntesis o corchetes
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", t)
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    # artículos al final, como los escribe la lista ("Addams Family, The")
    t = re.sub(r"\b(the|a|an)\b", " ", t)
    palabras = [_ROMANOS.get(p, p) for p in t.split()]
    return " ".join(palabras)


def buscar(titulo: str, umbral: float = 0.82):
    """Busca un juego por título. Devuelve (CompatEntry, similitud) o None.

    El título puede venir de la cabecera interna del ROM (21 caracteres,
    a menudo abreviado) o del nombre del archivo, así que la comparación es
    aproximada.
    """
    consulta = _normalizar(titulo)
    if not consulta:
        return None

    num_consulta = _numero_secuela(consulta)

    juegos = _cargar().get("juegos", [])
    mejor, mejor_ratio = None, 0.0
    for j in juegos:
        candidato = _normalizar(j["n"])
        if not candidato:
            continue

        # Un juego y su secuela no son el mismo juego: si los números de
        # entrega no coinciden, se descarta la pareja por muy parecidos que
        # sean los títulos.
        if _numero_secuela(candidato) != num_consulta:
            continue

        if candidato == consulta:
            return CompatEntry(j["n"], j["c"], j["o"]), 1.0
        # Coincidencia por prefijo: las cabeceras SNES truncan a 21 caracteres
        if len(consulta) >= 8 and candidato.startswith(consulta):
            ratio = 0.95
        else:
            ratio = difflib.SequenceMatcher(None, consulta, candidato).ratio()
        if ratio > mejor_ratio:
            mejor, mejor_ratio = j, ratio

    if mejor and mejor_ratio >= umbral:
        return CompatEntry(mejor["n"], mejor["c"], mejor["o"]), mejor_ratio
    return None


def buscar_todos(texto: str, limite: int = 25) -> list:
    """Búsqueda libre por subcadena, para el consultor de la interfaz."""
    consulta = _normalizar(texto)
    if not consulta:
        return []
    salida = []
    for j in _cargar().get("juegos", []):
        if consulta in _normalizar(j["n"]):
            salida.append(CompatEntry(j["n"], j["c"], j["o"]))
            if len(salida) >= limite:
                break
    return salida
