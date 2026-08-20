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

from PySide6.QtCore import Qt, Signal, QSize, QUrl
from PySide6.QtGui import (
    QFont, QFontDatabase, QTextCharFormat, QColor, QTextCursor, QIcon,
    QDesktopServices, QShortcut, QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QSplitter, QTabWidget,
    QScrollArea, QFrame, QPlainTextEdit, QTextEdit,
    QHeaderView, QSizePolicy, QFileDialog, QMessageBox, QDialog, QComboBox,
    QLineEdit, QDialogButtonBox, QTreeWidget, QTreeWidgetItem, QMenu,
    QProgressBar, QSlider, QCheckBox, QListView, QSpinBox,
)

import rom_formats as rf
import snes_tools as st
import cas_tape as ct
import tsx_tape as tt
import genesis_tools as gt
import msxdos_disk as md
import swc_compat as sc
import workspace as ws
from disk_panel import build_disk_panel
from folder_picker import choose_directory

APP_TITLE = "ASTURCONSOLE"
APP_BYLINE = "asturconsole by ritcher1986"

def _app_base_dir() -> str:
    """Carpeta base de la app: la del ejecutable si PyInstaller la ha
    empaquetado (sys._MEIPASS), o la del propio script en ejecución normal.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


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

class FloppySplitDialog(QDialog):
    """Diálogo para elegir el tamaño de fragmento al dividir un archivo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dividir en disquetes")
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        info = QLabel("Elige el tamaño de disquete de época para trocear el archivo:")
        info.setWordWrap(True)
        lay.addWidget(info)

        self.combo = QComboBox()
        self.combo.addItems(list(st.FLOPPY_SIZES.keys()))
        self.combo.addItem("Personalizado (KB)")
        self.combo.currentTextChanged.connect(self._on_change)
        lay.addWidget(self.combo)

        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("tamaño en KB, p. ej. 800")
        self.custom_edit.setVisible(False)
        lay.addWidget(self.custom_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _on_change(self, text: str):
        self.custom_edit.setVisible(text == "Personalizado (KB)")

    def chunk_size(self) -> Optional[int]:
        text = self.combo.currentText()
        if text == "Personalizado (KB)":
            try:
                kb = int(self.custom_edit.text().strip())
                if kb <= 0:
                    raise ValueError
                return kb * 1024
            except ValueError:
                QMessageBox.warning(self, APP_TITLE, "Introduce un tamaño en KB válido.")
                return None
        return st.FLOPPY_SIZES[text]


class BatchByteswapDialog(QDialog):
    """Diálogo para elegir la operación y la coletilla del proceso por lotes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Byte swap por lotes (SNES)")
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
                ws.folder("msxdos"), ws.folder("msxdos_utils"), version,
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

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        toolbar = QHBoxLayout()
        self.pick_btn = QPushButton("📂  Elegir carpeta")
        self.pick_btn.setObjectName("Primary")
        self.pick_btn.clicked.connect(self.pick_directory)
        self.path_lbl = QLabel("Ninguna carpeta seleccionada")
        self.path_lbl.setObjectName("Hint")
        self.workspace_btn = QPushButton(" Carpeta Asturconsole")
        self.workspace_btn.setIcon(QIcon(icon_path("asturias.svg")))
        self.workspace_btn.setIconSize(QSize(20, 20))
        self.workspace_btn.setToolTip(
            "Abrir la carpeta donde la aplicación lee y guarda los archivos"
        )
        self.workspace_btn.clicked.connect(self._open_workspace)
        toolbar.addWidget(self.pick_btn)
        toolbar.addWidget(self.workspace_btn)
        toolbar.addWidget(self.path_lbl, 1)
        if system == "msx":
            mappers_btn = QPushButton("🛈  Mappers MSX")
            mappers_btn.clicked.connect(lambda: MapperInfoDialog(self).exec())
            toolbar.addWidget(mappers_btn)
        root.addLayout(toolbar)

        self._current_path: Optional[str] = None
        self._current_name: Optional[str] = None
        self._current_data: Optional[bytes] = None

        if system == "snes":
            root.addWidget(self._build_snes_tools())
        if system == "msx":
            root.addWidget(self._build_tape_tools())
            root.addWidget(build_disk_panel(self, icon_path))
        if system == "genesis":
            root.addWidget(self._build_genesis_tools())
        if system in ("snes", "genesis"):
            root.addWidget(self._build_transfer_tools())

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
        ol.addWidget(self.orig_lbl)
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
            ws.folder(c) for c in ws.CATEGORIES if c != "source"
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
            QMessageBox.warning(self, APP_TITLE, f"No se pudo abrir la ventana: {e}")
            return

        dlg = WorkspaceBrowser(self, icon_dir=_icon_base_dir())
        dlg.abrir_archivo.connect(self._abrir_desde_explorador)
        dlg.abrir_imagenes.connect(self._abrir_imagenes_desde_explorador)
        dlg.exec()

    def _abrir_desde_explorador(self, ruta: str):
        """Analiza en el panel de detalle un archivo elegido en el explorador."""
        if not os.path.isfile(ruta):
            return
        try:
            with open(ruta, "rb") as fh:
                datos = fh.read()
        except OSError as e:
            QMessageBox.warning(self, APP_TITLE, f"No se pudo leer el archivo: {e}")
            return
        self.register_generated(ruta)
        nombre = os.path.basename(ruta)
        self._current_path, self._current_name, self._current_data = ruta, nombre, datos
        if self.system == "msx":
            self._render_msx(nombre, datos)
        elif self.system == "genesis":
            self._render_genesis(nombre, datos)
        else:
            self._render_snes(nombre, datos)

    def _abrir_imagenes_desde_explorador(self, rutas: list):
        """Abre imágenes de disco directamente en la ventana de extracción."""
        try:
            from extract_dialog import ExtractFilesDialog, MAX_IMAGENES
        except ImportError as e:
            QMessageBox.warning(self, APP_TITLE, f"No se pudo abrir la ventana: {e}")
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
        ExtractFilesDialog(imagenes, self).exec()

    # -- selección de carpeta -------------------------------------------------
    # Herramientas que se ofrecen en la ventana de trabajo, por sistema
    ACCIONES_TRABAJO = {
        "snes": [
            ("strip", "Quitar cabecera de copiador", "Elimina los 512 bytes de cabecera"),
            ("swc", "Añadir cabecera Super Wild Card", "Deja la ROM lista para el copión"),
            ("hdr", "Añadir cabecera genérica", "512 bytes en cero"),
            ("checksum", "Corregir checksum", "Recalcula y corrige el checksum interno"),
            ("deint", "Desentrelazar (HiROM)", ""),
            ("int", "Entrelazar (HiROM)", ""),
            ("split_swc", "Dividir en disquetes SWC", "Genera imágenes .img de 1.44 MB"),
        ],
        "genesis": [
            ("byteswap", "Byte swap (16 bits)", "Corrige el orden de bytes del volcado"),
            ("smd2bin", "SMD → BIN (desentrelazar)", ""),
            ("bin2smd", "BIN → SMD (entrelazar)", ""),
            ("strip_smd", "Quitar cabecera SMD", ""),
        ],
        "msx": [
            ("extraer", "Extraer archivos de las imágenes",
             "Abre la ventana de extracción con hasta 3 discos"),
            ("c720_trim", "Recortar imagen COPIA720 (720→360)", ""),
            ("c720_exp", "Expandir para COPIA720 (360→720)", ""),
            ("cas2wav", "Cinta CAS → WAV", ""),
            ("wav2cas", "Cinta WAV → CAS", ""),
            ("cas2tsx", "Cinta CAS → TSX", ""),
            ("tsx2cas", "Cinta TSX → CAS", ""),
        ],
    }

    def pick_directory(self):
        directory = choose_directory(self)
        if not directory:
            return
        # Se carga también en la lista lateral, para no perder ese acceso, pero
        # el trabajo de verdad se hace en la ventana grande.
        self.load_directory(directory)
        self.open_workbench(directory)

    def open_workbench(self, directory: str):
        """Abre la ventana grande de trabajo sobre una carpeta."""
        try:
            from file_workbench import FileWorkbench
        except ImportError as e:
            QMessageBox.warning(self, APP_TITLE, f"No se pudo abrir la ventana: {e}")
            return
        acciones = self.ACCIONES_TRABAJO.get(self.system, [])
        dlg = FileWorkbench(directory, self.system, acciones,
                            icon_dir=_icon_base_dir(), parent=self)
        dlg.analizar.connect(self._abrir_desde_explorador)
        dlg.accion.connect(self._accion_workbench)
        self._workbench = dlg
        dlg.exec()
        self._workbench = None

    def _accion_workbench(self, clave: str, rutas: list):
        """Aplica a los archivos seleccionados la herramienta elegida."""
        # Se apoya en la selección de la lista lateral, que es lo que usan
        # todas las operaciones ya existentes: se sincroniza y se reutiliza.
        self._workbench_paths = rutas
        anterior = getattr(self, "_forced_paths", None)
        self._forced_paths = rutas
        try:
            despachador = {
                "strip": self._snes_strip_header,
                "swc": lambda: self._snes_add_header("swc"),
                "hdr": lambda: self._snes_add_header("generic"),
                "checksum": self._snes_fix_checksum,
                "deint": lambda: self._snes_interleave_op(True),
                "int": lambda: self._snes_interleave_op(False),
                "split_swc": self._snes_split_swc_disks,
                "byteswap": self._genesis_byteswap,
                "smd2bin": self._genesis_smd_to_bin,
                "bin2smd": self._genesis_bin_to_smd,
                "strip_smd": self._genesis_strip_header,
                "extraer": self._open_extract_dialog,
                "c720_trim": self._copia720_trim,
                "c720_exp": self._copia720_expand,
                "cas2wav": self._tape_cas_to_wav,
                "wav2cas": self._tape_wav_to_cas,
                "cas2tsx": self._tape_cas_to_tsx,
                "tsx2cas": self._tape_tsx_to_cas,
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
        if getattr(self, "_workbench", None) is not None:
            self._workbench.refrescar()

    MAX_SCAN_FILES = 3000
    MAX_SCAN_DEPTH = 8

    def load_directory(self, directory: str):
        """Carga los archivos de una carpeta en la lista de originales.

        El recorrido está acotado a propósito: elegir por error la raíz de un
        disco grande recorrería cientos de miles de archivos y bloquearía la
        interfaz. Si se alcanza algún límite, se carga lo hallado hasta ese
        punto y se avisa de cómo afinar la selección.
        """
        if not directory or not os.path.isdir(directory):
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        encontrados: list[str] = []
        truncado = False
        base_depth = directory.rstrip(os.sep).count(os.sep)
        try:
            for dirpath, dirnames, filenames in os.walk(directory):
                if dirpath.count(os.sep) - base_depth >= self.MAX_SCAN_DEPTH:
                    dirnames[:] = []
                dirnames[:] = [d for d in dirnames
                               if not d.startswith(".") and d not in (
                                   "proc", "sys", "dev", "run", "lost+found",
                                   "node_modules", "__pycache__", "snap")]
                for fn in filenames:
                    if fn.startswith(".") or fn == "LEEME.txt":
                        continue
                    encontrados.append(os.path.join(dirpath, fn))
                    if len(encontrados) >= self.MAX_SCAN_FILES:
                        truncado = True
                        break
                if truncado:
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
                f"Esa carpeta contiene muchísimos archivos. Se han cargado los primeros "
                f"{self.MAX_SCAN_FILES} para no bloquear la aplicación.\n\n"
                "Si has elegido la raíz de un disco entero, vuelve a pulsar «Elegir "
                "carpeta» y usa «Explorar aquí…» para bajar hasta la carpeta concreta "
                "donde tengas las ROMs.",
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
        btn_split = QPushButton("Dividir en disquetes (bruto)…")
        btn_split.clicked.connect(self._snes_split_floppy)
        btn_split_swc = QPushButton(" Dividir en disquetes SWC…")
        btn_split_swc.setIcon(QIcon(icon_path("superwildcard.svg")))
        btn_split_swc.clicked.connect(self._snes_split_swc_disks)
        btn_deint = QPushButton("Desentrelazar (HiROM)")
        btn_deint.clicked.connect(self._snes_deinterleave)
        btn_int = QPushButton("Entrelazar (HiROM)")
        btn_int.clicked.connect(self._snes_interleave)
        btn_batch = QPushButton("🔁  Byte swap por lotes…")
        btn_batch.clicked.connect(self._snes_batch_byteswap)
        for b in (btn_strip, btn_gen, btn_swc, btn_chk, btn_split, btn_split_swc, btn_deint, btn_int, btn_batch):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

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
        btn_to_bin = QPushButton("SMD → BIN (desentrelazar)")
        btn_to_bin.clicked.connect(self._genesis_smd_to_bin)
        btn_to_smd = QPushButton("BIN → SMD (entrelazar)")
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

        hint = QLabel(
            "«Byte swap» intercambia los dos bytes de cada palabra de 16 bits en todo el "
            "archivo: es lo que distingue un volcado normal (SEGA GENESIS en 0x100) de uno "
            "con los bytes intercambiados (ESAGG NESESI). Es su propia inversa, y la app "
            "detecta automáticamente en qué estado está cada archivo.\n\n"
            "El formato .smd del Super Magic Drive es otra cosa distinta: entrelaza los "
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
        self._run_operation("Byte swap", transform, "byteswap")

    def _genesis_smd_to_bin(self):
        def transform(data, name):
            resultado, nota = gt.smd_to_bin(data)
            base, _ext = os.path.splitext(name)
            return resultado, f"{base}.bin", f"Convertido a formato plano.\n{nota}"
        self._run_operation("SMD → BIN", transform, "smd")

    def _genesis_bin_to_smd(self):
        def transform(data, name):
            resultado = gt.bin_to_smd(data, add_header=True)
            base, _ext = os.path.splitext(name)
            return (resultado, f"{base}.smd",
                    "Convertido a formato SMD entrelazado, con cabecera de 512 bytes.")
        self._run_operation("BIN → SMD", transform, "smd")

    def _genesis_strip_header(self):
        def transform(data, name):
            info = gt.detect_smd_header(data)
            if not info.present:
                raise ValueError("no tiene cabecera SMD de 512 bytes")
            base, ext = os.path.splitext(name)
            return (data[info.size:], f"{base}_sin_cabecera{ext}",
                    f"Cabecera SMD eliminada ({info.size} bytes; {info.notes}).")
        self._run_operation("Quitar cabecera SMD", transform, "no_header")

    def _build_transfer_tools(self) -> QWidget:
        box = QFrame()
        box.setObjectName("FieldChip")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title = QLabel("TRANSFERENCIA AL COPIÓN (PUERTO PARALELO)")
        title.setObjectName("SectionLabel")
        lay.addWidget(title)

        row = QHBoxLayout()
        etiqueta = ("Super Wild Card" if self.system == "snes" else "Super Magic Drive")
        btn = QPushButton(f"⇄  Enviar a {etiqueta}…")
        btn.clicked.connect(self._open_transfer_dialog)
        if self.system == "snes":
            btn.setIcon(QIcon(icon_path("superwildcard.svg")))
        row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)

        hint = QLabel(
            "Envía la ROM al copión usando uCON64 como motor de transferencia (protocolo "
            "probado, en C). Requiere un puerto paralelo real: los adaptadores USB→paralelo "
            "no sirven para esto."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return box

    def _open_transfer_dialog(self):
        try:
            from transfer_dialog import TransferDialog
        except ImportError as e:
            QMessageBox.warning(self, APP_TITLE, f"No se pudo abrir el diálogo: {e}")
            return
        initial = self._current_path if self._current_path else None
        dlg = TransferDialog(self, system=self.system, initial_rom=initial)
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
        btn_play = QPushButton("▶  Reproducir cinta…")
        btn_play.setObjectName("Primary")
        btn_play.clicked.connect(self._open_tape_player)
        row.addWidget(btn_c2w)
        row.addWidget(btn_w2c)
        row.addWidget(btn_c2t)
        row.addWidget(btn_t2c)
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
            QMessageBox.warning(self, APP_TITLE, f"No se pudo abrir la ventana: {e}")
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
                imagenes.append((os.path.basename(ruta), rf.parse_dsk(datos)))
            except Exception as e:  # noqa: BLE001
                fallos.append(f"{os.path.basename(ruta)}: {e}")

        if not imagenes:
            QMessageBox.warning(
                self, APP_TITLE,
                "No se pudo leer ninguna de las imágenes:\n\n" + "\n".join(fallos))
            return
        if fallos:
            QMessageBox.warning(
                self, APP_TITLE,
                "Algunas imágenes no se pudieron leer:\n\n" + "\n".join(fallos))

        ExtractFilesDialog(imagenes, self).exec()

    def _dsk_inject_files(self):
        """Crea una copia del disco abierto con archivos añadidos dentro."""
        ctx = self._require_dsk()
        if not ctx:
            return
        nombre, datos = ctx

        # Se abre directamente en la carpeta que la aplicación crea para esto,
        # que es de donde se querrá coger los archivos casi siempre. Desde ahí
        # el usuario puede navegar a cualquier otro sitio si lo necesita.
        inicio = ws.folder("extracted")
        try:
            if not os.listdir(inicio):
                inicio = ws.source_folder()
        except OSError:
            inicio = ws.source_folder()
        rutas, _ = QFileDialog.getOpenFileNames(
            self, "Archivos a inyectar en el disco  —  (empieza en la carpeta "
                  "de Asturconsole; puedes navegar a otra si lo necesitas)", inicio)
        if not rutas:
            return

        try:
            dsk = rf.parse_dsk(datos)
        except ValueError as e:
            QMessageBox.warning(self, APP_TITLE, f"No se pudo leer el disco: {e}")
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
                QMessageBox.warning(self, APP_TITLE, f"No se pudo leer {r}: {e}")
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
            QMessageBox.warning(self, APP_TITLE, f"No se pudo construir el disco: {e}")
            return

        base, ext = os.path.splitext(nombre)
        destino = ws.unique_path(ws.folder("blank_disks"), f"{base}_con_archivos{ext or '.dsk'}")
        try:
            with open(destino, "wb") as fh:
                fh.write(imagen)
        except OSError as e:
            QMessageBox.warning(self, APP_TITLE, f"No se pudo guardar: {e}")
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
            QMessageBox.warning(self, APP_TITLE, f"No se pudo abrir el diálogo: {e}")
            return
        FloppyWriteDialog(self, image_path=ruta, modo="escribir").exec()

    def _format_floppy_real(self):
        try:
            from floppy_write_dialog import FloppyWriteDialog
        except ImportError as e:
            QMessageBox.warning(self, APP_TITLE, f"No se pudo abrir el diálogo: {e}")
            return
        FloppyWriteDialog(self, modo="formatear").exec()

    def _format_usb_media(self):
        """Formateo de unidades USB: se hace escribiendo una imagen vacía.

        Un adaptador USB no admite formateo a bajo nivel (no expone las
        llamadas de formateo por pistas del controlador de disquete), así que
        la única forma equivalente es grabar encima una imagen ya formateada.
        """
        dlg = BlankDiskDialog(self)
        dlg.setWindowTitle("Formatear unidad USB — crear imagen vacía")
        if dlg.exec() != QDialog.Accepted:
            return
        fmt = dlg.disk_format()
        etiqueta = dlg.volume_label()
        try:
            imagen = rf.make_blank_msx_dsk(etiqueta, fmt=fmt)
        except ValueError as e:
            QMessageBox.warning(self, APP_TITLE, str(e))
            return
        destino = ws.unique_path(ws.folder("blank_disks"), f"formato_{fmt}k.dsk")
        try:
            with open(destino, "wb") as fh:
                fh.write(imagen)
        except OSError as e:
            QMessageBox.warning(self, APP_TITLE, f"No se pudo crear la imagen: {e}")
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

    def _read_floppy(self):
        try:
            from read_floppy_dialog import ReadFloppyDialog
        except ImportError as e:
            QMessageBox.warning(self, APP_TITLE, f"No se pudo abrir el diálogo: {e}")
            return
        ReadFloppyDialog(self).exec()

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
        self._run_operation("Recortar COPIA720", transform, "extracted")

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
        self._run_operation("Expandir para COPIA720", transform, "extracted")

    def _create_blank_disks(self):
        dlg = BlankDiskDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        nombres = dlg.names()
        etiqueta = dlg.volume_label()
        fmt = dlg.disk_format()
        version = dlg.dos_version()
        out_dir = ws.folder("blank_disks")

        # --- preparar la imagen base (vacía o con sistema) ---
        try:
            if version:
                plan = md.plan_system_disk(
                    ws.folder("msxdos"), ws.folder("msxdos_utils"), version,
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
            QMessageBox.warning(self, APP_TITLE, f"No se pudo preparar la imagen:\n{e}")
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
        QMessageBox.information(self, APP_TITLE, mensaje)

    def _write_image_to_disk(self, image_path: str):
        """Abre el diálogo de grabación en unidad física."""
        try:
            from write_image_dialog import WriteImageDialog
        except ImportError as e:
            QMessageBox.warning(self, APP_TITLE, f"No se pudo abrir el diálogo: {e}")
            return
        WriteImageDialog(image_path, self).exec()

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
        # Sin selección: empezar donde es probable que estén las cintas
        inicio = ws.folder("tapes")
        try:
            if not os.listdir(inicio):
                inicio = ws.source_folder()
        except OSError:
            inicio = ws.source_folder()
        in_path, _ = QFileDialog.getOpenFileName(self, titulo, inicio, filtro)
        return [in_path] if in_path else []

    def _run_tape_operation(self, label: str, paths: list[str], transform):
        """Convierte una o varias cintas, guardando en la carpeta 'cintas msx'."""
        if not paths:
            return
        out_dir = ws.folder("tapes")

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
                QMessageBox.warning(self, APP_TITLE, skip_lines[0])
            return

        report = (
            f"{label} — {len(paths)} archivo(s)\n"
            f"Carpeta de resultados: {out_dir}\n\n"
            f"Convertidos: {len(ok_lines)}\n"
            f"Omitidos / con error: {len(skip_lines)}\n\n"
            "Detalle:\n" + "\n".join(ok_lines + skip_lines)
        )
        BatchReportDialog(f"{label} — resultado", report, self).exec()

    def _tape_cas_to_wav(self):
        paths = self._tape_paths("Elegir archivo .CAS", "Cinta MSX (*.cas);;Todos (*)")
        if not paths:
            return
        dialog = TapeConvertDialog("cas2wav", self)
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
        dialog = TapeConvertDialog("cas2wav", self)   # reutiliza el selector de baudios
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

    def _snes_require_selection(self) -> bool:
        if self._current_data is None and not self._selected_paths():
            QMessageBox.information(self, APP_TITLE, "Primero selecciona un archivo de la lista.")
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
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar como", os.path.join(start_dir, suggested_name)
        )
        if not path:
            return None
        with open(path, "wb") as fh:
            fh.write(data)
        self.register_generated(path)
        return path

    def _run_operation(self, label: str, transform, category: str):
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
            QMessageBox.information(self, APP_TITLE, "Primero selecciona un archivo de la lista.")
            return

        out_dir = ws.folder(category)

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

        # Un solo archivo: mensaje breve. Varios: informe completo.
        if len(paths) == 1:
            if ok_lines:
                QMessageBox.information(
                    self, APP_TITLE,
                    f"{detalle_unico}\n\nGuardado en:\n{generados[0]}",
                )
            else:
                QMessageBox.warning(self, APP_TITLE, skip_lines[0] if skip_lines else "No se pudo procesar.")
            return

        report = (
            f"{label} — {len(paths)} archivo(s)\n"
            f"Carpeta de resultados: {out_dir}\n\n"
            f"Procesados correctamente: {len(ok_lines)}\n"
            f"Omitidos / con error: {len(skip_lines)}\n\n"
            "Detalle:\n" + "\n".join(ok_lines + skip_lines)
        )
        BatchReportDialog(f"{label} — resultado", report, self).exec()

    def _snes_strip_header(self):
        def transform(data, name):
            info = st.detect_copier_header(data)
            if not info.present:
                raise ValueError("no tiene cabecera de copiador")
            base, ext = os.path.splitext(name)
            return (st.strip_header(data), f"{base}_sin_cabecera{ext}",
                    f"Cabecera eliminada ({info.brand or 'genérica'}, {info.size} bytes).")
        self._run_operation("Quitar cabecera", transform, "no_header")

    def _snes_add_header(self, style: str):
        def transform(data, name):
            if st.detect_copier_header(data).present:
                raise ValueError("ya tiene una cabecera de copiador")
            header, _err = rf.parse_snes(data)
            hirom = bool(header and "HiROM" in header.kind)
            result = st.add_header(data, style=style, hirom=hirom)
            base, ext = os.path.splitext(name)
            if style == "swc":
                # Convención real de la Super Wild Card: los ROMs con esta
                # cabecera se nombran con extensión .swc.
                suggested = f"{base}_swc.swc"
                tipo = "Super Wild Card"
            else:
                suggested = f"{base}_hdr{ext}"
                tipo = "genérica (512 bytes en cero)"
            return result, suggested, f"Cabecera {tipo} añadida."
        etiqueta = "Añadir cabecera SWC" if style == "swc" else "Añadir cabecera genérica"
        self._run_operation(etiqueta, transform, "with_header")

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
        self._run_operation("Corregir checksum", transform, "checksum")

    def _snes_split_floppy(self):
        if not self._snes_require_selection():
            return
        dialog = FloppySplitDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        chunk_size = dialog.chunk_size()
        if not chunk_size:
            return
        parts = st.split_floppy(self._current_data, chunk_size)
        out_dir = ws.folder("split")
        base, ext = os.path.splitext(self._current_name)
        written = []
        generados = []
        for i, part in enumerate(parts, start=1):
            fname = f"{base}.{i:03d}"
            fpath = os.path.join(out_dir, fname)
            with open(fpath, "wb") as fh:
                fh.write(part)
            written.append((fname, len(part)))
            generados.append(fpath)
        self.register_generated(generados)
        summary = "\n".join(f"  {n}  —  {rf.fmt_bytes(s)}" for n, s in written)
        QMessageBox.information(
            self, APP_TITLE,
            f"Dividido en {len(parts)} fragmento(s) de {rf.fmt_bytes(chunk_size)}:\n\n{summary}\n\n"
            f"Carpeta: {out_dir}",
        )

    def _snes_split_swc_disks(self):
        """Divide en imágenes de disquete .img. Admite selección múltiple:
        procesa todos los archivos seleccionados que tengan cabecera Super
        Wild Card, saltando los que no proceda (por ejemplo los .img, que ya
        son el resultado final) y escribiendo sin pedir carpeta."""
        paths = self._selected_paths()
        if not paths and self._current_path:
            paths = [self._current_path]
        if not paths:
            QMessageBox.information(self, APP_TITLE, "Primero selecciona un archivo de la lista.")
            return

        out_dir = ws.folder("swc_disks")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        ok_lines, skip_lines, generados = [], [], []
        total_discos = 0
        for path in paths:
            name = os.path.basename(path)
            ext = os.path.splitext(name)[1].lower()
            try:
                # Los .img ya son imágenes de disquete: no procede reconvertirlas.
                if ext == ".img":
                    raise ValueError("ya es una imagen de disquete (.img)")
                with open(path, "rb") as fh:
                    data = fh.read()
                info = st.detect_copier_header(data)
                if not (info.present and info.brand == "Super Wild Card"):
                    raise ValueError(
                        "no tiene cabecera Super Wild Card (usa antes «Añadir cabecera "
                        "Super Wild Card»)"
                    )
                base, _e = os.path.splitext(name)
                parts = st.split_swc_disks(data, base_name=base)
                for p in parts:
                    out_path = ws.unique_path(out_dir, p.filename)
                    with open(out_path, "wb") as fh:
                        fh.write(p.image)
                    generados.append(out_path)
                total_discos += len(parts)
                ok_lines.append(
                    f"OK       {name}  ->  {len(parts)} disquete(s): "
                    + ", ".join(os.path.basename(g) for g in generados[-len(parts):])
                )
            except ValueError as e:
                skip_lines.append(f"OMITIDO  {name}  ({e})")
            except Exception as e:  # noqa: BLE001
                skip_lines.append(f"ERROR    {name}  ({e})")

        QApplication.restoreOverrideCursor()
        self.register_generated(generados)
        self._clear_selections()

        if len(paths) == 1 and ok_lines:
            QMessageBox.information(
                self, APP_TITLE,
                f"Generados {total_discos} disquete(s) .img de 1.44 MB, cada uno con su "
                f"propia cabecera SWC (heredada de la original; solo se ajustan las páginas "
                f"y el bit de continuación).\n\nCarpeta:\n{out_dir}",
            )
            return
        if len(paths) == 1 and skip_lines:
            QMessageBox.warning(self, APP_TITLE, skip_lines[0])
            return

        report = (
            f"Dividir en disquetes SWC — {len(paths)} archivo(s)\n"
            f"Carpeta de resultados: {out_dir}\n\n"
            f"Archivos procesados: {len(ok_lines)}   ·   disquetes generados: {total_discos}\n"
            f"Omitidos / con error: {len(skip_lines)}\n\n"
            "Detalle:\n" + "\n".join(ok_lines + skip_lines)
        )
        BatchReportDialog("Dividir en disquetes SWC — resultado", report, self).exec()

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

        self._run_operation(f"{accion} (HiROM)", transform, "interleave")

    def _snes_batch_byteswap(self):
        dialog = BatchByteswapDialog(self)
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
        BatchReportDialog(f"{accion} por lotes — resultado", report, self).exec()

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
            self._dsk_ctx = (name, payload)
            self._render_dsk_view(name, payload)
            return

        # raw / desconocido
        self.detail.build(
            [badge("SIN CABECERA RECONOCIDA", "warn")], name,
            f'{rf.fmt_bytes(len(data))} · no empieza con "AB" (ROM) ni 0xFE (binario con cabecera)',
            [], data,
        )

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
            dest_dir = ws.folder("extracted")
            target = ws.unique_path(dest_dir, entry.name)
            count, errors = self._extract_recursive(dsk, entry.children, target)
            self._show_extract_summary(count, errors, target)
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Extraer archivo", entry.name)
            if not path:
                return
            try:
                data = rf.reconstruct_dsk_file(dsk, entry)
                with open(path, "wb") as fh:
                    fh.write(data)
                QMessageBox.information(self, APP_TITLE, f"Archivo extraído a:\n{path}")
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, APP_TITLE, f"No se pudo extraer el archivo: {e}")

    def _extract_all(self, dsk: rf.DskImage, dsk_name: str):
        dest_dir = ws.folder("extracted")
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
        QMessageBox.information(self, APP_TITLE, msg)


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
        header, err = rf.parse_genesis(data)
        if header is None:
            # Antes de darlo por no reconocido, comprobar si es un volcado con
            # los bytes intercambiados o en formato SMD entrelazado: son casos
            # habituales y conviene decirlo en vez de un simple "no encontrada".
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
            self.detail.build(
                avisos, name,
                f"{rf.fmt_bytes(len(data))} · {err}{extra}",
                [], data[0x100:] if len(data) >= 0x100 else None,
            )
            return

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
        self.detail.build(
            [badge("CABECERA SEGA · 0x100")], name, rf.fmt_bytes(len(data)),
            fields, data[0x100:],
        )

    # -- SNES ----------------------------------------------------------
    def _render_snes(self, name: str, data: bytes):
        header, err = rf.parse_snes(data)
        if header is None:
            self.detail.build(
                [badge("CABECERA NO ENCONTRADA", "warn")], name,
                f"{rf.fmt_bytes(len(data))} · {err}", [], None,
            )
            return

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

        self.detail.build(
            badges, header.title or "(sin título)",
            f"{rf.fmt_bytes(len(data))} · cabecera localizada en {rf.hexn(header.base, 6)}",
            fields, data[header.base:], extra_widget=extra_widget,
        )

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
        self.setWindowTitle(APP_TITLE)
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
        sub2 = QLabel("MSX · SEGA MEGA DRIVE · SUPER NINTENDO")
        sub2.setObjectName("Sub")
        header_row.addWidget(brand)
        header_row.addSpacing(12)
        header_row.addWidget(sub)
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

        self._apply_theme("msx")

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
    # Crear el árbol de carpetas de trabajo antes de construir la interfaz,
    # para que las pestañas puedan cargar ya la carpeta de originales.
    try:
        ws.ensure_workspace()
    except OSError as e:
        print(f"Aviso: no se pudo crear la carpeta de trabajo: {e}", file=sys.stderr)
    app_icon = QIcon(icon_path("app_icon.svg"))
    app.setWindowIcon(app_icon)
    win = MainWindow()
    win.setWindowIcon(app_icon)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
