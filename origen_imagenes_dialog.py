"""Selector de origen de las imágenes de disco.

Sustituye a los avisos sueltos del tipo «Selecciona primero una imagen de
disco en la lista…» que salían al pulsar una herramienta del manipulador de
disquete, de la unidad real o de la unidad USB sin tener nada seleccionado.

En vez de decir al usuario que vaya a buscar otra cosa y vuelva a pulsar, se
le ofrece justo aquí, en una ventana grande y de alto contraste, de dónde
quiere coger las imágenes:

  1. Carpeta ASTURCONSOLE: navega por la carpeta de trabajo de la aplicación
     (discos creados, extraídos, SWC/SMD...).
  2. Elegir carpeta: cualquier carpeta del equipo o de una unidad externa.
  3. Última carpeta usada, si la hay.

Después la aplicación abre la ventana grande de trabajo sobre esa carpeta, ya
preparada para la tarea que se había pedido.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

ASTURCONSOLE = "asturconsole"
OTRA = "otra"
ULTIMA = "ultima"

ESTILO = """
QDialog { background: #0b0d13; }
QLabel { color: #ffffff; }
QLabel#Titulo { font-size: 20px; font-weight: 800; color: #ffffff; }
QLabel#Tarea {
    font-size: 14px; font-weight: 700; color: #000000;
    background: #ffd166; border-radius: 8px; padding: 10px 14px;
}
QLabel#Ayuda { font-size: 12px; color: #dfe5f2; }
QPushButton#Cancelar {
    background: #1f2330; color: #ffffff; border: 2px solid #8892a8;
    border-radius: 7px; padding: 9px 22px; font-weight: 700;
}
QPushButton#Cancelar:hover { border-color: #ffffff; }
"""


def _estilo_tarjeta(color: str) -> str:
    return f"""
QPushButton {{
    background: #141824; border: 3px solid {color}; border-radius: 12px;
}}
QPushButton:hover {{ background: #1f2638; border-color: #ffffff; }}
QPushButton:disabled {{ background: #10131b; border-color: #2c3342; }}
"""


class OrigenImagenesDialog(QDialog):
    """Pregunta de dónde coger las imágenes. El resultado queda en
    `eleccion` (ASTURCONSOLE / OTRA / ULTIMA) y, para ULTIMA, en `ruta`."""

    def __init__(self, tarea: str | None, requisito: str, ultima: str = "",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("ASTURCONSOLE — Elegir imágenes")
        self.setStyleSheet(ESTILO)
        self.setMinimumWidth(920)
        self.eleccion: str | None = None
        self.ruta: str = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(14)

        titulo = QLabel("¿De dónde cojo los archivos?")
        titulo.setObjectName("Titulo")
        lay.addWidget(titulo)

        if tarea:
            t = QLabel(f"▶  {tarea}")
            t.setObjectName("Tarea")
            t.setWordWrap(True)
            lay.addWidget(t)

        ayuda = QLabel(
            f"Necesito {requisito}. Elige la carpeta donde están y te abro una "
            "ventana grande de trabajo con todos sus archivos: ahí los marcas y "
            "se aplica la herramienta directamente.")
        ayuda.setObjectName("Ayuda")
        ayuda.setWordWrap(True)
        lay.addWidget(ayuda)

        fila = QHBoxLayout()
        fila.setSpacing(14)
        fila.addWidget(self._tarjeta(
            "📁  Carpeta ASTURCONSOLE",
            "Navega por la carpeta de trabajo de la aplicación: discos creados, "
            "extraídos, SWC, Super Magic Drive…", "#4e9ef6", ASTURCONSOLE))
        fila.addWidget(self._tarjeta(
            "📂  Elegir carpeta…",
            "Cualquier carpeta de tu equipo, de una memoria USB o de un disco "
            "externo.", "#3ef29a", OTRA))
        valida = bool(ultima) and os.path.isdir(ultima)
        b = self._tarjeta(
            "🕘  Última carpeta usada",
            (ultima if valida else "Todavía no has usado ninguna."),
            "#ffb454", ULTIMA)
        b.setEnabled(valida)
        self.ruta_ultima = ultima if valida else ""
        fila.addWidget(b)
        lay.addLayout(fila)

        marco = QFrame()
        marco.setFrameShape(QFrame.HLine)
        marco.setStyleSheet("background: #2c3342; max-height: 1px; border: none;")
        lay.addWidget(marco)

        pie = QHBoxLayout()
        pie.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.setObjectName("Cancelar")
        cancelar.setCursor(Qt.PointingHandCursor)
        cancelar.clicked.connect(self.reject)
        pie.addWidget(cancelar)
        lay.addLayout(pie)

    def _tarjeta(self, titulo: str, texto: str, color: str, clave: str) -> QPushButton:
        """Botón grande con título de color y texto que se ajusta a su ancho."""
        b = QPushButton()
        b.setMinimumHeight(150)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(_estilo_tarjeta(color))
        lay = QVBoxLayout(b)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        t = QLabel(titulo)
        t.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: 800; "
                        "background: transparent;")
        d = QLabel(texto)
        d.setWordWrap(True)
        d.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 600; "
                        "background: transparent;")
        for w in (t, d):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(t)
        lay.addWidget(d, 1)
        b.clicked.connect(lambda _c=False, k=clave: self._elegir(k))
        return b

    def _elegir(self, clave: str):
        self.eleccion = clave
        self.ruta = self.ruta_ultima if clave == ULTIMA else ""
        self.accept()
