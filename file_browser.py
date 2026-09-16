"""Navegador de archivos y carpetas propio, para cualquier ubicación del
sistema de archivos.

Sustituye a los diálogos NATIVOS de Qt (QFileDialog.getOpenFileName,
getOpenFileNames, getSaveFileName, getExistingDirectory), que en
instalaciones Linux mínimas (típico en equipos con hardware antiguo, sin
el entorno de escritorio completo) pueden no funcionar o no mostrar
contenido en absoluto. Es un único navegador reutilizable, dibujado con
los mismos widgets Qt que el resto de la aplicación, en vez de depender
de un backend nativo poco fiable.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)


class SystemFileBrowser(QDialog):
    """Navegador unificado: elegir carpeta, elegir archivo(s), o elegir
    dónde guardar uno nuevo, según el parámetro `modo`.

    modo:
      "folder"      — selecciona una carpeta.
      "open"        — selecciona un archivo existente.
      "open_multi"  — selecciona uno o varios archivos existentes.
      "save"        — elige carpeta + nombre para un archivo nuevo.
    """

    def __init__(self, parent=None, modo: str = "open", carpeta_inicial: str | None = None,
                 extensiones: tuple[str, ...] | None = None, nombre_sugerido: str = "",
                 titulo: str | None = None, mensaje: str | None = None):
        super().__init__(parent)
        self.modo = modo
        self.extensiones = tuple(e.lower() for e in extensiones) if extensiones else None
        self.selected_path: str | None = None
        self.selected_paths: list[str] = []

        self.setWindowTitle(titulo or {
            "folder": "Elegir carpeta", "open": "Elegir archivo",
            "open_multi": "Elegir archivos", "save": "Guardar como",
        }[modo])
        self.setMinimumSize(760, 520)

        self._actual = carpeta_inicial or os.path.expanduser("~")
        if not os.path.isdir(self._actual):
            self._actual = os.path.expanduser("~")

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        if mensaje:
            info = QLabel(mensaje)
            info.setWordWrap(True)
            lay.addWidget(info)

        nav = QHBoxLayout()
        self.subir_btn = QPushButton("↑  Subir")
        self.subir_btn.clicked.connect(self._subir)
        self.inicio_btn = QPushButton("Carpeta personal")
        self.inicio_btn.clicked.connect(lambda: self._ir(os.path.expanduser("~")))
        self.raiz_btn = QPushButton("Raíz del sistema")
        self.raiz_btn.clicked.connect(lambda: self._ir(os.path.abspath(os.sep)))
        nav.addWidget(self.subir_btn)
        nav.addWidget(self.inicio_btn)
        nav.addWidget(self.raiz_btn)
        nav.addStretch(1)
        lay.addLayout(nav)

        self.ruta_lbl = QLabel("")
        self.ruta_lbl.setWordWrap(True)
        lay.addWidget(self.ruta_lbl)

        self.lista = QListWidget()
        if self.modo == "open_multi":
            self.lista.setSelectionMode(QListWidget.ExtendedSelection)
        self.lista.itemDoubleClicked.connect(self._doble_clic)
        self.lista.itemSelectionChanged.connect(self._on_selection_changed)
        lay.addWidget(self.lista, 1)

        self.nombre_edit: QLineEdit | None = None
        if self.modo == "save":
            fila = QHBoxLayout()
            fila.addWidget(QLabel("Nombre del archivo:"))
            self.nombre_edit = QLineEdit(nombre_sugerido)
            fila.addWidget(self.nombre_edit, 1)
            lay.addLayout(fila)

        self.estado = QLabel("")
        self.estado.setWordWrap(True)
        lay.addWidget(self.estado)

        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        etiqueta_ok = {
            "folder": "Usar esta carpeta", "open": "Abrir",
            "open_multi": "Abrir", "save": "Guardar",
        }[modo]
        self.ok_button = botones.button(QDialogButtonBox.Ok)
        self.ok_button.setText(etiqueta_ok)
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

        self._poblar()
        self._on_selection_changed()

    def _ir(self, ruta: str):
        if os.path.isdir(ruta):
            self._actual = os.path.abspath(ruta)
            self._poblar()

    def _subir(self):
        padre = os.path.dirname(self._actual)
        if padre and padre != self._actual:
            self._ir(padre)

    def _incluir_archivo(self, nombre: str) -> bool:
        if self.extensiones is None:
            return True
        return nombre.lower().endswith(self.extensiones)

    def _poblar(self):
        self.lista.clear()
        self.estado.setText("")
        self.ruta_lbl.setText(self._actual)
        self.subir_btn.setEnabled(os.path.dirname(self._actual) != self._actual)
        try:
            entradas = sorted(os.listdir(self._actual), key=str.lower)
        except OSError as e:
            self.estado.setText(f"No se pudo leer la carpeta: {e}")
            return

        carpetas = [e for e in entradas
                    if not e.startswith(".") and os.path.isdir(os.path.join(self._actual, e))]
        for nombre in carpetas:
            item = QListWidgetItem(f"📁  {nombre}")
            item.setData(Qt.UserRole, ("dir", os.path.join(self._actual, nombre)))
            self.lista.addItem(item)

        archivos: list[str] = []
        if self.modo != "folder":
            archivos = [e for e in entradas
                        if not e.startswith(".")
                        and os.path.isfile(os.path.join(self._actual, e))
                        and self._incluir_archivo(e)]
            for nombre in archivos:
                item = QListWidgetItem(f"📄  {nombre}")
                item.setData(Qt.UserRole, ("file", os.path.join(self._actual, nombre)))
                self.lista.addItem(item)

        if not carpetas and not archivos:
            self.estado.setText("(esta carpeta está vacía, o no tiene nada que coincida)")

    def _doble_clic(self, item):
        tipo, ruta = item.data(Qt.UserRole)
        if tipo == "dir":
            self._ir(ruta)
        elif tipo == "file" and self.modo == "open":
            # Solo en selección única el doble clic acepta directamente: en
            # "open_multi" haría perder cualquier otra selección hecha con
            # Ctrl+clic, así que ahí el doble clic no hace nada especial en
            # archivos — se confirma con el botón, como en cualquier lista
            # de selección múltiple.
            self.selected_path = ruta
            self.selected_paths = [ruta]
            self.accept()

    def _on_selection_changed(self):
        if self.modo in ("open", "open_multi"):
            hay_archivo = any(
                it.data(Qt.UserRole)[0] == "file" for it in self.lista.selectedItems())
            self.ok_button.setEnabled(hay_archivo)
        # en "folder" y "save" siempre se puede confirmar (usa self._actual)

    def _aceptar(self):
        if self.modo == "folder":
            # Si hay una carpeta resaltada en la lista (un solo clic, sin
            # llegar a "entrar" con doble clic), se usa esa: es lo que se
            # espera al señalar una carpeta y confirmar directamente, sin
            # más pasos. Si no hay nada resaltado, se usa la carpeta
            # donde está posicionado el navegador ahora mismo (para
            # cuando lo que se quiere es "esta carpeta en la que estoy,
            # tal cual, sin entrar a ninguna subcarpeta").
            item_actual = self.lista.currentItem()
            if item_actual is not None:
                tipo, ruta = item_actual.data(Qt.UserRole)
                self.selected_path = ruta if tipo == "dir" else self._actual
            else:
                self.selected_path = self._actual
        elif self.modo == "save":
            nombre = (self.nombre_edit.text() if self.nombre_edit else "").strip()
            if not nombre:
                self.estado.setText("Escribe un nombre de archivo.")
                return
            self.selected_path = os.path.join(self._actual, nombre)
        else:  # open / open_multi
            seleccionados = [it.data(Qt.UserRole)[1] for it in self.lista.selectedItems()
                             if it.data(Qt.UserRole)[0] == "file"]
            if not seleccionados:
                return
            self.selected_paths = seleccionados
            self.selected_path = seleccionados[0]
        self.accept()


def elegir_carpeta(parent=None, carpeta_inicial: str | None = None,
                   mensaje: str | None = None) -> str | None:
    dlg = SystemFileBrowser(parent, modo="folder", carpeta_inicial=carpeta_inicial,
                            mensaje=mensaje)
    return dlg.selected_path if dlg.exec() == QDialog.Accepted else None


def elegir_archivo(parent=None, carpeta_inicial: str | None = None,
                   extensiones: tuple[str, ...] | None = None,
                   titulo: str | None = None, mensaje: str | None = None) -> str | None:
    dlg = SystemFileBrowser(parent, modo="open", carpeta_inicial=carpeta_inicial,
                            extensiones=extensiones, titulo=titulo, mensaje=mensaje)
    return dlg.selected_path if dlg.exec() == QDialog.Accepted else None


def elegir_archivos(parent=None, carpeta_inicial: str | None = None,
                    extensiones: tuple[str, ...] | None = None,
                    titulo: str | None = None, mensaje: str | None = None) -> list[str]:
    dlg = SystemFileBrowser(parent, modo="open_multi", carpeta_inicial=carpeta_inicial,
                            extensiones=extensiones, titulo=titulo, mensaje=mensaje)
    return dlg.selected_paths if dlg.exec() == QDialog.Accepted else []


def elegir_archivo_guardar(parent=None, carpeta_inicial: str | None = None,
                           nombre_sugerido: str = "", titulo: str | None = None,
                           mensaje: str | None = None) -> str | None:
    dlg = SystemFileBrowser(parent, modo="save", carpeta_inicial=carpeta_inicial,
                            nombre_sugerido=nombre_sugerido, titulo=titulo, mensaje=mensaje)
    return dlg.selected_path if dlg.exec() == QDialog.Accepted else None
