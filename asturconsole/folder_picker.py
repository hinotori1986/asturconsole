"""Selector de carpeta con acceso rápido a volúmenes del sistema y a
dispositivos USB conectados, incluidos los que aún no están montados.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

import volumes as vol


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

        # Carpetas de la propia aplicación, que es donde estará casi todo
        try:
            import workspace as ws
            self._add_header("— CARPETAS DE ASTURCONSOLE —")
            for clave, nombre in ws.CATEGORIES.items():
                ruta = ws.folder(clave)
                try:
                    n = len([f for f in os.listdir(ruta)
                             if not f.startswith(".") and f != "LEEME.txt"])
                except OSError:
                    n = 0
                etiqueta = f"{nombre}" + (f"    ({n} archivo(s))" if n else "    (vacía)")
                item = QListWidgetItem(etiqueta)
                item.setData(Qt.UserRole, ("path", ruta))
                self.list.addItem(item)
        except Exception:  # noqa: BLE001
            pass

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
                item = QListWidgetItem(f"{v.display_name()}    ({v.mountpoint})")
                item.setData(Qt.UserRole, ("path", v.mountpoint))
                self.list.addItem(item)

        if sin_montar:
            self._add_header("— CONECTADOS PERO SIN MONTAR —")
            for v in sin_montar:
                item = QListWidgetItem(f"{v.display_name()}    [{v.path}]  — sin montar")
                item.setData(Qt.UserRole, ("mount", v.path))
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
        self.mount_btn.setEnabled(bool(data) and data[0] == "mount")

    # -- acciones ---------------------------------------------------------
    def _mount_selected(self):
        item = self.list.currentItem()
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data or data[0] != "mount":
            return
        device = data[1]

        QApplication.setOverrideCursor(Qt.WaitCursor)
        ok, mensaje = vol.mount_device(device)
        QApplication.restoreOverrideCursor()

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
            elif data and data[0] == "mount":
                QMessageBox.information(
                    self, "Elegir carpeta",
                    "Ese dispositivo aún no está montado. Pulsa «Montar dispositivo» "
                    "primero y después vuelve a explorarlo.",
                )
                return
        path = QFileDialog.getExistingDirectory(
            self, "Elegir carpeta", inicio,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if path:
            self.selected_path = path
            self.accept()

    def _open_selected(self):
        item = self.list.currentItem()
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
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
        self.selected_path = path
        self.accept()


def choose_directory(parent=None) -> str | None:
    """Abre el selector y devuelve la carpeta elegida, o None."""
    dlg = FolderPickerDialog(parent)
    if dlg.exec() == QDialog.Accepted:
        return dlg.selected_path
    return None
