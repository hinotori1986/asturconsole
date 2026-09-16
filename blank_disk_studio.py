"""Creación de discos vacíos/sistema — ventana dedicada para generar
imágenes .dsk/.img vacías en cualquiera de los formatos que maneja el
proyecto: MSX estándar, el "superformateado" de los copiones de
SNES/Genesis, y los formatos estándar de PC (360KB a 2.88MB).

Antes esta función vivía repartida (y duplicada) dentro de las tarjetas de
"disquetera real"/"manipulador" de cada pestaña, lo que podía dar a entender
que hacía falta una unidad física conectada para generar una imagen vacía —
no es el caso en absoluto: es pura generación de bytes. Con su propio
espacio, separado de cualquier mención a hardware, esto queda más claro.

El contenido de sistema a inyectar (MSX-DOS, utilidades, o lo que sea) ya
no se elige de una lista fija de versiones conocidas: el propio usuario
prepara sus carpetas dentro de ASTURCONSOLE/Sistema/, y aquí solo se elige
cuál de ellas aplicar — sin ninguna comprobación de que tenga sentido para
la familia de disco elegida (ver system_folder_dialog.py).
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
    QSpinBox, QVBoxLayout, QWidget,
)

import rom_formats as rf
from system_folder_dialog import SystemFolderDialog


ORO = "#d4af37"

QSS = """
QDialog#EstudioDiscos {
    background: #0a0d14;
    border: 5px solid %(oro)s;
    border-radius: 10px;
}

QFrame#Losa {
    background: #12161f;
    border: 2px solid #262c3a;
    border-radius: 10px;
}
QFrame#Losa[seleccionada="true"] { border-color: %(color)s; background: #161c28; }
QFrame#Losa QLabel#LosaTitulo { color: #e8ecf5; font-size: 13px; font-weight: 700; }
QFrame#Losa QLabel#LosaDesc { color: #838da3; font-size: 10px; }
QRadioButton#LosaRadio::indicator { width: 0; height: 0; }

QFrame#Chip {
    background: #10141c;
    border: 1.5px solid #2c3342;
    border-radius: 7px;
}
QFrame#Chip[seleccionado="true"] { border-color: %(color)s; background: #171d2a; }
QFrame#Chip QLabel#ChipTam { color: %(color)s; font-family: "DejaVu Sans Mono", monospace;
                             font-size: 13.5px; font-weight: 700; }
QFrame#Chip QLabel#ChipDesc { color: #99a2b8; font-size: 10px; }
QRadioButton#ChipRadio::indicator { width: 0; height: 0; }

QLabel#TituloEstudio { color: %(oro)s; font-size: 18px; font-weight: 700; }
QLabel#SubtituloEstudio { color: #6b7488; font-size: 10.5px; }
QLabel#EtiquetaCampo { color: #aab2c5; font-size: 11px; }
QLabel#EstadoSistema { color: #8892a8; font-size: 11px; font-style: italic; }

QPushButton#Generar {
    background: %(color)s; color: #0a0d14; font-weight: 700; font-size: 13px;
    border: none; border-radius: 7px; padding: 10px;
}
QPushButton#Generar:hover { background: %(color_hover)s; }
QPushButton#Generar:disabled { background: #262c3a; color: #565f74; }

