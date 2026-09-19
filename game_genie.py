"""Índice y búsqueda de códigos Game Genie, para SNES y Genesis (los dos
únicos sistemas con ROM en ASTURCONSOLE; MSX no tiene Game Genie).

Los archivos fuente (data/game_genie/*.txt) llevan también NES, Game Boy
y Game Gear — se incluyen en el proyecto tal cual, para quien quiera
consultarlos por su cuenta (ver _abrir_carpeta_game_genie en
file_workbench.py), pero solo SNES y Genesis se indexan y aplican aquí,
que es lo único que tiene sentido dentro de esta aplicación.

Formato de cada .txt (ver la extracción original de las hojas de cálculo
de nesworld.com):

    ## Nombre del juego
      CODIGO-AAAA
          -> descripción del efecto
      CODIGO-BBBB + CODIGO-CCCC
          -> otro efecto (Genesis: varios códigos juntos, un solo efecto)

Un mismo nombre de juego puede repetirse (ediciones de región distintas
con el mismo título) — se fusionan sus códigos en una sola entrada.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

_ARCHIVO_POR_SISTEMA = {
    "snes": "game_genie_snes.txt",
    "genesis": "game_genie_genesis.txt",
}


@dataclass
class CodigoGG:
    codigo: str          # tal cual aparece en el .txt — puede llevar " + "
    descripcion: str


@dataclass
class JuegoGG:
    nombre: str
    codigos: list[CodigoGG] = field(default_factory=list)


def _parsear(ruta: str) -> list[JuegoGG]:
    juegos: dict[str, JuegoGG] = {}
    actual: JuegoGG | None = None
    codigo_pendiente: str | None = None
    with open(ruta, "r", encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.rstrip("\n")
            if linea.startswith("## "):
                nombre = linea[3:].strip()
                actual = juegos.setdefault(nombre, JuegoGG(nombre=nombre))
                codigo_pendiente = None
            elif linea.startswith("      -> ") and actual is not None and codigo_pendiente:
                actual.codigos.append(CodigoGG(
                    codigo=codigo_pendiente, descripcion=linea[9:].strip()))
                codigo_pendiente = None
            elif linea.startswith("  ") and not linea.startswith("   ") and actual is not None:
                codigo_pendiente = linea.strip()
    return list(juegos.values())


@lru_cache(maxsize=None)
def _indice(sistema: str, carpeta_datos: str) -> tuple[JuegoGG, ...]:
    """Cacheado por (sistema, carpeta): se parsea una sola vez por
    ejecución de la app, no en cada apertura del panel de Game Genie."""
    nombre_archivo = _ARCHIVO_POR_SISTEMA.get(sistema)
    if not nombre_archivo:
        return ()
    ruta = os.path.join(carpeta_datos, nombre_archivo)
    if not os.path.isfile(ruta):
        return ()
    return tuple(_parsear(ruta))


def cargar_indice(sistema: str, carpeta_datos: str) -> tuple[JuegoGG, ...]:
    """sistema: 'snes' o 'genesis'. carpeta_datos: la carpeta
    data/game_genie del proyecto (o la equivalente empaquetada)."""
    return _indice(sistema, carpeta_datos)


def buscar(indice: tuple[JuegoGG, ...], texto: str, limite: int = 60) -> list[JuegoGG]:
    """Busca por subcadena en el nombre, sin distinguir mayúsculas ni
    acentos exactos (comparación simple, suficiente para nombres en
    inglés). Con el campo vacío no devuelve nada — evita mostrar de
    golpe una lista de cientos de juegos sin que el usuario haya pedido
    nada todavía."""
    texto = texto.strip().lower()
    if not texto:
        return []
    coincidencias = [j for j in indice if texto in j.nombre.lower()]
    coincidencias.sort(key=lambda j: (not j.nombre.lower().startswith(texto), j.nombre))
    return coincidencias[:limite]


def separar_codigo(codigo: str) -> list[str]:
    """Un CodigoGG.codigo puede llevar varios códigos combinados con
    " + " (frecuente en Genesis: un solo efecto necesita aplicar más de
    un código). ucon64 --gg solo acepta un código por llamada, así que se
    aplican por separado, uno detrás de otro, sobre el mismo archivo."""
    return [c.strip() for c in codigo.split("+") if c.strip()]
