"""Ventana grande de trabajo con los archivos de una carpeta.

Sustituye a la lista estrecha de la ventana principal, que se quedaba corta
en cuanto una carpeta tenía muchos archivos. Aquí se trabaja con comodidad:

  - Rejilla de iconos con todos los archivos de la carpeta, filtrable.
  - Las herramientas del sistema activo (añadir cabecera, dividir en
    disquetes, byte swap...) están en esta misma ventana, aplicadas a lo que
    haya seleccionado.
  - Si lo seleccionado son imágenes de disco, se puede abrir el extractor
    directamente.

Las acciones no se implementan aquí: se reciben ya listas desde el panel
principal, que es quien sabe hacer cada operación. Esta ventana solo se
ocupa de mostrar y seleccionar.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

import rom_formats as rf

ESTILO = """
QDialog { background: #0f111a; }
QLabel { color: #dde3ef; }
QLabel#Titulo { font-size: 15px; font-weight: 700; }
QLabel#Ruta {
    color: #8892a8; font-family: "IBM Plex Mono", monospace; font-size: 11px;
}
QLineEdit, QComboBox {
    background: #0a0b10; color: #dde3ef;
    border: 1px solid #2c3342; border-radius: 5px; padding: 7px 10px;
}
QLineEdit:focus { border-color: #3ef29a; }
QListWidget {
    background: #0a0b10; color: #dde3ef;
    border: 1px solid #2c3342; border-radius: 6px; outline: none;
}
QListWidget::item { border-radius: 8px; padding: 6px; margin: 3px; color: #c8d0e0; }
QListWidget::item:hover { background: #161c28; }
QListWidget::item:selected { background: #22304a; color: #ffffff; }
QPushButton {
    background: #1f2330; color: #dde3ef;
    border: 1px solid #39404f; border-radius: 5px;
    padding: 8px 13px; font-weight: 600; text-align: left;
}
QPushButton:hover { border-color: #8892a8; background: #262b38; }
QPushButton#Principal {
    background: rgba(62,242,154,0.16); color: #3ef29a;
    border: 2px solid #3ef29a; text-align: center;
}
QPushButton#Principal:hover { background: rgba(62,242,154,0.30); }
QFrame#Panel {
    background: #161a24; border: 1px solid #2c3342; border-radius: 8px;
}
QLabel#Seccion { color: #8892a8; font-size: 10px; font-weight: 700; }
"""

EXT_IMAGENES = (".dsk", ".img", ".di1", ".di2")


class FileWorkbench(QDialog):
    """Ventana de trabajo sobre los archivos de una carpeta."""

    analizar = Signal(str)               # ver un archivo en el panel de detalle
    accion = Signal(str, list)           # (clave de acción, rutas seleccionadas)

    def __init__(self, carpeta: str, sistema: str, acciones: list,
                 icon_dir: str = "", parent=None):
        """`acciones` es una lista de (clave, texto, descripción)."""
        super().__init__(parent)
        self.setWindowTitle(f"Trabajar con archivos — {os.path.basename(carpeta)}")
        self.setMinimumSize(1060, 680)
        self.setStyleSheet(ESTILO)

        self._carpeta = carpeta
        self._sistema = sistema
        self._icon_dir = icon_dir
        self._archivos: list = []

        raiz = QVBoxLayout(self)
        raiz.setSpacing(10)

        titulo = QLabel(os.path.basename(carpeta) or carpeta)
        titulo.setObjectName("Titulo")
        raiz.addWidget(titulo)
        ruta = QLabel(carpeta)
        ruta.setObjectName("Ruta")
        ruta.setWordWrap(True)
        raiz.addWidget(ruta)

        # --- barra de filtro ---
        barra = QHBoxLayout()
        barra.addWidget(QLabel("Filtrar:"))
        self.filtro = QLineEdit()
        self.filtro.setPlaceholderText("escribe parte del nombre…")
        self.filtro.textChanged.connect(self._poblar)
        barra.addWidget(self.filtro, 1)

        barra.addWidget(QLabel("Tipo:"))
        self.tipo_combo = QComboBox()
        self.tipo_combo.addItem("Todos los archivos", None)
        self.tipo_combo.addItem("Imágenes de disco", EXT_IMAGENES)
        self.tipo_combo.addItem("ROMs SNES", (".sfc", ".smc", ".swc", ".fig", ".ufo"))
        self.tipo_combo.addItem("ROMs Mega Drive", (".smd", ".bin", ".md", ".gen"))
        self.tipo_combo.addItem("ROMs / archivos MSX", (".rom", ".mx1", ".mx2"))
        self.tipo_combo.addItem("Cintas", (".cas", ".tsx", ".wav"))
        self.tipo_combo.currentIndexChanged.connect(self._poblar)
        barra.addWidget(self.tipo_combo)

        self.todos_btn = QPushButton("Seleccionar todo")
        self.todos_btn.clicked.connect(lambda: self.lista.selectAll())
        barra.addWidget(self.todos_btn)
        raiz.addLayout(barra)

        # --- cuerpo: archivos a la izquierda, acciones a la derecha ---
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)

        self.lista = QListWidget()
        self.lista.setViewMode(QListView.IconMode)
        self.lista.setIconSize(QSize(56, 56))
        self.lista.setGridSize(QSize(180, 104))
        self.lista.setResizeMode(QListView.Adjust)
        self.lista.setMovement(QListView.Static)
        self.lista.setWordWrap(True)
        self.lista.setSelectionMode(QListWidget.ExtendedSelection)
        self.lista.itemSelectionChanged.connect(self._actualizar_estado)
        self.lista.itemDoubleClicked.connect(self._doble_clic)
        cuerpo.addWidget(self.lista, 1)

        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(310)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(7)

        et = QLabel("HERRAMIENTAS")
        et.setObjectName("Seccion")
        pl.addWidget(et)

        self._botones = []
        for clave, texto, descripcion in acciones:
            b = QPushButton(texto)
            if descripcion:
                b.setToolTip(descripcion)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _checked=False, c=clave: self._lanzar(c))
            pl.addWidget(b)
            self._botones.append(b)

        pl.addStretch(1)
        self.ver_btn = QPushButton("Analizar el seleccionado")
        self.ver_btn.setObjectName("Principal")
        self.ver_btn.setCursor(Qt.PointingHandCursor)
        self.ver_btn.clicked.connect(self._analizar_seleccion)
        pl.addWidget(self.ver_btn)
        cuerpo.addWidget(panel)
        raiz.addLayout(cuerpo, 1)

        self.estado = QLabel("")
        self.estado.setStyleSheet("color: #8892a8; font-size: 11px;")
        self.estado.setWordWrap(True)
        raiz.addWidget(self.estado)

        self._poblar()

    # -- contenido ---------------------------------------------------------
    def _icono(self, nombre: str) -> QIcon:
        ext = os.path.splitext(nombre)[1].lower()
        mapa = {
            EXT_IMAGENES: "floppy.svg",
            (".cas", ".tsx", ".wav"): "msx.svg",
            (".sfc", ".smc", ".swc", ".fig", ".ufo"): "snes.svg",
            (".smd", ".gen", ".md", ".bin"): "genesis.svg",
            (".rom", ".mx1", ".mx2"): "msx.svg",
        }
        for exts, archivo in mapa.items():
            if ext in exts:
                ruta = os.path.join(self._icon_dir, archivo)
                if os.path.isfile(ruta):
                    return QIcon(ruta)
        return QIcon()

    def _poblar(self):
        self.lista.clear()
        texto = self.filtro.text().strip().lower()
        exts = self.tipo_combo.currentData()

        try:
            entradas = sorted(os.listdir(self._carpeta), key=str.lower)
        except OSError as e:
            self.estado.setText(f"No se pudo leer la carpeta: {e}")
            return

        mostrados = 0
        for nombre in entradas:
            ruta = os.path.join(self._carpeta, nombre)
            if not os.path.isfile(ruta) or nombre.startswith("."):
                continue
            if nombre == "LEEME.txt":
                continue
            if exts and os.path.splitext(nombre)[1].lower() not in exts:
                continue
            if texto and texto not in nombre.lower():
                continue
            try:
                tam = rf.fmt_bytes(os.path.getsize(ruta))
            except OSError:
                tam = "?"
            corto = nombre if len(nombre) <= 26 else nombre[:23] + "…"
            item = QListWidgetItem(self._icono(nombre), f"{corto}\n{tam}")
            item.setData(Qt.UserRole, ruta)
            item.setToolTip(f"{nombre}\n{tam}")
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.lista.addItem(item)
            mostrados += 1

        self._actualizar_estado(total=mostrados)

    def _actualizar_estado(self, total: int | None = None):
        if total is None:
            total = self.lista.count()
        seleccionados = len(self.lista.selectedItems())
        texto = f"{total} archivo(s) visibles"
        if seleccionados:
            bytes_totales = 0
            for i in self.lista.selectedItems():
                try:
                    bytes_totales += os.path.getsize(i.data(Qt.UserRole))
                except OSError:
                    pass
            texto += f"   ·   {seleccionados} seleccionado(s), {rf.fmt_bytes(bytes_totales)}"
        else:
            texto += "   ·   selecciona archivos para aplicarles una herramienta"
        self.estado.setText(texto)

    # -- acciones ----------------------------------------------------------
    def seleccion(self) -> list:
        return [i.data(Qt.UserRole) for i in self.lista.selectedItems()]

    def _lanzar(self, clave: str):
        rutas = self.seleccion()
        if not rutas:
            self.estado.setText(
                "Selecciona primero uno o varios archivos: las herramientas se "
                "aplican a lo que esté seleccionado.")
            return
        self.accion.emit(clave, rutas)

    def _analizar_seleccion(self):
        rutas = self.seleccion()
        if rutas:
            self.analizar.emit(rutas[0])

    def _doble_clic(self, item: QListWidgetItem):
        self.analizar.emit(item.data(Qt.UserRole))

    def refrescar(self):
        self._poblar()
