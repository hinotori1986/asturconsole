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

from PySide6.QtCore import Qt, Signal
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


# ---------------------------------------------------------------------------
# Comprobación previa de un lote de imágenes
# ---------------------------------------------------------------------------

ESTILO_CHECK = ESTILO + """
QListWidget#Buenos {
    border: 2px solid #2f6b4f; background: #0a1310;
}
QListWidget#Malos {
    border: 2px solid #6b3630; background: #150c0b;
}
QLabel#TitBueno { color: #3ef29a; font-weight: 700; font-size: 12px; }
QLabel#TitMalo  { color: #ff7a68; font-weight: 700; font-size: 12px; }
"""


class DiskCheckDialog(QDialog):
    """Muestra, en dos columnas, qué imágenes se pueden extraer y cuáles no.

    Sustituye al botón «Analizar» dentro de la ventana de trabajo, que mandaba
    la información al panel de la ventana principal —que queda detrás y no es
    accesible— y por tanto no parecía hacer nada.
    """

    extraer_compatibles = Signal(list)     # rutas de las imágenes legibles

    def __init__(self, rutas: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Comprobación de imágenes de disco")
        self.setMinimumSize(1000, 600)
        self.setStyleSheet(ESTILO_CHECK)

        self._buenas: list = []

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        intro = QLabel(
            f"Se han comprobado {len(rutas)} imagen(es). A la izquierda las que "
            "tienen un sistema de archivos legible y se pueden extraer; a la "
            "derecha las que no, con el motivo."
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        columnas = QHBoxLayout()
        columnas.setSpacing(12)

        # --- columna de las que sí ---
        izq = QVBoxLayout()
        self.tit_bueno = QLabel("")
        self.tit_bueno.setObjectName("TitBueno")
        izq.addWidget(self.tit_bueno)
        self.lista_buenos = QTreeWidget()
        self.lista_buenos.setObjectName("Buenos")
        self.lista_buenos.setColumnCount(2)
        self.lista_buenos.setHeaderLabels(["Imagen", "Contenido"])
        self.lista_buenos.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.lista_buenos.setRootIsDecorated(False)
        izq.addWidget(self.lista_buenos, 1)
        columnas.addLayout(izq, 1)

        # --- columna de las que no ---
        der = QVBoxLayout()
        self.tit_malo = QLabel("")
        self.tit_malo.setObjectName("TitMalo")
        der.addWidget(self.tit_malo)
        self.lista_malos = QTreeWidget()
        self.lista_malos.setObjectName("Malos")
        self.lista_malos.setColumnCount(2)
        self.lista_malos.setHeaderLabels(["Imagen", "Motivo"])
        self.lista_malos.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.lista_malos.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.lista_malos.setRootIsDecorated(False)
        self.lista_malos.setWordWrap(True)
        der.addWidget(self.lista_malos, 1)
        columnas.addLayout(der, 1)

        lay.addLayout(columnas, 1)

        self.detalle = QLabel(
            "Pincha en una imagen de la derecha para ver la explicación completa.")
        self.detalle.setWordWrap(True)
        self.detalle.setStyleSheet("color: #8892a8; font-size: 11px;")
        lay.addWidget(self.detalle)
        self.lista_malos.itemSelectionChanged.connect(self._mostrar_motivo)

        botones = QDialogButtonBox(QDialogButtonBox.Close)
        self.btn_extraer = QPushButton("Extraer las compatibles")
        self.btn_extraer.setStyleSheet(
            "QPushButton { background: rgba(62,242,154,0.16); color: #3ef29a;"
            " border: 2px solid #3ef29a; border-radius: 6px; padding: 8px 16px;"
            " font-weight: 700; }"
            "QPushButton:hover:enabled { background: rgba(62,242,154,0.30); }"
            "QPushButton:disabled { color:#4d5468; border-color:#2c3342;"
            " background: transparent; }")
        self.btn_extraer.setCursor(Qt.PointingHandCursor)
        self.btn_extraer.clicked.connect(self._extraer)
        botones.addButton(self.btn_extraer, QDialogButtonBox.AcceptRole)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

        self._comprobar(rutas)

    def _comprobar(self, rutas: list):
        buenas, malas = 0, 0
        for ruta in rutas:
            nombre = os.path.basename(ruta)
            try:
                with open(ruta, "rb") as fh:
                    datos = fh.read()
                nota = ""
                if rf.detect_copia720_single_sided(datos):
                    datos = rf.copia720_to_single_sided(datos)
                    nota = " · cara simple COPIA720"
                valido, motivo = rf.validate_dsk(datos)
                if not valido:
                    item = QTreeWidgetItem(self.lista_malos)
                    item.setText(0, nombre)
                    item.setText(1, motivo.split("\\n")[0])
                    item.setData(0, Qt.UserRole, motivo)
                    malas += 1
                    continue
                dsk = rf.parse_dsk(datos)
                archivos = [e for e in dsk.entries if not e.is_dir]
                carpetas = [e for e in dsk.entries if e.is_dir]
                if not archivos and not carpetas:
                    item = QTreeWidgetItem(self.lista_malos)
                    item.setText(0, nombre)
                    item.setText(1, "el disco está formateado pero vacío")
                    item.setData(0, Qt.UserRole,
                                 "El disco tiene un sistema de archivos correcto, pero "
                                 "no contiene ningún archivo: está vacío.")
                    malas += 1
                    continue
                item = QTreeWidgetItem(self.lista_buenos)
                item.setText(0, nombre)
                resumen = f"{len(archivos)} archivo(s)"
                if carpetas:
                    resumen += f", {len(carpetas)} carpeta(s)"
                item.setText(1, resumen + nota)
                self._buenas.append(ruta)
                buenas += 1
            except Exception as e:  # noqa: BLE001
                item = QTreeWidgetItem(self.lista_malos)
                item.setText(0, nombre)
                item.setText(1, str(e)[:90])
                item.setData(0, Qt.UserRole, str(e))
                malas += 1

        self.tit_bueno.setText(f"✔  SE PUEDEN EXTRAER  ({buenas})")
        self.tit_malo.setText(f"✘  NO SE PUEDEN EXTRAER  ({malas})")
        self.btn_extraer.setEnabled(buenas > 0)
        if buenas == 0:
            self.btn_extraer.setText("Ninguna imagen es extraíble")

    def _mostrar_motivo(self):
        items = self.lista_malos.selectedItems()
        if not items:
            return
        motivo = items[0].data(0, Qt.UserRole) or items[0].text(1)
        self.detalle.setText(motivo)

    def _extraer(self):
        self.extraer_compatibles.emit(list(self._buenas))
        self.accept()
