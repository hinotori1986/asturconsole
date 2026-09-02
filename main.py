#!/usr/bin/env python3
"""ASTURCONSOLE — Qt6 (PySide6)

Explorador de directorios que interpreta cabeceras de ROM/disco para
MSX, Sega Mega Drive y Super Nintendo.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize, QTimer, QUrl
from PySide6.QtGui import (
    QFont, QFontDatabase, QTextCharFormat, QColor, QTextCursor, QIcon,
    QDesktopServices, QShortcut, QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QSplitter, QTabWidget,
    QScrollArea, QFrame, QPlainTextEdit, QTextEdit,
    QHeaderView, QSizePolicy, QMessageBox, QDialog, QComboBox,
    QLineEdit, QDialogButtonBox, QTreeWidget, QTreeWidgetItem, QMenu,
    QProgressBar, QSlider, QCheckBox, QListView, QSpinBox, QButtonGroup,
    QProgressDialog,
)

import rom_formats as rf
import system_detect as sd
from file_browser import elegir_archivos, elegir_archivo_guardar
import snes_tools as st
import cas_tape as ct
import tsx_tape as tt
import genesis_tools as gt
import hfe_format as hfe
import msxdos_disk as md
import swc_compat as sc
import snes_crack as crk
import workspace as ws
from disk_panel import build_disk_panel, build_floppy_writer_panel
from folder_picker import choose_directory

APP_TITLE = "ASTURCONSOLE"

# Estilo compartido por los diálogos de "elige una tarjeta" (formato de
# disco, tamaño de partición...): la tarjeta marcada se resalta con marco
# verde. Constante de módulo en vez de vivir en una clase concreta para no
# depender del orden en que se definen las clases que la usan.
ESTILO_TARJETA_SELECCIONABLE = """
    QPushButton {
        background: #161a24; color: #dde3ef;
        border: 2px solid #2c3342; border-radius: 10px;
        padding: 14px; font-weight: 600; text-align: center;
    }
    QPushButton:hover { border-color: #4a5468; }
    QPushButton:checked {
        background: rgba(62,242,154,0.12); color: #3ef29a;
        border: 2px solid #3ef29a;
    }
"""


def _app_base_dir() -> str:
    """Carpeta base de la app: la del ejecutable si PyInstaller la ha
    empaquetado (sys._MEIPASS), o la del propio script en ejecución normal.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


# Número de versión: se edita a mano aquí en cada entrega. Hubo una temporada
# en la que se calculaba solo a partir del tag de git (ver el historial si
# hace falta recuperarlo), pero sin usar tags de git de forma habitual el
# resultado era un valor de reserva poco legible ("dev-..."), así que se
# volvió a este esquema simple, más predecible aunque haya que acordarse de
# subir el número.
APP_VERSION = "1.0.1"
APP_BYLINE = "asturconsole by ritcher1986"

ASSETS_DIR = os.path.join(_app_base_dir(), "assets", "icons")


def _icon_base_dir() -> str:
    return os.path.join(_app_base_dir(), "assets", "icons")



def icon_path(name: str) -> str:
    return os.path.join(ASSETS_DIR, name)


ACCENTS = {
    "msx": "#3ef29a",
    "genesis": "#ff5340",
    "snes": "#b494f5",
}

SNES_ROM_EXTENSIONS = {".sfc", ".smc", ".fig", ".swc", ".ufo", ".bin"}

BASE_QSS = """
QMainWindow, QWidget {{
    background: #0a0b10;
    color: #dde3ef;
    font-family: "IBM Plex Sans", "Noto Sans", sans-serif;
    font-size: 13px;
}}
QMainWindow {{
    background-image: url({scanline_bg});
    background-repeat: repeat-xy;
}}
QLabel#Brand {{
    color: {accent};
    font-weight: 700;
    font-size: 15px;
    letter-spacing: 1px;
}}
QLabel#Sub {{
    color: #727a90;
    font-size: 11px;
}}
QLabel#Byline {{
    color: #5aa0ff;
    padding: 0px 4px;
}}
QLabel#Version {{
    color: #ffffff;
    font-family: "IBM Plex Mono", monospace;
    font-size: 12px;
    font-weight: 600;
    padding: 0px 2px;
}}
QTabWidget::pane {{
    border: 1px solid #262a3a;
    border-radius: 6px;
    top: -1px;
}}
QTabBar::tab {{
    background: #12141c;
    color: #727a90;
    border: 1px solid #262a3a;
    border-bottom: 3px solid #262a3a;
    padding: 14px 26px;
    margin-right: 14px;
    min-width: 130px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
    font-size: 14px;
    font-family: "IBM Plex Mono", monospace;
}}
QTabBar::tab:!selected {{
    margin-top: 4px;
}}
QTabBar {{
    qproperty-drawBase: 0;
}}
QTabBar::tab:selected {{
    background: #181b26;
    color: {accent};
    border-bottom: 3px solid {accent};
}}
QTabBar::tab:hover {{ color: #dde3ef; }}

#CornerSeparator {{
    background: #262a3a;
    border: none;
    max-width: 1px;
    min-width: 1px;
    margin: 2px 2px;
}}

QPushButton {{
    background: #1f2330;
    color: #dde3ef;
    border: 1px solid #262a3a;
    border-radius: 6px;
    padding: 7px 14px;
    font-family: "IBM Plex Mono", monospace;
    font-weight: 600;
}}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton#Primary {{
    background: {accent_bg};
    color: {accent};
    border-color: {accent};
}}

QListWidget, QTableWidget, QTreeWidget, QPlainTextEdit {{
    background: #12141c;
    border: 1px solid #262a3a;
    border-radius: 6px;
    font-family: "IBM Plex Mono", monospace;
}}
QListWidget::item {{ padding: 7px 8px; border-bottom: 1px solid #1c1f2b; }}
QListWidget::item:selected {{ background: {accent_bg}; color: {accent}; }}
QListWidget::item:hover {{ background: #181b26; }}

QTableWidget {{ gridline-color: #262a3a; }}
QHeaderView::section {{
    background: #181b26; color: #727a90; border: none;
    border-bottom: 1px solid #262a3a; padding: 6px; font-size: 10px;
    text-transform: uppercase; font-weight: 600;
}}
QTableWidget::item {{ padding: 4px; }}
QTableWidget::item:selected {{ background: {accent_bg}; color: {accent}; }}

QTreeWidget::item {{ padding: 4px; border: none; }}
QTreeWidget::item:selected {{ background: {accent_bg}; color: {accent}; }}
QTreeWidget::item:hover {{ background: #181b26; }}
QTreeWidget::branch {{ background: transparent; }}

QPlainTextEdit {{ color: #8892a8; font-size: 11px; padding: 6px; }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: #12141c; width: 10px; }}
QScrollBar::handle:vertical {{ background: #262a3a; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {accent}; }}

QFrame#FieldChip {{
    background: #181b26;
    border: 1px solid #262a3a;
    border-radius: 4px;
}}
QFrame#FieldChip[hover="true"] {{
    background: {accent_bg};
    border-color: {accent};
}}
QLabel#FieldLabel {{ color: #727a90; font-size: 9px; font-weight: 600; }}
QLabel#FieldValue {{ color: #dde3ef; font-family: "IBM Plex Mono", monospace; font-size: 12.5px; }}

QLabel#Badge {{
    background: {accent_bg}; color: {accent};
    border: 1px solid {accent}; border-radius: 4px;
    padding: 3px 8px; font-family: "IBM Plex Mono", monospace;
    font-weight: 700; font-size: 10px;
}}
QLabel#Badge[variant="warn"] {{ background: rgba(255,180,84,0.15); color: #ffb454; border-color: #ffb454; }}
QLabel#Badge[variant="bad"] {{ background: rgba(255,95,109,0.15); color: #ff5f6d; border-color: #ff5f6d; }}

QLabel#DTitle {{ font-family: "IBM Plex Mono", monospace; font-size: 16px; font-weight: 700; margin-top: 8px; }}
QLabel#DSub {{ color: #727a90; font-size: 11px; margin-bottom: 8px; }}
QLabel#SectionLabel {{ color: #727a90; font-size: 10.5px; font-weight: 600; margin-top: 14px; }}
QLabel#Hint {{ color: #727a90; font-size: 11.5px; }}
QLabel#BackLink {{ color: {accent}; font-family: "IBM Plex Mono", monospace; font-weight: 600; }}
"""


BYLINE_COLOR = "#5aa0ff"          # azul de la firma

# Familias blackletter/góticas reales, por si el usuario las tiene instaladas.
# Si no hay ninguna, se recurre a la tipografía incluida con la aplicación.
_GOTHIC_FAMILIES = (
    "UnifrakturMaguntia", "UnifrakturCook", "Cloister Black",
    "Old English Text MT", "Fette Fraktur", "Blackletter686 BT",
    "Berliner Fraktur", "Textura",
)


def load_byline_font(size: int = 15) -> QFont:
    """Tipografía de la firma: gótica real si está disponible en el sistema,
    y si no, la Gloock incluida con la aplicación (serif de alto contraste,
    con aire gótico). Devuelve una QFont lista para usar."""
    disponibles = set(QFontDatabase.families())

    for familia in _GOTHIC_FAMILIES:
        if familia in disponibles:
            f = QFont(familia, size)
            f.setStyleStrategy(QFont.PreferAntialias)
            return f

    ruta = os.path.join(_app_base_dir(), "assets", "fonts", "Gloock-Regular.ttf")
    if os.path.isfile(ruta):
        fid = QFontDatabase.addApplicationFont(ruta)
        if fid != -1:
            familias = QFontDatabase.applicationFontFamilies(fid)
            if familias:
                f = QFont(familias[0], size)
                f.setStyleStrategy(QFont.PreferAntialias)
                return f

    # Último recurso: serif del sistema en cursiva, que al menos evoca el estilo
    f = QFont()
    f.setStyleHint(QFont.Serif)
    f.setPointSize(size)
    f.setItalic(True)
    return f


def hex_to_rgba(color: str, alpha: float) -> str:
    color = color.lstrip("#")
    r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def mono_font(size: int = 12) -> QFont:
    families = QFontDatabase.families()
    for fam in ("JetBrains Mono", "Cascadia Code", "IBM Plex Mono", "DejaVu Sans Mono", "Monospace"):
        if fam in families:
            f = QFont(fam, size)
            f.setStyleHint(QFont.Monospace)
            return f
    f = QFont()
    f.setStyleHint(QFont.Monospace)
    f.setPointSize(size)
    return f


# ---------------------------------------------------------------------------
# Widgets reutilizables
# ---------------------------------------------------------------------------

@dataclass
class FieldSpec:
    label: str
    value: str
    offset: Optional[int] = None
    length: Optional[int] = None


class HexView(QPlainTextEdit):
    """Volcado hexadecimal con resaltado de rangos de bytes."""

    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setFont(mono_font(11))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setMaximumBlockCount(0)
        self._byte_pos: dict[int, tuple[int, int]] = {}
        self._accent = "#3ef29a"

    def set_accent(self, color: str):
        self._accent = color

    def load(self, data: bytes, max_len: int = 512):
        data = data[:max_len]
        self._byte_pos = {}
        lines = []
        pos = 0
        for row_start in range(0, len(data), 16):
            chunk = data[row_start:row_start + 16]
            offset_str = f"{row_start:04X}  "
            pos += len(offset_str)
            hex_parts = []
            for i, b in enumerate(chunk):
                idx = row_start + i
                token = f"{b:02X}"
                self._byte_pos[idx] = (pos, pos + len(token))
                hex_parts.append(token)
                pos += len(token) + 1  # + espacio
            hex_str = " ".join(hex_parts)
            ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            pad = " " * (3 * (16 - len(chunk)))
            line = f"{offset_str}{hex_str}{pad}   {ascii_str}"
            lines.append(line)
            pos += 2 + 3 + len(ascii_str) + 1  # separador + ascii + salto de línea aproximado
        self.setPlainText("\n".join(lines))
        # recalcular posiciones reales tras el render (evita desajustes por padding variable)
        self._recompute_positions(data)

    def _recompute_positions(self, data: bytes):
        text = self.toPlainText()
        self._byte_pos = {}
        for row_start in range(0, len(data), 16):
            line_no = row_start // 16
            block = self.document().findBlockByNumber(line_no)
            if not block.isValid():
                continue
            line_text = block.text()
            base = block.position()
            search_from = 6  # tras "XXXX  "
            for i in range(min(16, len(data) - row_start)):
                idx = row_start + i
                token = f"{data[idx]:02X}"
                pos_in_line = line_text.find(token, search_from)
                if pos_in_line == -1:
                    continue
                start = base + pos_in_line
                end = start + len(token)
                self._byte_pos[idx] = (start, end)
                search_from = pos_in_line + len(token)

    def clear_highlight(self):
        self.setExtraSelections([])

    def highlight_range(self, offset: int, length: int):
        if offset not in self._byte_pos:
            return
        end_idx = offset + length - 1
        while end_idx not in self._byte_pos and end_idx > offset:
            end_idx -= 1
        if end_idx not in self._byte_pos:
            return
        start = self._byte_pos[offset][0]
        end = self._byte_pos[end_idx][1]

        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)

        fmt = QTextCharFormat()
        fmt.setBackground(QColor(self._accent))
        fmt.setForeground(QColor("#000000"))

        sel = QTextEdit.ExtraSelection()
        sel.cursor = cursor
        sel.format = fmt
        self.setExtraSelections([sel])
        self.setTextCursor(cursor)
        self.ensureCursorVisible()


class FieldChip(QFrame):
    """Campo interpretado; si tiene offset/length, ilumina el HexView al pasar el ratón."""

    def __init__(self, spec: FieldSpec, hex_view: Optional[HexView]):
        super().__init__()
        self.setObjectName("FieldChip")
        self._hex_view = hex_view
        self._spec = spec
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(2)
        lbl = QLabel(spec.label.upper())
        lbl.setObjectName("FieldLabel")
        val = QLabel(str(spec.value))
        val.setObjectName("FieldValue")
        val.setWordWrap(True)
        lay.addWidget(lbl)
        lay.addWidget(val)
        if spec.offset is not None and hex_view is not None:
            self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, event):
        if self._hex_view is not None and self._spec.offset is not None:
            self.setProperty("hover", True)
            self.style().unpolish(self)
            self.style().polish(self)
            self._hex_view.highlight_range(self._spec.offset, self._spec.length or 1)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._hex_view is not None and self._spec.offset is not None:
            self.setProperty("hover", False)
            self.style().unpolish(self)
            self.style().polish(self)
            self._hex_view.clear_highlight()
        super().leaveEvent(event)


