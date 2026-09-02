"""Interfaz para leer o escribir un disquete físico real usando un
dispositivo Greaseweazle. Ejecuta "gw" como proceso externo y muestra su
salida en tiempo real — la lógica de comandos está en
`greaseweazle_tools.py`.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
    QVBoxLayout,
)

import greaseweazle_tools as gwt
from file_browser import elegir_archivo, elegir_archivo_guardar
from transfer_dialog import ESTILO_DIALOGO, ESTILO_OPCION_ROM


class GreaseweazleDialog(QDialog):
    def __init__(self, parent=None, system: str = "genesis",
                 initial_image: str | None = None, app_base_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Greaseweazle (disquete físico por USB)")
        self.setMinimumWidth(640)
        self.setStyleSheet(ESTILO_DIALOGO)

        self._process: QProcess | None = None
        self._gw = gwt.find_gw()
        self._diskdefs = gwt.diskdefs_path(app_base_dir)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        aviso = QLabel(gwt.HARDWARE_NOTICE)
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color: #8892a8; font-size: 11px;")
        lay.addWidget(aviso)

        if self._gw is None:
            no_encontrado = QLabel(
                "No se encuentra el ejecutable 'gw' de Greaseweazle en el sistema. "
                "Instálalo siguiendo la wiki oficial (enlace de arriba) y vuelve a abrir "
                "este diálogo.")
            no_encontrado.setWordWrap(True)
            no_encontrado.setStyleSheet("color: #ff8a7a; font-weight: 600;")
            lay.addWidget(no_encontrado)

        # --- modo: leer o escribir ---
        modo_row = QHBoxLayout()
        self.modo_grupo = QButtonGroup(self)
        self.radio_escribir = QRadioButton("Escribir imagen → disco")
        self.radio_leer = QRadioButton("Leer disco → imagen")
        self.radio_escribir.setChecked(True)
        self.radio_escribir.setStyleSheet(ESTILO_OPCION_ROM)
        self.radio_leer.setStyleSheet(ESTILO_OPCION_ROM)
        self.modo_grupo.addButton(self.radio_escribir)
        self.modo_grupo.addButton(self.radio_leer)
        self.radio_escribir.toggled.connect(self._on_modo_changed)
        modo_row.addWidget(self.radio_escribir)
        modo_row.addWidget(self.radio_leer)
        modo_row.addStretch(1)
        lay.addLayout(modo_row)

        # --- formato de disco (solo los que tienen sentido para este sistema) ---
        formato_row = QHBoxLayout()
        formato_row.addWidget(QLabel("Formato:"))
        self.formato_combo = QComboBox()
        claves = gwt.FORMATOS_POR_SISTEMA.get(system, list(gwt.NOMBRE_FORMATO))
        for clave in claves:
            self.formato_combo.addItem(gwt.NOMBRE_FORMATO[clave], clave)
        formato_row.addWidget(self.formato_combo, 1)
        lay.addLayout(formato_row)

        # --- archivo de imagen ---
        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        if initial_image:
            self.file_edit.setText(initial_image)
        self.file_btn = QPushButton("Elegir imagen…")
        self.file_btn.clicked.connect(self._choose_file)
        file_row.addWidget(self.file_btn)
        file_row.addWidget(self.file_edit, 1)
        lay.addLayout(file_row)

        # --- botones de acción ---
        btn_row = QHBoxLayout()
        self.send_btn = QPushButton("▶  Empezar")
        self.send_btn.setStyleSheet(
            "QPushButton { color: #3ef29a; border: 2px solid #2b6b52; border-radius: 6px;"
            " padding: 9px 18px; font-weight: 700; }"
            "QPushButton:hover:enabled { border-color: #3ef29a; background: rgba(62,242,154,0.14); }"
            "QPushButton:disabled { color: #4d5468; border-color: #2c3342; }"
        )
        self.send_btn.clicked.connect(self._start)
        self.send_btn.setEnabled(self._gw is not None)
        self.cancel_btn = QPushButton("■  Cancelar")
        self.cancel_btn.setStyleSheet(
            "QPushButton { color: #ff8a7a; border: 2px solid #6b3630; border-radius: 6px;"
            " padding: 9px 18px; font-weight: 700; }"
            "QPushButton:hover:enabled { border-color: #ff5f6d; background: rgba(255,95,109,0.14); }"
            "QPushButton:disabled { color: #4d5468; border-color: #2c3342; }"
        )
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self.send_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        # Sin un porcentaje preciso disponible (Greaseweazle no informa
        # pista a pista en el caso normal, a diferencia de uCON64 con
        # --frontend), la barra se queda en modo indeterminado: sigue
        # siendo una señal honesta de "trabajando", sin inventar un
        # número que no tenemos forma de calcular con precisión.
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(180)
        f = QFont("monospace")
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(10)
        self.console.setFont(f)
        self.console.setPlaceholderText("La salida de Greaseweazle aparecerá aquí…")
        lay.addWidget(self.console, 1)

        self._on_modo_changed()

    def _on_modo_changed(self, *_args):
        if self.radio_escribir.isChecked():
            self.file_edit.setPlaceholderText("Imagen a escribir en el disco")
        else:
            self.file_edit.setPlaceholderText("Dónde guardar la imagen leída")

    def _choose_file(self):
        if self.radio_escribir.isChecked():
            path = elegir_archivo(self, titulo="Elegir imagen a escribir",
                                  extensiones=(".img", ".dsk"))
        else:
            path = elegir_archivo_guardar(self, nombre_sugerido="disco_leido.img",
                                          titulo="Guardar la imagen leída")
        if path:
            self.file_edit.setText(path)

    def _log(self, text: str):
        self.console.appendPlainText(text.rstrip())

    def _start(self):
        image = self.file_edit.text().strip()
        if not image:
            QMessageBox.information(self, "Greaseweazle", "Indica el archivo de imagen.")
            return
        escribir = self.radio_escribir.isChecked()
        if escribir and not os.path.isfile(image):
            QMessageBox.warning(self, "Greaseweazle", f"No se encuentra el archivo:\n{image}")
            return
        if not escribir and os.path.isdir(os.path.dirname(image) or "."):
            os.makedirs(os.path.dirname(image) or ".", exist_ok=True)

        formato = self.formato_combo.currentData()
        if escribir:
            cmd = gwt.build_write_command(self._gw, self._diskdefs, formato, image)
            aviso = QMessageBox.question(
                self, "Greaseweazle",
                "Esto va a SOBRESCRIBIR el disquete que tengas puesto en la disquetera "
                "conectada al Greaseweazle. ¿Continuar?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if aviso != QMessageBox.Yes:
                return
        else:
            cmd = gwt.build_read_command(self._gw, self._diskdefs, formato, image)

        self.console.clear()
        self._log("$ " + " ".join(cmd))
        self._log("")

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_output)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        if os.name == "nt":
            # Ver transfer_dialog.py: en Windows, gw (como uCON64) puede
            # quedarse colgado sin ninguna consola asociada, lanzándolo
            # a través de cmd.exe /c en vez de directamente le da el
            # mismo contexto que tendría ejecutado a mano.
            self._process.start("cmd.exe", ["/c"] + cmd)
        else:
            self._process.start(cmd[0], cmd[1:])
        # Igual que con uCON64 (ver transfer_dialog.py): cerrar stdin
        # explícitamente evita que el proceso se quede colgado a la
        # espera de una entrada que nunca va a llegar, un patrón que
        # confirmamos con hardware real en Windows.
        self._process.closeWriteChannel()

        self._set_running(True)

    def _cancel(self):
        if self._process is not None:
            self._log("\n[cancelando…]")
            self._process.terminate()
            if not self._process.waitForFinished(3000):
                self._process.kill()

    def _set_running(self, running: bool):
        self.send_btn.setEnabled(not running and self._gw is not None)
        self.cancel_btn.setEnabled(running)
        self.progress.setVisible(running)
        for w in (self.formato_combo, self.file_btn, self.file_edit,
                  self.radio_escribir, self.radio_leer):
            w.setEnabled(not running)

    def _on_output(self):
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput())
        text = data.decode("utf-8", errors="replace")
        for chunk in text.replace("\r", "\n").split("\n"):
            if chunk.strip():
                self._log(chunk)

    def _on_error(self, err):
        nombres = {
            QProcess.FailedToStart: "no se pudo iniciar el proceso (¿ruta incorrecta?)",
            QProcess.Crashed: "el proceso terminó de forma anómala",
            QProcess.Timedout: "tiempo de espera agotado",
            QProcess.WriteError: "error de escritura",
            QProcess.ReadError: "error de lectura",
        }
        self._log(f"\n[ERROR] {nombres.get(err, 'error desconocido')}")

    def _on_finished(self, exit_code: int, _status):
        self._set_running(False)
        self._process = None
        if exit_code == 0:
            self._log("\n[Operación finalizada correctamente]")
        else:
            self._log(f"\n[gw terminó con código {exit_code}]")
            self._log(
                "Comprueba que el Greaseweazle está conectado y encendido, que el cable "
                "de 34 pines a la disquetera está bien orientado, y que hay un disquete "
                "en la unidad."
            )