QPushButton#BotonSistema {
    background: #171d2a; color: #dde3ef; font-size: 11.5px;
    border: 1.5px solid #2c3342; border-radius: 7px; padding: 7px 12px;
}
QPushButton#BotonSistema:hover { border-color: %(oro)s; color: %(oro)s; }
"""


class _Losa(QFrame):
    """Una de las tres 'losas' grandes de selección de familia."""

    def __init__(self, titulo: str, descripcion: str, icono: str, color: str,
                 grupo: QButtonGroup, parent=None):
        super().__init__(parent)
        self.setObjectName("Losa")
        self.color = color
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("seleccionada", False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        self.radio = QRadioButton()
        self.radio.setObjectName("LosaRadio")
        grupo.addButton(self.radio)
        lay.addWidget(self.radio)

        icon_lbl = QLabel()
        if icono and os.path.isfile(icono):
            icon_lbl.setPixmap(QIcon(icono).pixmap(QSize(40, 40)))
        icon_lbl.setFixedSize(40, 40)
        lay.addWidget(icon_lbl)

        textos = QVBoxLayout()
        textos.setSpacing(1)
        t = QLabel(titulo)
        t.setObjectName("LosaTitulo")
        d = QLabel(descripcion)
        d.setObjectName("LosaDesc")
        d.setWordWrap(True)
        textos.addWidget(t)
        textos.addWidget(d)
        lay.addLayout(textos, 1)

        self.mousePressEvent = lambda ev: self.radio.setChecked(True)

    def set_seleccionada(self, sel: bool):
        self.setProperty("seleccionada", sel)
        self.style().unpolish(self)
        self.style().polish(self)


class _Chip(QFrame):
    """Un formato concreto dentro de la familia elegida, como chip clicable."""

    def __init__(self, etiqueta_tam: str, descripcion: str, clave: str,
                 grupo: QButtonGroup, parent=None):
        super().__init__(parent)
        self.setObjectName("Chip")
        self.clave = clave
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("seleccionado", False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(2)

        fila = QHBoxLayout()
        self.radio = QRadioButton()
        self.radio.setObjectName("ChipRadio")
        grupo.addButton(self.radio)
        fila.addWidget(self.radio)
        tam = QLabel(etiqueta_tam)
        tam.setObjectName("ChipTam")
        fila.addWidget(tam)
        fila.addStretch(1)
        lay.addLayout(fila)

        desc = QLabel(descripcion)
        desc.setObjectName("ChipDesc")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        self.mousePressEvent = lambda ev: self.radio.setChecked(True)

    def set_seleccionado(self, sel: bool):
        self.setProperty("seleccionado", sel)
        self.style().unpolish(self)
        self.style().polish(self)


class BlankDiskStudioDialog(QDialog):
    """Ventana única para crear discos vacíos de cualquier familia."""

    _FAMILIAS = [
        ("msx", "MSX", "Disquetes estándar MSX/MSX2",
         "studio_msx.svg", "#3ef29a"),
        ("smd", "SNES / Genesis", "Formato de los copiones Super Wild Card "
         "y Super Magic Drive, incluido el \"superformateado\" de 1600 KB",
         "studio_smd.svg", "#ffb454"),
        ("pc", "PC estándar", "Los cinco tamaños clásicos, de 360 KB a 2.88 MB",
         "studio_pc.svg", "#5aa0ff"),
    ]

    def __init__(self, parent=None, icon_dir: str = ""):
        super().__init__(parent)
        self.setObjectName("EstudioDiscos")
        self.setWindowTitle("Creación de discos vacíos/sistema")
        self._icon_dir = icon_dir
        self._chips: list[_Chip] = []
        self._losas: dict[str, _Losa] = {}
        self._carpeta_sistema = ""
        self._modo_minimo = True

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 16, 18, 14)
        raiz.setSpacing(11)

        cabecera = QVBoxLayout()
        cabecera.setSpacing(2)
        t = QLabel("Creación de discos vacíos/sistema")
        t.setObjectName("TituloEstudio")
        cabecera.addWidget(t)
        s = QLabel("Imágenes ya formateadas, sin necesidad de ninguna unidad conectada.")
        s.setObjectName("SubtituloEstudio")
        cabecera.addWidget(s)
        raiz.addLayout(cabecera)

        self._grupo_familia = QButtonGroup(self)
        losas_lay = QVBoxLayout()
        losas_lay.setSpacing(7)
        for clave, titulo, desc, icono, color in self._FAMILIAS:
            ruta_icono = os.path.join(icon_dir, icono) if icon_dir else ""
            losa = _Losa(titulo, desc, ruta_icono, color, self._grupo_familia)
            losa.setStyleSheet(QSS % {"color": color, "color_hover": color, "oro": ORO})
            losa.radio.toggled.connect(
                lambda chk, c=clave: self._cambiar_familia(c) if chk else None)
            losas_lay.addWidget(losa)
            self._losas[clave] = losa
        raiz.addLayout(losas_lay)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#1c212e; max-height:1px; border:none;")
        raiz.addWidget(sep)

        self._chips_grid = QGridLayout()
        self._chips_grid.setSpacing(8)
        chips_wrap = QWidget()
        chips_wrap.setLayout(self._chips_grid)
        raiz.addWidget(chips_wrap)

        # --- contenido de sistema: solo tiene sentido para MSX y PC; los
        # discos de SNES/Genesis son siempre vacíos para el copión, sin
        # ningún concepto de "sistema" que inyectar (se oculta esta fila
        # entera al elegir esa familia, ver _cambiar_familia) ---
        self.widget_sistema = QWidget()
        fila_sistema = QHBoxLayout(self.widget_sistema)
        fila_sistema.setContentsMargins(0, 0, 0, 0)
        self.btn_sistema = QPushButton("Añadir contenido de sistema…")
        self.btn_sistema.setObjectName("BotonSistema")
        self.btn_sistema.setCursor(Qt.PointingHandCursor)
        self.btn_sistema.clicked.connect(self._elegir_carpeta_sistema)
        fila_sistema.addWidget(self.btn_sistema)
        self.lbl_estado_sistema = QLabel("Sin contenido de sistema")
        self.lbl_estado_sistema.setObjectName("EstadoSistema")
        fila_sistema.addWidget(self.lbl_estado_sistema, 1)
        raiz.addWidget(self.widget_sistema)

        formulario = QGridLayout()
        formulario.setSpacing(7)
        et_nombre = QLabel("Nombre base:")
        et_nombre.setObjectName("EtiquetaCampo")
        formulario.addWidget(et_nombre, 0, 0)
        self.name_edit = QLineEdit("DISCO001")
        formulario.addWidget(self.name_edit, 0, 1)

        et_cant = QLabel("Cantidad:")
        et_cant.setObjectName("EtiquetaCampo")
        formulario.addWidget(et_cant, 0, 2)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 100)
        self.count_spin.setValue(1)
        formulario.addWidget(self.count_spin, 0, 3)
        raiz.addLayout(formulario)

        self.btn_generar = QPushButton("Generar discos")
        self.btn_generar.setObjectName("Generar")
        self.btn_generar.setMinimumHeight(38)
        self.btn_generar.clicked.connect(self.accept)
        raiz.addWidget(self.btn_generar)

        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        cancelar.setFlat(True)
        raiz.addWidget(cancelar, alignment=Qt.AlignRight)

        self.setStyleSheet(QSS % {"color": "#3ef29a", "color_hover": "#5cf5b3", "oro": ORO})

        # arranca en MSX
        self._losas["msx"].radio.setChecked(True)

    def _cambiar_familia(self, clave: str):
        for k, losa in self._losas.items():
            losa.set_seleccionada(k == clave)
        color = next(c for k, _, _, _, c in self._FAMILIAS if k == clave)
        self.btn_generar.setStyleSheet(QSS % {"color": color, "color_hover": color, "oro": ORO})

        for i in reversed(range(self._chips_grid.count())):
            w = self._chips_grid.takeAt(i).widget()
            if w:
                w.deleteLater()
        self._chips = []
        self._grupo_formato = QButtonGroup(self)

        tabla = {"msx": rf.MSX_DISK_FORMATS, "smd": rf.SMD_DISK_FORMATS,
                 "pc": rf.PC_DISK_FORMATS}[clave]
        for i, (fclave, f) in enumerate(tabla.items()):
            tam_kb = f.size // 1024
            etiqueta_tam = f"{tam_kb} KB" if tam_kb < 1024 else f"{tam_kb/1024:.2f} MB"
            chip = _Chip(etiqueta_tam, f.label, fclave, self._grupo_formato)
            chip.setStyleSheet(QSS % {"color": color, "color_hover": color, "oro": ORO})
            chip.radio.toggled.connect(
                lambda chk, c=chip: self._marcar_chip(c) if chk else None)
            self._chips_grid.addWidget(chip, i // 2, i % 2)
            self._chips.append(chip)
        if self._chips:
            self._chips[0].radio.setChecked(True)

        self.widget_sistema.setVisible(clave != "smd")

        self._familia_actual = clave

    def _marcar_chip(self, chip_activo: _Chip):
        for c in self._chips:
            c.set_seleccionado(c is chip_activo)

    def _elegir_carpeta_sistema(self):
        dlg = SystemFolderDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._carpeta_sistema = dlg.carpeta_elegida()
        self._modo_minimo = dlg.modo_minimo()
        etiqueta = ""
        if self._carpeta_sistema:
            etiqueta = f"Carpeta: {self._carpeta_sistema}"
            etiqueta += " (mínimo)" if self._modo_minimo else " (completo)"
        self.lbl_estado_sistema.setText(etiqueta or "Sin contenido de sistema")

    def valores(self):
        """(familia, clave_formato, nombre_base, cantidad, carpeta_sistema, modo_minimo)"""
        clave_formato = next((c.clave for c in self._chips if c.radio.isChecked()),
                              self._chips[0].clave)
        # SNES/Genesis: siempre discos vacíos para el copión, sin concepto de
        # "sistema" — por si quedó algo elegido de antes de cambiar de familia.
        carpeta_sistema = "" if self._familia_actual == "smd" else self._carpeta_sistema
        return (
            self._familia_actual,
            clave_formato,
            self.name_edit.text().strip() or "DISCO",
            self.count_spin.value(),
            carpeta_sistema,
            self._modo_minimo,
        )
