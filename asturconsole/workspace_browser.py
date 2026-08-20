"""Explorador de la carpeta de trabajo de ASTURCONSOLE.

Se abre con el botón «Carpeta Asturconsole» y muestra, en iconos grandes, la
estructura de carpetas que crea la aplicación. Cada carpeta conocida tiene su
icono propio; las que haya creado el usuario llevan todas el mismo icono
genérico, para distinguir de un vistazo lo que es de la aplicación y lo que
has añadido tú.

Es una ventana propia y no una llamada al explorador del sistema: así
funciona igual en cualquier equipo, sin depender de que haya un escritorio
instalado ni de que xdg-open esté disponible.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QVBoxLayout,
)

import rom_formats as rf
import workspace as ws

ESTILO = """
QDialog { background: #0f111a; }
QLabel { color: #dde3ef; }
QLabel#Ruta {
    color: #8892a8; font-family: "IBM Plex Mono", monospace; font-size: 11px;
    background: #0a0b10; border: 1px solid #2c3342; border-radius: 5px; padding: 7px 10px;
}
QListWidget {
    background: #0a0b10; color: #dde3ef;
    border: 1px solid #2c3342; border-radius: 6px;
    outline: none;
}
QListWidget::item {
    border-radius: 8px; padding: 8px; margin: 4px;
    color: #c8d0e0;
}
QListWidget::item:hover { background: #161c28; }
QListWidget::item:selected { background: #22304a; color: #ffffff; }
QPushButton {
    background: #1f2330; color: #dde3ef;
    border: 1px solid #39404f; border-radius: 5px;
    padding: 7px 13px; font-weight: 600;
}
QPushButton:hover { border-color: #8892a8; background: #262b38; }
"""

# Extensiones que la aplicación sabe abrir, para ofrecerlo al hacer doble clic
EXT_IMAGENES = (".dsk", ".img", ".di1", ".di2")


class WorkspaceBrowser(QDialog):
    """Explorador propio de la carpeta de trabajo."""

    abrir_archivo = Signal(str)          # el usuario quiere analizar un archivo
    abrir_imagenes = Signal(list)        # abrir imágenes de disco en el extractor

    def __init__(self, parent=None, icon_dir: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Carpeta Asturconsole")
        self.setMinimumSize(940, 620)
        self.setStyleSheet(ESTILO)

        self._raiz = ws.ensure_workspace()
        self._actual = self._raiz
        self._icon_dir = icon_dir or ""

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        cabecera = QLabel(
            "Carpetas de trabajo de ASTURCONSOLE. Las que crea la aplicación tienen "
            "su propio icono; las que hayas creado tú llevan el icono de usuario."
        )
        cabecera.setWordWrap(True)
        lay.addWidget(cabecera)

        nav = QHBoxLayout()
        self.subir_btn = QPushButton("↑  Subir")
        self.subir_btn.clicked.connect(self._subir)
        self.raiz_btn = QPushButton("Inicio")
        self.raiz_btn.clicked.connect(lambda: self._ir(self._raiz))
        self.refrescar_btn = QPushButton("Actualizar")
        self.refrescar_btn.clicked.connect(self._poblar)
        self.sistema_btn = QPushButton("Abrir en el sistema")
        self.sistema_btn.setToolTip(
            "Intenta abrir esta carpeta en el explorador de archivos del sistema")
        self.sistema_btn.clicked.connect(self._abrir_en_sistema)
        nav.addWidget(self.subir_btn)
        nav.addWidget(self.raiz_btn)
        nav.addWidget(self.refrescar_btn)
        nav.addStretch(1)
        nav.addWidget(self.sistema_btn)
        lay.addLayout(nav)

        self.ruta_lbl = QLabel("")
        self.ruta_lbl.setObjectName("Ruta")
        self.ruta_lbl.setWordWrap(True)
        lay.addWidget(self.ruta_lbl)

        self.lista = QListWidget()
        self.lista.setViewMode(QListView.IconMode)
        self.lista.setIconSize(QSize(72, 72))
        self.lista.setGridSize(QSize(150, 128))
        self.lista.setResizeMode(QListView.Adjust)
        self.lista.setMovement(QListView.Static)
        self.lista.setWordWrap(True)
        self.lista.setSpacing(4)
        self.lista.setSelectionMode(QListWidget.ExtendedSelection)
        self.lista.itemDoubleClicked.connect(self._doble_clic)
        self.lista.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu_contextual)
        lay.addWidget(self.lista, 1)

        self.estado = QLabel("")
        self.estado.setStyleSheet("color: #8892a8; font-size: 11px;")
        self.estado.setWordWrap(True)
        lay.addWidget(self.estado)

        self._poblar()

    # -- iconos ------------------------------------------------------------
    def _icono_carpeta(self, nombre: str) -> QIcon:
        """Icono propio si es una carpeta de la aplicación; genérico si no."""
        conocidas = set(ws.CATEGORIES.values())
        archivo = (nombre.replace(" ", "_") + ".svg") if nombre in conocidas else "_usuario.svg"
        ruta = os.path.join(self._icon_dir, "folders", archivo)
        if not os.path.isfile(ruta):
            ruta = os.path.join(self._icon_dir, "folders", "_usuario.svg")
        return QIcon(ruta) if os.path.isfile(ruta) else QIcon()

    def _icono_archivo(self, nombre: str) -> QIcon:
        ext = os.path.splitext(nombre)[1].lower()
        mapa = {
            (".dsk", ".img", ".di1", ".di2"): "floppy.svg",
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

    # -- navegación --------------------------------------------------------
    def _ir(self, ruta: str):
        if os.path.isdir(ruta):
            self._actual = os.path.abspath(ruta)
            self._poblar()

    def _subir(self):
        # No se sale de la carpeta de trabajo: es un explorador de ESA carpeta
        if os.path.abspath(self._actual) == os.path.abspath(self._raiz):
            return
        self._ir(os.path.dirname(self._actual))

    def _poblar(self):
        self.lista.clear()
        rel = os.path.relpath(self._actual, self._raiz)
        self.ruta_lbl.setText(self._actual if rel == "." else f"{self._raiz}  ›  {rel}")
        self.subir_btn.setEnabled(os.path.abspath(self._actual) != os.path.abspath(self._raiz))

        try:
            entradas = sorted(os.listdir(self._actual), key=str.lower)
        except OSError as e:
            self.estado.setText(f"No se pudo leer la carpeta: {e}")
            return

        carpetas = [e for e in entradas if os.path.isdir(os.path.join(self._actual, e))]
        archivos = [e for e in entradas
                    if os.path.isfile(os.path.join(self._actual, e)) and not e.startswith(".")]

        conocidas = set(ws.CATEGORIES.values())
        propias = 0
        for nombre in carpetas:
            ruta = os.path.join(self._actual, nombre)
            try:
                n = len([f for f in os.listdir(ruta)
                         if not f.startswith(".") and f != "LEEME.txt"])
            except OSError:
                n = 0
            item = QListWidgetItem(self._icono_carpeta(nombre),
                                    f"{nombre}\n{n} elemento(s)" if n else f"{nombre}\nvacía")
            item.setData(Qt.UserRole, ("dir", ruta))
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            if nombre in conocidas:
                propias += 1
            else:
                item.setToolTip("Carpeta creada por ti")
            self.lista.addItem(item)

        for nombre in archivos:
            ruta = os.path.join(self._actual, nombre)
            try:
                tam = rf.fmt_bytes(os.path.getsize(ruta))
            except OSError:
                tam = "?"
            corto = nombre if len(nombre) <= 22 else nombre[:19] + "…"
            item = QListWidgetItem(self._icono_archivo(nombre), f"{corto}\n{tam}")
            item.setData(Qt.UserRole, ("file", ruta))
            item.setToolTip(f"{nombre}\n{tam}")
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.lista.addItem(item)

        self.estado.setText(
            f"{len(carpetas)} carpeta(s) ({propias} de la aplicación, "
            f"{len(carpetas) - propias} tuyas) · {len(archivos)} archivo(s). "
            "Doble clic para entrar o abrir; clic derecho para más opciones."
        )

    # -- acciones ----------------------------------------------------------
    def _doble_clic(self, item: QListWidgetItem):
        tipo, ruta = item.data(Qt.UserRole)
        if tipo == "dir":
            self._ir(ruta)
            return
        if os.path.splitext(ruta)[1].lower() in EXT_IMAGENES:
            self.abrir_imagenes.emit([ruta])
            return
        self.abrir_archivo.emit(ruta)

    def _seleccion(self) -> list:
        return [i.data(Qt.UserRole)[1] for i in self.lista.selectedItems()]

    def _menu_contextual(self, pos):
        item = self.lista.itemAt(pos)
        if item is None:
            return
        tipo, ruta = item.data(Qt.UserRole)
        menu = QMenu(self.lista)

        act_imagenes = act_analizar = act_entrar = None
        if tipo == "dir":
            act_entrar = menu.addAction("Entrar en la carpeta")
        else:
            if os.path.splitext(ruta)[1].lower() in EXT_IMAGENES:
                act_imagenes = menu.addAction(
                    "Abrir en el extractor de archivos (hasta 3 seleccionadas)")
            act_analizar = menu.addAction("Analizar este archivo")
        menu.addSeparator()
        act_sistema = menu.addAction("Abrir en el explorador del sistema")

        elegido = menu.exec(self.lista.viewport().mapToGlobal(pos))
        if elegido is None:
            return
        if elegido is act_entrar:
            self._ir(ruta)
        elif elegido is act_imagenes:
            imagenes = [p for p in self._seleccion()
                        if os.path.splitext(p)[1].lower() in EXT_IMAGENES]
            self.abrir_imagenes.emit(imagenes or [ruta])
        elif elegido is act_analizar:
            self.abrir_archivo.emit(ruta)
        elif elegido is act_sistema:
            self._abrir_en_sistema(ruta if tipo == "dir" else self._actual)

    def _abrir_en_sistema(self, ruta: str | None = None):
        """Intenta abrir la carpeta en el explorador del sistema.

        Se comprueba el resultado de verdad en vez de dar por hecho que
        funcionó: lanzar el proceso puede tener éxito y aun así no abrirse
        nada (falta de escritorio, xdg-open mal configurado...). Si no se
        consigue, se muestra la ruta en un cuadro del que se puede copiar.
        """
        destino = ruta if isinstance(ruta, str) else self._actual
        intentos = []

        # 1) La vía de Qt
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            if QDesktopServices.openUrl(QUrl.fromLocalFile(destino)):
                return
            intentos.append("QDesktopServices: devolvió fallo")
        except Exception as e:  # noqa: BLE001
            intentos.append(f"QDesktopServices: {e}")

        # 2) Los abridores habituales, comprobando el código de salida
        for programa in ("xdg-open", "gio", "kde-open", "exo-open",
                         "thunar", "nautilus", "dolphin", "pcmanfm", "nemo"):
            ejecutable = shutil.which(programa)
            if not ejecutable:
                continue
            args = ([ejecutable, "open", destino] if programa == "gio"
                    else [ejecutable, destino])
            try:
                proceso = subprocess.Popen(
                    args, start_new_session=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                try:
                    # Si termina enseguida con error, es que no ha abierto nada
                    _salida, err = proceso.communicate(timeout=1.5)
                    if proceso.returncode == 0:
                        return
                    intentos.append(
                        f"{programa}: código {proceso.returncode} "
                        f"{(err or b'').decode(errors='replace').strip()[:60]}")
                except subprocess.TimeoutExpired:
                    # Sigue vivo: señal de que ha abierto la ventana
                    return
            except OSError as e:
                intentos.append(f"{programa}: {e}")

        self._mostrar_ruta(destino, intentos)

    def _mostrar_ruta(self, destino: str, intentos: list):
        """Cuadro con la ruta seleccionable, para poder copiarla."""
        from PySide6.QtWidgets import (QDialogButtonBox, QLineEdit, QPlainTextEdit,
                                       QVBoxLayout as VB)
        dlg = QDialog(self)
        dlg.setWindowTitle("Abrir en el sistema")
        dlg.setMinimumWidth(620)
        dlg.setStyleSheet(ESTILO)
        v = VB(dlg)
        etiqueta = QLabel(
            "No se pudo abrir el explorador de archivos del sistema. Es habitual en "
            "escritorios ligeros o instalaciones sin xdg-utils.\n\n"
            "Puedes copiar la ruta desde aquí:")
        etiqueta.setWordWrap(True)
        v.addWidget(etiqueta)

        campo = QLineEdit(destino)
        campo.setReadOnly(True)
        campo.selectAll()
        campo.setStyleSheet(
            "background:#0a0b10; color:#3ef29a; border:1px solid #2c3342;"
            "border-radius:5px; padding:8px; font-family:'IBM Plex Mono',monospace;")
        v.addWidget(campo)

        pista = QLabel(
            "Para que funcione el botón, instala las herramientas de escritorio:\n"
            "    sudo apt install xdg-utils")
        pista.setWordWrap(True)
        pista.setStyleSheet("color:#8892a8; font-size:11px;")
        v.addWidget(pista)

        if intentos:
            detalle = QPlainTextEdit("\n".join(intentos))
            detalle.setReadOnly(True)
            detalle.setMaximumHeight(110)
            detalle.setStyleSheet(
                "background:#05070c; color:#8892a8; border:1px solid #2c3342;"
                "border-radius:5px; font-size:11px;")
            v.addWidget(QLabel("Detalle de los intentos:"))
            v.addWidget(detalle)

        botones = QDialogButtonBox(QDialogButtonBox.Close)
        botones.rejected.connect(dlg.reject)
        v.addWidget(botones)
        dlg.exec()
