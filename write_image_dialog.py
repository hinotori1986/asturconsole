"""Grabación de una imagen de disco en una unidad física.

Escribir en crudo sobre un dispositivo de bloque BORRA TODO su contenido,
así que este diálogo está construido en torno a evitar accidentes:

  - Solo aparecen discos completos extraíbles o disqueteras; los internos se
    listan atenuados y hay que activar una casilla aparte para verlos
    siquiera como opción.
  - Se avisa si el tamaño de la imagen no coincide con el del dispositivo.
  - Se desmonta automáticamente antes de escribir.
  - Hay que escribir la palabra GRABAR para confirmar.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QVBoxLayout,
)

import volumes as vol


class _WriteThread(QThread):
    """La escritura puede tardar; se hace fuera del hilo de la interfaz."""

    finished_ok = Signal(bool, str)

    def __init__(self, image_path: str, device_path: str, parent=None):
        super().__init__(parent)
        self._image = image_path
        self._device = device_path

    def run(self):
        ok, mensaje = vol.write_image_to_device(self._image, self._device)
        self.finished_ok.emit(ok, mensaje)


class WriteImageDialog(QDialog):
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Grabar imagen en disquete físico")
        self.setMinimumWidth(620)
        self._image_path = image_path
        self._thread: _WriteThread | None = None

        try:
            self._image_size = os.path.getsize(image_path)
        except OSError:
            self._image_size = 0

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        cabecera = QLabel(
            f"<b>Imagen:</b> {os.path.basename(image_path)}<br>"
            f"<b>Tamaño:</b> {self._image_size / 1024:.0f} KB"
        )
        cabecera.setWordWrap(True)
        lay.addWidget(cabecera)

        aviso = QLabel(
            "⚠ La grabación <b>borra por completo</b> el contenido del dispositivo "
            "elegido. Comprueba dos veces que seleccionas la unidad correcta: no hay "
            "forma de deshacerlo."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color: #ff5f6d;")
        lay.addWidget(aviso)

        lay.addWidget(QLabel("Dispositivo de destino:"))
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_selection)
        lay.addWidget(self.list, 1)

        fila = QHBoxLayout()
        self.show_all_chk = QCheckBox("Mostrar también discos NO extraíbles (peligroso)")
        self.show_all_chk.stateChanged.connect(self._populate)
        fila.addWidget(self.show_all_chk, 1)
        self.refresh_btn = QPushButton("Actualizar")
        self.refresh_btn.clicked.connect(lambda: self._populate())
        fila.addWidget(self.refresh_btn)
        lay.addLayout(fila)

        self.info_lbl = QLabel("")
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setStyleSheet("color: #ffb454;")
        lay.addWidget(self.info_lbl)

        fila_conf = QHBoxLayout()
        fila_conf.addWidget(QLabel("Para confirmar, escribe <b>GRABAR</b>:"))
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setMaxLength(10)
        self.confirm_edit.setPlaceholderText("escribe aquí: GRABAR")
        self.confirm_edit.setStyleSheet(
            "background:#12141c; color:#ffb454; border:2px solid #ffb454;"
            "border-radius:5px; padding:7px; font-weight:700;")
        self.confirm_edit.textChanged.connect(self._update_button)
        fila_conf.addWidget(self.confirm_edit, 1)
        lay.addLayout(fila_conf)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.write_btn = QPushButton("Grabar")
        self.write_btn.setStyleSheet(
            "QPushButton { background: rgba(62,242,154,0.16); color:#3ef29a;"
            " border:2px solid #3ef29a; border-radius:6px; padding:9px 18px;"
            " font-weight:700; }"
            "QPushButton:hover:enabled { background: rgba(62,242,154,0.30); }"
            "QPushButton:disabled { color:#6b7488; border-color:#39404f;"
            " background:transparent; }")
        self.write_btn.setEnabled(False)
        self.write_btn.clicked.connect(self._start_write)
        self.buttons.addButton(self.write_btn, QDialogButtonBox.AcceptRole)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self._populate()

    # -- lista de dispositivos --------------------------------------------
    def _populate(self):
        self.list.clear()
        mostrar_todos = self.show_all_chk.isChecked()
        destinos = vol.list_write_targets()
        alguno = False
        for t in destinos:
            if not t.looks_safe and not mostrar_todos:
                continue
            texto = t.describe()
            if t.mountpoints:
                texto += f"   [montado en {', '.join(t.mountpoints)}]"
            item = QListWidgetItem(texto)
            item.setData(Qt.UserRole, t)
            if not t.looks_safe:
                item.setForeground(Qt.red)
                item.setText("⚠ NO EXTRAÍBLE — " + texto)
            self.list.addItem(item)
            alguno = True

        if not alguno:
            item = QListWidgetItem(
                "(no se detectó ninguna unidad extraíble ni disquetera)")
            item.setFlags(Qt.NoItemFlags)
            self.list.addItem(item)
        elif self.list.count() == 1 and self.list.item(0).data(Qt.UserRole) is not None:
            # Si solo hay una unidad posible, se selecciona sola
            self.list.setCurrentRow(0)
        self._update_button()

    def _current_target(self):
        item = self.list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _on_selection(self, *_args):
        t = self._current_target()
        avisos = []
        if t is not None:
            if not t.looks_safe:
                avisos.append(
                    "Este dispositivo NO parece extraíble. Si es un disco del sistema, "
                    "grabar aquí destruiría su contenido."
                )
            if t.size_bytes and self._image_size:
                if t.size_bytes < self._image_size:
                    avisos.append(
                        f"La imagen ({self._image_size/1024:.0f} KB) es MÁS GRANDE que el "
                        f"dispositivo ({t.size_label}): no cabe."
                    )
                elif t.size_bytes > self._image_size * 4:
                    avisos.append(
                        f"El dispositivo ({t.size_label}) es mucho mayor que la imagen "
                        f"({self._image_size/1024:.0f} KB). Comprueba que es la unidad "
                        "que quieres: ¿seguro que no es una memoria USB de datos?"
                    )
            if t.mountpoints:
                avisos.append("Está montado; se desmontará automáticamente antes de grabar.")

            # Disquete de 720 KB en una unidad de 1.44 MB: hay que indicar la
            # geometría, igual que COPIA720 hace bajo DOS reprogramando la
            # tabla de parámetros del disco. En Linux se consigue usando el
            # nodo de dispositivo con la geometría explícita.
            if t.is_floppy and self._image_size and self._image_size <= 800 * 1024:
                base = os.path.basename(t.path)
                if not any(base.endswith(s) for s in ("u720", "u360")):
                    avisos.append(
                        f"La imagen es de {self._image_size // 1024} KB. Si la disquetera "
                        f"es de 1.44 MB, escribir en {t.path} puede dar un disco "
                        f"ilegible, porque el sistema asume 1.44 MB. Usa el nodo con la "
                        f"geometría correcta: /dev/{base}u720 (o u360 para 360 KB)."
                    )
        self.info_lbl.setText("  ".join(avisos))
        self.info_lbl.setVisible(bool(avisos))
        self._update_button()

    def _update_button(self, *_args):
        """Habilita el botón y, sobre todo, EXPLICA por qué no lo está.

        Antes el botón se quedaba apagado sin más y no había forma de saber
        qué faltaba: seleccionar la unidad o escribir la palabra de
        confirmación. Ahora el propio botón lo indica.
        """
        t = self._current_target()
        confirmado = self.confirm_edit.text().strip().upper() == "GRABAR"
        cabe = True
        if t is not None and t.size_bytes and self._image_size:
            cabe = t.size_bytes >= self._image_size

        if self._thread is not None:
            self.write_btn.setText("Grabando…")
            self.write_btn.setEnabled(False)
            return
        if t is None:
            self.write_btn.setText("Elige antes la unidad de destino")
            self.write_btn.setEnabled(False)
            return
        if not cabe:
            self.write_btn.setText("La imagen no cabe en esa unidad")
            self.write_btn.setEnabled(False)
            return
        if not confirmado:
            self.write_btn.setText("Escribe GRABAR para continuar  ↑")
            self.write_btn.setEnabled(False)
            return

        self.write_btn.setText(f"Grabar en {os.path.basename(t.path)}")
        self.write_btn.setEnabled(True)

    # -- escritura ---------------------------------------------------------
    def _start_write(self):
        t = self._current_target()
        if t is None:
            return

        respuesta = QMessageBox.warning(
            self, "Confirmar grabación",
            f"Se va a BORRAR todo el contenido de:\n\n    {t.describe()}\n\n"
            f"y se escribirá la imagen «{os.path.basename(self._image_path)}».\n\n"
            "Esta operación no se puede deshacer. ¿Continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if respuesta != QMessageBox.Yes:
            return

        if t.mountpoints:
            ok, mensaje = vol.unmount_device(t.path)
            if not ok:
                QMessageBox.warning(
                    self, "Grabar imagen",
                    f"No se pudo desmontar el dispositivo:\n{mensaje}\n\n"
                    "Desmóntalo manualmente e inténtalo de nuevo.",
                )
                return

        self.progress.setVisible(True)
        self.write_btn.setEnabled(False)
        self.list.setEnabled(False)
        self.confirm_edit.setEnabled(False)

        self._thread = _WriteThread(self._image_path, t.path, self)
        self._thread.finished_ok.connect(self._on_write_finished)
        self._thread.start()

    def _on_write_finished(self, ok: bool, mensaje: str):
        self.progress.setVisible(False)
        self.list.setEnabled(True)
        self.confirm_edit.setEnabled(True)
        self._thread = None

        if ok:
            QMessageBox.information(
                self, "Grabar imagen",
                "Imagen grabada correctamente.\n\nExpulsa el disquete o la unidad antes "
                "de retirarla, para asegurar que se ha volcado todo.",
            )
            self.accept()
        else:
            QMessageBox.warning(self, "Grabar imagen", f"No se pudo grabar:\n\n{mensaje}")
            self._update_button()

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(
                self, "Grabar imagen",
                "Hay una grabación en curso. Espera a que termine antes de cerrar.",
            )
            event.ignore()
            return
        super().closeEvent(event)