def fields_grid(specs: list[FieldSpec], hex_view: Optional[HexView], columns: int = 3) -> QWidget:
    w = QWidget()
    grid = QGridLayout(w)
    grid.setSpacing(1)
    grid.setContentsMargins(0, 0, 0, 0)
    for i, spec in enumerate(specs):
        chip = FieldChip(spec, hex_view)
        grid.addWidget(chip, i // columns, i % columns)
    for c in range(columns):
        grid.setColumnStretch(c, 1)
    return w


_BADGE_COLORS = {
    "warn": "#ffb454",
    "bad": "#ff5f6d",
}


def badge(text: str, variant: str = "default") -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Badge")
    if variant in _BADGE_COLORS:
        color = _BADGE_COLORS[variant]
        bg = hex_to_rgba(color, 0.15)
        lbl.setStyleSheet(
            f"background: {bg}; color: {color}; border: 1px solid {color}; "
            "border-radius: 4px; padding: 3px 8px; font-family: 'IBM Plex Mono', monospace; "
            "font-weight: 700; font-size: 10px;"
        )
    return lbl


# Color por tipo de archivo en las listas. Ayuda a distinguir de un vistazo
# los formatos cuando una carpeta mezcla varios (ROMs, discos, cintas...).
EXT_COLORS = {
    # ROMs de cartucho
    ".sfc": "#b494f5", ".smc": "#b494f5", ".fig": "#b494f5", ".swc": "#c9b0ff",
    ".ufo": "#b494f5",
    ".md": "#ff7a68", ".gen": "#ff7a68", ".smd": "#ff5340", ".bin": "#ff9b8d",
    ".rom": "#3ef29a", ".mx1": "#3ef29a", ".mx2": "#3ef29a",
    # Discos
    ".dsk": "#5ad1ff", ".img": "#5ad1ff", ".di1": "#5ad1ff", ".di2": "#5ad1ff",
    # Cintas
    ".cas": "#ffb454", ".tsx": "#ffd08a", ".wav": "#ff8ad8",
    # Otros
    ".txt": "#8892a8", ".bat": "#8892a8", ".sys": "#a0a8bc", ".com": "#a0a8bc",
}
DEFAULT_EXT_COLOR = "#dde3ef"


def color_for_path(path: str) -> QColor:
    ext = os.path.splitext(path)[1].lower()
    return QColor(EXT_COLORS.get(ext, DEFAULT_EXT_COLOR))


BOTON_EXTRAER = """
QPushButton {
    background: rgba(62,242,154,0.16); color: #3ef29a;
    border: 2px solid #3ef29a; border-radius: 6px;
    padding: 7px 14px; font-weight: 700;
}
QPushButton:hover { background: rgba(62,242,154,0.30); }
"""

# Botones de "seleccionar todo" / "deseleccionar todo". Antes eran botones
# sin ningún color, iguales a cualquier otro, y se perdían visualmente en
# medio de una barra con más botones. Verde para marcar (mismo lenguaje de
# color que el resto de acciones "positivas" de la app) y ámbar para
# desmarcar, con marco grueso para que resalten a simple vista.
BOTON_SELECCIONAR_TODO = """
QPushButton {
    background: rgba(62,242,154,0.14); color: #3ef29a;
    border: 2px solid #3ef29a; border-radius: 5px;
    padding: 5px 12px; font-weight: 700;
}
QPushButton:hover { background: rgba(62,242,154,0.28); }
"""

BOTON_DESELECCIONAR_TODO = """
QPushButton {
    background: rgba(255,180,84,0.14); color: #ffb454;
    border: 2px solid #ffb454; border-radius: 5px;
    padding: 5px 12px; font-weight: 700;
}
QPushButton:hover { background: rgba(255,180,84,0.28); }
"""

LIST_COLUMN_WIDTH = 250
LIST_ROW_HEIGHT = 22


def _configure_multicolumn(lst: QListWidget) -> None:
    """Presenta la lista en varias columnas en vez de una sola larga.

    Con nombres cortos, una lista de una sola columna desperdicia casi todo
    el ancho disponible y obliga a desplazarse mucho. Con `setWrapping` y un
    tamaño de celda fijo, los elementos se ordenan de arriba abajo y saltan a
    la columna siguiente, de modo que se ven muchos más de un vistazo.
    """
    lst.setFlow(QListView.TopToBottom)
    lst.setWrapping(True)
    lst.setResizeMode(QListView.Adjust)
    lst.setUniformItemSizes(True)
    lst.setGridSize(QSize(LIST_COLUMN_WIDTH, LIST_ROW_HEIGHT))
    lst.setTextElideMode(Qt.ElideMiddle)
    lst.setHorizontalScrollMode(QListView.ScrollPerPixel)
    lst.setWordWrap(False)


def mapper_fields(guess: rf.MapperGuess) -> list[FieldSpec]:
    fields = [
        FieldSpec("Mapper detectado", f"{guess.name} (confianza: {guess.confidence})"),
        FieldSpec("Detalle de la detección", guess.detail),
    ]
    return fields


def mapper_badge(guess: rf.MapperGuess) -> Optional[QLabel]:
    if guess.name in ("No determinado",) or guess.name.startswith("Sin mapper"):
        return None
    variant = "default" if guess.confidence == "alta" else "warn"
    return badge(f"MAPPER: {guess.name.upper()}", variant)


# ---------------------------------------------------------------------------
# Panel de detalle (contenido dinámico, reconstruido en cada selección)
# ---------------------------------------------------------------------------

class DetailPanel(QScrollArea):
    def __init__(self, accent_getter):
        super().__init__()
        self.setWidgetResizable(True)
        self._accent_getter = accent_getter
        self._body = QWidget()
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(16, 14, 16, 16)
        self._layout.setSpacing(4)
        self._layout.addStretch(1)
        self.setWidget(self._body)
        self.show_placeholder(
            "Selecciona un archivo de la lista para analizar su cabecera."
        )

    def _clear(self):
        """Vacía el panel por completo, incluidos los sublayouts.

        Importante: la fila de insignias se añade con addLayout, y para un
        elemento de tipo layout `item.widget()` devuelve None. Al borrar solo
        widgets, esas insignias sobrevivían y se iban acumulando una encima
        de otra al cambiar de archivo, hasta volverse ilegibles.
        """
        while self._layout.count():
            item = self._layout.takeAt(0)
            self._delete_item(item)

    @staticmethod
    def _delete_item(item):
        if item is None:
            return
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
            return
        sub = item.layout()
        if sub is not None:
            while sub.count():
                DetailPanel._delete_item(sub.takeAt(0))
            sub.deleteLater()

    def show_placeholder(self, text: str):
        self._clear()
        lbl = QLabel(text)
        lbl.setObjectName("Hint")
        lbl.setWordWrap(True)
        self._layout.addWidget(lbl)
        self._layout.addStretch(1)

    def build(self, badges: list[QLabel], title: str, subtitle: str,
              fields: list[FieldSpec], data_for_hex: Optional[bytes] = None,
              extra_widget: Optional[QWidget] = None,
              back_callback=None, back_text: str = "",
              header_actions=None):
        self._clear()

        if back_callback is not None:
            back = QLabel(f"←  {back_text}")
            back.setObjectName("BackLink")
            back.setCursor(Qt.PointingHandCursor)
            back.mousePressEvent = lambda e: back_callback()
            self._layout.addWidget(back)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(6)
        for b in badges:
            badge_row.addWidget(b)
        badge_row.addStretch(1)
        self._layout.addLayout(badge_row)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("DTitle")
        title_lbl.setWordWrap(True)
        self._layout.addWidget(title_lbl)

        sub_lbl = QLabel(subtitle)
        sub_lbl.setObjectName("DSub")
        sub_lbl.setWordWrap(True)
        self._layout.addWidget(sub_lbl)

        # Acciones justo debajo del título: así quedan siempre a la vista, sin
        # tener que desplazarse hasta el final del panel.
        if header_actions is not None:
            self._layout.addSpacing(4)
            self._layout.addLayout(header_actions)
            self._layout.addSpacing(4)

        hex_view = HexView() if data_for_hex is not None else None
        if hex_view is not None:
            hex_view.set_accent(self._accent_getter())

        if fields:
            self._layout.addWidget(fields_grid(fields, hex_view))

        if extra_widget is not None:
            self._layout.addWidget(extra_widget)

        if data_for_hex is not None:
            sect = QLabel("VOLCADO HEXADECIMAL")
            sect.setObjectName("SectionLabel")
            self._layout.addWidget(sect)
            hex_view.load(data_for_hex, max_len=512)
            hex_view.setMinimumHeight(260)
            hex_view.setMaximumHeight(320)
            self._layout.addWidget(hex_view)
            if len(data_for_hex) > 512:
                more = QLabel(f"mostrando los primeros 512 de {len(data_for_hex)} bytes")
                more.setObjectName("Hint")
                self._layout.addWidget(more)

        self._layout.addStretch(1)


# ---------------------------------------------------------------------------
# Panel por sistema (MSX / Genesis / SNES)
# ---------------------------------------------------------------------------

class FileSplitDialog(QDialog):
    """Divide un archivo cualquiera en partes de tamaño fijo — sin cabecera
    ni estructura de disco, es un corte mecánico cada N bytes (como el
    comando `split` de Unix). Útil para preparar trozos de tamaño exacto
    para herramientas o medios que lo esperen así.

    Dos categorías de tamaños habituales como tarjetas seleccionables
    (disquetes de época, y tamaños de bloque típicos de MegaROM), más un
    campo personalizado en KB o MB para cualquier otro valor.
    """

    ESTILO_TARJETA = ESTILO_TARJETA_SELECCIONABLE

    TAMANOS_DISQUETE = [
        ("360 KB", 360 * 1024, "5.25\" DD\ncara simple"),
        ("720 KB", 720 * 1024, "3.5\" DD\ndoble cara"),
        ("1.44 MB", 1440 * 1024, "3.5\" HD\nestándar"),
        ("1.6 MB", 1600 * 1024, "3.5\" HD\n\"superformateado\"\n(SMD/SWC)"),
    ]
    TAMANOS_ROM = [
        ("128 KB", 128 * 1024, ""),
        ("512 KB", 512 * 1024, ""),
        ("1024 KB", 1024 * 1024, "(1 MB)"),
        ("2048 KB", 2048 * 1024, "(2 MB)"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dividir archivo en partes")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setSpacing(14)

        info = QLabel(
            "Corta el archivo en partes de tamaño fijo, numeradas (.001, .002...). "
            "Sin cabecera ni formato de disco: es un corte mecánico, cada N bytes."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self._botones_preset: list[tuple[QPushButton, int]] = []

        def _fila_tarjetas(titulo: str, tamanos: list[tuple[str, int, str]]) -> QVBoxLayout:
            bloque = QVBoxLayout()
            bloque.setSpacing(6)
            etiqueta = QLabel(titulo)
            etiqueta.setObjectName("SectionLabel")
            bloque.addWidget(etiqueta)
            fila = QHBoxLayout()
            fila.setSpacing(8)
            for nombre, tam_bytes, sub in tamanos:
                texto = f"💾\n\n{nombre}" + (f"\n{sub}" if sub else "")
                b = QPushButton(texto)
                b.setCheckable(True)
                b.setMinimumHeight(110)
                b.setStyleSheet(self.ESTILO_TARJETA)
                self._grupo.addButton(b)
                self._botones_preset.append((b, tam_bytes))
                fila.addWidget(b)
            bloque.addLayout(fila)
            return bloque

        lay.addLayout(_fila_tarjetas("DISQUETES DE ÉPOCA", self.TAMANOS_DISQUETE))
        lay.addLayout(_fila_tarjetas("TAMAÑOS DE MEGAROM HABITUALES", self.TAMANOS_ROM))

        # Personalizado: su propia "tarjeta" (un botón checkable más, en el
        # mismo grupo exclusivo) que activa el campo de texto al elegirla.
        fila_custom = QHBoxLayout()
        fila_custom.setSpacing(8)
        self.btn_custom = QPushButton("✏️\n\nPersonalizado")
        self.btn_custom.setCheckable(True)
        self.btn_custom.setMinimumHeight(110)
        self.btn_custom.setMaximumWidth(140)
        self.btn_custom.setStyleSheet(self.ESTILO_TARJETA)
        self._grupo.addButton(self.btn_custom)
        self.btn_custom.toggled.connect(self._on_custom_toggled)
        fila_custom.addWidget(self.btn_custom)

        campo = QVBoxLayout()
        campo.addStretch(1)
        fila_valor = QHBoxLayout()
        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("tamaño, p. ej. 800")
        self.custom_edit.setEnabled(False)
        self.custom_unidad = QComboBox()
        self.custom_unidad.addItems(["KB", "MB"])
        self.custom_unidad.setEnabled(False)
        fila_valor.addWidget(self.custom_edit, 1)
        fila_valor.addWidget(self.custom_unidad)
        campo.addLayout(fila_valor)
        campo.addStretch(1)
        fila_custom.addLayout(campo, 1)
        lay.addLayout(fila_custom)

        # El primer preset (360 KB) marcado por defecto, para que el diálogo
        # siempre salga con una opción válida elegida.
        if self._botones_preset:
            self._botones_preset[0][0].setChecked(True)

        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.accepted.connect(self._on_accept)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

        self._tamano_elegido: Optional[int] = None

    def _on_custom_toggled(self, activo: bool):
        self.custom_edit.setEnabled(activo)
        self.custom_unidad.setEnabled(activo)
        if activo:
            self.custom_edit.setFocus()

    def _on_accept(self):
        if self.btn_custom.isChecked():
            texto = self.custom_edit.text().strip().replace(",", ".")
            try:
                valor = float(texto)
                if valor <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, APP_TITLE, "Introduce un tamaño válido, mayor que cero.")
                return
            multiplicador = 1024 * 1024 if self.custom_unidad.currentText() == "MB" else 1024
            self._tamano_elegido = int(valor * multiplicador)
        else:
            for boton, tam_bytes in self._botones_preset:
                if boton.isChecked():
                    self._tamano_elegido = tam_bytes
                    break
            else:
                QMessageBox.warning(self, APP_TITLE, "Elige un tamaño primero.")
                return
        self.accept()

    def chunk_size(self) -> Optional[int]:
        return self._tamano_elegido


class BatchByteswapDialog(QDialog):
    """Diálogo para elegir la operación y la coletilla del proceso por lotes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Intercambiar bancos HiROM por lotes (SNES)")
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        info = QLabel(
            "Aplica entrelazado/desentrelazado de HiROM a todos los archivos "
            f"SNES ({', '.join(sorted(SNES_ROM_EXTENSIONS))}) de una carpeta "
            "(incluidas subcarpetas). Los originales no se tocan: cada "
            "resultado se guarda como un archivo nuevo con la coletilla "
            "indicada."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        self.combo = QComboBox()
        self.combo.addItems(["Desentrelazar (HiROM)", "Entrelazar (HiROM)"])
        self.combo.currentTextChanged.connect(self._on_op_change)
        lay.addWidget(self.combo)

        suffix_row = QHBoxLayout()
        suffix_row.addWidget(QLabel("Coletilla:"))
        self.suffix_edit = QLineEdit("_deint")
        suffix_row.addWidget(self.suffix_edit)
        lay.addLayout(suffix_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _on_op_change(self, text: str):
        self.suffix_edit.setText("_deint" if text.startswith("Desentrelazar") else "_int")

    def deinterleave(self) -> bool:
        return self.combo.currentText().startswith("Desentrelazar")

    def suffix(self) -> str:
        s = self.suffix_edit.text().strip()
        return s or ("_deint" if self.deinterleave() else "_int")


class RomAnalysisDialog(QDialog):
    """Analiza una o varias ROMs (SNES o Mega Drive) en pestañas.

    Sustituye al antiguo comportamiento de "Analizar la selección" en la
    ventana de trabajo, que actualizaba el panel de detalle EMBEBIDO en la
    ventana principal: como esa ventana queda tapada detrás de la ventana de
    trabajo, el resultado no se veía y parecía que el botón no hacía nada.
    Además, solo mostraba la primera ROM seleccionada. Aquí se abre una
    pestaña por cada ROM analizada.
    """

    def __init__(self, panel: "SystemPanel", archivos: list, sistema: str, parent=None):
        """`archivos` es una lista de (nombre, datos). `panel` es el
        SystemPanel del que se reutilizan los métodos de análisis
        (_analyze_snes / _analyze_genesis) y el widget DetailPanel."""
        super().__init__(parent)
        self.setWindowTitle(
            f"Análisis de {len(archivos)} ROM(s) — "
            + ("Super Nintendo" if sistema == "snes" else "Mega Drive"))
        self.resize(900, 620)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        if len(archivos) > 1:
            tabs = QTabWidget()
            for nombre, datos in archivos:
                panel_detalle = self._crear_panel(panel, nombre, datos, sistema)
                etiqueta = nombre if len(nombre) <= 24 else nombre[:21] + "…"
                tabs.addTab(panel_detalle, etiqueta)
            lay.addWidget(tabs, 1)
        else:
            nombre, datos = archivos[0]
            lay.addWidget(self._crear_panel(panel, nombre, datos, sistema), 1)

        botones = QDialogButtonBox(QDialogButtonBox.Close)
        botones.rejected.connect(self.reject)
        botones.accepted.connect(self.accept)
        lay.addWidget(botones)

    @staticmethod
    def _crear_panel(panel: "SystemPanel", nombre: str, datos: bytes, sistema: str) -> QWidget:
        detalle = DetailPanel(panel._accent_getter)
        if sistema == "genesis":
            resultado = panel._analyze_genesis(nombre, datos)
        else:
            resultado = panel._analyze_snes(nombre, datos)
        badges, titulo, subtitulo, fields, hexdata, extra = resultado
        detalle.build(badges, titulo, subtitulo, fields, hexdata, extra_widget=extra)
        return detalle


class BatchReportDialog(QDialog):
    """Ventana de resultado de un proceso por lotes (lista larga, con scroll)."""

    def __init__(self, title: str, report_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(600, 440)
        lay = QVBoxLayout(self)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(report_text)
        text.setFont(mono_font(11))
        lay.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)


class TapeConvertDialog(QDialog):
    """Opciones de conversión CAS <-> WAV."""

    def __init__(self, direction: str, parent=None):
        super().__init__(parent)
        self.direction = direction  # "cas2wav" | "wav2cas"
        self.setWindowTitle("Convertir CAS → WAV" if direction == "cas2wav" else "Convertir WAV → CAS")
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        info = QLabel(
            "Codificación FSK 'Kansas City' de la BIOS del MSX. A 1200 baudios "
            "(el habitual) el bit 0 es un ciclo a 1200 Hz y el bit 1 son dos ciclos "
            "a 2400 Hz; a 2400 baudios (turbo) se dobla: 2400/4800 Hz."
            if direction == "cas2wav" else
            "Decodificación pensada para audio limpio (generado por esta misma "
            "herramienta, un emulador, etc.), no para grabaciones reales de casete "
            "con ruido — para eso hacen falta herramientas especializadas."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        baud_row = QHBoxLayout()
        baud_row.addWidget(QLabel("Baudios:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["1200 (estándar)", "2400 (turbo)"])
        baud_row.addWidget(self.baud_combo)
        lay.addLayout(baud_row)

        if direction == "cas2wav":
            rate_row = QHBoxLayout()
            rate_row.addWidget(QLabel("Frecuencia de muestreo:"))
            self.rate_combo = QComboBox()
            self.rate_combo.addItems(["44100 Hz", "48000 Hz", "22050 Hz"])
            rate_row.addWidget(self.rate_combo)
            lay.addLayout(rate_row)

            depth_row = QHBoxLayout()
            depth_row.addWidget(QLabel("Profundidad:"))
            self.depth_combo = QComboBox()
            self.depth_combo.addItems(["8 bit (como las herramientas clásicas)", "16 bit"])
            depth_row.addWidget(self.depth_combo)
            lay.addLayout(depth_row)

            pilot_row = QHBoxLayout()
            pilot_row.addWidget(QLabel("Tono piloto (segundos):"))
            self.pilot_edit = QLineEdit("2.0")
            pilot_row.addWidget(self.pilot_edit)
            lay.addLayout(pilot_row)

            mono_note = QLabel("El WAV se genera siempre en mono: el casete del MSX es una única línea de señal.")
            mono_note.setObjectName("Hint")
            mono_note.setWordWrap(True)
            lay.addWidget(mono_note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def baud(self) -> int:
        return 1200 if self.baud_combo.currentIndex() == 0 else 2400

    def sample_rate(self) -> int:
        return int(self.rate_combo.currentText().split()[0])

    def bit_depth(self) -> int:
        return 8 if self.depth_combo.currentIndex() == 0 else 16

    def pilot_seconds(self) -> float:
        try:
            v = float(self.pilot_edit.text().strip())
            return v if v > 0 else 2.0
        except ValueError:
            return 2.0


class SwcDiskFormatDialog(QDialog):
    """Elige entre 1.44 MB (estándar, más compatible) y 1.6 MB (el formato
    "superformateado" propio del Super Wild Card, algo más de capacidad por
    disco) antes de dividir una ROM en disquetes.

    Dos tarjetas grandes, una por formato: la seleccionada se resalta con
    marco verde. Se puede elegir con el ratón o siguen siendo accesibles
    por teclado (son QPushButton normales, marcables).
    """

    ESTILO_TARJETA = ESTILO_TARJETA_SELECCIONABLE

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Formato de los disquetes SWC")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        info = QLabel(
            "El Super Wild Card admite dos formatos de disquete de alta densidad. "
            "Elige cuál generar:"
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        fila = QHBoxLayout()
        fila.setSpacing(10)

        self.btn_1440 = QPushButton(
            "💾\n\n1.44 MB\nEstándar\n\nMás compatible con lectores\nUSB y FlashFloppy")
        self.btn_1440.setCheckable(True)
        self.btn_1440.setChecked(True)
        self.btn_1440.setMinimumHeight(140)
        self.btn_1440.setStyleSheet(self.ESTILO_TARJETA)

        self.btn_1600 = QPushButton(
            "💾\n\n1.6 MB\n\"Superformateado\"\n\nAlgo más de capacidad por disco\n"
            "(propio del SWC, 20 sect./pista)")
        self.btn_1600.setCheckable(True)
        self.btn_1600.setMinimumHeight(140)
        self.btn_1600.setStyleSheet(self.ESTILO_TARJETA)

        grupo = QButtonGroup(self)
        grupo.addButton(self.btn_1440)
        grupo.addButton(self.btn_1600)
        grupo.setExclusive(True)

        fila.addWidget(self.btn_1440)
        fila.addWidget(self.btn_1600)
        lay.addLayout(fila)

        hint = QLabel(
            "Si vas a usar los disquetes en un HxC o en una disquetera física del "
            "propio SWC, el de 1.6 MB es válido y algo más eficiente. Si los vas a leer "
            "o escribir con herramientas genéricas de PC, el de 1.44 MB es más seguro."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

    def formato(self) -> str:
        return "1600" if self.btn_1600.isChecked() else "1440"


class SmdDiskFormatDialog(QDialog):
    """Elige, de los cuatro formatos del Super Magic Drive, cuál usar antes
    de guardar una ROM en disco. Igual que SwcDiskFormatDialog para SNES,
    pero con cuatro tarjetas en vez de dos: el formato elegido se usa fijo
    para todas las ROMs seleccionadas, dividiendo en varios discos de ESE
    mismo tamaño si alguna no cabe en uno solo (nunca cambia de formato
    automáticamente a mitad de la operación).
    """

    ESTILO_TARJETA = ESTILO_TARJETA_SELECCIONABLE

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Formato de los disquetes del Super Magic Drive")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        info = QLabel(
            "Elige el formato de disco a usar. Si alguna ROM no cabe en un solo "
            "disco de este tamaño, se dividirá en varios del MISMO formato — nunca "
            "cambia de tamaño automáticamente a mitad de la operación."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        fila = QHBoxLayout()
        fila.setSpacing(8)

        textos = {
            "1600": "💾\n\n1.6 MB\n\"Superformateado\"\n\nMás capacidad por disco\n(20 sect./pista)",
            "1440": "💾\n\n1.44 MB\nEstándar HD\n\nMás compatible con\nlectores USB genéricos",
            "800":  "💾\n\n800 KB\n\"Superformateado\"\n\n(10 sect./pista)",
            "720":  "💾\n\n720 KB\nEstándar DD\n\nMás compatible con\nlectores USB genéricos",
        }
        self.botones: dict[str, QPushButton] = {}
        grupo = QButtonGroup(self)
        grupo.setExclusive(True)
        for clave in ("1600", "1440", "800", "720"):
            b = QPushButton(textos[clave])
            b.setCheckable(True)
            b.setMinimumHeight(150)
            b.setStyleSheet(self.ESTILO_TARJETA)
            grupo.addButton(b)
            fila.addWidget(b)
            self.botones[clave] = b
        self.botones["1600"].setChecked(True)  # el más característico del SMD, por defecto
        lay.addLayout(fila)

        hint = QLabel(
            "Los formatos \"superformateados\" (1.6 MB / 800 KB) son propios del Super "
            "Magic Drive / Super Wild Card: para leerlos o escribirlos hace falta una "
            "disquetera física real, o un Gotek con FlashFloppy/HxC convirtiendo antes "
            "a HFE. Los adaptadores USB de disquete genéricos solo admiten 720 KB y "
            "1.44 MB."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

    def formato(self) -> str:
        for clave, boton in self.botones.items():
            if boton.isChecked():
                return clave
        return "1600"


class SmdBlankDiskDialog(QDialog):
    """Crea disquetes vacíos con la geometría del Super Magic Drive/Super
    Wild Card — mismo formato de disco para ambos, solo cambia el nombre
    del copión que se muestra, según desde qué sistema se abra."""

    def __init__(self, parent=None, sistema: str = "genesis"):
        super().__init__(parent)
        nombre_copion = "Super Wild Card" if sistema == "snes" else "Super Magic Drive"
        self.setWindowTitle(f"Crear disco vacío del {nombre_copion}")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        info = QLabel(
            "La geometría de estos 4 formatos se extrajo directamente del firmware "
            "del propio copiador (misma tabla, verificada en dos versiones distintas "
            "de la BIOS). El de 1600 KB es el formato \"superformateado\" propio del "
            f"{nombre_copion}, no un tamaño estándar de disquete."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        fila_fmt = QHBoxLayout()
        fila_fmt.addWidget(QLabel("Formato:"))
        self.fmt_combo = QComboBox()
        for clave, f in rf.SMD_DISK_FORMATS.items():
            etiqueta = f.label.replace("Super Magic Drive", nombre_copion)
            self.fmt_combo.addItem(etiqueta, clave)
        self.fmt_combo.setCurrentIndex(0)  # el de 1600 KB, el más característico
        fila_fmt.addWidget(self.fmt_combo, 1)
        lay.addLayout(fila_fmt)

        fila_nombre = QHBoxLayout()
        fila_nombre.addWidget(QLabel("Nombre base:"))
        self.name_edit = QLineEdit("SMDISK01")
        fila_nombre.addWidget(self.name_edit, 1)
        lay.addLayout(fila_nombre)

        fila_num = QHBoxLayout()
        fila_num.addWidget(QLabel("Cantidad:"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 50)
        self.count_spin.setValue(1)
        fila_num.addWidget(self.count_spin)
        fila_num.addStretch(1)
        lay.addLayout(fila_num)

        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

    def valores(self) -> tuple[str, int, str]:
        return (self.fmt_combo.currentData(), self.count_spin.value(),
                self.name_edit.text().strip() or "SMDISK")


class BlankDiskDialog(QDialog):
    """Pide nombre base y cantidad de disquetes MSX vacíos a crear."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crear disquetes MSX vacíos")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        info = QLabel(
            "Crea imágenes .dsk de 720 KB recién formateadas y vacías (formato "
            "estándar MSX: 80 pistas, 9 sectores, doble cara). Los nombres se "
            "numeran automáticamente."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        fila_nombre = QHBoxLayout()
        fila_nombre.addWidget(QLabel("Nombre base:"))
        self.name_edit = QLineEdit("MSXDD001")
        self.name_edit.setToolTip(
            "Si termina en dígitos, la numeración continúa desde ese valor "
            "(MSXDD001, MSXDD002, ...)"
        )
        self.name_edit.textChanged.connect(self._update_preview)
        fila_nombre.addWidget(self.name_edit, 1)
        lay.addLayout(fila_nombre)

        fila_fmt = QHBoxLayout()
        fila_fmt.addWidget(QLabel("Formato:"))
        self.fmt_combo = QComboBox()
        for clave, f in rf.MSX_DISK_FORMATS.items():
            self.fmt_combo.addItem(f.label, clave)
        self.fmt_combo.currentIndexChanged.connect(self._update_preview)
        fila_fmt.addWidget(self.fmt_combo, 1)
        lay.addLayout(fila_fmt)

        fila_sys = QHBoxLayout()
        fila_sys.addWidget(QLabel("Sistema:"))
        self.sys_combo = QComboBox()
        self.sys_combo.addItem("Ninguno (disco vacío)", "")
        for clave, (etiqueta, _f) in md.DOS_VERSIONS.items():
            self.sys_combo.addItem(etiqueta, clave)
        self.sys_combo.currentIndexChanged.connect(self._update_preview)
        fila_sys.addWidget(self.sys_combo, 1)
        self.utils_chk = QCheckBox("Incluir utilidades")
        self.utils_chk.setChecked(True)
        self.utils_chk.setToolTip("Añadir también los archivos de la carpeta «msxdos_utils»")
        self.utils_chk.stateChanged.connect(self._update_preview)
        fila_sys.addWidget(self.utils_chk)
        lay.addLayout(fila_sys)

        fila_num = QHBoxLayout()
        fila_num.addWidget(QLabel("Cantidad:"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 100)
        self.count_spin.setValue(1)
        self.count_spin.valueChanged.connect(self._update_preview)
        fila_num.addWidget(self.count_spin)
        fila_num.addWidget(QLabel("(máximo 100)"))
        fila_num.addStretch(1)
        lay.addLayout(fila_num)

        fila_etiq = QHBoxLayout()
        fila_etiq.addWidget(QLabel("Etiqueta de volumen:"))
        self.label_edit = QLineEdit("")
        self.label_edit.setPlaceholderText("opcional, máx. 11 caracteres")
        self.label_edit.setMaxLength(11)
        fila_etiq.addWidget(self.label_edit, 1)
        lay.addLayout(fila_etiq)

        self.preview = QLabel("")
        self.preview.setObjectName("Hint")
        self.preview.setWordWrap(True)
        lay.addWidget(self.preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Crear")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._update_preview()

    @staticmethod
    def split_numeric_suffix(nombre: str) -> tuple[str, int, int]:
        """Separa 'MSXDD001' en ('MSXDD', 1, 3): prefijo, número y ancho."""
        i = len(nombre)
        while i > 0 and nombre[i - 1].isdigit():
            i -= 1
        if i == len(nombre):
            return nombre, 1, 3          # sin dígitos: empezar en 1
        digitos = nombre[i:]
        return nombre[:i], int(digitos), len(digitos)

    def names(self) -> list[str]:
        prefijo, inicio, ancho = self.split_numeric_suffix(self.name_edit.text().strip() or "MSXDD001")
        return [f"{prefijo}{str(inicio + i).zfill(ancho)}.dsk"
                for i in range(self.count_spin.value())]

    def volume_label(self) -> str:
        return self.label_edit.text().strip()

    def disk_format(self) -> str:
        return self.fmt_combo.currentData()

    def dos_version(self) -> str:
        return self.sys_combo.currentData()

    def include_utils(self) -> bool:
        return self.utils_chk.isChecked()

    def _update_preview(self):
        nombres = self.names()
        f = rf.MSX_DISK_FORMATS[self.disk_format()]
        kb = f.size // 1024
        if len(nombres) == 1:
            texto = f"Se creará: {nombres[0]}"
        else:
            texto = f"Se crearán {len(nombres)}: {nombres[0]}, {nombres[1]} … {nombres[-1]}"
        texto += f"   ·   {len(nombres) * kb} KB en total"

        version = self.dos_version()
        self.utils_chk.setEnabled(bool(version))
        if version:
            plan = md.plan_system_disk(
                ws.folder("msxdos", "msx"), ws.folder("msxdos_utils", "msx"), version,
                self.disk_format(), self.include_utils(), self.volume_label(),
            )
            if plan.errors:
                texto += "\n\n⚠ " + plan.errors[0]
            else:
                archivos = ", ".join(n for n, _d in plan.files[:6])
                if len(plan.files) > 6:
                    archivos += f" … (+{len(plan.files)-6})"
                texto += (f"\n\nContenido: {archivos}"
                          f"\nOcupa {rf.fmt_bytes(plan.used_bytes)} de "
                          f"{rf.fmt_bytes(plan.free_bytes)} libres")
                if plan.boot_source:
                    texto += f"\nArranque copiado de: {plan.boot_source}"
                elif plan.warnings:
                    texto += "\n⚠ sin código de arranque: probablemente arranque en DISK-BASIC"
        self.preview.setText(texto)


class MapperInfoDialog(QDialog):
    """Lista de referencia de mappers MSX conocidos, tradicionales y modernos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mappers MSX conocidos")
        self.resize(620, 480)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        intro = QLabel(
            "Esta app detecta activamente los mappers marcados con ✅ (heurística de "
            "direcciones para los clásicos; firma exacta para NEO-8/NEO-16). Los marcados "
            "con ⬜ se documentan aquí pero no se autodetectan por falta de direcciones de "
            "conmutación publicadas de forma fiable."
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setFont(mono_font(11))
        lines = []
        for cat in ("clásico", "moderno"):
            lines.append(f"— {cat.upper()} " + "-" * 40)
            for m in rf.KNOWN_MSX_MAPPERS:
                if m.category != cat:
                    continue
                mark = "✅" if m.detected else "⬜"
                lines.append(f"{mark} {m.name}")
                lines.append(f"   {m.description}")
                lines.append("")
        text.setPlainText("\n".join(lines))
        lay.addWidget(text)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)


class SystemPanel(QWidget):
    def __init__(self, system: str, accent_getter):
        super().__init__()
        self.system = system
        self._accent_getter = accent_getter
        self._files: list[str] = []          # rutas absolutas
        self._dsk_ctx: Optional[tuple[str, rf.DskImage]] = None
        self._workbench = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        toolbar = QHBoxLayout()
        self.path_lbl = QLabel("Ninguna carpeta seleccionada")
        self.path_lbl.setObjectName("Hint")
        toolbar.addWidget(self.path_lbl, 1)
        if system == "msx":
            mappers_btn = QPushButton("🛈  Mappers MSX")
            mappers_btn.clicked.connect(lambda: MapperInfoDialog(self._active_parent()).exec())
            toolbar.addWidget(mappers_btn)
        root.addLayout(toolbar)

        self._current_path: Optional[str] = None
        self._current_name: Optional[str] = None
        self._current_data: Optional[bytes] = None

        if system == "snes":
            root.addWidget(self._build_snes_tools())
            root.addWidget(build_floppy_writer_panel(self, icon_path, "SUPER WILD CARD"))
        if system == "msx":
            root.addWidget(self._build_tape_tools())
            root.addWidget(build_disk_panel(self, icon_path))
        if system == "genesis":
            root.addWidget(self._build_genesis_tools())
            root.addWidget(build_floppy_writer_panel(self, icon_path, "SUPER MAGIC DRIVE"))

        splitter = QSplitter(Qt.Horizontal)

        # --- panel izquierdo: originales (arriba) + generados (abajo) ---
        left_split = QSplitter(Qt.Vertical)
        left_split.setMinimumWidth(420)

        originals_box = QWidget()
        ol = QVBoxLayout(originals_box)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(4)
        self.orig_lbl = QLabel("ARCHIVOS DE ORIGEN")
        self.orig_lbl.setObjectName("SectionLabel")
        cabecera_orig = QHBoxLayout()
        cabecera_orig.addWidget(self.orig_lbl)
        cabecera_orig.addStretch(1)
        btn_todo_orig = QPushButton("Todo")
        btn_todo_orig.setToolTip("Seleccionar todos los archivos de origen (Ctrl+A)")
        btn_todo_orig.setFixedHeight(20)
        btn_todo_orig.setStyleSheet(BOTON_SELECCIONAR_TODO + "QPushButton { padding: 0px 8px; font-size: 10px; }")
        btn_todo_orig.clicked.connect(lambda: self.file_list.selectAll())
        cabecera_orig.addWidget(btn_todo_orig)
        ol.addLayout(cabecera_orig)
        self.file_list = QListWidget()
        _configure_multicolumn(self.file_list)
        self.file_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.file_list.currentItemChanged.connect(self._on_select)
        self.file_list.setMouseTracking(True)
        self.file_list.itemEntered.connect(self._on_filelist_hover)
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self._source_context_menu)
        sc_src = QShortcut(QKeySequence("Ctrl+E"), self.file_list)
        sc_src.setContext(Qt.WidgetShortcut)
        sc_src.activated.connect(self._select_source_by_extension)
        self._preview_cache: dict[str, str] = {}
        ol.addWidget(self.file_list, 1)
        hint_row = QHBoxLayout()
        sel_hint = QLabel("Ctrl+clic o Mayús+clic: varios · Ctrl+A: todo · Ctrl+E: misma extensión")
        sel_hint.setObjectName("Hint")
        sel_hint.setStyleSheet("font-size: 10px;")
        hint_row.addWidget(sel_hint, 1)
        col_lbl = QLabel("Ancho de columna:")
        col_lbl.setObjectName("Hint")
        col_lbl.setStyleSheet("font-size: 10px;")
        self.col_slider = QSlider(Qt.Horizontal)
        self.col_slider.setRange(140, 520)
        self.col_slider.setValue(LIST_COLUMN_WIDTH)
        self.col_slider.setFixedWidth(110)
        self.col_slider.setToolTip(
            "Ajusta el ancho de las columnas de ambas listas. Más estrecho = más "
            "archivos visibles a la vez; más ancho = nombres largos legibles."
        )
        self.col_slider.valueChanged.connect(self._set_column_width)
        hint_row.addWidget(col_lbl)
        hint_row.addWidget(self.col_slider)
        ol.addLayout(hint_row)

        # Leyenda de colores por formato
        leyenda = QLabel(
            "  ".join(
                f'<span style="color:{EXT_COLORS[e]}">■ {n}</span>'
                for e, n in (
                    (".sfc", "SNES"), (".smd", "Mega Drive"), (".rom", "MSX ROM"),
                    (".dsk", "disco"), (".cas", "CAS"), (".tsx", "TSX"), (".wav", "WAV"),
                )
            )
        )
        leyenda.setTextFormat(Qt.RichText)
        leyenda.setStyleSheet("font-size: 10px;")
        ol.addWidget(leyenda)
        left_split.addWidget(originals_box)

        generated_box = QWidget()
        gl = QVBoxLayout(generated_box)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(4)
        gen_head = QHBoxLayout()
        self.gen_lbl = QLabel("ARCHIVOS GENERADOS")
        self.gen_lbl.setObjectName("SectionLabel")
        gen_head.addWidget(self.gen_lbl, 1)
        refresh_btn = QPushButton("Refrescar")
        refresh_btn.setToolTip("Volver a escanear las carpetas de resultados")
        refresh_btn.clicked.connect(self.refresh_generated)
        clear_btn = QPushButton("Vaciar lista")
        clear_btn.setToolTip("Quita los archivos de esta lista (NO los borra del disco)")
        clear_btn.clicked.connect(self.clear_generated)
        btn_todo_gen = QPushButton("Todo")
        btn_todo_gen.setToolTip("Seleccionar todos los archivos generados (Ctrl+A)")
        btn_todo_gen.setStyleSheet(BOTON_SELECCIONAR_TODO)
        btn_todo_gen.clicked.connect(lambda: self.generated_list.selectAll())
        gen_head.addWidget(btn_todo_gen)
        gen_head.addWidget(refresh_btn)
        gen_head.addWidget(clear_btn)
        gl.addLayout(gen_head)
        self.generated_list = QListWidget()
        _configure_multicolumn(self.generated_list)
        self.generated_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.generated_list.currentItemChanged.connect(self._on_select_generated)
        self.generated_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.generated_list.customContextMenuRequested.connect(self._generated_context_menu)
        sc_gen = QShortcut(QKeySequence("Ctrl+E"), self.generated_list)
        sc_gen.setContext(Qt.WidgetShortcut)
        sc_gen.activated.connect(lambda: self.select_generated_by_extension())
        gl.addWidget(self.generated_list, 1)
        left_split.addWidget(generated_box)

        # Qué lista manda al operar: la última en la que el usuario ha
        # seleccionado algo. Sin esto, una selección antigua en "origen"
        # eclipsaría la selección nueva en "generados" (y viceversa).
        self._active_list = self.file_list
        self._suppress_active_tracking = False
        self.file_list.itemSelectionChanged.connect(
            lambda: self._set_active_list(self.file_list))
        self.generated_list.itemSelectionChanged.connect(
            lambda: self._set_active_list(self.generated_list))

        left_split.setStretchFactor(0, 3)
        left_split.setStretchFactor(1, 2)
        splitter.addWidget(left_split)

        # rutas registradas de archivos generados en esta sesión, y carpetas
        # donde buscar al pulsar "refrescar"
        self._generated: list[str] = []
        # Todas las subcarpetas de resultados se conocen de antemano, así el
        # botón "Refrescar" funciona aunque aún no se haya generado nada en
        # esta sesión (por ejemplo, resultados de una ejecución anterior).
        self._generated_dirs: set[str] = {
            ruta for _sistema, clave, ruta in ws.all_folders() if clave != "source"
        }

        self.detail = DetailPanel(accent_getter)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([560, 620])
        root.addWidget(splitter, 1)

        self.load_workspace_source()

    def _set_column_width(self, width: int):
        for lst in (self.file_list, self.generated_list):
            lst.setGridSize(QSize(width, LIST_ROW_HEIGHT))

    def _open_workspace(self):
        """Abre el explorador propio de la carpeta de trabajo.

        Es una ventana de la propia aplicación, no una llamada al sistema:
        QDesktopServices fallaba en silencio en equipos sin escritorio o sin
        xdg-open, y el botón parecía no hacer nada. Así funciona siempre.
        """
        try:
            from workspace_browser import WorkspaceBrowser
        except ImportError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo abrir la ventana: {e}")
            return

        dlg = WorkspaceBrowser(self, icon_dir=_icon_base_dir())
        dlg.abrir_archivo.connect(self._abrir_desde_explorador)
        dlg.abrir_imagenes.connect(self._abrir_imagenes_desde_explorador)
        dlg.abrir_carpeta.connect(self.open_workbench)
        dlg.exec()

    def _abrir_desde_explorador(self, ruta: str):
        """Analiza en el panel de detalle un archivo elegido en el explorador.

        El sistema se decide por el CONTENIDO real del archivo (con
        system_detect.detectar), no por la pestaña que tengas activa en la
        pantalla de inicio: antes se usaba self.system directamente, así
        que si tenías la pestaña de MSX activa y elegías una ROM de Mega
        Drive desde el explorador, se abrían las herramientas de MSX en
        vez de las de Mega Drive — el archivo elegido manda, no la pestaña.
        """
        if not os.path.isfile(ruta):
            return
        try:
            with open(ruta, "rb") as fh:
                datos = fh.read()
        except OSError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo leer el archivo: {e}")
            return
        self.register_generated(ruta)
        nombre = os.path.basename(ruta)
        self._current_path, self._current_name, self._current_data = ruta, nombre, datos
        sistema = sd.detectar(datos, nombre).sistema
        if sistema == "msx":
            self._render_msx(nombre, datos)
        elif sistema == "genesis":
            self._render_genesis(nombre, datos)
        else:
            self._render_snes(nombre, datos)

    def _abrir_imagenes_desde_explorador(self, rutas: list):
        """Abre imágenes de disco directamente en la ventana de extracción."""
        try:
            from extract_dialog import ExtractFilesDialog, MAX_IMAGENES
        except ImportError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo abrir la ventana: {e}")
            return
        imagenes, fallos = [], []
        for ruta in rutas[:MAX_IMAGENES]:
            try:
                with open(ruta, "rb") as fh:
                    datos = fh.read()
                if rf.detect_copia720_single_sided(datos):
                    datos = rf.copia720_to_single_sided(datos)
                imagenes.append((os.path.basename(ruta), rf.parse_dsk(datos)))
            except Exception as e:  # noqa: BLE001
                fallos.append(f"{os.path.basename(ruta)}: {e}")
        if not imagenes:
            QMessageBox.warning(
                self, APP_TITLE,
                "No se pudo leer ninguna imagen:\n\n" + "\n".join(fallos))
            return
        ExtractFilesDialog(imagenes, self._active_parent()).exec()

    # -- selección de carpeta -------------------------------------------------
    # Herramientas que se ofrecen en la ventana de trabajo, por sistema
    ACCIONES_TRABAJO = {
        "snes": [
            ("strip", "Quitar cabecera de copiador", "Elimina los 512 bytes de cabecera"),
            ("swc", "Añadir cabecera Super Wild Card", "Deja la ROM lista para el copión"),
            ("hdr", "Añadir cabecera genérica", "512 bytes en cero"),
            ("checksum", "Corregir checksum", "Recalcula y corrige el checksum interno"),
            ("deint", "Intercambiar bancos HiROM → normal",
             "Deshace el intercambio de mitades de 32 KB dentro de cada banco de 64 KB"),
            ("int", "Intercambiar bancos HiROM → copiador",
             "Aplica el intercambio de mitades que esperan algunos copiadores"),
            ("prep_swc", "★ Añadir cabecera y dividir SWC",
             "Hace los dos pasos de una vez: añade la cabecera Super Wild Card "
             "y divide el resultado en disquetes (elige entre 1.44 o 1.6 MB)"),
            ("rebuild_disks", "↩ Reconstruir desde discos divididos",
             "Recompone el archivo original con su cabecera a partir de uno o "
             "varios discos ya divididos (de esta aplicación o de cualquier "
             "otra): basta con seleccionar uno cualquiera, el resto de la "
             "serie se localiza sola en la misma carpeta"),
            ("split", "Dividir archivo en partes",
             "Corte mecánico cada N bytes, sin cabecera ni formato de disco "
             "(disquetes de época, tamaños de MegaROM, o un tamaño a tu elección)"),
            ("rename83", "Renombrar a 8.3", "Genera un nombre corto válido para FAT (MSX-DOS y similares)"),
            ("export_hfe", "Exportar a HFE (HxC / FlashFloppy)",
             "Convierte una imagen .img/.dsk ya generada a formato HFEv3, para probarla "
             "sin escribir un disquete físico"),
        ],
        "genesis": [
            ("byteswap", "Byte swap (16 bits)", "Corrige el orden de bytes del volcado"),
            ("smd2bin", "SMD → BIN (unir par/impar)",
             "Vuelve a mezclar los bytes pares e impares que el formato SMD separa"),
            ("bin2smd", "★ Convertir a formato SMD (un solo archivo)",
             "Construye la cabecera de 512 bytes del Super Magic Drive Y separa "
             "los bytes por paridad, las dos cosas juntas: así es exactamente "
             "como uCON64 (--smd) genera un .smd real, no son dos pasos "
             "independientes. Genera un archivo .smd, NO un disco: para eso "
             "está «Añadir cabecera SMD y guardar en disco», más abajo"),
            ("strip_smd", "Quitar cabecera SMD", ""),
            ("prep_smd", "★ Añadir cabecera SMD y guardar en disco",
             "Convierte la ROM y la guarda en el disco más pequeño que quepa de "
             "los 4 formatos del Super Magic Drive (un solo disco; el multi-disco "
             "no está soportado todavía)"),
            ("rebuild_disks", "↩ Reconstruir desde discos divididos",
             "Recompone el archivo original con su cabecera a partir de uno o "
             "varios discos ya divididos (de esta aplicación o de cualquier "
             "otra): basta con seleccionar uno cualquiera, el resto de la "
             "serie se localiza sola en la misma carpeta"),
            ("split", "Dividir archivo en partes",
             "Corte mecánico cada N bytes, sin cabecera ni formato de disco "
             "(disquetes de época, tamaños de MegaROM, o un tamaño a tu elección)"),
            ("rename83", "Renombrar a 8.3", "Genera un nombre corto válido para FAT (MSX-DOS y similares)"),
            ("export_hfe", "Exportar a HFE (HxC / FlashFloppy)",
             "Convierte una imagen .dsk ya generada a formato HFEv3, para probarla "
             "sin escribir un disquete físico"),
        ],
        "msx": [
            ("extraer", "Explorar archivos (máx. 3)",
             "Abre la ventana de extracción con hasta 3 discos"),
            ("extraer_todo", "★ Extraer varias imágenes de golpe",
             "Extrae el contenido completo de todas las imágenes seleccionadas, "
             "cada una en su propia subcarpeta"),
            ("c720_trim", "Recortar imagen COPIA720 (720→360)", ""),
            ("c720_exp", "Expandir para COPIA720 (360→720)", ""),
            ("cas2wav", "Cinta CAS → WAV", ""),
            ("wav2cas", "Cinta WAV → CAS", ""),
            ("cas2tsx", "Cinta CAS → TSX", ""),
            ("tsx2cas", "Cinta TSX → CAS", ""),
            ("tsx2wav", "Cinta TSX → WAV", "Pasa por CAS internamente"),
            ("wav2tsx", "Cinta WAV → TSX", "Pasa por CAS internamente"),
            ("split", "Dividir archivo en partes",
             "Corte mecánico cada N bytes, sin cabecera ni formato de disco "
             "(disquetes de época, tamaños de MegaROM, o un tamaño a tu elección)"),
            ("rename83", "Renombrar a 8.3", "Genera un nombre corto válido para MSX-DOS (FAT12)"),
            ("export_hfe", "Exportar a HFE (HxC / FlashFloppy)",
             "Convierte una imagen .dsk ya generada a formato HFEv3, para probarla "
             "sin escribir un disquete físico"),
        ],
    }

    def _active_parent(self) -> QWidget:
        """Ventana correcta para mostrar avisos y diálogos de resultado.

        Si la ventana grande de trabajo está abierta, los avisos deben
        colgar de ELLA, no de este panel (que en ese momento suele estar
        tapado detrás). Antes todos los QMessageBox y BatchReportDialog se
        mostraban con `self` como padre; si se lanzaban desde dentro de la
        ventana de trabajo, el resultado se veía —o el panel se actualizaba—
        detrás de ella, y daba la sensación de que el botón no había hecho
        nada, aunque la operación sí se hubiera ejecutado y guardado.
        """
        wb = getattr(self, "_workbench", None)
        if wb is not None:
            try:
                if wb.isVisible():
                    return wb
            except RuntimeError:
                # El objeto de Qt ya fue destruido por debajo
                self._workbench = None
        return self

    def pick_directory(self):
        directory = choose_directory(self)
        if not directory:
            return
        # Se carga también en la lista lateral, para no perder ese acceso, pero
        # el trabajo de verdad se hace en la ventana grande.
        self.load_directory(directory)
        self._open_workbench_deferred(directory)

    def _open_workbench_deferred(self, directory: str):
        """Abre la ventana de trabajo en cuanto el bucle de eventos esté libre.

        «Elegir carpeta» anida un diálogo interno («Explorar aquí…», nuestro
        propio navegador) dentro de otro diálogo modal (el selector con
        volúmenes), y ambos se cierran en el mismo evento de clic. Abrir
        inmediatamente después una ventana NO modal (la de trabajo) puede
        dejarla con el agarre de ratón o teclado heredado de esos diálogos
        que se están cerrando: se ve, pero ningún botón responde a los
        clics. Diferir la apertura con QTimer a 0 hace que ocurra en una
        vuelta limpia del bucle de eventos, con todo lo anterior ya
        completamente cerrado. Con un nivel más de diálogos anidados que
        antes (ver el refuerzo de raise()/activateWindow() en
        open_workbench), un margen pequeño pero no nulo es más robusto que
        0 puro.
        """
        QTimer.singleShot(30, lambda: self.open_workbench(directory))

    def open_workbench(self, directory: str):
        """Abre la ventana grande de trabajo sobre una carpeta."""
        try:
            from file_workbench import FileWorkbench
        except ImportError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo abrir la ventana: {e}")
            return
        # Se le pasan TODAS las herramientas: la ventana elige las del sistema
        # que detecte en la carpeta, y permite cambiarlo a mano.
        dlg = FileWorkbench(directory, self.system, self.ACCIONES_TRABAJO,
                            icon_dir=_icon_base_dir(), parent=self)
        dlg.analizar.connect(self._abrir_desde_explorador)
        dlg.accion.connect(self._accion_workbench)
        dlg.comprobar_discos.connect(self._comprobar_discos)
        dlg.analizar_roms.connect(self._analizar_roms_seleccionadas)
        dlg.volver_a_asturconsole.connect(lambda: (dlg.close(), self._open_workspace()))
        self._workbench = dlg

        # IMPORTANTE: se abre con show(), no con exec(). Las herramientas que
        # se lanzan desde aquí muestran sus propios avisos (QMessageBox,
        # informes por lotes...) con esta ventana principal como padre, no
        # con FileWorkbench. Si FileWorkbench fuera modal (exec()), esos
        # avisos podían quedar tapados detrás de ella y todo el flujo daba
        # la sensación de "no hacer nada" al pulsar un botón, aunque la
        # operación sí se hubiera ejecutado y guardado el resultado.
        def _al_cerrar(_resultado=None):
            if getattr(self, "_workbench", None) is dlg:
                self._workbench = None
        dlg.finished.connect(_al_cerrar)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        # Refuerzo: con «Elegir carpeta» ahora hay DOS diálogos modales
        # anidados en el mismo clic (el selector de volúmenes, y dentro de
        # él, «Explorar aquí…», nuestro propio navegador) en vez de uno como
        # antes de tener navegador propio. Con dos niveles, un solo
        # raise()/activateWindow() inmediato a veces no basta: el gestor de
        # ventanas puede tardar un instante más en asentarse tras cerrar
        # ambos, y la ventana de trabajo queda creada y visible pero por
        # detrás de la principal, aunque el código ya haya pedido traerla
        # al frente. Repetirlo una vez más, con un pequeño margen, es
        # mucho más fiable que un único intento inmediato.
        QTimer.singleShot(60, lambda: (dlg.raise_(), dlg.activateWindow()))

    def _comprobar_discos(self, rutas: list):
        """Abre la comprobación en dos columnas de un lote de imágenes."""
        try:
            from extract_dialog import DiskCheckDialog
        except ImportError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo abrir la ventana: {e}")
            return
        dlg = DiskCheckDialog(rutas, self._active_parent())
        dlg.extraer_compatibles.connect(self._extraer_lote_comprobado)
        dlg.exec()

    def _extraer_lote_comprobado(self, rutas: list):
        """Extrae en bloque las imágenes que la comprobación dio por buenas."""
        anterior = getattr(self, "_forced_paths", None)
        self._forced_paths = rutas
        try:
            self._msx_extract_many()
        finally:
            self._forced_paths = anterior

    def _analizar_roms_seleccionadas(self, rutas: list, sistema: str):
        """Abre la ventana de análisis de cabeceras para una o varias ROMs.

        Sustituye al antiguo comportamiento de actualizar el panel de detalle
        embebido en la ventana principal (que queda tapado detrás de la
        ventana de trabajo) y de mostrar solo la primera ROM seleccionada.
        """
        archivos, errores = [], []
        for ruta in rutas:
            try:
                with open(ruta, "rb") as fh:
                    datos = fh.read()
                archivos.append((os.path.basename(ruta), datos))
                self.register_generated(ruta)
            except OSError as e:
                errores.append(f"{os.path.basename(ruta)}: {e}")

        if not archivos:
            QMessageBox.warning(
                self._active_parent(), APP_TITLE,
                "No se pudo leer ningún archivo:\n\n" + "\n".join(errores))
            return

        dlg = RomAnalysisDialog(self, archivos, sistema, self._active_parent())
        dlg.exec()

        if errores:
            QMessageBox.warning(
                self._active_parent(), APP_TITLE,
                "Algunos archivos no se pudieron leer:\n\n" + "\n".join(errores))

    def _accion_workbench(self, clave: str, rutas: list, sistema: str = ""):
        """Aplica a los archivos seleccionados la herramienta elegida.

        `sistema` es el que detectó la propia ventana de trabajo para esa
        carpeta, que puede NO coincidir con `self.system` (la pestaña activa
        del panel principal): por ejemplo, si estando en la pestaña de MSX
        se abre una carpeta con ROMs de SNES, la ventana de trabajo detecta
        "snes", pero self.system seguiría siendo "msx". Las acciones que
        existen en varios sistemas a la vez (como "rename83") necesitan
        saber cuál de los dos es el correcto para guardar el resultado en
        la carpeta que toca.
        """
        # Se apoya en la selección de la lista lateral, que es lo que usan
        # todas las operaciones ya existentes: se sincroniza y se reutiliza.
        self._workbench_paths = rutas
        anterior = getattr(self, "_forced_paths", None)
        self._forced_paths = rutas
        sistema_anterior = getattr(self, "_workbench_system", None)
        self._workbench_system = sistema or self.system
        try:
            despachador = {
                "strip": self._snes_strip_header,
                "swc": lambda: self._snes_add_header("swc"),
                "hdr": lambda: self._snes_add_header("generic"),
                "checksum": self._snes_fix_checksum,
                "deint": lambda: self._snes_interleave_op(True),
                "int": lambda: self._snes_interleave_op(False),
                "prep_swc": self._snes_header_and_split,
                "rebuild_disks": self._rebuild_copier_disks,
                "extraer_todo": self._msx_extract_many,
                "byteswap": self._genesis_byteswap,
                "smd2bin": self._genesis_smd_to_bin,
                "bin2smd": self._genesis_bin_to_smd,
                "strip_smd": self._genesis_strip_header,
                "prep_smd": self._genesis_header_and_disk,
                "extraer": self._open_extract_dialog,
                "c720_trim": self._copia720_trim,
                "c720_exp": self._copia720_expand,
                "cas2wav": self._tape_cas_to_wav,
                "wav2cas": self._tape_wav_to_cas,
                "cas2tsx": self._tape_cas_to_tsx,
                "tsx2cas": self._tape_tsx_to_cas,
                "tsx2wav": self._tape_tsx_to_wav,
                "wav2tsx": self._tape_wav_to_tsx,
                "rename83": self._rename_to_8_3,
                "split": self._split_file_generic,
                "export_hfe": self._export_to_hfe,
                "send": self._send_to_copier,
            }.get(clave)
            if despachador is None:
                return
            # Para operaciones de un solo archivo, se usa el primero
            if len(rutas) == 1:
                try:
                    with open(rutas[0], "rb") as fh:
                        self._current_data = fh.read()
                    self._current_path = rutas[0]
                    self._current_name = os.path.basename(rutas[0])
                except OSError:
                    pass
            despachador()
        finally:
            self._forced_paths = anterior
            self._workbench_system = sistema_anterior
        if getattr(self, "_workbench", None) is not None:
            self._workbench.refrescar()

    MAX_SCAN_FILES = 3000

    def load_directory(self, directory: str):
        """Carga los archivos de una carpeta en la lista de originales.

        Solo el contenido DIRECTO de la carpeta elegida, sin bajar a
        subcarpetas: antes se recorría todo el árbol con os.walk, así que
        elegir una carpeta con pocos archivos propios pero con subcarpetas
        llenas (por ejemplo "MSX", que por dentro tiene "DSK MSX" con
        muchos .dsk) disparaba el aviso de "demasiados archivos" con
        contenido que ni siquiera pertenecía a la carpeta seleccionada.
        Esto además iguala el comportamiento con el de la ventana de
        trabajo, que tampoco baja a subcarpetas — así lo que se ve aquí y
        lo que se ve allí es siempre lo mismo. El límite de archivos se
        mantiene como protección residual, por si una sola carpeta tuviera
        miles de archivos sueltos directamente dentro.
        """
        if not directory or not os.path.isdir(directory):
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        encontrados: list[str] = []
        truncado = False
        try:
            for fn in os.listdir(directory):
                if fn.startswith(".") or fn == "LEEME.txt":
                    continue
                ruta = os.path.join(directory, fn)
                if not os.path.isfile(ruta):
                    continue
                encontrados.append(ruta)
                if len(encontrados) >= self.MAX_SCAN_FILES:
                    truncado = True
                    break
        except OSError:
            pass
        finally:
            QApplication.restoreOverrideCursor()

        self.path_lbl.setText(directory)
        self._preview_cache.clear()
        self._files = encontrados
        self._files.sort(key=lambda p: os.path.relpath(p, directory).lower())

        self.file_list.clear()
        for path in self._files:
            try:
                size = rf.fmt_bytes(os.path.getsize(path))
            except OSError:
                size = "?"
            rel = os.path.relpath(path, directory)
            item = QListWidgetItem(f"{rel}    {size}")
            item.setData(Qt.UserRole, path)
            item.setToolTip(f"{rel}\n{size}")
            item.setForeground(color_for_path(path))
            self.file_list.addItem(item)

        if truncado:
            QMessageBox.information(
                self, APP_TITLE,
                f"Esta carpeta tiene muchísimos archivos sueltos. Se han cargado los "
                f"primeros {self.MAX_SCAN_FILES} para no bloquear la aplicación.\n\n"
                "Prueba a organizarlos en subcarpetas si necesitas trabajar con todos.",
            )
        self.detail.show_placeholder("Selecciona un archivo de la lista para analizar su cabecera.")

    def load_workspace_source(self):
        """Al arrancar: cargar 'roms originales' si tiene contenido."""
        if ws.source_has_files():
            self.load_directory(ws.source_folder())
        else:
            self.path_lbl.setText(
                f"Deja tus archivos en:  {ws.source_folder()}   "
                "(o pulsa «Elegir carpeta»)"
            )

    # -- panel de archivos generados -------------------------------------
    def register_generated(self, paths):
        """Registra archivos recién creados para que aparezcan al instante
        en el panel inferior, sin esperar a un refresco."""
        if isinstance(paths, str):
            paths = [paths]
        nuevos = 0
        for p in paths:
            if not p:
                continue
            p = os.path.abspath(p)
            self._generated_dirs.add(os.path.dirname(p))
            if p not in self._generated:
                self._generated.append(p)
                nuevos += 1
        if nuevos:
            self._rebuild_generated_list()

    def _rebuild_generated_list(self):
        self.generated_list.clear()
        for p in self._generated:
            existe = os.path.isfile(p)
            try:
                size = rf.fmt_bytes(os.path.getsize(p)) if existe else "(no encontrado)"
            except OSError:
                size = "(?)"
            item = QListWidgetItem(f"{os.path.basename(p)}    {size}")
            item.setData(Qt.UserRole, p)
            item.setToolTip(f"{p}\n{size}")
            item.setForeground(color_for_path(p) if existe else QColor("#4d5468"))
            self.generated_list.addItem(item)

    def refresh_generated(self):
        """Re-escanea las carpetas de destino conocidas, para recoger también
        archivos creados fuera de la aplicación."""
        if not self._generated_dirs:
            QMessageBox.information(
                self, APP_TITLE,
                "Todavía no se ha generado ningún archivo en esta sesión, así que no hay "
                "carpetas de destino que refrescar.",
            )
            return
        conocidos = set(self._generated)
        encontrados = 0
        for d in sorted(self._generated_dirs):
            if not os.path.isdir(d):
                continue
            try:
                for fn in sorted(os.listdir(d)):
                    p = os.path.join(d, fn)
                    if os.path.isfile(p) and not fn.startswith(".") and p not in conocidos:
                        self._generated.append(p)
                        conocidos.add(p)
                        encontrados += 1
            except OSError:
                continue
        self._rebuild_generated_list()
        QMessageBox.information(
            self, APP_TITLE,
            f"Refrescado. Archivos nuevos encontrados en las carpetas de destino: {encontrados}",
        )

    def clear_generated(self):
        if not self._generated:
            return
        self._generated.clear()
        self._rebuild_generated_list()

    def _on_select_generated(self, current: QListWidgetItem, _previous):
        if current is None:
            return
        path = current.data(Qt.UserRole)
        if not os.path.isfile(path):
            self.detail.show_placeholder(f"El archivo ya no existe:\n{path}")
            return
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as e:
            self.detail.show_placeholder(f"No se pudo leer el archivo: {e}")
            return
        name = os.path.basename(path)
        self._current_path = path
        self._current_name = name
        self._current_data = data
        if self.system == "msx":
            self._render_msx(name, data)
        elif self.system == "genesis":
            self._render_genesis(name, data)
        else:
            self._render_snes(name, data)

    def _generated_context_menu(self, pos):
        item = self.generated_list.itemAt(pos)
        if item is None:
            return
        path = item.data(Qt.UserRole)
        ext = os.path.splitext(path)[1].lower()
        menu = QMenu(self.generated_list)
        act_same = menu.addAction(f"Seleccionar todos los «{ext or 'sin extensión'}»   (Ctrl+E)")
        act_all = menu.addAction("Seleccionar todo   (Ctrl+A)")
        menu.addSeparator()
        act_write = None
        if ext in (".dsk", ".img"):
            act_write = menu.addAction("Grabar en disquete físico…")
            menu.addSeparator()
        act_open = menu.addAction("Abrir carpeta contenedora")
        act_remove = menu.addAction("Quitar de la lista")
        chosen = menu.exec(self.generated_list.viewport().mapToGlobal(pos))
        if act_write is not None and chosen is act_write:
            self._write_image_to_disk(path)
        elif chosen is act_same:
            self.select_generated_by_extension(ext)
        elif chosen is act_all:
            self.generated_list.selectAll()
        elif chosen is act_open:
            folder = os.path.dirname(path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        elif chosen is act_remove:
            if path in self._generated:
                self._generated.remove(path)
                self._rebuild_generated_list()

    def _source_context_menu(self, pos):
        item = self.file_list.itemAt(pos)
        if item is None:
            return
        ext = os.path.splitext(item.data(Qt.UserRole))[1].lower()
        menu = QMenu(self.file_list)
        act_same = menu.addAction(f"Seleccionar todos los «{ext or 'sin extensión'}»   (Ctrl+E)")
        act_all = menu.addAction("Seleccionar todo   (Ctrl+A)")
        chosen = menu.exec(self.file_list.viewport().mapToGlobal(pos))
        if chosen is act_same:
            self._select_source_by_extension()
        elif chosen is act_all:
            self.file_list.selectAll()

    def select_generated_by_extension(self, ext: str | None = None):
        """Selecciona en la lista de generados todos los archivos con la misma
        extensión que el elemento actual (o la indicada). Los `.img` se
        excluyen salvo que sean justamente la extensión buscada, ya que son
        resultados finales que no procede volver a convertir."""
        if ext is None:
            item = self.generated_list.currentItem()
            if item is None:
                return
            ext = os.path.splitext(item.data(Qt.UserRole))[1].lower()
        ext = ext.lower()

        contados = 0
        self.generated_list.clearSelection()
        for i in range(self.generated_list.count()):
            it = self.generated_list.item(i)
            p = it.data(Qt.UserRole)
            p_ext = os.path.splitext(p)[1].lower()
            if p_ext == ext:
                it.setSelected(True)
                contados += 1
        if contados:
            self.path_lbl.setText(
                f"Seleccionados {contados} archivo(s) con extensión «{ext}» en la lista de generados"
            )

    def _select_source_by_extension(self):
        item = self.file_list.currentItem()
        if item is None:
            return
        ext = os.path.splitext(item.data(Qt.UserRole))[1].lower()
        contados = 0
        self.file_list.clearSelection()
        for i in range(self.file_list.count()):
            it = self.file_list.item(i)
            if os.path.splitext(it.data(Qt.UserRole))[1].lower() == ext:
                it.setSelected(True)
                contados += 1
        if contados:
            self.path_lbl.setText(f"Seleccionados {contados} archivo(s) con extensión «{ext}»")

    def _on_select(self, current: QListWidgetItem, _previous):
        if current is None:
            return
        path = current.data(Qt.UserRole)
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as e:
            self.detail.show_placeholder(f"No se pudo leer el archivo: {e}")
            return
        name = os.path.basename(path)
        self._current_path = path
        self._current_name = name
        self._current_data = data
        if self.system == "msx":
            self._render_msx(name, data)
        elif self.system == "genesis":
            self._render_genesis(name, data)
        else:
            self._render_snes(name, data)

    def _on_filelist_hover(self, item: QListWidgetItem):
        path = item.data(Qt.UserRole)
        if path in self._preview_cache:
            item.setToolTip(self._preview_cache[path])
            return
        try:
            size = os.path.getsize(path)
            if size > 1_572_864:  # ~1.5 MB: por encima de eso no parece un archivo MSX típico
                text = f"{os.path.basename(path)}  ·  {rf.fmt_bytes(size)}\n(archivo grande; vista previa omitida)"
            else:
                with open(path, "rb") as fh:
                    data = fh.read()
                text = rf.build_preview(os.path.basename(path), data)
        except OSError as e:
            text = f"No se pudo leer el archivo: {e}"
        self._preview_cache[path] = text
        item.setToolTip(text)

    # -- herramientas de conversión SNES ---------------------------------
    def _build_snes_tools(self) -> QWidget:
        box = QFrame()
        box.setObjectName("FieldChip")  # reutiliza el estilo de panel oscuro con borde
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title = QLabel("HERRAMIENTAS DE CONVERSIÓN (COPIADORAS DE ÉPOCA)")
        title.setObjectName("SectionLabel")
        lay.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_strip = QPushButton("Quitar cabecera")
        btn_strip.clicked.connect(self._snes_strip_header)
        btn_gen = QPushButton("Añadir cabecera genérica")
        btn_gen.clicked.connect(lambda: self._snes_add_header("generic"))
        btn_swc = QPushButton(" Añadir cabecera Super Wild Card")
        btn_swc.setIcon(QIcon(icon_path("superwildcard.svg")))
        btn_swc.clicked.connect(lambda: self._snes_add_header("swc"))
        btn_chk = QPushButton("Verificar / corregir checksum")
        btn_chk.clicked.connect(self._snes_fix_checksum)
        btn_deint = QPushButton("Intercambiar bancos HiROM → normal")
        btn_deint.clicked.connect(self._snes_deinterleave)
        btn_int = QPushButton("Intercambiar bancos HiROM → copiador")
        btn_int.clicked.connect(self._snes_interleave)
        btn_batch = QPushButton("🔁  Intercambiar bancos HiROM por lotes…")
        btn_batch.clicked.connect(self._snes_batch_byteswap)
        for b in (btn_strip, btn_gen, btn_swc, btn_chk, btn_deint, btn_int, btn_batch):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        row_hfe = QHBoxLayout()
        btn_hfe = QPushButton("💾  Exportar a HFE (HxC / FlashFloppy)…")
        btn_hfe.setToolTip(
            "Convierte una imagen .img ya generada (1.44 o 1.6 MB) a formato HFEv3, "
            "para probarla en un Gotek/HxC sin escribir un disquete físico")
        btn_hfe.clicked.connect(self._export_to_hfe)
        row_hfe.addWidget(btn_hfe)
        row_hfe.addStretch(1)
        lay.addLayout(row_hfe)

        hint = QLabel(
            "Actúan sobre el archivo seleccionado en la lista y siempre guardan el "
            "resultado como un archivo nuevo (nunca sobrescriben el original). "
            "Entrelazar/desentrelazar solo aplica a HiROM y solo al formato "
            "\"simple\" (Game Doctor / Super UFO / SWC mal configurada) — "
            "consulta el README para más detalle."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return box

    # -- conversor de cintas MSX (CAS <-> WAV <-> TSX) ---------------------
    # -- transferencia por puerto paralelo (copiones) ---------------------
    # -- herramientas Mega Drive -----------------------------------------
    def _build_genesis_tools(self) -> QWidget:
        box = QFrame()
        box.setObjectName("FieldChip")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title = QLabel("CONVERSIÓN DE FORMATO (SUPER MAGIC DRIVE)")
        title.setObjectName("SectionLabel")
        lay.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_to_bin = QPushButton("SMD → BIN (unir par/impar)")
        btn_to_bin.clicked.connect(self._genesis_smd_to_bin)
        btn_to_smd = QPushButton("★ Convertir a formato SMD (archivo)")
        btn_to_smd.setToolTip(
            "Añade la cabecera y entrelaza en par/impar, en un solo archivo .smd. "
            "No genera ningún disco: para eso está la sección de abajo.")
        btn_to_smd.clicked.connect(self._genesis_bin_to_smd)
        btn_strip = QPushButton("Quitar cabecera SMD")
        btn_strip.clicked.connect(self._genesis_strip_header)
        btn_swap = QPushButton("⇄  Byte swap (16 bits)")
        btn_swap.setObjectName("Primary")
        btn_swap.clicked.connect(self._genesis_byteswap)
        for b in (btn_swap, btn_to_bin, btn_to_smd, btn_strip):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        title2 = QLabel("DISCOS DEL SUPER MAGIC DRIVE")
        title2.setObjectName("SectionLabel")
        lay.addWidget(title2)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        btn_prep_disk = QPushButton("★  Añadir cabecera y guardar en disco")
        btn_prep_disk.setObjectName("Primary")
        btn_prep_disk.clicked.connect(self._genesis_header_and_disk)
        btn_blank_disk = QPushButton("Crear disco vacío…")
        btn_blank_disk.clicked.connect(self._genesis_blank_disk)
        row2.addWidget(btn_prep_disk)
        row2.addWidget(btn_blank_disk)
        row2.addStretch(1)
        lay.addLayout(row2)

        row3 = QHBoxLayout()
        btn_hfe_genesis = QPushButton("💾  Exportar a HFE (HxC / FlashFloppy)…")
        btn_hfe_genesis.setToolTip(
            "Convierte un disco .dsk ya generado a formato HFEv3, para probarlo en "
            "un Gotek/HxC sin escribir un disquete físico")
        btn_hfe_genesis.clicked.connect(self._export_to_hfe)
        row3.addWidget(btn_hfe_genesis)
        row3.addStretch(1)
        lay.addLayout(row3)

        hint2 = QLabel(
            "La geometría de los 4 formatos (1600/1440/800/720 KB) se extrajo "
            "directamente del firmware del propio copiador: se localizó y verificó la "
            "misma tabla de parámetros de disco, byte a byte, en TRES BIOS distintas "
            "(dos del Super Magic Drive, una del Super Wild Card — comparten firmware). "
            "El de 1600 KB es un formato \"superformateado\" propio del copiador (20 "
            "sectores por pista en vez de los 18 estándar), no un tamaño de disquete "
            "habitual.\n\n"
            "Si la ROM no cabe en un solo disco, se divide en varios del formato más "
            "grande (1600 KB): esto activa un campo de la cabecera SMD cuya existencia "
            "está confirmada en el propio formato, pero cuyo comportamiento exacto en "
            "el firmware del SMD es EXPERIMENTAL — no se ha podido verificar contra "
            "hardware real. Comprueba el resultado con un HxC antes que con un "
            "disquete físico."
        )
        hint2.setObjectName("Hint")
        hint2.setWordWrap(True)
        lay.addWidget(hint2)

        hint = QLabel(
            "«Byte swap» intercambia los dos bytes de cada palabra de 16 bits en todo el "
            "archivo: es lo que distingue un volcado normal (SEGA GENESIS en 0x100) de uno "
            "con los bytes intercambiados (ESAGG NESESI). Es su propia inversa, y la app "
            "detecta automáticamente en qué estado está cada archivo.\n\n"
            "El formato .smd del Super Magic Drive es otra cosa distinta: separa los "
            "bytes POR PARIDAD en bloques de 16 KB (primero los 8 KB de los bytes "
            "pares, después los 8 KB de los impares). El motivo es que la BIOS del "
            "copiador carga en modo de compatibilidad con Master System, donde quien "
            "accede a la memoria es el Z80, de 8 bits, y no el 68000 de 16 bits de la "
            "Mega Drive: por eso hay que separar los bytes por paridad. Entrelaza los "
            "bytes en bloques de 16 KB "
            "(mitad de una paridad, mitad de la otra) y añade una cabecera de 512 bytes. "
            "Al desentrelazar, la app verifica el resultado comprobando que aparezca la "
            "firma SEGA en el offset 0x100, y avisa si no la encuentra. Admite selección "
            "múltiple para procesar varios archivos a la vez."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return box

    def _genesis_byteswap(self):
        def transform(data, name):
            estado = gt.is_byteswapped(data)
            resultado = gt.byteswap(data)
            base, ext = os.path.splitext(name)
            if estado is True:
                detalle = ("El archivo tenía los bytes intercambiados; se ha devuelto al "
                           "orden normal (firma SEGA correcta en 0x100).")
                sufijo = "_normal"
            elif estado is False:
                detalle = ("El archivo estaba en orden normal; se han intercambiado los "
                           "bytes (quedará como ESAGG NESESI en 0x100).")
                sufijo = "_swapped"
            else:
                detalle = ("AVISO: no se reconoció la firma SEGA ni antes ni después del "
                           "intercambio. Puede no ser un ROM de Mega Drive estándar; "
                           "verifica el resultado.")
                sufijo = "_swap"
            return resultado, f"{base}{sufijo}{ext}", detalle
        self._run_operation("Byte swap", transform, "byteswap", "genesis")

    def _genesis_smd_to_bin(self):
        def transform(data, name):
            resultado, nota = gt.smd_to_bin(data)
            base, _ext = os.path.splitext(name)
            return resultado, f"{base}.bin", f"Convertido a formato plano.\n{nota}"
        self._run_operation("SMD → BIN (unir par/impar)", transform, "smd", "genesis")

    def _genesis_bin_to_smd(self):
        def transform(data, name):
            resultado = gt.bin_to_smd(data, add_header=True)
            base, _ext = os.path.splitext(name)
            return (resultado, f"{base}.smd",
                    "Convertido a formato SMD: cabecera de 512 bytes del Super Magic "
                    "Drive añadida y bytes separados por paridad, todo en un solo "
                    "paso (equivalente a uCON64 --smd).")
        self._run_operation("Añadir cabecera SMD y dividir en par/impar", transform, "smd", "genesis")

    def _genesis_strip_header(self):
        def transform(data, name):
            info = gt.detect_smd_header(data)
            if not info.present:
                raise ValueError("no tiene cabecera SMD de 512 bytes")
            base, ext = os.path.splitext(name)
            return (data[info.size:], f"{base}_sin_cabecera{ext}",
                    f"Cabecera SMD eliminada ({info.size} bytes; {info.notes}).")
        self._run_operation("Quitar cabecera SMD", transform, "no_header", "genesis")

    def _genesis_header_and_disk(self):
        """Añade la cabecera SMD (si hace falta) y guarda en disco(s) del
        Super Magic Drive, en el formato que elija el usuario.

        La geometría de los cuatro formatos (1600/1440/800/720 KB) se
        extrajo directamente del firmware del propio copiador (ver
        SMD_DISK_FORMATS en rom_formats.py), verificada en TRES BIOS
        distintas (dos del Super Magic Drive, una del Super Wild Card):
        la tabla es idéntica byte a byte en los tres firmwares.

        El formato elegido se usa FIJO para todas las ROMs seleccionadas:
        si alguna no cabe en un solo disco, se divide en varios discos del
        MISMO formato (nunca cambia de tamaño automáticamente a mitad de
        la operación) — igual que el combo equivalente de SNES.

        La división en varios discos (ver split_smd_disks en
        genesis_tools.py) es EXPERIMENTAL: activa un campo de la cabecera
        SMD ("split") cuya existencia está confirmada en el propio formato,
        pero cuyo comportamiento exacto en el firmware del SMD no se ha
        podido verificar contra hardware ni firmware real. Se basa en la
        analogía con el Super Wild Card, que usa el mismo mecanismo en la
        misma posición de su propia cabecera, y que SÍ está verificado con
        discos reales. Se recomienda comprobar el resultado con un HxC
        antes que con un disquete físico.
        """
        paths = self._selected_paths()
        if not paths and self._current_path:
            paths = [self._current_path]
        if not paths:
            QMessageBox.information(
                self._active_parent(), APP_TITLE,
                "Selecciona una o varias ROMs de Mega Drive para prepararlas.")
            return

        dlg_fmt = SmdDiskFormatDialog(self._active_parent())
        if dlg_fmt.exec() != QDialog.Accepted:
            return
        formato_disco = dlg_fmt.formato()
        formato_info = rf.SMD_DISK_FORMATS[formato_disco]

        out_dir = ws.folder("smd_disks", "genesis")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        ok_lines, skip_lines, generados = [], [], []
        algun_multidisco = False

        for path in paths:
            name = os.path.basename(path)
            try:
                with open(path, "rb") as fh:
                    datos = fh.read()

                info = gt.detect_smd_header(datos)
                if info.present:
                    smd_datos = datos
                    paso1 = "ya tenía cabecera SMD"
                else:
                    smd_datos = gt.bin_to_smd(datos, add_header=True)
                    paso1 = "cabecera SMD añadida"

                base = os.path.splitext(name)[0]

                if len(smd_datos) <= formato_info.free_bytes:
                    # Cabe en un solo disco del formato elegido.
                    nombre_83 = rf.rename_to_8_3(f"{base}.smd")
                    img = rf.write_files_to_smd_disk(
                        [(nombre_83, smd_datos)], fmt=formato_disco,
                        volume_label=rf.rename_to_8_3(base)[:8] or "GAME")
                    destino = ws.unique_path(out_dir, f"{base}_{formato_disco}kb.dsk")
                    with open(destino, "wb") as fh:
                        fh.write(img)
                    generados.append(destino)
                    ok_lines.append(
                        f"OK       {name}  ·  {paso1}  ->  disco de {formato_disco} KB "
                        f"({nombre_83})")
                else:
                    # No cabe en un solo disco del formato elegido: se divide
                    # en varios del MISMO formato (nunca cambia de tamaño).
                    partes = gt.split_smd_disks(smd_datos, base_name=base[:6], fmt=formato_disco)
                    for parte in partes:
                        destino = ws.unique_path(out_dir, parte.filename)
                        with open(destino, "wb") as fh:
                            fh.write(parte.image)
                        generados.append(destino)
                    algun_multidisco = True
                    ok_lines.append(
                        f"OK       {name}  ·  {paso1}  ->  {len(partes)} discos de "
                        f"{formato_disco} KB (★ multi-disco EXPERIMENTAL, ver aviso abajo)")
            except ValueError as e:
                skip_lines.append(f"OMITIDO  {name}\n           ({e})")
            except Exception as e:  # noqa: BLE001
                skip_lines.append(f"ERROR    {name}  ({e})")

        QApplication.restoreOverrideCursor()
        self.register_generated(generados)
        self._clear_selections()

        report = (
            f"Añadir cabecera SMD y guardar en disco — {len(paths)} ROM(s)\n"
            f"Carpeta de resultados: {out_dir}\n\n"
            f"Preparadas: {len(ok_lines)}   ·   omitidas/con error: {len(skip_lines)}\n\n"
            + ("⚠ Alguna ROM se dividió en varios discos (marcadas ★ arriba). Este "
               "mecanismo es EXPERIMENTAL: se basa en un campo de la cabecera SMD cuya "
               "existencia está confirmada, pero no se ha podido verificar contra "
               "hardware real que el firmware lo interprete como se espera. Antes de "
               "usar los discos generados en una disquetera física, compruébalos con "
               "un HxC si tienes uno a mano.\n\n" if algun_multidisco else "")
            + "Detalle:\n" + "\n".join(ok_lines + skip_lines)
        )
        BatchReportDialog("Preparar disco SMD — resultado", report, self._active_parent()).exec()

    def _smd_blank_disk(self):
        """Crea uno o varios disquetes vacíos con la geometría del Super
        Magic Drive / Super Wild Card, en el formato que elija el usuario
        (720/800/1440/1600 KB) — sirve igual para SNES y Genesis, la
        geometría es la misma para ambos copiones."""
        dlg = SmdBlankDiskDialog(self._active_parent(), sistema=self.system)
        if dlg.exec() != QDialog.Accepted:
            return
        clave, cantidad, base_nombre = dlg.valores()
        out_dir = (ws.folder("smd_disks", "genesis") if self.system == "genesis"
                  else ws.folder("swc_disks", "snes"))
        generados = []
        for i in range(1, cantidad + 1):
            etiqueta = f"{base_nombre}{i:02d}" if cantidad > 1 else base_nombre
            img = rf.make_blank_smd_disk(etiqueta[:11], fmt=clave)
            destino = ws.unique_path(out_dir, f"{etiqueta}_{clave}kb.img")
            with open(destino, "wb") as fh:
                fh.write(img)
            generados.append(destino)
        self.register_generated(generados)
        QMessageBox.information(
            self._active_parent(), APP_TITLE,
            f"Creado(s) {cantidad} disco(s) vacío(s) de {clave} KB en:\n{out_dir}")

    def _genesis_blank_disk(self):
        """Alias histórico: el botón de la pantalla principal de Genesis
        sigue llamando a este nombre; la lógica ya es la unificada."""
        self._smd_blank_disk()

    def _export_to_hfe(self):
        """Convierte a formato HFEv3 (para HxC / FlashFloppy), aceptando
        tres situaciones de partida distintas, para no obligar a pasar
        antes por otros botones:

          1. Una ROM SIN cabecera de copiador: se le añade la cabecera
             (SWC o SMD según el sistema, con el tamaño de SRAM real del
             juego) y se divide en tantos discos de 1,6 MB —el formato
             "superformateado" propio del SMD/SWC, el que más aprovecha
             el disco— como haga falta, convirtiendo cada uno a HFE.
          2. Un disco (o serie de varios) con cabecera de copiador en OTRO
             formato (720/800/1,44 MB): se reconstruye el juego completo
             y se vuelve a dividir en discos de 1,6 MB antes de convertir.
          3. Un disco (o varios) que YA está en 1,6 MB: se comprueba que
             su geometría interna es de verdad la de 20 sectores/pista
             (no solo que "pese lo mismo") y se convierte directamente,
             sin tocar el contenido.

        Los discos SIN cabecera de copiador en absoluto (por ejemplo, un
        .dsk de MSX estándar) se convierten tal cual, como siempre.

        El gap3 usado en la codificación MFM es el valor REAL verificado
        para cada geometría (ver hfe_format.GAP3_CONOCIDOS), no una
        fórmula aproximada.

        Codificar un disco de 1,6 MB tarda del orden de medio segundo
        (antes de optimizar el CRC y la codificación MFM con tablas de
        lookup, tardaba más de 5 segundos): con varios discos a la vez el
        total puede notarse, así que se muestra un diálogo de progreso en
        vez de solo cambiar el cursor — así queda claro que el programa
        está trabajando, no colgado. Cualquier error en un archivo
        concreto se recoge en el informe final sin interrumpir el resto
        (antes solo se capturaban ValueError/OSError; un error de otro
        tipo en un archivo dañado o con geometría inesperada podía escapar
        sin capturar, dejando el cursor de espera puesto indefinidamente
        y dando la sensación de que el botón "no hacía nada").
        """
        exts_disco = {".dsk", ".img"}
        exts_rom_snes = SNES_ROM_EXTENSIONS
        exts_rom_genesis = {".bin", ".md", ".gen", ".smd"}
        exts_rom = exts_rom_snes if self.system == "snes" else exts_rom_genesis

        paths = [p for p in self._selected_paths()
                if os.path.splitext(p)[1].lower() in exts_disco | exts_rom]
        if not paths and self._current_path and \
                os.path.splitext(self._current_path)[1].lower() in exts_disco | exts_rom:
            paths = [self._current_path]
        if not paths:
            QMessageBox.information(
                self._active_parent(), APP_TITLE,
                "Selecciona una o varias imágenes de disco (.dsk/.img), o ROMs "
                "sin cabecera de copiador, para convertir a HFE.")
            return

        sistema = getattr(self, "_workbench_system", None) or self.system
        out_dir = ws.folder("hfe", sistema)
        ok_lines, skip_lines, generados = [], [], []

        TAM_1600 = rf.SMD_DISK_FORMATS["1600"].size

        def _convertir_y_guardar(datos_disco: bytes, nombre_base: str):
            geo = hfe.geometria_desde_dsk(datos_disco)
            datos_hfe = hfe.dsk_a_hfe(datos_disco, **geo)
            recuperado, _info = hfe.hfe_a_dsk(datos_hfe)
            if recuperado[:len(datos_disco)] != datos_disco:
                raise ValueError(
                    "la verificación interna de la codificación HFE falló: "
                    "no se ha guardado el archivo, por seguridad")
            destino = ws.unique_path(out_dir, f"{nombre_base}.hfe")
            with open(destino, "wb") as fh:
                fh.write(datos_hfe)
            return destino, geo

        # --- Clasificar cada archivo seleccionado ---
        series_a_redividir = {}    # clave_serie -> path representante
        discos_1600_directos = []  # ya en 1,6 MB: conversión directa (escenario 3)
        discos_sin_cabecera = []   # sin cabecera de copiador (MSX u otros): como siempre
        roms_crudas = []           # ROM sin cabecera: cabecera + dividir en 1600 (escenario 1)

        for path in paths:
            ext = os.path.splitext(path)[1].lower()
            if ext not in exts_disco:
                roms_crudas.append(path)
                continue
            try:
                with open(path, "rb") as fh:
                    datos_disco = fh.read()
            except OSError as e:
                skip_lines.append(f"ERROR    {os.path.basename(path)}  ({e})")
                continue
            valido, motivo = rf.validate_dsk(datos_disco)
            if not valido:
                skip_lines.append(
                    f"ERROR    {os.path.basename(path)}  (no es una imagen de disco "
                    f"válida: {motivo.splitlines()[0]})")
                continue
            try:
                partes = rf.leer_partes_de_disco(path)
            except ValueError:
                discos_sin_cabecera.append(path)
                continue
            if len(datos_disco) == TAM_1600:
                discos_1600_directos.append(path)
            else:
                series_a_redividir.setdefault(partes[0].clave_serie(), path)

        total_pasos = (len(discos_sin_cabecera) + len(discos_1600_directos)
                      + len(series_a_redividir) + len(roms_crudas))

        progreso = QProgressDialog(
            "Preparando…", "Cancelar", 0, max(total_pasos, 1), self._active_parent())
        progreso.setWindowTitle("Exportando a HFE")
        progreso.setWindowModality(Qt.WindowModal)
        progreso.setMinimumDuration(0)
        progreso.setValue(0)
        paso_actual = 0

        def _avanzar(etiqueta: str) -> bool:
            """Actualiza el progreso; devuelve False si el usuario canceló."""
            nonlocal paso_actual
            paso_actual += 1
            progreso.setLabelText(etiqueta)
            progreso.setValue(paso_actual)
            QApplication.processEvents()
            return not progreso.wasCanceled()

        cancelado = False

        # --- Escenario "de siempre": discos sin cabecera de copiador ---
        for path in discos_sin_cabecera:
            name = os.path.basename(path)
            if not _avanzar(f"Convirtiendo {name}…"):
                cancelado = True
                break
            try:
                with open(path, "rb") as fh:
                    datos_disco = fh.read()
                destino, geo = _convertir_y_guardar(datos_disco, os.path.splitext(name)[0])
                generados.append(destino)
                ok_lines.append(
                    f"OK       {name}  ->  {os.path.basename(destino)}  "
                    f"({geo['sectores_por_pista']} sect./pista, verificado)")
            except Exception as e:  # noqa: BLE001 — nunca dejar un archivo sin informe
                skip_lines.append(f"ERROR    {name}  ({e})")

        # --- Escenario 3: ya en 1,6 MB -> comprobar geometría y convertir tal cual ---
        if not cancelado:
            for path in discos_1600_directos:
                name = os.path.basename(path)
                if not _avanzar(f"Comprobando {name}…"):
                    cancelado = True
                    break
                try:
                    with open(path, "rb") as fh:
                        datos_disco = fh.read()
                    geo_detectada = hfe.geometria_desde_dsk(datos_disco)
                    if geo_detectada["sectores_por_pista"] != 20:
                        raise ValueError(
                            f"pesa 1,6 MB pero su geometría interna no es la esperada "
                            f"({geo_detectada['sectores_por_pista']} sectores/pista, no 20)")
                    destino, geo = _convertir_y_guardar(datos_disco, os.path.splitext(name)[0])
                    generados.append(destino)
                    ok_lines.append(
                        f"OK       {name}  ->  {os.path.basename(destino)}  "
                        f"(ya en 1,6 MB, geometría comprobada)")
                except Exception as e:  # noqa: BLE001
                    skip_lines.append(f"ERROR    {name}  ({e})")

        # --- Escenario 2: cabecera de copiador en otro formato -> reconstruir + redividir a 1600 ---
        if not cancelado:
            for (nombre_base, _huella), path_rep in series_a_redividir.items():
                if not _avanzar(f"Reconstruyendo {nombre_base}…"):
                    cancelado = True
                    break
                try:
                    partes = rf.find_disk_series(path_rep)
                    datos_completos, _nb = rf.rebuild_from_disk_series(partes)
                    if sistema == "genesis":
                        discos_1600 = gt.split_smd_disks(datos_completos, base_name=nombre_base, fmt="1600")
                    else:
                        discos_1600 = st.split_swc_disks(datos_completos, base_name=nombre_base, fmt="1600")
                    n_ok = 0
                    for d in discos_1600:
                        destino, _geo = _convertir_y_guardar(d.image, os.path.splitext(d.filename)[0])
                        generados.append(destino)
                        n_ok += 1
                    ok_lines.append(
                        f"OK       {nombre_base}  ({len(partes)} disco(s) originales -> "
                        f"{n_ok} disco(s) de 1,6 MB en HFE)")
                except Exception as e:  # noqa: BLE001
                    skip_lines.append(f"ERROR    {nombre_base}  ({e})")

        # --- Escenario 1: ROM sin cabecera -> cabecera + dividir en 1600 ---
        if not cancelado:
            for path in roms_crudas:
                name = os.path.basename(path)
                if not _avanzar(f"Preparando {name}…"):
                    cancelado = True
                    break
                try:
                    with open(path, "rb") as fh:
                        datos = fh.read()
                    base = os.path.splitext(name)[0]
                    if sistema == "genesis":
                        if gt.detect_smd_header(datos).present:
                            raise ValueError("ya tiene cabecera SMD; usa la opción de disco, no de ROM")
                        smd_datos = gt.bin_to_smd(datos, add_header=True)
                        discos_1600 = gt.split_smd_disks(smd_datos, base_name=base, fmt="1600")
                    else:
                        if st.detect_copier_header(datos).present:
                            raise ValueError("ya tiene cabecera de copiador; usa la opción de disco, no de ROM")
                        header_snes, _e = rf.parse_snes(datos)
                        hirom = bool(header_snes and "HiROM" in header_snes.kind)
                        sram_size = (st.sram_size_from_ram_size_n(header_snes.ram_size_n)
                                    if header_snes else 32 * 1024)
                        con_cabecera = st.add_header(datos, style="swc", hirom=hirom, sram_size=sram_size)
                        discos_1600 = st.split_swc_disks(con_cabecera, base_name=base, fmt="1600")
                    n_ok = 0
                    for d in discos_1600:
                        destino, _geo = _convertir_y_guardar(d.image, os.path.splitext(d.filename)[0])
                        generados.append(destino)
                        n_ok += 1
                    ok_lines.append(
                        f"OK       {name}  (ROM original -> cabecera + {n_ok} disco(s) "
                        f"de 1,6 MB en HFE)")
                except Exception as e:  # noqa: BLE001
                    skip_lines.append(f"ERROR    {name}  ({e})")

        progreso.setValue(total_pasos)
        self.register_generated(generados)
        self._clear_selections()

        if cancelado:
            skip_lines.append("(cancelado por el usuario: el resto de archivos no se procesó)")

        report = (
            f"Exportar a HFE — {len(paths)} archivo(s) de partida\n"
            f"Carpeta de resultados: {out_dir}\n\n"
            f"Convertidas: {len(ok_lines)}   ·   omitidas/con error: {len(skip_lines)}\n\n"
            "Detalle:\n" + "\n".join(ok_lines + skip_lines)
        )
        BatchReportDialog("Exportar a HFE — resultado", report, self._active_parent()).exec()

    def _rename_to_8_3(self):
        """Genera un nombre corto FAT 8.3, replicando la opción --r83 de
        uCON64: útil para preparar archivos que va a leer MSX-DOS, DOS, o
        cualquier copión/sistema de la época limitado a ese formato de
        nombre. No toca el contenido del archivo, solo el nombre; el
        archivo se guarda con el nombre nuevo en la carpeta correspondiente.
        """
        sistema = getattr(self, "_workbench_system", None) or self.system

        def transform(data, name):
            nuevo_nombre = rf.rename_to_8_3(name)
            if nuevo_nombre == name:
                raise ValueError("el nombre ya cabe en el formato 8.3, no hace falta cambiarlo")
            return (data, nuevo_nombre,
                    f"Renombrado de «{name}» a «{nuevo_nombre}» (formato FAT 8.3).")
        self._run_operation("Renombrar a 8.3", transform, "rename83", sistema)

    def _open_greaseweazle(self):
        """Abre el diálogo de lectura/escritura con Greaseweazle. A
        diferencia de _send_to_copier, aquí SÍ se ofrece un selector de
        archivo dentro del propio diálogo: esta tarjeta vive en la
        pantalla de inicio, no en la ventana de trabajo, así que no
        siempre habrá ya un archivo elegido de antemano.
        """
        try:
            from greaseweazle_dialog import GreaseweazleDialog
        except ImportError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo abrir el diálogo: {e}")
            return
        inicial = self._current_path if self._current_path else None
        dlg = GreaseweazleDialog(self._active_parent(), system=self.system,
                                 initial_image=inicial, app_base_dir=_app_base_dir())
        dlg.exec()

    def _send_to_copier(self):
        """Abre el diálogo de transferencia por puerto paralelo con la ROM
        ya seleccionada en la ventana de trabajo — antes era un panel aparte
        en la pantalla de inicio, con su propio selector de archivo (que
        usaba el diálogo nativo del sistema operativo, poco fiable en
        instalaciones Linux mínimas). Integrado aquí, el archivo ya viene
        decidido por la selección hecha en la ventana de trabajo, así que
        TransferDialog no necesita ofrecer su propio selector en absoluto.
        """
        paths = self._selected_paths()
        if not paths and self._current_path:
            paths = [self._current_path]
        if not paths:
            QMessageBox.information(
                self._active_parent(), APP_TITLE,
                "Selecciona la ROM que quieres transferir al copión.")
            return
        if len(paths) > 1:
            QMessageBox.information(
                self._active_parent(), APP_TITLE,
                "Selecciona una sola ROM: la transferencia es de una en una.")
            return

        sistema = getattr(self, "_workbench_system", None) or self.system
        try:
            from transfer_dialog import TransferDialog
        except ImportError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo abrir el diálogo: {e}")
            return
        dlg = TransferDialog(self._active_parent(), system=sistema, initial_rom=paths[0],
                            icon_dir=_icon_base_dir())
        dlg.exec()

    def _build_tape_tools(self) -> QWidget:
        box = QFrame()
        box.setObjectName("FieldChip")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title = QLabel("CONVERSOR DE CINTAS (CAS ⇄ WAV ⇄ TSX)")
        title.setObjectName("SectionLabel")
        lay.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_c2w = QPushButton("CAS → WAV…")
        btn_c2w.clicked.connect(self._tape_cas_to_wav)
        btn_w2c = QPushButton("WAV → CAS…")
        btn_w2c.clicked.connect(self._tape_wav_to_cas)
        btn_c2t = QPushButton("CAS → TSX…")
        btn_c2t.clicked.connect(self._tape_cas_to_tsx)
        btn_t2c = QPushButton("TSX → CAS…")
        btn_t2c.clicked.connect(self._tape_tsx_to_cas)
        btn_t2w = QPushButton("TSX → WAV…")
        btn_t2w.setToolTip("Pasa por CAS internamente")
        btn_t2w.clicked.connect(self._tape_tsx_to_wav)
        btn_w2t = QPushButton("WAV → TSX…")
        btn_w2t.setToolTip("Pasa por CAS internamente")
        btn_w2t.clicked.connect(self._tape_wav_to_tsx)
        btn_play = QPushButton("▶  Reproducir cinta…")
        btn_play.setObjectName("Primary")
        btn_play.clicked.connect(self._open_tape_player)
        row.addWidget(btn_c2w)
        row.addWidget(btn_w2c)
        row.addWidget(btn_c2t)
        row.addWidget(btn_t2c)
        row.addWidget(btn_t2w)
        row.addWidget(btn_w2t)
        row.addWidget(btn_play)

        row.addStretch(1)
        lay.addLayout(row)

        hint = QLabel(
            "Elige un archivo de origen (no hace falta que esté en la carpeta abierta "
            "arriba) y dónde guardar el resultado. El WAV se genera en mono, con el "
            "esquema FSK 'Kansas City' que usa la BIOS del MSX. El TSX usa el bloque "
            "#4B (KCS) sobre TZX 1.21; la marca de sincronismo de cada bloque CAS es "
            "implícita en el TSX (no se guarda), se reconstruye al volver a CAS."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return box

    # -- acciones del panel de disquetera ---------------------------------
    def _require_dsk(self):
        """Devuelve (nombre, imagen) del disco abierto, o None avisando."""
        ctx = getattr(self, "_dsk_ctx", None)
        if not ctx:
            QMessageBox.information(
                self, APP_TITLE,
                "Primero selecciona una imagen de disco (.dsk o .img) en la lista "
                "de archivos, para que la aplicación la abra y muestre su contenido.")
            return None
        return ctx

    def _dsk_extract_all(self):
        """Abre la ventana de extracción con los discos seleccionados.

        Nota: `_dsk_ctx` guarda un DskImage ya analizado, no los bytes en
        crudo. Aplicarle parse_dsk otra vez fallaba y el botón parecía no
        hacer nada.
        """
        self._open_extract_dialog()

    def _open_extract_dialog(self):
        """Reúne hasta tres imágenes de disco y abre la ventana de extracción."""
        try:
            from extract_dialog import ExtractFilesDialog, MAX_IMAGENES
        except ImportError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo abrir la ventana: {e}")
            return

        rutas = [p for p in self._selected_paths()
                 if os.path.splitext(p)[1].lower() in (".dsk", ".img", ".di1", ".di2")]
        # Si no hay selección, se usa el disco que esté abierto
        if not rutas and self._current_path:
            if os.path.splitext(self._current_path)[1].lower() in (".dsk", ".img"):
                rutas = [self._current_path]

        if not rutas:
            QMessageBox.information(
                self, APP_TITLE,
                "Selecciona en la lista una o varias imágenes de disco (.dsk o .img) "
                f"—hasta {MAX_IMAGENES}— y vuelve a pulsar.\n\n"
                "Puedes marcar varias con Ctrl+clic para extraer archivos de unas y "
                "otras en la misma operación.")
            return

        if len(rutas) > MAX_IMAGENES:
            QMessageBox.information(
                self, APP_TITLE,
                f"Has seleccionado {len(rutas)} imágenes. Se abrirán las "
                f"{MAX_IMAGENES} primeras: más de tres pestañas resultan incómodas "
                "de manejar.")
            rutas = rutas[:MAX_IMAGENES]

        imagenes = []
        fallos = []
        for ruta in rutas:
            try:
                with open(ruta, "rb") as fh:
                    datos = fh.read()
                if rf.detect_copia720_single_sided(datos):
                    datos = rf.copia720_to_single_sided(datos)
                valido, motivo = rf.validate_dsk(datos)
                if not valido:
                    fallos.append(f"· {os.path.basename(ruta)}:\n   {motivo}")
                    continue
                imagenes.append((os.path.basename(ruta), rf.parse_dsk(datos)))
            except Exception as e:  # noqa: BLE001
                fallos.append(f"· {os.path.basename(ruta)}: {e}")

        if not imagenes:
            QMessageBox.warning(
                self, APP_TITLE,
                "Ninguna de las imágenes seleccionadas tiene un sistema de archivos "
                "que se pueda abrir:\n\n" + "\n\n".join(fallos))
            return
        if fallos:
            QMessageBox.warning(
                self, APP_TITLE,
                "Algunas imágenes no se pudieron leer:\n\n" + "\n".join(fallos))

        ExtractFilesDialog(imagenes, self._active_parent()).exec()

    def _dsk_inject_files(self):
        """Crea una copia del disco abierto con archivos añadidos dentro."""
        ctx = self._require_dsk()
        if not ctx:
            return
        nombre, datos = ctx

        # Se abre directamente en la carpeta que la aplicación crea para esto,
        # que es de donde se querrá coger los archivos casi siempre. Desde ahí
        # el usuario puede navegar a cualquier otro sitio si lo necesita.
        inicio = ws.folder("extracted", "msx")
        try:
            if not os.listdir(inicio):
                inicio = ws.source_folder()
        except OSError:
            inicio = ws.source_folder()
        rutas = elegir_archivos(
            self, carpeta_inicial=inicio,
            mensaje="Archivos a inyectar en el disco  —  (empieza en la carpeta "
                    "de Asturconsole; puedes navegar a otra si lo necesitas)")
        if not rutas:
            return

        try:
            dsk = rf.parse_dsk(datos)
        except ValueError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo leer el disco: {e}")
            return

        # Se reconstruye el disco entero: lo que ya había, más lo nuevo. Es más
        # sencillo y seguro que insertar en el FAT existente, y el resultado es
        # un disco limpio y sin fragmentar.
        archivos = []
        for e in dsk.entries:
            if e.is_dir:
                continue
            try:
                archivos.append((e.name, rf.reconstruct_dsk_file(dsk, e)))
            except Exception:  # noqa: BLE001
                continue

        nuevos = 0
        for r in rutas:
            try:
                with open(r, "rb") as fh:
                    archivos.append((os.path.basename(r), fh.read()))
                nuevos += 1
            except OSError as e:
                QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo leer {r}: {e}")
                return

        # Formato de destino: el mismo tamaño que tenía el disco original
        fmt = "360" if len(datos) == rf.MSX_DISK_FORMATS["360"].size else "720"
        try:
            usados, libres, entradas = rf.plan_msx_disk(archivos, fmt)
            if usados > libres:
                QMessageBox.warning(
                    self, APP_TITLE,
                    f"No caben: harían falta {rf.fmt_bytes(usados)} y el disco de "
                    f"{fmt} KB solo tiene {rf.fmt_bytes(libres)}.\n\n"
                    "Quita algún archivo o usa un disco de 720 KB.")
                return
            imagen = rf.write_files_to_msx_dsk(archivos, fmt=fmt)
        except ValueError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo construir el disco: {e}")
            return

        base, ext = os.path.splitext(nombre)
        destino = ws.unique_path(ws.folder("blank_disks", "msx"), f"{base}_con_archivos{ext or '.dsk'}")
        try:
            with open(destino, "wb") as fh:
                fh.write(imagen)
        except OSError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo guardar: {e}")
            return

        self.register_generated(destino)
        QMessageBox.information(
            self, APP_TITLE,
            f"Disco reconstruido con {len(archivos)} archivo(s), de los cuales "
            f"{nuevos} son nuevos.\n\nOcupa {rf.fmt_bytes(usados)} de "
            f"{rf.fmt_bytes(libres)}.\n\nGuardado en:\n{destino}")

    def _selected_image_path(self):
        """Ruta de la imagen seleccionada, para grabarla en un disquete."""
        paths = self._selected_paths()
        if not paths and self._current_path:
            paths = [self._current_path]
        if not paths:
            QMessageBox.information(
                self, APP_TITLE,
                "Selecciona primero la imagen (.dsk o .img) que quieres grabar.")
            return None
        if len(paths) > 1:
            QMessageBox.information(
                self, APP_TITLE,
                "Selecciona una sola imagen: los disquetes se graban de uno en uno.")
            return None
        return paths[0]

    def _write_floppy_real(self):
        ruta = self._selected_image_path()
        if not ruta:
            return
        try:
            from floppy_write_dialog import FloppyWriteDialog
        except ImportError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo abrir el diálogo: {e}")
            return
        FloppyWriteDialog(self, image_path=ruta, modo="escribir").exec()

    def _format_floppy_real(self):
        try:
            from floppy_write_dialog import FloppyWriteDialog
        except ImportError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo abrir el diálogo: {e}")
            return
        FloppyWriteDialog(self, modo="formatear").exec()

    def _format_usb_media(self):
        """Formateo de unidades USB: se hace escribiendo una imagen vacía.

        Un adaptador USB no admite formateo a bajo nivel (no expone las
        llamadas de formateo por pistas del controlador de disquete), así que
        la única forma equivalente es grabar encima una imagen ya formateada.
        """
        dlg = BlankDiskDialog(self._active_parent())
        dlg.setWindowTitle("Formatear unidad USB — crear imagen vacía")
        if dlg.exec() != QDialog.Accepted:
            return
        fmt = dlg.disk_format()
        etiqueta = dlg.volume_label()
        try:
            imagen = rf.make_blank_msx_dsk(etiqueta, fmt=fmt)
        except ValueError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, str(e))
            return
        destino = ws.unique_path(ws.folder("blank_disks", "msx"), f"formato_{fmt}k.dsk")
        try:
            with open(destino, "wb") as fh:
                fh.write(imagen)
        except OSError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo crear la imagen: {e}")
            return
        self.register_generated(destino)
        QMessageBox.information(
            self, APP_TITLE,
            "Los adaptadores USB de disquete no admiten formateo a bajo nivel, así "
            "que se ha creado una imagen vacía ya formateada.\n\nA continuación se "
            "abrirá el grabador para volcarla en la unidad, lo que deja el disquete "
            "formateado y vacío.")
        self._write_image_to_disk(destino)

    def _write_image_usb(self):
        ruta = self._selected_image_path()
        if not ruta:
            return
        self._write_image_to_disk(ruta)

    def _generar_img_cfg(self):
        """Genera el archivo IMG.CFG que necesitan FlashFloppy/HxC para
        reconocer los discos "superformateados" (1600/800 KB) del Super
        Magic Drive / Super Wild Card directamente como imagen en bruto,
        sin tener que convertirlos a HFE.
        """
        contenido = rf.generar_flashfloppy_img_cfg()
        destino = ws.unique_path(ws.folder("smd_disks", self.system) if self.system == "genesis"
                                 else ws.folder("swc_disks", self.system), "IMG.CFG")
        try:
            with open(destino, "w", encoding="ascii") as fh:
                fh.write(contenido)
        except OSError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo crear el archivo: {e}")
            return
        self.register_generated(destino)
        QMessageBox.information(
            self._active_parent(), APP_TITLE,
            f"Generado: {destino}\n\n"
            "Cópialo a la memoria USB del Gotek (a la carpeta FF/ si existe, o si no "
            "a la raíz), junto con los discos .dsk/.img de 1600 u 800 KB. Los de "
            "720 KB y 1.44 MB no lo necesitan: FlashFloppy/HxC los reconocen solos.")

    def _read_floppy(self):
        try:
            from read_floppy_dialog import ReadFloppyDialog
        except ImportError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo abrir el diálogo: {e}")
            return
        ReadFloppyDialog(self._active_parent()).exec()

    def _copia720_trim(self):
        def transform(data, name):
            if not rf.detect_copia720_single_sided(data):
                if len(data) == rf.COPIA720_SIZE:
                    raise ValueError(
                        "es un disco de 720 KB con datos en las dos caras: no procede "
                        "recortarlo")
                raise ValueError(
                    f"no es una imagen de 720 KB de COPIA720 ({rf.fmt_bytes(len(data))})")
            resultado = rf.copia720_to_single_sided(data)
            base, ext = os.path.splitext(name)
            return (resultado, f"{base}_360{ext or '.dsk'}",
                    "Imagen recortada a 360 KB: se ha descartado la cara 1, que COPIA720 "
                    "rellena con 0xE5 al volcar discos de cara simple.")
        self._run_operation("Recortar COPIA720", transform, "extracted", "msx")

    def _copia720_expand(self):
        def transform(data, name):
            esperado = rf.COPIA720_TRACK_BYTES * (rf.COPIA720_TRACKS // 2)
            if len(data) != esperado:
                raise ValueError(
                    f"debe ser un disco de cara simple de {rf.fmt_bytes(esperado)} "
                    f"(este mide {rf.fmt_bytes(len(data))})")
            resultado = rf.single_sided_to_copia720(data)
            base, ext = os.path.splitext(name)
            return (resultado, f"{base}_copia720{ext or '.dsk'}",
                    "Imagen expandida a 720 KB con la cara 1 rellena de 0xE5, tal como "
                    "COPIA720 espera al grabar con la opción /1.")
        self._run_operation("Expandir para COPIA720", transform, "extracted", "msx")

    def _create_blank_disks(self):
        dlg = BlankDiskDialog(self._active_parent())
        if dlg.exec() != QDialog.Accepted:
            return
        nombres = dlg.names()
        etiqueta = dlg.volume_label()
        fmt = dlg.disk_format()
        version = dlg.dos_version()
        out_dir = ws.folder("blank_disks", "msx")

        # --- preparar la imagen base (vacía o con sistema) ---
        try:
            if version:
                plan = md.plan_system_disk(
                    ws.folder("msxdos", "msx"), ws.folder("msxdos_utils", "msx"), version,
                    fmt, dlg.include_utils(), etiqueta,
                )
                if not plan.ok:
                    QMessageBox.warning(
                        self, APP_TITLE,
                        "No se puede crear el disco de sistema:\n\n"
                        + "\n\n".join(plan.errors)
                        + f"\n\nCarpeta de archivos de sistema:\n{ws.folder('msxdos')}",
                    )
                    return
                if plan.warnings:
                    respuesta = QMessageBox.warning(
                        self, APP_TITLE,
                        "\n\n".join(plan.warnings) + "\n\n¿Crear los discos de todos modos?",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                    )
                    if respuesta != QMessageBox.Yes:
                        return
                imagen = md.build_system_disk(plan, fmt, etiqueta)
                descripcion = md.DOS_VERSIONS[version][0]
                detalle = (f"con {descripcion} y {len(plan.files)} archivo(s): "
                           + ", ".join(n for n, _d in plan.files[:8]))
            else:
                imagen = rf.make_blank_msx_dsk(etiqueta, fmt=fmt)
                detalle = "vacíos y formateados"
        except (ValueError, OSError) as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo preparar la imagen:\n{e}")
            return

        # --- escribir tantas copias como se hayan pedido ---
        QApplication.setOverrideCursor(Qt.WaitCursor)
        generados, errores = [], []
        try:
            for nombre in nombres:
                try:
                    destino = ws.unique_path(out_dir, nombre)
                    with open(destino, "wb") as fh:
                        fh.write(imagen)
                    generados.append(destino)
                except OSError as e:
                    errores.append(f"{nombre}: {e}")
        finally:
            QApplication.restoreOverrideCursor()

        self.register_generated(generados)
        f = rf.MSX_DISK_FORMATS[fmt]
        mensaje = (
            f"Creado(s) {len(generados)} disquete(s) de {f.label}, {detalle}"
            + (f", con etiqueta «{etiqueta}»" if etiqueta else "")
            + f".\n\nCarpeta:\n{out_dir}"
        )
        if errores:
            mensaje += "\n\nErrores:\n" + "\n".join(errores[:10])

        # Ofrecer grabar en una unidad física (disquetera USB, lector de
        # disquete...) si hay alguna disponible.
        if generados:
            mensaje += "\n\n¿Grabar ahora una de estas imágenes en un disquete físico?"
            respuesta = QMessageBox.question(
                self, APP_TITLE, mensaje,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if respuesta == QMessageBox.Yes:
                self._write_image_to_disk(generados[0])
            return
        QMessageBox.information(self._active_parent(), APP_TITLE, mensaje)

    def _write_image_to_disk(self, image_path: str):
        """Abre el diálogo de grabación en unidad física."""
        try:
            from write_image_dialog import WriteImageDialog
        except ImportError as e:
            QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo abrir el diálogo: {e}")
            return
        WriteImageDialog(image_path, self._active_parent()).exec()

    def _open_tape_player(self):
        # Import diferido: QtMultimedia no siempre está instalado y solo hace
        # falta al abrir el reproductor, no al arrancar la aplicación.
        try:
            from tape_player_dialog import TapePlayerDialog
        except ImportError as e:
            QMessageBox.warning(
                self, APP_TITLE,
                "No se pudo cargar el reproductor: falta el módulo de audio de Qt "
                f"(QtMultimedia).\n\nDetalle: {e}\n\n"
                "En Debian/Ubuntu suele resolverse instalando el paquete "
                "'python3-pyside6.qtmultimedia', o reinstalando PySide6 completo "
                "con 'pip install --force-reinstall PySide6'.",
            )
            return

        initial = None
        if self._current_path and os.path.splitext(self._current_path)[1].lower() in (".cas", ".tsx"):
            initial = self._current_path
        dlg = TapePlayerDialog(self, initial_path=initial)
        dlg.exec()

    def _tape_paths(self, titulo: str, filtro: str) -> list[str]:
        """Archivos sobre los que operar: la selección actual si la hay, o uno
        elegido con el diálogo de archivos si no hay nada seleccionado."""
        paths = self._selected_paths()
        if paths:
            return paths

        # Sin selección: en vez del explorador de archivos escueto, se usa el
        # mismo selector de ubicaciones del botón «Elegir carpeta» (con las
        # carpetas de la aplicación, los discos y los USB montados) y después
        # se abre la ventana de trabajo, donde se ven los archivos con sus
        # iconos y se pueden seleccionar varios.
        QMessageBox.information(
            self, APP_TITLE,
            "No hay ninguna cinta seleccionada.\n\nElige la ubicación donde estén "
            "tus archivos; después podrás seleccionarlos en la ventana de trabajo "
            "y volver a pulsar esta conversión.")
        carpeta = choose_directory(self)
        if carpeta:
            self._open_workbench_deferred(carpeta)
        return []

    def _run_tape_operation(self, label: str, paths: list[str], transform):
        """Convierte una o varias cintas, guardando en la carpeta 'cintas msx'."""
        if not paths:
            return
        out_dir = ws.folder("tapes", "msx")

        QApplication.setOverrideCursor(Qt.WaitCursor)
        ok_lines, skip_lines, generados = [], [], []
        detalle_unico = ""
        for path in paths:
            name = os.path.basename(path)
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
                result, suggested, detalle = transform(data, name)
                out_path = ws.unique_path(out_dir, suggested)
                with open(out_path, "wb") as fh:
                    fh.write(result)
                generados.append(out_path)
                detalle_unico = detalle
                ok_lines.append(f"OK       {name}  ->  {os.path.basename(out_path)}")
            except ValueError as e:
                skip_lines.append(f"OMITIDO  {name}  ({e})")
            except Exception as e:  # noqa: BLE001
                skip_lines.append(f"ERROR    {name}  ({e})")
        QApplication.restoreOverrideCursor()

        self.register_generated(generados)
        self._clear_selections()

        if len(paths) == 1:
            if ok_lines:
                QMessageBox.information(
                    self, APP_TITLE, f"{detalle_unico}\n\nGuardado en:\n{generados[0]}")
            else:
                QMessageBox.warning(self._active_parent(), APP_TITLE, skip_lines[0])
            return

        report = (
            f"{label} — {len(paths)} archivo(s)\n"
            f"Carpeta de resultados: {out_dir}\n\n"
            f"Convertidos: {len(ok_lines)}\n"
            f"Omitidos / con error: {len(skip_lines)}\n\n"
            "Detalle:\n" + "\n".join(ok_lines + skip_lines)
        )
        BatchReportDialog(f"{label} — resultado", report, self._active_parent()).exec()

    def _tape_cas_to_wav(self):
        paths = self._tape_paths("Elegir archivo .CAS", "Cinta MSX (*.cas);;Todos (*)")
        if not paths:
            return
        dialog = TapeConvertDialog("cas2wav", self._active_parent())
        if dialog.exec() != QDialog.Accepted:
            return
        baud, rate, depth = dialog.baud(), dialog.sample_rate(), dialog.bit_depth()
        pilot = dialog.pilot_seconds()

        def transform(data, name):
            wav = ct.cas_to_wav(data, baud=baud, sample_rate=rate,
                                 bit_depth=depth, pilot_seconds=pilot)
            base, _e = os.path.splitext(name)
            n = len(ct.find_sync_positions(data))
            return wav, f"{base}.wav", (
                f"Convertido a WAV ({baud} baudios, {rate} Hz, {depth} bit, mono).\n"
                f"Bloques detectados en el CAS: {n}\n"
                f"Tamaño resultante: {rf.fmt_bytes(len(wav))}")
        self._run_tape_operation("CAS → WAV", paths, transform)

    def _tape_wav_to_cas(self):
        paths = self._tape_paths("Elegir archivo .WAV", "Audio WAV (*.wav);;Todos (*)")
        if not paths:
            return
        def transform(data, name):
            # La velocidad se mide de la propia señal: las cintas reales no
            # van a velocidades redondas (se han visto ripeos a 1225 y 1696
            # baudios), así que imponer un valor fijo haría fallar la lectura.
            sr, _pa, _pg, medidos = ct.measure_signal(data)
            cas = ct.wav_to_cas(data)
            base, _e = os.path.splitext(name)
            n = len(ct.find_sync_positions(cas))
            return cas, f"{base}.cas", (
                f"Convertido a CAS.\nVelocidad medida en la señal: {medidos:.0f} baudios "
                f"({sr} Hz de muestreo).\n"
                f"Bloques detectados: {n}\n"
                f"Tamaño resultante: {rf.fmt_bytes(len(cas))}")
        self._run_tape_operation("WAV → CAS", paths, transform)

    def _tape_cas_to_tsx(self):
        paths = self._tape_paths("Elegir archivo .CAS", "Cinta MSX (*.cas);;Todos (*)")
        if not paths:
            return
        dialog = TapeConvertDialog("cas2wav", self._active_parent())   # reutiliza el selector de baudios
        if dialog.exec() != QDialog.Accepted:
            return
        baud = dialog.baud()

        def transform(data, name):
            tsx = tt.cas_to_tsx(data, baud=baud)
            base, _e = os.path.splitext(name)
            return tsx, f"{base}.tsx", (
                f"Convertido a TSX ({baud} baudios, bloque #4B KCS).\n"
                f"Tamaño resultante: {rf.fmt_bytes(len(tsx))}")
        self._run_tape_operation("CAS → TSX", paths, transform)

    def _tape_tsx_to_cas(self):
        paths = self._tape_paths("Elegir archivo .TSX", "Cinta MSX TZX/TSX (*.tsx);;Todos (*)")
        if not paths:
            return

        def transform(data, name):
            try:
                cas = tt.tsx_to_cas(data)
            except ValueError as e:
                try:
                    censo = tt.scan_tsx_blocks(data)
                    no_kcs = sum(t for bid, (_n, t) in censo.items()
                                 if bid in tt.NON_KCS_DATA_BLOCK_IDS)
                except Exception:  # noqa: BLE001
                    no_kcs = 0
                if no_kcs > 0:
                    raise ValueError(
                        "sin bloques KCS/MSX: cargador de protección de otro tipo, no "
                        "representable en formato CAS") from e
                raise
            censo = tt.scan_tsx_blocks(data)
            no_kcs = sum(t for bid, (_n, t) in censo.items()
                         if bid in tt.NON_KCS_DATA_BLOCK_IDS)
            base, _e = os.path.splitext(name)
            n = len(ct.find_sync_positions(cas))
            detalle = (f"Convertido a CAS.\nBloques de sincronismo reconstruidos: {n}\n"
                       f"Tamaño resultante: {rf.fmt_bytes(len(cas))}")
            if no_kcs > len(cas):
                detalle += (f"\n\nAVISO: el TSX contiene {rf.fmt_bytes(no_kcs)} en bloques "
                            "que NO son KCS/MSX (cargador de protección): el CAS resultante "
                            "está incompleto. No es un fallo de la herramienta, sino una "
                            "limitación del formato CAS.")
            return cas, f"{base}.cas", detalle
        self._run_tape_operation("TSX → CAS", paths, transform)

    def _tape_tsx_to_wav(self):
        paths = self._tape_paths("Elegir archivo .TSX", "Cinta MSX TZX/TSX (*.tsx);;Todos (*)")
        if not paths:
            return
        dialog = TapeConvertDialog("cas2wav", self._active_parent())   # reutiliza el selector de baudios
        if dialog.exec() != QDialog.Accepted:
            return
        baud, rate, depth = dialog.baud(), dialog.sample_rate(), dialog.bit_depth()
        pilot = dialog.pilot_seconds()

        def transform(data, name):
            wav = tt.tsx_to_wav(data, baud=baud, sample_rate=rate,
                                 bit_depth=depth, pilot_seconds=pilot)
            base, _e = os.path.splitext(name)
            return wav, f"{base}.wav", (
                f"Convertido a WAV ({baud} baudios, {rate} Hz, {depth} bit, mono), "
                "pasando por CAS internamente.\n"
                f"Tamaño resultante: {rf.fmt_bytes(len(wav))}")
        self._run_tape_operation("TSX → WAV", paths, transform)

    def _tape_wav_to_tsx(self):
        paths = self._tape_paths("Elegir archivo .WAV", "Audio WAV (*.wav);;Todos (*)")
        if not paths:
            return

        def transform(data, name):
            sr, _pa, _pg, medidos = ct.measure_signal(data)
            tsx = tt.wav_to_tsx(data)
            base, _e = os.path.splitext(name)
            return tsx, f"{base}.tsx", (
                f"Convertido a TSX (bloque #4B KCS), pasando por CAS internamente.\n"
                f"Velocidad medida en la señal: {medidos:.0f} baudios ({sr} Hz de "
                "muestreo).\n"
                f"Tamaño resultante: {rf.fmt_bytes(len(tsx))}")
        self._run_tape_operation("WAV → TSX", paths, transform)

    def _require_selection(self) -> bool:
        if self._current_data is None and not self._selected_paths():
            QMessageBox.information(self._active_parent(), APP_TITLE, "Primero selecciona un archivo de la lista.")
            return False
        return True

    def _set_active_list(self, lst):
        """Marca como activa la lista donde el usuario acaba de seleccionar."""
        if self._suppress_active_tracking:
            return
        if lst.selectedItems():
            self._active_list = lst
            # Al pasar a trabajar con una lista, se limpia la selección de la
            # otra: así nunca hay dos selecciones vivas a la vez y siempre
            # está claro sobre qué archivos actúan las herramientas.
            otra = self.generated_list if lst is self.file_list else self.file_list
            if otra.selectedItems():
                self._suppress_active_tracking = True
                otra.clearSelection()
                self._suppress_active_tracking = False
        self._update_active_labels()

    def _selected_paths(self) -> list[str]:
        """Rutas seleccionadas en la lista activa (la última usada).

        Si la operación viene de la ventana grande de trabajo, manda su
        selección: es la que el usuario acaba de hacer.
        """
        forzadas = getattr(self, "_forced_paths", None)
        if forzadas:
            return list(forzadas)
        items = self._active_list.selectedItems()
        if not items:
            otra = self.generated_list if self._active_list is self.file_list else self.file_list
            items = otra.selectedItems()
        return [i.data(Qt.UserRole) for i in items]

    def _clear_selections(self):
        """Deja ambas listas sin selección tras completar una operación."""
        self._suppress_active_tracking = True
        self.file_list.clearSelection()
        self.generated_list.clearSelection()
        self._suppress_active_tracking = False
        self._update_active_labels()

    def _update_active_labels(self):
        """Indica visualmente sobre qué lista actuarán las herramientas."""
        n_src = len(self.file_list.selectedItems())
        n_gen = len(self.generated_list.selectedItems())
        accent = ACCENTS[self.system]
        self.orig_lbl.setText(
            f"ARCHIVOS DE ORIGEN — {n_src} SELECCIONADO(S)" if n_src else "ARCHIVOS DE ORIGEN"
        )
        self.gen_lbl.setText(
            f"ARCHIVOS GENERADOS — {n_gen} SELECCIONADO(S)" if n_gen else "ARCHIVOS GENERADOS"
        )
        self.orig_lbl.setStyleSheet(f"color: {accent};" if n_src else "")
        self.gen_lbl.setStyleSheet(f"color: {accent};" if n_gen else "")

    def _snes_save_as(self, data: bytes, suggested_name: str) -> Optional[str]:
        start_dir = os.path.dirname(self._current_path or "") or "."
        path = elegir_archivo_guardar(
            self, carpeta_inicial=start_dir, nombre_sugerido=suggested_name,
            titulo="Guardar como")
        if not path:
            return None
        with open(path, "wb") as fh:
            fh.write(data)
        self.register_generated(path)
        return path

    def _run_operation(self, label: str, transform, category: str,
                       sistema: str | None = None):
        """Ejecuta una operación sobre el archivo seleccionado o, si hay
        varios, sobre todos ellos.

        El resultado se guarda automáticamente en la subcarpeta del espacio
        de trabajo que corresponde a `category`, sin pedir carpeta de
        destino. `transform(data, name)` devuelve
        `(bytes_resultado, nombre_sugerido, mensaje_detalle)` o lanza
        ValueError con el motivo si ese archivo no se puede procesar.
        """
        paths = self._selected_paths()
        if not paths and self._current_data is not None and self._current_path:
            paths = [self._current_path]
        if not paths:
            QMessageBox.information(self._active_parent(), APP_TITLE, "Primero selecciona un archivo de la lista.")
            return

        # El sistema determina en qué rama del árbol se guarda el resultado.
        # Si no se indica, se usa el de la pestaña activa.
        out_dir = ws.folder(category, sistema or self.system)

        # Indicador de actividad: antes solo se cambiaba el cursor a
        # "espera", sin más señal — con varios archivos (o alguno grande,
        # como al aplicar el crack/fix PAL sobre un ROM completo) daba la
        # sensación de que el programa se había quedado colgado, aunque
        # estuviera trabajando. Con el archivo actual a la vista, queda
        # claro que avanza.
        progreso = QProgressDialog(
            "Preparando…", "Cancelar", 0, len(paths), self._active_parent())
        progreso.setWindowTitle(label)
        progreso.setWindowModality(Qt.WindowModal)
        progreso.setMinimumDuration(0)
        progreso.setValue(0)

        ok_lines, skip_lines, generados = [], [], []
        detalle_unico = ""
        cancelado = False
        for i, path in enumerate(paths):
            name = os.path.basename(path)
            progreso.setLabelText(f"Procesando {name}…")
            progreso.setValue(i)
            QApplication.processEvents()
            if progreso.wasCanceled():
                cancelado = True
                break
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
                result, suggested, detalle = transform(data, name)
                out_path = ws.unique_path(out_dir, suggested)
                with open(out_path, "wb") as fh:
                    fh.write(result)
                generados.append(out_path)
                detalle_unico = detalle
                ok_lines.append(f"OK       {name}  ->  {os.path.basename(out_path)}")
            except ValueError as e:
                skip_lines.append(f"OMITIDO  {name}  ({e})")
            except Exception as e:  # noqa: BLE001
                skip_lines.append(f"ERROR    {name}  ({e})")
        progreso.setValue(len(paths))

        self.register_generated(generados)
        self._clear_selections()

        if cancelado:
            skip_lines.append("(cancelado por el usuario: el resto de archivos no se procesó)")

        # Un solo archivo: mensaje breve. Varios: informe completo.
        if len(paths) == 1 and not cancelado:
            if ok_lines:
                QMessageBox.information(
                    self, APP_TITLE,
                    f"{detalle_unico}\n\nGuardado en:\n{generados[0]}",
                )
            else:
                QMessageBox.warning(self._active_parent(), APP_TITLE, skip_lines[0] if skip_lines else "No se pudo procesar.")
            return

        report = (
            f"{label} — {len(paths)} archivo(s)\n"
            f"Carpeta de resultados: {out_dir}\n\n"
            f"Procesados correctamente: {len(ok_lines)}\n"
            f"Omitidos / con error: {len(skip_lines)}\n\n"
            "Detalle:\n" + "\n".join(ok_lines + skip_lines)
        )
        BatchReportDialog(f"{label} — resultado", report, self._active_parent()).exec()

    def _snes_strip_header(self):
        def transform(data, name):
            info = st.detect_copier_header(data)
            if not info.present:
                raise ValueError("no tiene cabecera de copiador")
            base, ext = os.path.splitext(name)
            return (st.strip_header(data), f"{base}_sin_cabecera{ext}",
                    f"Cabecera eliminada ({info.brand or 'genérica'}, {info.size} bytes).")
        self._run_operation("Quitar cabecera", transform, "no_header", "snes")

    def _snes_add_header(self, style: str):
        # En vez de decidir solo con la lista de compatibilidad si hay
        # algo que ofrecer (hemos comprobado con hardware real que puede
        # estar incompleta: documenta el crack de un juego pero no un fix
        # de PAL que el propio código fuente de uCON64 sí conoce), se
        # comprueba de verdad si alguno de los archivos seleccionados
        # tiene algún patrón aplicable —tanto de protección de SRAM (-k)
        # como de PAL/NTSC (-f)— antes de preguntar. Una sola pregunta
        # para todo el lote, no una por archivo, ya que _run_operation no
        # permite interacción dentro de su bucle.
        aplicar_correcciones_lote = False
        if style == "swc":
            paths_previos = self._selected_paths()
            if not paths_previos and self._current_path:
                paths_previos = [self._current_path]
            algun_candidato = False
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                for path in paths_previos:
                    try:
                        with open(path, "rb") as fh:
                            datos_previos = fh.read()
                        header_previo, _e = rf.parse_snes(datos_previos)
                        if not header_previo:
                            continue
                        sram_previo = st.sram_size_from_ram_size_n(header_previo.ram_size_n)
                        _d, cambios_k = crk.aplicar_crack(datos_previos, sram_previo)
                        _d, cambios_f = crk.aplicar_fix_pal(datos_previos)
                        if cambios_k or cambios_f:
                            algun_candidato = True
                            break
                    except OSError:
                        continue
            finally:
                QApplication.restoreOverrideCursor()
            if algun_candidato:
                resp = QMessageBox.question(
                    self._active_parent(), APP_TITLE,
                    "Se han detectado patrones conocidos de protección (anti-copia "
                    "y/o de PAL/NTSC) en uno o varios de estos ROM — el mismo "
                    "mecanismo que las opciones -k y -f de uCON64.\n\n"
                    "Antes de aplicarlos, ten en cuenta que ASTURCONSOLE ya ajusta el "
                    "tamaño real de SRAM en la cabecera SWC (ver más abajo), que por "
                    "sí solo resuelve muchos casos sin tocar el código del juego — "
                    "pero no todos, como confirmamos con un caso real que sí "
                    "necesitaba además esta corrección.\n\n"
                    "¿Aplicarlas también?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                aplicar_correcciones_lote = (resp == QMessageBox.Yes)

        def transform(data, name):
            if st.detect_copier_header(data).present:
                raise ValueError("ya tiene una cabecera de copiador")
            header, _err = rf.parse_snes(data)
            hirom = bool(header and "HiROM" in header.kind)
            # El tamaño de SRAM se lee del propio ROM, no se asume 32 KB
            # (el máximo, valor por defecto anterior): ver el docstring de
            # make_swc_header para el porqué — es la causa real de que
            # muchos juegos SNES necesiten "crackearse" para funcionar en
            # un copión, confirmado con hardware real.
            sram_size = st.sram_size_from_ram_size_n(header.ram_size_n) if header else 32 * 1024

            nota = ""
            if aplicar_correcciones_lote and style == "swc":
                data, cambios_k = crk.aplicar_crack(data, sram_size)
                data, cambios_f = crk.aplicar_fix_pal(data)
                cambios = cambios_k + cambios_f
                if cambios:
                    nota = f" Correcciones aplicadas: {', '.join(cambios)}."
                else:
                    nota = " No se encontró ningún patrón conocido que aplicar en este ROM."

            result = st.add_header(data, style=style, hirom=hirom, sram_size=sram_size)
            base, ext = os.path.splitext(name)
            if style == "swc":
                # Convención real de la Super Wild Card: los ROMs con esta
                # cabecera se nombran con extensión .swc.
                suggested = f"{base}_swc.swc"
                tipo = "Super Wild Card"
            else:
                suggested = f"{base}_hdr{ext}"
                tipo = "genérica (512 bytes en cero)"
            return result, suggested, f"Cabecera {tipo} añadida.{nota}"
        etiqueta = "Añadir cabecera SWC" if style == "swc" else "Añadir cabecera genérica"
        self._run_operation(etiqueta, transform, "with_header", "snes")

    def _snes_fix_checksum(self):
        def transform(data, name):
            header, err = rf.parse_snes(data)
            if header is None:
                raise ValueError(f"no se localizó la cabecera SNES: {err}")
            info = st.detect_copier_header(data)
            fixed, checksum, complement = st.fix_checksum(
                data, header.base, info.size if info.present else 0
            )
            base, ext = os.path.splitext(name)
            estado = "ya era correcto" if header.valid else "estaba mal y se ha corregido"
            return (fixed, f"{base}_checksum{ext}",
                    f"Checksum {estado}.\nChecksum: {rf.hexn(checksum, 4)}   "
                    f"Complemento: {rf.hexn(complement, 4)}")
        self._run_operation("Corregir checksum", transform, "checksum", "snes")

    def _split_file_generic(self):
        """Divide uno o varios archivos en partes de tamaño fijo, sin
        cabecera ni estructura de disco — un corte mecánico cada N bytes.
        Disponible igual en los tres sistemas: la operación no depende de
        ninguno en particular, solo cambia la carpeta donde se guarda el
        resultado. Pensada para usarse desde la ventana de trabajo, sobre
        los archivos que se tengan seleccionados ahí.
        """
        paths = self._selected_paths()
        if not paths and self._current_path:
            paths = [self._current_path]
        if not paths:
            QMessageBox.information(
                self._active_parent(), APP_TITLE,
                "Selecciona uno o varios archivos para dividirlos.")
            return

        dialog = FileSplitDialog(self._active_parent())
        if dialog.exec() != QDialog.Accepted:
            return
        chunk_size = dialog.chunk_size()
        if not chunk_size:
            return

        sistema = getattr(self, "_workbench_system", None) or self.system
        out_dir = ws.folder("split", sistema)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        ok_lines, skip_lines, generados = [], [], []

        for path in paths:
            name = os.path.basename(path)
            try:
                with open(path, "rb") as fh:
                    datos = fh.read()
                parts = st.split_floppy(datos, chunk_size)
                base, _ext = os.path.splitext(name)
                for i, part in enumerate(parts, start=1):
                    fpath = ws.unique_path(out_dir, f"{base}.{i:03d}")
                    with open(fpath, "wb") as fh:
                        fh.write(part)
                    generados.append(fpath)
                ok_lines.append(
                    f"OK       {name}  ->  {len(parts)} fragmento(s) de "
                    f"{rf.fmt_bytes(chunk_size)}")
            except OSError as e:
                skip_lines.append(f"ERROR    {name}  ({e})")

        QApplication.restoreOverrideCursor()
        self.register_generated(generados)
        self._clear_selections()

        if len(paths) == 1 and ok_lines:
            QMessageBox.information(
                self._active_parent(), APP_TITLE,
                f"{ok_lines[0]}\n\nCarpeta: {out_dir}")
            return

        report = (
            f"Dividir archivo en partes — {len(paths)} archivo(s)\n"
            f"Carpeta de resultados: {out_dir}\n\n"
            f"Procesados: {len(ok_lines)}   ·   con error: {len(skip_lines)}\n\n"
            "Detalle:\n" + "\n".join(ok_lines + skip_lines)
        )
        BatchReportDialog("Dividir archivo en partes — resultado", report, self._active_parent()).exec()

    def _rebuild_copier_disks(self):
        """Reconstruye el archivo original con cabecera de copiador (Super
        Wild Card o Super Magic Drive — comparten la misma cabecera de 512
        bytes, mismo fabricante de firmware) a partir de discos ya
        divididos, generados por esta aplicación o por cualquier otra
        herramienta de terceros.

        No hace falta seleccionar todos los discos de la serie: con uno
        solo basta (se localiza el resto en la misma carpeta, comparando
        el nombre BASE INTERNO real de cada disco —el que lleva el propio
        archivo dentro del .img—, no el nombre externo del archivo: así
        funciona igual sin importar qué convención de nombres use la
        herramienta que los haya creado).

        El sistema de destino (SNES o Genesis) se decide mirando el
        contenido ya reconstruido, no la pestaña activa: la cabecera por
        sí sola no lo dice, porque es idéntica para ambos.
        """
        paths = self._selected_paths()
        if not paths and self._current_path:
            paths = [self._current_path]
        if not paths:
            QMessageBox.information(
                self._active_parent(), APP_TITLE,
                "Selecciona uno o varios discos divididos (basta con uno "
                "por cada juego: el resto de la serie se localiza sola).")
            return

        # Agrupar por serie usando la clave de cabecera (nombre base +
        # resto de la cabecera constante), leyendo TODAS las partes de
        # cada disco seleccionado: algunas herramientas de terceros, como
        # WinImage (visto en discos reales de "Donkey Kong Country 2"),
        # meten más de una parte en el mismo disco físico cuando cada una
        # por separado dejaría demasiado espacio libre.
        series_representante: dict[tuple, str] = {}
        no_reconocidos = []
        for path in paths:
            try:
                partes_del_disco = rf.leer_partes_de_disco(path)
            except ValueError:
                no_reconocidos.append(os.path.basename(path))
                continue
            for parte in partes_del_disco:
                series_representante.setdefault(parte.clave_serie(), path)

        if not series_representante:
            QMessageBox.warning(
                self._active_parent(), APP_TITLE,
                "Ninguno de los archivos seleccionados es un disco con cabecera "
                "de copiador Super Wild Card / Super Magic Drive reconocible.")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        ok_lines, skip_lines, generados = [], [], []
        ultima_carpeta = ""

        for (nombre_base, _huella), path_representante in series_representante.items():
            try:
                # Siempre se completa la serie entera buscando en la
                # carpeta a partir de un representante: así da igual si
                # el usuario seleccionó una parte suelta, varias, o un
                # disco que ya trae dos partes juntas.
                partes = rf.find_disk_series(path_representante)
                datos, _nombre = rf.rebuild_from_disk_series(partes)

                sistema = sd.detectar(datos, nombre_base).sistema or "snes"
                if sistema == "genesis":
                    carpeta_destino, extension = ws.folder("smd", "genesis"), ".smd"
                else:
                    carpeta_destino, extension = ws.folder("with_header", "snes"), ".swc"
                ultima_carpeta = carpeta_destino

                out_path = ws.unique_path(carpeta_destino, f"{nombre_base}{extension}")
                with open(out_path, "wb") as fh:
                    fh.write(datos)
                generados.append(out_path)
                nombre_sistema = {"snes": "SNES", "genesis": "Mega Drive"}.get(sistema, sistema)
                ok_lines.append(
                    f"OK       {nombre_base}  ({len(partes)} parte(s), {nombre_sistema})  ->  "
                    f"{os.path.basename(out_path)}  ({rf.fmt_bytes(len(datos))})")
            except (ValueError, OSError) as e:
                skip_lines.append(f"ERROR    {nombre_base}  ({e})")

        QApplication.restoreOverrideCursor()
        self.register_generated(generados)
        self._clear_selections()

        if no_reconocidos:
            skip_lines.append(
                f"IGNORADOS, no son discos de copiador reconocibles ({len(no_reconocidos)}): "
                + ", ".join(no_reconocidos))

        if len(series_representante) == 1 and not no_reconocidos and ok_lines:
            QMessageBox.information(
                self._active_parent(), APP_TITLE, ok_lines[0] + f"\n\nCarpeta: {ultima_carpeta}")
            return

        report = (
            f"Reconstruir desde discos divididos — {len(series_representante)} serie(s)\n\n"
            f"Reconstruidas: {len(ok_lines)}   ·   con error: {len(skip_lines)}\n\n"
            "Detalle:\n" + "\n".join(ok_lines + skip_lines)
        )
        BatchReportDialog("Reconstruir desde discos — resultado", report, self._active_parent()).exec()

    def _snes_header_and_split(self):
        """Añade la cabecera Super Wild Card y divide en disquetes, de una vez.

        Es la secuencia habitual al preparar un juego para el copión, y
        hacerla en dos pasos obligaba a volver atrás y buscar de nuevo los
        archivos ya convertidos. Aquí se encadena: a cada ROM se le añade la
        cabecera si le falta, y el resultado se divide directamente.
        """
        paths = self._selected_paths()
        if not paths and self._current_path:
            paths = [self._current_path]
        if not paths:
            QMessageBox.information(
                self, APP_TITLE,
                "Selecciona una o varias ROMs de SNES para prepararlas.")
            return

        dlg_fmt = SwcDiskFormatDialog(self._active_parent())
        if dlg_fmt.exec() != QDialog.Accepted:
            return
        formato_disco = dlg_fmt.formato()

        out_dir = ws.folder("swc_disks", "snes")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        ok_lines, skip_lines, generados = [], [], []
        total_discos = 0
        for path in paths:
            name = os.path.basename(path)
            try:
                if os.path.splitext(name)[1].lower() == ".img":
                    raise ValueError("ya es una imagen de disquete")
                with open(path, "rb") as fh:
                    datos = fh.read()

                # Paso 1: cabecera Super Wild Card, si no la tiene ya
                info = st.detect_copier_header(datos)
                paso1 = ""
                if info.present and info.brand == "Super Wild Card":
                    paso1 = "ya tenía cabecera SWC"
                elif info.present:
                    # Otra cabecera de copiador: se sustituye por la de SWC
                    limpio = st.strip_header(datos)
                    cab, _e = rf.parse_snes(limpio)
                    hirom = bool(cab and "HiROM" in cab.kind)
                    sram_size = st.sram_size_from_ram_size_n(cab.ram_size_n) if cab else 32 * 1024
                    datos = st.add_header(limpio, style="swc", hirom=hirom, sram_size=sram_size)
                    paso1 = f"cabecera {info.brand or 'genérica'} sustituida por SWC"
                else:
                    cab, _e = rf.parse_snes(datos)
                    hirom = bool(cab and "HiROM" in cab.kind)
                    sram_size = st.sram_size_from_ram_size_n(cab.ram_size_n) if cab else 32 * 1024
                    datos = st.add_header(datos, style="swc", hirom=hirom, sram_size=sram_size)
                    paso1 = "cabecera SWC añadida"

                # Se guarda también la ROM con la cabecera puesta: es un
                # resultado útil por sí mismo y antes se perdía, porque solo
                # se escribían los disquetes.
                base = os.path.splitext(name)[0]
                if paso1 != "ya tenía cabecera SWC":
                    copia = ws.unique_path(ws.folder("with_header", "snes"),
                                            f"{base}_swc.swc")
                    with open(copia, "wb") as fh:
                        fh.write(datos)
                    generados.append(copia)

                # Paso 2: dividir en disquetes
                partes = st.split_swc_disks(datos, base_name=base, fmt=formato_disco)
                for p in partes:
                    destino = ws.unique_path(out_dir, p.filename)
                    with open(destino, "wb") as fh:
                        fh.write(p.image)
                    generados.append(destino)
                total_discos += len(partes)
                ok_lines.append(
                    f"OK       {name}  ·  {paso1}  ->  {len(partes)} disquete(s)"
                    + ("" if paso1 == "ya tenía cabecera SWC"
                       else "  (+ copia con cabecera guardada)"))
            except ValueError as e:
                skip_lines.append(f"OMITIDO  {name}  ({e})")
            except Exception as e:  # noqa: BLE001
                skip_lines.append(f"ERROR    {name}  ({e})")

        QApplication.restoreOverrideCursor()
        self.register_generated(generados)
        self._clear_selections()

        report = (
            f"Preparar para copión (cabecera SWC + división) — {len(paths)} ROM(s)\n"
            f"Carpeta de resultados: {out_dir}\n\n"
            f"Preparadas: {len(ok_lines)}   ·   disquetes generados: {total_discos}\n"
            f"Omitidas / con error: {len(skip_lines)}\n\n"
            "Detalle:\n" + "\n".join(ok_lines + skip_lines)
        )
        BatchReportDialog("Preparar para copión — resultado", report, self._active_parent()).exec()

    def _msx_extract_many(self):
        """Extrae en bloque el contenido de varias imágenes de disco.

        Cada imagen va a su propia subcarpeta. Es la vía rápida cuando lo que
        se quiere es volcar muchos discos de golpe, sin la selección fina de
        la ventana de extracción (que sigue siendo lo indicado para elegir
        archivos concretos, y está limitada a tres discos).
        """
        rutas = [p for p in self._selected_paths()
                 if os.path.splitext(p)[1].lower() in (".dsk", ".img", ".di1", ".di2")]
        if not rutas and self._current_path:
            if os.path.splitext(self._current_path)[1].lower() in (".dsk", ".img"):
                rutas = [self._current_path]
        if not rutas:
            QMessageBox.information(
                self, APP_TITLE,
                "Selecciona las imágenes de disco que quieras volcar. Puedes marcar "
                "todas las que quieras: cada una se extraerá a su propia subcarpeta.")
            return

        respuesta = QMessageBox.question(
            self, APP_TITLE,
            f"Se va a extraer TODO el contenido de {len(rutas)} imagen(es), cada una "
            f"en su propia subcarpeta dentro de:\n\n{ws.folder('extracted')}\n\n"
            "¿Continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if respuesta != QMessageBox.Yes:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        ok_lines, skip_lines = [], []
        total_archivos = 0
        base_dir = ws.folder("extracted", "msx")

        for ruta in rutas:
            nombre = os.path.basename(ruta)
            try:
                with open(ruta, "rb") as fh:
                    datos = fh.read()
                nota = ""
                if rf.detect_copia720_single_sided(datos):
                    datos = rf.copia720_to_single_sided(datos)
                    nota = " (COPIA720 recortada)"
                valido, motivo = rf.validate_dsk(datos)
                if not valido:
                    # Se resume el motivo para que quepa en el informe
                    raise ValueError(motivo.split(".")[0])
                dsk = rf.parse_dsk(datos)
                archivos = [e for e in dsk.entries if not e.is_dir]
                if not archivos and not any(e.is_dir for e in dsk.entries):
                    raise ValueError("el disco no contiene ningún archivo")
                carpeta = ws.unique_path(base_dir, os.path.splitext(nombre)[0])
                n, errores = self._extract_recursive(dsk, dsk.entries, carpeta)
                if n == 0:
                    # Sin archivos extraídos, la carpeta quedaría vacía
                    try:
                        os.rmdir(carpeta)
                    except OSError:
                        pass
                    raise ValueError("no se pudo extraer ningún archivo del disco")
                total_archivos += n
                if errores:
                    skip_lines.append(
                        f"PARCIAL  {nombre}{nota}: {n} archivo(s), "
                        f"{len(errores)} con error")
                else:
                    ok_lines.append(f"OK       {nombre}{nota}  ->  {n} archivo(s)")
            except Exception as e:  # noqa: BLE001
                skip_lines.append(f"ERROR    {nombre}  ({e})")

        QApplication.restoreOverrideCursor()
        self._clear_selections()

        report = (
            f"Extracción en bloque — {len(rutas)} imagen(es)\n"
            f"Carpeta de resultados: {base_dir}\n\n"
            f"Imágenes volcadas: {len(ok_lines)}   ·   archivos extraídos: {total_archivos}\n"
            f"Con errores: {len(skip_lines)}\n\n"
            "Cada imagen se ha volcado en su propia subcarpeta.\n\n"
            "Detalle:\n" + "\n".join(ok_lines + skip_lines)
        )
        BatchReportDialog("Extracción en bloque — resultado", report, self._active_parent()).exec()

    def _snes_deinterleave(self):
        self._snes_interleave_op(deinterleave=True)

    def _snes_interleave(self):
        self._snes_interleave_op(deinterleave=False)

    def _snes_interleave_op(self, deinterleave: bool):
        accion = "Desentrelazar" if deinterleave else "Entrelazar"
        suffix = "_deint" if deinterleave else "_int"

        def transform(data, name):
            info = st.detect_copier_header(data)
            header_bytes = data[:info.size] if info.present else b""
            rom = data[info.size:] if info.present else data
            result_rom = st.deinterleave_hirom(rom) if deinterleave else st.interleave_hirom(rom)
            base, ext = os.path.splitext(name)
            hecho = "Desentrelazado" if deinterleave else "Entrelazado"
            return (header_bytes + result_rom, f"{base}{suffix}{ext}",
                    f"{hecho} correctamente (formato simple: mitades de 32 KB por banco de 64 KB).\n"
                    "Recuerda recalcular el checksum sobre el resultado si vas a usarlo.")

        self._run_operation(f"Intercambiar bancos HiROM ({accion})", transform, "interleave", "snes")

    def _snes_batch_byteswap(self):
        dialog = BatchByteswapDialog(self._active_parent())
        if dialog.exec() != QDialog.Accepted:
            return
        deinterleave = dialog.deinterleave()
        suffix = dialog.suffix()

        directory = choose_directory(self)
        if not directory:
            return

        candidates = []
        for dirpath, _dirnames, filenames in os.walk(directory):
            for fn in filenames:
                if fn.startswith("."):
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if ext in SNES_ROM_EXTENSIONS and suffix not in fn:
                    candidates.append(os.path.join(dirpath, fn))
        candidates.sort()

        if not candidates:
            QMessageBox.information(
                self, APP_TITLE,
                "No se encontraron archivos SNES en esa carpeta "
                f"({', '.join(sorted(SNES_ROM_EXTENSIONS))}), o todos ya tienen la coletilla "
                f'"{suffix}" (se omiten para no reprocesar resultados anteriores).',
            )
            return

        ok_lines, skip_lines, batch_generados = [], [], []
        for path in candidates:
            name = os.path.basename(path)
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
                info = st.detect_copier_header(data)
                header_bytes = data[:info.size] if info.present else b""
                rom = data[info.size:] if info.present else data
                result_rom = st.deinterleave_hirom(rom) if deinterleave else st.interleave_hirom(rom)
                result = header_bytes + result_rom
                base, ext = os.path.splitext(name)
                out_path = os.path.join(os.path.dirname(path), f"{base}{suffix}{ext}")
                with open(out_path, "wb") as fh:
                    fh.write(result)
                batch_generados.append(out_path)
                ok_lines.append(f"OK      {os.path.relpath(path, directory)}  ->  {os.path.basename(out_path)}")
            except Exception as e:  # noqa: BLE001
                skip_lines.append(f"OMITIDO {os.path.relpath(path, directory)}  ({e})")

        self.register_generated(batch_generados)
        accion = "Desentrelazado" if deinterleave else "Entrelazado"
        report = (
            f"{accion} por lotes\n"
            f"Carpeta: {directory}\n"
            f"Coletilla: {suffix}\n\n"
            f"Procesados correctamente: {len(ok_lines)}\n"
            f"Omitidos: {len(skip_lines)}\n"
            + ("\n\nDetalle:\n" + "\n".join(ok_lines + skip_lines) if (ok_lines or skip_lines) else "")
        )
        BatchReportDialog(f"{accion} por lotes — resultado", report, self._active_parent()).exec()

    # -- MSX -------------------------------------------------------------
    def _render_msx(self, name: str, data: bytes):
        # Las imágenes volcadas con COPIA720 en modo cara simple (/1) miden
        # 720 KB con la segunda cara rellena de 0xE5. Se detectan y se
        # muestran ya recortadas a su tamaño real de 360 KB, indicándolo.
        aviso_copia720 = ""
        if rf.detect_copia720_single_sided(data):
            data = rf.copia720_to_single_sided(data)
            aviso_copia720 = (
                "Imagen de COPIA720 en modo cara simple (/1): ocupaba 720 KB con la "
                "segunda cara rellena de 0xE5. Se muestra ya recortada a sus 360 KB "
                "reales. Usa «Recortar imagen COPIA720» para guardarla así."
            )
        self._copia720_detected = bool(aviso_copia720)

        kind, payload = rf.classify_msx(name, data)

        if kind == "error":
            self.detail.build([badge("ERROR", "bad")], name, str(payload), [], None)
            return

        if kind == "rom":
            h: rf.MSXRomHeader = payload
            guess = rf.guess_msx_mapper(data)
            fields = [
                FieldSpec("Firma", "AB", 0, 2),
                FieldSpec("INIT (arranque en frío)", rf.hexn(h.init, 4), 2, 2),
                FieldSpec("STATEMENT (extensión BASIC)", rf.hexn(h.statement, 4), 4, 2),
                FieldSpec("DEVICE (driver de dispositivo)", rf.hexn(h.device, 4), 6, 2),
                FieldSpec("TEXT (puntero de texto)", rf.hexn(h.text, 4), 8, 2),
            ] + mapper_fields(guess)
            badges = [badge("ROM DE CARTUCHO")]
            mb = mapper_badge(guess)
            if mb:
                badges.append(mb)
            if guess.sram:
                badges.append(badge("POSIBLE SRAM", "warn"))
            self.detail.build(
                badges, name,
                f'{rf.fmt_bytes(len(data))} · firma "AB" detectada en offset 0x0000',
                fields, data,
            )
            return

        if kind == "bin":
            h: rf.MSXBinHeader = payload
            fields = [
                FieldSpec("Byte de tipo", "0xFE", 0, 1),
                FieldSpec("Dirección de inicio", rf.hexn(h.start, 4), 1, 2),
                FieldSpec("Dirección de fin", rf.hexn(h.end, 4), 3, 2),
                FieldSpec("Dirección de ejecución", rf.hexn(h.exec_addr, 4), 5, 2),
                FieldSpec("Tamaño de datos", rf.fmt_bytes(h.end - h.start + 1)),
            ]
            self.detail.build(
                [badge("BINARIO CON CABECERA (BLOAD)")], name,
                f"{rf.fmt_bytes(len(data))} · byte de tipo 0xFE en offset 0x0000",
                fields, data,
            )
            return

        if kind == "dsk":
            valido, motivo = rf.validate_dsk(data)
            if not valido:
                self._dsk_ctx = None
                self.detail.build(
                    [badge("DISCO SIN SISTEMA DE ARCHIVOS", "warn")], name,
                    f"{rf.fmt_bytes(len(data))} · no se puede listar su contenido",
                    [], data[:512],
                    extra_widget=self._build_aviso_disco(motivo))
                return
            self._dsk_ctx = (name, payload)
            self._render_dsk_view(name, payload)
            return

        # raw / desconocido
        self.detail.build(
            [badge("SIN CABECERA RECONOCIDA", "warn")], name,
            f'{rf.fmt_bytes(len(data))} · no empieza con "AB" (ROM) ni 0xFE (binario con cabecera)',
            [], data,
        )

    def _build_aviso_disco(self, motivo: str) -> QWidget:
        """Explicación de por qué no se puede leer el contenido de un disco."""
        box = QFrame()
        box.setObjectName("FieldChip")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(7)

        titulo = QLabel("POR QUÉ NO SE PUEDE EXTRAER SU CONTENIDO")
        titulo.setObjectName("SectionLabel")
        lay.addWidget(titulo)

        texto = QLabel(motivo)
        texto.setWordWrap(True)
        texto.setStyleSheet("color: #ffb454;")
        lay.addWidget(texto)

        pista = QLabel(
            "Lo que SÍ puedes hacer con este disco: grabarlo en un disquete real "
            "(la imagen es correcta y arrancará en el MSX), copiarlo, convertirlo "
            "entre formatos de 360 y 720 KB, o examinar su sector de arranque en el "
            "volcado hexadecimal de arriba."
        )
        pista.setObjectName("Hint")
        pista.setWordWrap(True)
        lay.addWidget(pista)
        return box

    def _render_dsk_view(self, dsk_name: str, dsk: rf.DskImage):
        tree = QTreeWidget()
        tree.setColumnCount(4)
        tree.setHeaderLabels(["Nombre", "Tamaño", "Clúster inicial", "Atributo"])
        tree.setEditTriggers(QTreeWidget.NoEditTriggers)
        tree.setSelectionBehavior(QTreeWidget.SelectRows)
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tree.setMouseTracking(True)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.setMinimumHeight(min(60 + 24 * max(len(dsk.entries), 1), 360))
        preview_cache: dict[int, str] = {}

        def add_entries(parent_item, entries):
            for e in entries:
                icon = "📁 " if e.is_dir else "📄 "
                item = QTreeWidgetItem([
                    icon + e.name,
                    "—" if e.is_dir else rf.fmt_bytes(e.size),
                    str(e.cluster),
                    f"0x{e.attr:02X}",
                ])
                item.setData(0, Qt.UserRole, e)
                if parent_item is None:
                    tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                if e.is_dir:
                    add_entries(item, e.children)

        add_entries(None, dsk.entries)

        def on_double_click(item, _col):
            entry = item.data(0, Qt.UserRole)
            if entry.is_dir:
                item.setExpanded(not item.isExpanded())
                return
            try:
                sub_bytes = rf.reconstruct_dsk_file(dsk, entry)
            except Exception as e:  # noqa: BLE001
                self.detail.show_placeholder(f"No se pudo reconstruir el archivo: {e}")
                return
            self._render_msx_subfile(entry.name, sub_bytes, dsk_name, dsk)

        tree.itemDoubleClicked.connect(on_double_click)

        def on_hover(item, _col=0):
            entry = item.data(0, Qt.UserRole)
            key = id(entry)
            if key in preview_cache:
                item.setToolTip(0, preview_cache[key])
                return
            try:
                if entry.is_dir:
                    files, dirs = rf.count_entries(entry.children)
                    text = f"{entry.name}  ·  carpeta ({files} archivo(s), {dirs} subcarpeta(s))"
                else:
                    data = rf.reconstruct_dsk_file(dsk, entry)
                    text = rf.build_preview(entry.name, data)
            except Exception as e:  # noqa: BLE001
                text = f"No se pudo leer: {e}"
            preview_cache[key] = text
            item.setToolTip(0, text)

        tree.itemEntered.connect(on_hover)

        def on_context_menu(pos):
            item = tree.itemAt(pos)
            if item is None:
                return
            entry = item.data(0, Qt.UserRole)
            menu = QMenu(tree)
            label = f'Extraer carpeta "{entry.name}"…' if entry.is_dir else f'Extraer "{entry.name}"…'
            action = menu.addAction(label)
            chosen = menu.exec(tree.viewport().mapToGlobal(pos))
            if chosen is action:
                self._extract_entry(dsk, entry)

        tree.customContextMenuRequested.connect(on_context_menu)

        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(6)

        top_row = QHBoxLayout()
        sect = QLabel(
            "CONTENIDO DEL DISCO — doble clic: inspeccionar archivo / expandir carpeta · "
            "ratón encima: vista previa · clic derecho: extraer"
        )
        sect.setObjectName("SectionLabel")
        sect.setWordWrap(True)
        top_row.addWidget(sect, 1)
        wl.addLayout(top_row)
        wl.addWidget(tree)

        total_files, total_dirs = rf.count_entries(dsk.entries)
        fields = [
            FieldSpec("Sectores reservados", dsk.reserved),
            FieldSpec("Nº de copias de FAT", dsk.nfat),
            FieldSpec("Entradas en raíz", dsk.root_entries),
            FieldSpec("Sectores totales", dsk.total_sectors),
            FieldSpec("Sectores por FAT", dsk.spf),
            FieldSpec("Archivos (total)", total_files),
            FieldSpec("Subcarpetas (total)", total_dirs),
        ]

        badges = [badge("DISCO MSX-DOS (DSK)")]
        subtitulo = (f"{rf.fmt_bytes(len(dsk.raw))} · {dsk.bps} bytes/sector · "
                     f"{dsk.spc} sector(es)/clúster · media 0x{dsk.media:02X}")
        if getattr(self, "_copia720_detected", False):
            badges.append(badge("COPIA720 CARA SIMPLE", "warn"))
            subtitulo += (" · recortada de 720 KB a 360 KB (la segunda cara era "
                          "relleno de COPIA720 /1)")

        # Los botones de extracción van ARRIBA, junto a la insignia del tipo de
        # disco: antes estaban al final del panel y había que hacer scroll para
        # llegar a ellos, que es justo lo contrario de lo que uno espera.
        acciones = QHBoxLayout()
        acciones.setSpacing(8)
        b_sueltos = QPushButton("Extraer archivos sueltos…")
        b_sueltos.setToolTip(
            "Abre una ventana grande para marcar cómodamente qué archivos "
            "extraer, incluso de varias imágenes a la vez")
        b_sueltos.setStyleSheet(BOTON_EXTRAER)
        b_sueltos.setCursor(Qt.PointingHandCursor)
        b_sueltos.clicked.connect(self._open_extract_dialog)
        b_todo = QPushButton("Extraer todo el disco")
        b_todo.setToolTip("Vuelca de una vez todo el contenido de esta imagen")
        b_todo.setCursor(Qt.PointingHandCursor)
        b_todo.clicked.connect(lambda: self._extract_all(dsk, dsk_name))
        acciones.addWidget(b_sueltos)
        acciones.addWidget(b_todo)
        acciones.addStretch(1)

        self.detail.build(
            badges, dsk_name, subtitulo,
            fields, None, extra_widget=wrapper, header_actions=acciones,
        )

    # -- extracción de archivos del DSK ----------------------------------
    def _extract_entry(self, dsk: rf.DskImage, entry: rf.DskEntry):
        if entry.is_dir:
            dest_dir = ws.folder("extracted", "msx")
            target = ws.unique_path(dest_dir, entry.name)
            count, errors = self._extract_recursive(dsk, entry.children, target)
            self._show_extract_summary(count, errors, target)
        else:
            path = elegir_archivo_guardar(
                self, nombre_sugerido=entry.name, titulo="Extraer archivo")
            if not path:
                return
            try:
                data = rf.reconstruct_dsk_file(dsk, entry)
                with open(path, "wb") as fh:
                    fh.write(data)
                QMessageBox.information(self._active_parent(), APP_TITLE, f"Archivo extraído a:\n{path}")
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self._active_parent(), APP_TITLE, f"No se pudo extraer el archivo: {e}")

    def _extract_all(self, dsk: rf.DskImage, dsk_name: str):
        dest_dir = ws.folder("extracted", "msx")
        base, _ext = os.path.splitext(dsk_name)
        target = ws.unique_path(dest_dir, base)
        count, errors = self._extract_recursive(dsk, dsk.entries, target)
        self._show_extract_summary(count, errors, target)

    def _extract_recursive(self, dsk: rf.DskImage, entries: list, dest_dir: str):
        count = 0
        errors: list[str] = []
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except OSError as e:
            return 0, [f"No se pudo crear la carpeta {dest_dir}: {e}"]
        for e in entries:
            if e.is_dir:
                sub_count, sub_errors = self._extract_recursive(dsk, e.children, os.path.join(dest_dir, e.name))
                count += sub_count
                errors.extend(sub_errors)
            else:
                try:
                    data = rf.reconstruct_dsk_file(dsk, e)
                    with open(os.path.join(dest_dir, e.name), "wb") as fh:
                        fh.write(data)
                    count += 1
                except Exception as ex:  # noqa: BLE001
                    errors.append(f"{e.name}: {ex}")
        return count, errors

    def _show_extract_summary(self, count: int, errors: list, target: str):
        msg = f"Extraído(s) {count} archivo(s) a:\n{target}"
        if errors:
            shown = errors[:20]
            msg += f"\n\n{len(errors)} error(es):\n" + "\n".join(shown)
            if len(errors) > 20:
                msg += f"\n… y {len(errors) - 20} más"
        QMessageBox.information(self._active_parent(), APP_TITLE, msg)


    def _render_msx_subfile(self, name: str, data: bytes, dsk_name: str, dsk: rf.DskImage):
        kind, payload = rf.classify_msx(name, data)
        back = lambda: self._render_dsk_view(dsk_name, dsk)  # noqa: E731

        if kind == "rom":
            h: rf.MSXRomHeader = payload
            guess = rf.guess_msx_mapper(data)
            fields = [
                FieldSpec("Firma", "AB", 0, 2),
                FieldSpec("INIT", rf.hexn(h.init, 4), 2, 2),
                FieldSpec("STATEMENT", rf.hexn(h.statement, 4), 4, 2),
                FieldSpec("DEVICE", rf.hexn(h.device, 4), 6, 2),
                FieldSpec("TEXT", rf.hexn(h.text, 4), 8, 2),
            ] + mapper_fields(guess)
            badges = [badge("ROM DE CARTUCHO (dentro del DSK)")]
            mb = mapper_badge(guess)
            if mb:
                badges.append(mb)
            if guess.sram:
                badges.append(badge("POSIBLE SRAM", "warn"))
            self.detail.build(
                badges, name,
                f"{rf.fmt_bytes(len(data))} reconstruidos desde el disco",
                fields, data, back_callback=back, back_text=f"volver a {dsk_name}",
            )
        elif kind == "bin":
            h: rf.MSXBinHeader = payload
            fields = [
                FieldSpec("Dirección de inicio", rf.hexn(h.start, 4), 1, 2),
                FieldSpec("Dirección de fin", rf.hexn(h.end, 4), 3, 2),
                FieldSpec("Dirección de ejecución", rf.hexn(h.exec_addr, 4), 5, 2),
            ]
            self.detail.build(
                [badge("BINARIO CON CABECERA (dentro del DSK)")], name,
                f"{rf.fmt_bytes(len(data))} reconstruidos desde el disco",
                fields, data, back_callback=back, back_text=f"volver a {dsk_name}",
            )
        else:
            self.detail.build(
                [badge("SIN CABECERA RECONOCIDA", "warn")], name,
                f"{rf.fmt_bytes(len(data))} reconstruidos desde el disco",
                [], data, back_callback=back, back_text=f"volver a {dsk_name}",
            )

    # -- Mega Drive --------------------------------------------------------
    def _render_genesis(self, name: str, data: bytes):
        badges, titulo, subtitulo, fields, hexdata, extra = self._analyze_genesis(name, data)
        self.detail.build(badges, titulo, subtitulo, fields, hexdata, extra_widget=extra)

    def _analyze_genesis(self, name: str, data: bytes):
        """Calcula el análisis de una ROM de Mega Drive, sin tocar la UI.

        Devuelve (badges, titulo, subtitulo, fields, hexdata, extra_widget),
        exactamente lo que espera DetailPanel.build(). Separado de
        _render_genesis para poder reutilizarlo tanto en el panel embebido
        como en la ventana de análisis por lotes (RomAnalysisDialog).
        """
        header, err = rf.parse_genesis(data)
        if header is None:
            avisos = [badge("CABECERA NO ENCONTRADA", "warn")]
            extra = ""
            if gt.is_byteswapped(data) is True:
                avisos.append(badge("BYTES INTERCAMBIADOS", "warn"))
                extra = (" · Parece un volcado con los bytes intercambiados (aparece "
                         "\"ESAGG NESESI\" en 0x100). Usa «Byte swap» para corregirlo.")
            else:
                smd_info = gt.detect_smd_header(data)
                if smd_info.present:
                    avisos.append(badge("POSIBLE FORMATO SMD", "warn"))
                    extra = (" · Parece estar en formato SMD entrelazado. Usa «SMD → BIN» "
                             "para convertirlo.")
            return (avisos, name, f"{rf.fmt_bytes(len(data))} · {err}{extra}",
                    [], data[0x100:] if len(data) >= 0x100 else None, None)

        fields = [
            FieldSpec("Consola", header.console_name, 0, 16),
            FieldSpec("Copyright / fecha", header.copyright, 0x10, 16),
            FieldSpec("Título (Japón)", header.domestic, 0x20, 48),
            FieldSpec("Título (exportación)", header.overseas, 0x50, 48),
            FieldSpec("Nº de serie", header.serial, 0x80, 14),
            FieldSpec("Checksum", rf.hexn(header.checksum, 4), 0x8E, 2),
            FieldSpec("Dispositivos de entrada", header.io_support, 0x90, 16),
            FieldSpec("Inicio de ROM", rf.hexn(header.rom_start, 8), 0xA0, 4),
            FieldSpec("Fin de ROM", rf.hexn(header.rom_end, 8), 0xA4, 4),
            FieldSpec("Inicio de RAM", rf.hexn(header.ram_start, 8), 0xA8, 4),
            FieldSpec("Fin de RAM", rf.hexn(header.ram_end, 8), 0xAC, 4),
            FieldSpec("SRAM", header.sram or "—", 0xB0, 12),
            FieldSpec("Región", header.region, 0xF0, 16),
        ]
        return ([badge("CABECERA SEGA · 0x100")], name, rf.fmt_bytes(len(data)),
                fields, data[0x100:], None)

    # -- SNES ----------------------------------------------------------
    def _render_snes(self, name: str, data: bytes):
        badges, titulo, subtitulo, fields, hexdata, extra = self._analyze_snes(name, data)
        self.detail.build(badges, titulo, subtitulo, fields, hexdata, extra_widget=extra)

    def _analyze_snes(self, name: str, data: bytes):
        """Calcula el análisis de una ROM de SNES, sin tocar la UI.

        Devuelve (badges, titulo, subtitulo, fields, hexdata, extra_widget).
        Ver _analyze_genesis: mismo motivo, reutilizable en varios sitios.
        """
        header, err = rf.parse_snes(data)
        if header is None:
            return ([badge("CABECERA NO ENCONTRADA", "warn")], name,
                    f"{rf.fmt_bytes(len(data))} · {err}", [], None, None)

        rom_kb = 2 ** header.rom_size_n
        ram_kb = 2 ** header.ram_size_n if header.ram_size_n else 0
        is_fast = bool(header.map_mode & 0x10)

        badges = [badge(header.kind.upper() + (" · CHECKSUM OK" if header.valid else ""),
                         "default" if header.valid else "warn")]
        copier_info = st.detect_copier_header(data)
        if copier_info.present:
            badges.append(badge(f"COPIADORA: {copier_info.brand.upper()} (+512)", "warn"))

        fields = [
            FieldSpec("Título", header.title or "—", 0, 21),
            FieldSpec("Modo de mapeo", rf.hexn(header.map_mode, 2) + f" ({'FastROM' if is_fast else 'SlowROM'})", 21, 1),
            FieldSpec("Tipo de cartucho / chip", rf.hexn(header.rom_type, 2), 22, 1),
            FieldSpec("Tamaño de ROM", f"{rom_kb} KB", 23, 1),
            FieldSpec("Tamaño de RAM", f"{ram_kb} KB" if ram_kb else "sin RAM", 24, 1),
            FieldSpec("Región", f"{rf.SNES_REGIONS.get(header.dest_code, 'desconocida')} ({header.dest_code})", 25, 1),
            FieldSpec("Versión", f"1.{header.version}", 27, 1),
            FieldSpec("Complemento de checksum", rf.hexn(header.ccomp, 4), 28, 2),
            FieldSpec("Checksum", rf.hexn(header.csum, 4), 30, 2),
        ]
        if copier_info.present and copier_info.block_count is not None:
            fields.append(FieldSpec("Bloques SWC (8 KB)", copier_info.block_count))
        # Compatibilidad conocida con la Super Wild Card
        compat = sc.buscar(header.title or "") or sc.buscar(name)
        extra_widget = None
        if compat:
            entrada, _ratio = compat
            badges.append(badge(
                "SWC: " + ("COMPATIBLE" if entrada.funciona else entrada.gravedad.upper()),
                {"ok": "default", "aviso": "warn",
                 "accion": "warn", "problema": "bad"}[entrada.gravedad],
            ))
            extra_widget = self._build_compat_panel(entrada)

        return (badges, header.title or "(sin título)",
                f"{rf.fmt_bytes(len(data))} · cabecera localizada en {rf.hexn(header.base, 6)}",
                fields, data[header.base:], extra_widget)

    def _build_compat_panel(self, entrada) -> QWidget:
        """Aviso de compatibilidad del juego con la Super Wild Card."""
        box = QFrame()
        box.setObjectName("FieldChip")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(5)

        titulo = QLabel(f"COMPATIBILIDAD SUPER WILD CARD — {entrada.nombre}")
        titulo.setObjectName("SectionLabel")
        titulo.setWordWrap(True)
        lay.addWidget(titulo)

        color = {"ok": "#3ef29a", "aviso": "#ffb454",
                 "accion": "#ffb454", "problema": "#ff5f6d"}[entrada.gravedad]
        for texto in entrada.descripciones():
            l = QLabel("• " + texto)
            l.setWordWrap(True)
            l.setStyleSheet(f"color: {color};")
            lay.addWidget(l)

        opciones = entrada.opciones_ucon64()
        if opciones:
            l = QLabel("Al transferir con uCON64, añade: " + "  ".join(opciones))
            l.setWordWrap(True)
            l.setStyleSheet("color: #dde3ef; font-family: 'IBM Plex Mono', monospace;")
            lay.addWidget(l)

        if entrada.nota:
            l = QLabel("Nota del autor de la lista: " + entrada.nota)
            l.setObjectName("Hint")
            l.setWordWrap(True)
            lay.addWidget(l)

        fuente = QLabel(
            f"Fuente: lista de compatibilidad de dbjh (uCON64), versión "
            f"{sc.meta().get('Version', '?')} — probada en una Super Wild Card 2.8cc "
            f"32 Mbit PAL. {sc.total()} juegos catalogados."
        )
        fuente.setObjectName("Hint")
        fuente.setWordWrap(True)
        fuente.setStyleSheet("font-size: 10px;")
        lay.addWidget(fuente)
        return box


# ---------------------------------------------------------------------------
# Ventana principal
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} {APP_VERSION}")
        self.resize(1180, 760)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        brand = QLabel(APP_TITLE)
        brand.setObjectName("Brand")
        sub = QLabel(APP_BYLINE)
        sub.setObjectName("Byline")
        sub.setFont(load_byline_font(16))

        # La versión va justo después de la firma, en blanco para que resalte
        # sobre el azul de esta sin competir con ella.
        version_lbl = QLabel(f"v{APP_VERSION}")
        version_lbl.setObjectName("Version")
        sub2 = QLabel("MSX · SEGA MEGA DRIVE · SUPER NINTENDO")
        sub2.setObjectName("Sub")
        header_row.addWidget(brand)
        header_row.addSpacing(12)
        header_row.addWidget(sub)
        header_row.addSpacing(8)
        header_row.addWidget(version_lbl)
        header_row.addStretch(1)
        header_row.addWidget(sub2)
        root.addLayout(header_row)

        self.tabs = QTabWidget()
        self.panels = {
            "msx": SystemPanel("msx", lambda: ACCENTS["msx"]),
            "genesis": SystemPanel("genesis", lambda: ACCENTS["genesis"]),
            "snes": SystemPanel("snes", lambda: ACCENTS["snes"]),
        }
        self.tabs.addTab(self.panels["msx"], "MSX")
        self.tabs.addTab(self.panels["genesis"], "MEGA DRIVE")
        self.tabs.addTab(self.panels["snes"], "SUPER NES")
        self.tabs.setIconSize(QSize(40, 40))
        self.tabs.setTabIcon(0, QIcon(icon_path("msx.svg")))
        self.tabs.setTabIcon(1, QIcon(icon_path("genesis.svg")))
        self.tabs.setTabIcon(2, QIcon(icon_path("snes.svg")))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        # "Elegir carpeta" y "Carpeta Asturconsole" viven en la esquina de la
        # barra de pestañas (no repetidos dentro de cada panel): actúan
        # siempre sobre el sistema activo en ese momento.
        esquina = QWidget()
        esquina_lay = QHBoxLayout(esquina)
        esquina_lay.setContentsMargins(0, 0, 6, 0)
        esquina_lay.setSpacing(8)

        separador = QFrame()
        separador.setFrameShape(QFrame.VLine)
        separador.setObjectName("CornerSeparator")
        separador.setFixedHeight(24)
        esquina_lay.addWidget(separador)

        self.pick_btn = QPushButton("📂  Elegir carpeta")
        self.pick_btn.setObjectName("Primary")
        self.pick_btn.clicked.connect(self._pick_directory_current)
        esquina_lay.addWidget(self.pick_btn)

        self.workspace_btn = QPushButton(" Carpeta Asturconsole")
        self.workspace_btn.setIcon(QIcon(icon_path("asturias.svg")))
        self.workspace_btn.setIconSize(QSize(20, 20))
        self.workspace_btn.setToolTip(
            "Abrir la carpeta donde la aplicación lee y guarda los archivos"
        )
        self.workspace_btn.clicked.connect(self._open_workspace_current)
        esquina_lay.addWidget(self.workspace_btn)

        self.tabs.setCornerWidget(esquina, Qt.TopRightCorner)

        self._apply_theme("msx")

    def _current_panel(self) -> "SystemPanel":
        return self.panels[["msx", "genesis", "snes"][self.tabs.currentIndex()]]

    def _pick_directory_current(self):
        self._current_panel().pick_directory()

    def _open_workspace_current(self):
        self._current_panel()._open_workspace()

    def _on_tab_changed(self, index: int):
        system = ["msx", "genesis", "snes"][index]
        self._apply_theme(system)

    def _apply_theme(self, system: str):
        accent = ACCENTS[system]
        accent_bg = hex_to_rgba(accent, 0.15)
        scanline_bg = icon_path("scanlines_bg.png").replace("\\", "/")
        qss = BASE_QSS.format(accent=accent, accent_bg=accent_bg, scanline_bg=scanline_bg)
        QApplication.instance().setStyleSheet(qss)
        for panel in self.panels.values():
            # el color de resaltado del hex view activo se relee al reconstruir el panel
            pass


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(APP_VERSION)
    # Crear el árbol de carpetas de trabajo antes de construir la interfaz,
    # para que las pestañas puedan cargar ya la carpeta de originales.
    try:
        ws.ensure_workspace()
    except OSError as e:
        print(f"Aviso: no se pudo crear la carpeta de trabajo: {e}", file=sys.stderr)

    # Aviso informativo (nunca se toca nada automáticamente): si hay
    # contenido en una ubicación antigua de la carpeta de trabajo —de
    # cuando esta se creaba junto al ejecutable en vez de en el HOME—
    # se avisa para que el usuario decida qué hacer con él, con su propio
    # gestor de archivos y sin ningún riesgo de que la aplicación mueva
    # nada por su cuenta.
    antigua = ws.ubicacion_antigua_con_contenido()
    if antigua:
        QMessageBox.information(
            None, APP_TITLE,
            f"Se ha encontrado contenido en una ubicación antigua de la carpeta "
            f"de trabajo:\n\n{antigua}\n\n"
            f"La carpeta de trabajo actual es:\n{ws.base_dir()}\n\n"
            "Si quieres conservar ese contenido anterior, muévelo tú mismo a la "
            "carpeta actual (esta aplicación no lo hará automáticamente). Este "
            "aviso no volverá a salir una vez que la carpeta antigua quede vacía."
        )

    app_icon = QIcon(icon_path("app_icon.svg"))
    app.setWindowIcon(app_icon)
    win = MainWindow()
    win.setWindowIcon(app_icon)
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
