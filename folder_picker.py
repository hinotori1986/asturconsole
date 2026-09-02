"""Selector de carpeta con acceso rápido a volúmenes del sistema y a
dispositivos USB conectados, incluidos los que aún no están montados.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

import volumes as vol
from file_browser import SystemFileBrowser, elegir_carpeta


def _settings() -> QSettings:
    return QSettings("ASTURCONSOLE", "asturconsole")


def _guardar_ultima_carpeta(ruta: str) -> None:
    """Recuerda la carpeta elegida, para ofrecerla destacada la próxima vez
    que se abra este selector.

    Si la carpeta está dentro de un volumen que en este momento está
    montado, se guarda también su dispositivo (p. ej. /dev/sdb1) y la
    ruta relativa dentro de él: así, si la próxima vez ese dispositivo
    aparece conectado pero sin montar (el punto de montaje puede variar
    de una sesión a otra), se puede ofrecer montarlo y entrar directo a
    la misma carpeta, en vez de solo recordar una ruta que ya no existe.
    """
    s = _settings()
    s.setValue("folder_picker/ultima_ruta", ruta)
    device, subruta = "", ""
    try:
        montados, _sin_montar = vol.list_volumes()
        ruta_abs = os.path.abspath(ruta)
        for v in montados:
            if not v.mountpoint:
                continue
            mp_abs = os.path.abspath(v.mountpoint)
            if ruta_abs == mp_abs or ruta_abs.startswith(mp_abs + os.sep):
                device = v.path
                subruta = os.path.relpath(ruta_abs, mp_abs)
                break
    except Exception:  # noqa: BLE001
        pass  # decorativo: si algo falla aquí, simplemente no se ofrece el atajo
    s.setValue("folder_picker/ultimo_device", device)
    s.setValue("folder_picker/ultima_subruta", subruta)


def _cargar_ultima_carpeta() -> tuple[str, str, str]:
    s = _settings()
    return (
        str(s.value("folder_picker/ultima_ruta", "")),
        str(s.value("folder_picker/ultimo_device", "")),
        str(s.value("folder_picker/ultima_subruta", "")),
    )



class FolderPickerDialog(QDialog):
    """Muestra volúmenes montados, atajos habituales y dispositivos sin
    montar (con opción de montarlos). Devuelve la carpeta elegida en
    `selected_path`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Elegir carpeta")
        self.setMinimumSize(560, 440)
        self.selected_path: str | None = None

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        info = QLabel(
            "Selecciona un volumen y pulsa «Explorar aquí…» para navegar dentro de él "
            "hasta la carpeta que quieras (recomendado en discos grandes). "
            "«Usar esta carpeta» carga directamente la ruta seleccionada."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._browse())
        lay.addWidget(self.list, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #ffb454; font-size: 11px;")
        self.status.setVisible(False)
        lay.addWidget(self.status)

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Actualizar lista")
        self.refresh_btn.clicked.connect(self._populate)
        self.mount_btn = QPushButton("Montar dispositivo")
        self.mount_btn.clicked.connect(self._mount_selected)
        self.mount_btn.setEnabled(False)
        if not vol.can_mount():
            # En Windows (o en Linux sin udisksctl) esta acción no tiene
            # nada que hacer: en Windows, además, NUNCA hay nada "pendiente
            # de montar" que mostrar (list_volumes() ya lo garantiza), así
            # que el botón sobra en vez de quedar deshabilitado sin motivo
            # aparente.
            self.mount_btn.setVisible(False)
        btn_row.addWidget(self.refresh_btn)
        btn_row.addWidget(self.mount_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.browse_btn = QPushButton("Explorar aquí…")
        self.browse_btn.setToolTip(
            "Abre el navegador de carpetas empezando en el elemento seleccionado"
        )
        self.browse_btn.clicked.connect(self._browse)
        self.use_btn = QPushButton("Usar esta carpeta")
        self.use_btn.setToolTip("Cargar directamente la carpeta seleccionada")
        self.use_btn.setDefault(True)
        self.use_btn.clicked.connect(self._open_selected)
        buttons.addButton(self.browse_btn, QDialogButtonBox.ActionRole)
        buttons.addButton(self.use_btn, QDialogButtonBox.AcceptRole)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.list.currentItemChanged.connect(self._on_current_changed)
        self._populate()

    # -- contenido --------------------------------------------------------
    def _add_header(self, texto: str):
        item = QListWidgetItem(texto)
        item.setFlags(Qt.NoItemFlags)
        item.setForeground(Qt.gray)
        self.list.addItem(item)

    def _populate(self):
        self.list.clear()
        self.status.setVisible(False)

        # Última carpeta usada, si la hay: destacada arriba de todo, en
        # verde y negrita (el mismo acento que usa el resto de la app para
        # señalar "esto es lo importante/lo que está activo ahora"), para
        # que salte a la vista antes que ninguna otra opción.
        ultima_ruta, ultimo_device, ultima_subruta = _cargar_ultima_carpeta()
        fuente_destacada = QFont()
        fuente_destacada.setBold(True)
        if ultima_ruta and os.path.isdir(ultima_ruta):
            self._add_header("⭐ ÚLTIMA CARPETA USADA")
            item = QListWidgetItem(f"⭐  {ultima_ruta}")
            item.setData(Qt.UserRole, ("path", ultima_ruta))
            item.setForeground(QColor("#3ef29a"))
            item.setFont(fuente_destacada)
            self.list.addItem(item)
        elif ultimo_device:
            _montados, sin_montar = vol.list_volumes()
            if any(v.path == ultimo_device for v in sin_montar):
                self._add_header("⭐ ÚLTIMA CARPETA USADA (dispositivo sin montar)")
                etiqueta = (f"⭐  Montar y abrir…/{ultima_subruta}" if ultima_subruta
                           else "⭐  Montar y abrir")
                item = QListWidgetItem(etiqueta)
                item.setData(Qt.UserRole, ("mount_and_go", ultimo_device, ultima_subruta))
                item.setForeground(QColor("#3ef29a"))
                item.setFont(fuente_destacada)
                self.list.addItem(item)

        # Las carpetas de ASTURCONSOLE se han quitado deliberadamente de
        # esta lista: solo añadían más que elegir entre, cuando al lado ya
        # está el botón "Carpeta Asturconsole", que lleva directo a ellas
        # con su propio explorador (más cómodo para eso: navega y muestra
        # contenido, cosa que esta lista plana no hace). Este selector
        # queda así centrado en su función real: elegir una carpeta de
        # FUERA de la estructura de trabajo (un volumen, un USB, etc).

        atajos = vol.home_volumes()
        if atajos:
            self._add_header("— ACCESO RÁPIDO —")
            for v in atajos:
                item = QListWidgetItem(f"{v.label or v.mountpoint}    ({v.mountpoint})")
                item.setData(Qt.UserRole, ("path", v.mountpoint))
                self.list.addItem(item)

        montados, sin_montar = vol.list_volumes()

        if montados:
            self._add_header("— VOLÚMENES MONTADOS —")
            for v in montados:
                item = QListWidgetItem(f"🟢  {v.display_name()}    ({v.mountpoint})")
                item.setData(Qt.UserRole, ("path", v.mountpoint))
                # Verde: disponible para usar ahora mismo, sin ningún paso
                # adicional — para distinguirlo a simple vista de los que
                # todavía necesitan montarse antes.
                item.setForeground(QColor("#dde3ef"))
                self.list.addItem(item)

        if sin_montar:
            self._add_header("— CONECTADOS PERO SIN MONTAR —")
            for v in sin_montar:
                item = QListWidgetItem(f"⚪  {v.display_name()}    [{v.path}]  — sin montar")
                item.setData(Qt.UserRole, ("mount", v.path))
                # Atenuado a propósito: hace falta montarlo antes de poder
                # explorarlo, así que no debe competir visualmente con los
                # volúmenes ya listos para usar.
                item.setForeground(QColor("#6b7385"))
                self.list.addItem(item)
            if not vol.can_mount():
                self.status.setText(
                    "Hay dispositivos sin montar, pero no se encontró «udisksctl» "
                    "(paquete udisks2) para montarlos desde aquí. Puedes montarlos a mano "
                    "y pulsar Actualizar."
                )
                self.status.setVisible(True)

        if self.list.count() == 0:
            self._add_header("(no se detectaron volúmenes; usa «Examinar…»)")

    def _on_current_changed(self, current: QListWidgetItem, _prev):
        if current is None:
            self.mount_btn.setEnabled(False)
            return
        data = current.data(Qt.UserRole)
        self.mount_btn.setEnabled(bool(data) and data[0] in ("mount", "mount_and_go"))

    # -- acciones ---------------------------------------------------------
    def _mount_selected(self):
        item = self.list.currentItem()
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data or data[0] not in ("mount", "mount_and_go"):
            return
        device = data[1]
        subruta = data[2] if data[0] == "mount_and_go" else ""

        QApplication.setOverrideCursor(Qt.WaitCursor)
        ok, mensaje = vol.mount_device(device)
        QApplication.restoreOverrideCursor()

        if ok and subruta:
            # "Última carpeta usada": tras montar, ir directo a la subcarpeta
            # guardada y dar el diálogo por resuelto, en vez de dejar al
            # usuario navegando desde el punto de montaje recién creado.
            destino = os.path.join(mensaje, subruta)
            if os.path.isdir(destino):
                self.selected_path = destino
                _guardar_ultima_carpeta(destino)
                self.accept()
                return
            # La subcarpeta ya no existe dentro del volumen (se borró o el
            # contenido cambió): seguir igualmente hasta el punto de montaje.
            QMessageBox.information(
                self, "Montar dispositivo",
                f"Dispositivo montado en:\n{mensaje}\n\n"
                f"La subcarpeta que se recordaba (…/{subruta}) ya no existe ahí.",
            )
            self.selected_path = mensaje
            self.accept()
            return

        if ok:
            QMessageBox.information(
                self, "Montar dispositivo",
                f"Dispositivo montado en:\n{mensaje}",
            )
            self._populate()
            # seleccionar automáticamente el punto de montaje recién creado
            for i in range(self.list.count()):
                it = self.list.item(i)
                d = it.data(Qt.UserRole)
                if d and d[0] == "path" and d[1] == mensaje:
                    self.list.setCurrentItem(it)
                    break
        else:
            QMessageBox.warning(self, "Montar dispositivo", mensaje)

    def _browse(self):
        inicio = ""
        item = self.list.currentItem()
        if item is not None:
            data = item.data(Qt.UserRole)
            if data and data[0] == "path":
                inicio = data[1]
            elif data and data[0] in ("mount", "mount_and_go"):
                QMessageBox.information(
                    self, "Elegir carpeta",
                    "Ese dispositivo aún no está montado. Pulsa «Montar dispositivo» "
                    "primero y después vuelve a explorarlo.",
                )
                return
        path = elegir_carpeta(self, carpeta_inicial=inicio or None)
        if path:
            self.selected_path = path
            _guardar_ultima_carpeta(path)
            self.accept()

    def _open_selected(self):
        item = self.list.currentItem()
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        if data[0] == "mount_and_go":
            # Ya implementa montar, navegar a la subcarpeta y aceptar el diálogo.
            self._mount_selected()
            return
        if data[0] == "mount":
            QMessageBox.information(
                self, "Elegir carpeta",
                "Ese dispositivo aún no está montado. Pulsa «Montar dispositivo» primero.",
            )
            return
        path = data[1]
        if not os.path.isdir(path):
            QMessageBox.warning(self, "Elegir carpeta", f"La carpeta ya no existe:\n{path}")
            self._populate()
            return
        # No se confirma directamente: se abre el mismo navegador que
        # "Explorar aquí…", empezando en esta carpeta, para poder bajar a una
        # subcarpeta concreta antes de confirmar. Antes esto aceptaba la
        # carpeta del acceso directo tal cual (p. ej. la raíz "SNES"), sin
        # dejar entrar a la subcarpeta real donde estuvieran las ROMs — el
        # usuario elegía "SNES" esperando "entrar" y se encontraba con el
        # contenido (casi vacío) de esa carpeta raíz, no el de donde
        # realmente quería ir.
        dlg = SystemFileBrowser(self, modo="folder", carpeta_inicial=path)
        if dlg.exec() == QDialog.Accepted and dlg.selected_path:
            self.selected_path = dlg.selected_path
            _guardar_ultima_carpeta(self.selected_path)
            self.accept()


def choose_directory(parent=None) -> str | None:
    """Abre el selector y devuelve la carpeta elegida, o None."""
    dlg = FolderPickerDialog(parent)
    if dlg.exec() == QDialog.Accepted:
        return dlg.selected_path
    return None
