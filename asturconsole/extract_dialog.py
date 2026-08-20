"""Ventana de extracción de archivos de imágenes de disco MSX.

Permite abrir hasta tres imágenes a la vez y marcar cómodamente qué
archivos extraer, incluso mezclando archivos de discos distintos en una
misma operación. Es lo que hacía falta para trabajar con colecciones: antes
había que extraer disco por disco y todo o nada.

Las tres imágenes se muestran en pestañas, cada una con su árbol de
archivos y subdirectorios. La selección se mantiene al cambiar de pestaña,
así que se pueden marcar archivos de un disco, pasar al siguiente, marcar
más, y extraerlos todos de una vez.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

import rom_formats as rf
import workspace as ws

MAX_IMAGENES = 3

ESTILO = """
QDialog { background: #0f111a; }
QLabel { color: #dde3ef; }
QTabWidget::pane { border: 1px solid #2c3342; border-radius: 6px; top: -1px; }
QTabBar::tab {
    background: #161a24; color: #8892a8;
    border: 1px solid #2c3342; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
    padding: 8px 16px; margin-right: 3px; font-weight: 600;
}
QTabBar::tab:selected { background: #1f2532; color: #3ef29a; border-color: #3ef29a; }
QTreeWidget {
    background: #0a0b10; color: #dde3ef;
    border: 1px solid #2c3342; border-radius: 5px;
    alternate-background-color: #10131b;
}
QTreeWidget::item { padding: 3px; }
QTreeWidget::item:selected { background: #263043; }
QTreeWidget::indicator {
    width: 16px; height: 16px; border-radius: 3px;
    border: 2px solid #5a6478; background: #12141c;
}
QTreeWidget::indicator:checked { background: #3ef29a; border-color: #3ef29a; }
QTreeWidget::indicator:indeterminate { background: #8892a8; border-color: #8892a8; }
QHeaderView::section {
    background: #161a24; color: #8892a8;
    border: none; border-right: 1px solid #2c3342; padding: 6px;
}
QPushButton {
    background: #1f2330; color: #dde3ef;
    border: 1px solid #39404f; border-radius: 5px;
    padding: 7px 13px; font-weight: 600;
}
QPushButton:hover { border-color: #8892a8; background: #262b38; }
QFrame#Resumen {
    background: #161a24; border: 1px solid #2c3342; border-radius: 6px;
}
"""


class _DiskTab(QWidget):
    """Una pestaña: el árbol de archivos de una imagen."""

    def __init__(self, nombre: str, dsk: rf.DskImage, on_change, parent=None):
        super().__init__(parent)
        self.nombre = nombre
        self.dsk = dsk
        self._on_change = on_change

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Archivo", "Tamaño", "Atributo"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self._propagar)
        lay.addWidget(self.tree, 1)

        fila = QHBoxLayout()
        b_todo = QPushButton("Marcar todo")
        b_todo.clicked.connect(lambda: self._marcar_todo(True))
        b_nada = QPushButton("Desmarcar todo")
        b_nada.clicked.connect(lambda: self._marcar_todo(False))
        fila.addWidget(b_todo)
        fila.addWidget(b_nada)
        fila.addStretch(1)
        self.info = QLabel("")
        self.info.setStyleSheet("color: #8892a8; font-size: 11px;")
        fila.addWidget(self.info)
        lay.addLayout(fila)

        self._poblar()

    def _poblar(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        total = self._añadir(self.dsk.entries, self.tree.invisibleRootItem(), "")
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self.info.setText(f"{total} archivo(s) en la imagen")

    def _añadir(self, entradas, padre, ruta) -> int:
        total = 0
        for e in entradas:
            if e.name in (".", ".."):
                continue
            item = QTreeWidgetItem(padre)
            item.setText(0, e.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            item.setData(0, Qt.UserRole, (e, os.path.join(ruta, e.name)))
            if e.is_dir:
                item.setText(1, "<carpeta>")
                hijos = getattr(e, "children", None)
                if hijos:
                    total += self._añadir(hijos, item, os.path.join(ruta, e.name))
            else:
                item.setText(1, rf.fmt_bytes(e.size))
                item.setText(2, f"0x{e.attr:02X}")
                total += 1
        return total

    def _propagar(self, item, columna):
        """Marcar una carpeta marca todo su contenido."""
        if columna != 0:
            return
        self.tree.blockSignals(True)
        estado = item.checkState(0)
        for i in range(item.childCount()):
            item.child(i).setCheckState(0, estado)
        self.tree.blockSignals(False)
        self._on_change()

    def _marcar_todo(self, marcar: bool):
        estado = Qt.Checked if marcar else Qt.Unchecked
        self.tree.blockSignals(True)

        def recorrer(padre):
            for i in range(padre.childCount()):
                hijo = padre.child(i)
                hijo.setCheckState(0, estado)
                recorrer(hijo)

        recorrer(self.tree.invisibleRootItem())
        self.tree.blockSignals(False)
        self._on_change()

    def seleccionados(self) -> list:
        """[(entrada, ruta_relativa)] de los archivos marcados."""
        salida = []

        def recorrer(padre):
            for i in range(padre.childCount()):
                hijo = padre.child(i)
                datos = hijo.data(0, Qt.UserRole)
                if datos and hijo.checkState(0) == Qt.Checked:
                    entrada, ruta = datos
                    if not entrada.is_dir:
                        salida.append((entrada, ruta))
                recorrer(hijo)

        recorrer(self.tree.invisibleRootItem())
        return salida


class ExtractFilesDialog(QDialog):
    """Ventana grande para elegir y extraer archivos de hasta tres imágenes."""

    def __init__(self, imagenes: list, parent=None):
        """`imagenes` es una lista de (nombre, DskImage)."""
        super().__init__(parent)
        self.setWindowTitle("Extraer archivos de imágenes de disco")
        self.setMinimumSize(900, 620)
        self.setStyleSheet(ESTILO)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        intro = QLabel(
            "Marca los archivos que quieras extraer. Puedes moverte entre las "
            "pestañas y mezclar archivos de discos distintos: se extraerán todos "
            "juntos, cada uno en la subcarpeta de su imagen."
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.tabs = QTabWidget()
        self._tabs = []
        for nombre, dsk in imagenes[:MAX_IMAGENES]:
            tab = _DiskTab(nombre, dsk, self._actualizar_resumen)
            self.tabs.addTab(tab, os.path.basename(nombre))
            self._tabs.append(tab)
        lay.addWidget(self.tabs, 1)

        resumen = QFrame()
        resumen.setObjectName("Resumen")
        rl = QHBoxLayout(resumen)
        rl.setContentsMargins(12, 8, 12, 8)
        self.resumen_lbl = QLabel("Ningún archivo marcado.")
        self.resumen_lbl.setWordWrap(True)
        rl.addWidget(self.resumen_lbl, 1)
        lay.addWidget(resumen)

        botones = QDialogButtonBox(QDialogButtonBox.Close)
        self.extraer_btn = QPushButton("Extraer los marcados")
        self.extraer_btn.setStyleSheet(
            "QPushButton { background: rgba(62,242,154,0.16); color: #3ef29a;"
            " border: 2px solid #3ef29a; border-radius: 6px; padding: 8px 16px;"
            " font-weight: 700; }"
            "QPushButton:hover { background: rgba(62,242,154,0.30); }"
            "QPushButton:disabled { color: #4d5468; border-color: #2c3342;"
            " background: transparent; }")
        self.extraer_btn.setCursor(Qt.PointingHandCursor)
        self.extraer_btn.setEnabled(False)
        self.extraer_btn.clicked.connect(self._extraer)
        botones.addButton(self.extraer_btn, QDialogButtonBox.AcceptRole)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

        self._actualizar_resumen()

    # -- lógica ------------------------------------------------------------
    def _actualizar_resumen(self):
        total, bytes_totales, discos = 0, 0, 0
        for tab in self._tabs:
            sel = tab.seleccionados()
            if sel:
                discos += 1
            total += len(sel)
            bytes_totales += sum(e.size for e, _r in sel)

        if total == 0:
            self.resumen_lbl.setText("Ningún archivo marcado.")
        else:
            texto = f"{total} archivo(s) marcados · {rf.fmt_bytes(bytes_totales)}"
            if discos > 1:
                texto += f" · de {discos} imágenes distintas"
            self.resumen_lbl.setText(texto)
        self.extraer_btn.setEnabled(total > 0)

    def _extraer(self):
        destino_base = ws.folder("extracted")
        extraidos, errores = 0, []

        for tab in self._tabs:
            seleccion = tab.seleccionados()
            if not seleccion:
                continue
            base = os.path.splitext(os.path.basename(tab.nombre))[0]
            carpeta = ws.unique_path(destino_base, base)
            try:
                os.makedirs(carpeta, exist_ok=True)
            except OSError as e:
                errores.append(f"{base}: {e}")
                continue

            for entrada, ruta_rel in seleccion:
                destino = os.path.join(carpeta, ruta_rel)
                try:
                    os.makedirs(os.path.dirname(destino), exist_ok=True)
                    datos = rf.reconstruct_dsk_file(tab.dsk, entrada)
                    with open(destino, "wb") as fh:
                        fh.write(datos)
                    extraidos += 1
                    padre = self.parent()
                    if padre is not None and hasattr(padre, "register_generated"):
                        padre.register_generated(destino)
                except Exception as e:  # noqa: BLE001
                    errores.append(f"{ruta_rel}: {e}")

        mensaje = f"Extraídos {extraidos} archivo(s) en:\n{destino_base}"
        if errores:
            mensaje += ("\n\nNo se pudieron extraer " + str(len(errores)) + ":\n"
                        + "\n".join(errores[:10]))
            if len(errores) > 10:
                mensaje += f"\n… y {len(errores) - 10} más"
            QMessageBox.warning(self, "Extraer archivos", mensaje)
        else:
            QMessageBox.information(self, "Extraer archivos", mensaje)
            self.accept()
