"""Interfaz de transferencia por puerto paralelo a copiones de época.

Ejecuta uCON64 como proceso externo y muestra su salida en tiempo real.
La lógica de comandos y validaciones está en `transfer_ucon64.py`.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
)

import transfer_ucon64 as tu


class TransferDialog(QDialog):
    def __init__(self, parent=None, system: str = "snes", initial_rom: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Transferir al copión (puerto paralelo)")
        self.setMinimumWidth(640)

        self._process: QProcess | None = None
        self._ucon64 = tu.find_ucon64()

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # --- copión ---
        row = QHBoxLayout()
        row.addWidget(QLabel("Copión:"))
        self.copier_combo = QComboBox()
        for c in tu.COPIERS:
            self.copier_combo.addItem(c.label, c)
        # preseleccionar según la pestaña desde la que se abre
        for i, c in enumerate(tu.COPIERS):
            if c.system == system:
                self.copier_combo.setCurrentIndex(i)
                break
        self.copier_combo.currentIndexChanged.connect(self._on_copier_changed)
        row.addWidget(self.copier_combo, 1)
        lay.addLayout(row)

        self.notes_lbl = QLabel("")
        self.notes_lbl.setWordWrap(True)
        self.notes_lbl.setStyleSheet("color: #727a90; font-size: 11px;")
        lay.addWidget(self.notes_lbl)

        # --- archivo ---
        file_row = QHBoxLayout()
        self.file_btn = QPushButton("Elegir ROM…")
        self.file_btn.clicked.connect(self._choose_file)
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("Archivo de ROM a enviar al copión")
        if initial_rom:
            self.file_edit.setText(initial_rom)
        file_row.addWidget(self.file_btn)
        file_row.addWidget(self.file_edit, 1)
        lay.addLayout(file_row)

        # --- puerto ---
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Puerto:"))
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.addItem("(automático)")
        for dev in tu.list_parallel_devices():
            self.port_combo.addItem(dev)
        for addr in ("0x378", "0x278", "0x3bc"):
            self.port_combo.addItem(addr)
        port_row.addWidget(self.port_combo, 1)
        self.sram_chk = QCheckBox("Transferir SRAM en vez de la ROM")
        port_row.addWidget(self.sram_chk)
        lay.addLayout(port_row)

        # --- ruta a ucon64 ---
        uc_row = QHBoxLayout()
        uc_row.addWidget(QLabel("uCON64:"))
        self.ucon64_edit = QLineEdit(self._ucon64 or "")
        self.ucon64_edit.setPlaceholderText("ruta al ejecutable de uCON64")
        uc_btn = QPushButton("…")
        uc_btn.setFixedWidth(32)
        uc_btn.clicked.connect(self._choose_ucon64)
        uc_row.addWidget(self.ucon64_edit, 1)
        uc_row.addWidget(uc_btn)
        lay.addLayout(uc_row)

        if not self._ucon64:
            missing = QLabel(
                "No se ha encontrado uCON64 en el sistema. Instálalo (en Debian/Ubuntu: "
                "<code>sudo apt install ucon64</code>, o compílalo desde ucon64.sourceforge.io) "
                "e indica aquí su ruta."
            )
            missing.setWordWrap(True)
            missing.setStyleSheet("color: #ffb454; font-size: 11px;")
            lay.addWidget(missing)

        # --- aviso de hardware ---
        hw = QLabel(tu.HARDWARE_NOTICE)
        hw.setWordWrap(True)
        hw.setStyleSheet("color: #727a90; font-size: 11px;")
        lay.addWidget(hw)

        # --- transporte ---
        btn_row = QHBoxLayout()
        self.send_btn = QPushButton("▶  Iniciar transferencia")
        self.send_btn.setObjectName("Primary")
        self.send_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("■  Cancelar")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self.send_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)   # indeterminado mientras corre
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        # --- consola ---
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(200)
        f = QFont("monospace")
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(10)
        self.console.setFont(f)
        self.console.setPlaceholderText("La salida de uCON64 aparecerá aquí…")
        lay.addWidget(self.console)

        self._on_copier_changed()

    # -- interfaz ---------------------------------------------------------
    def _current_copier(self) -> tu.CopierProfile:
        return self.copier_combo.currentData()

    def _on_copier_changed(self):
        self.notes_lbl.setText(self._current_copier().notes)

    def _choose_file(self):
        c = self._current_copier()
        patrones = " ".join(f"*{e}" for e in c.extensions)
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir ROM", "", f"ROMs ({patrones});;Todos (*)"
        )
        if path:
            self.file_edit.setText(path)

    def _choose_ucon64(self):
        path, _ = QFileDialog.getOpenFileName(self, "Localizar el ejecutable de uCON64")
        if path:
            self.ucon64_edit.setText(path)

    def _port_value(self) -> str | None:
        txt = self.port_combo.currentText().strip()
        if not txt or txt.startswith("("):
            return None
        return txt

    def _log(self, text: str):
        self.console.appendPlainText(text.rstrip())

    # -- ejecución --------------------------------------------------------
    def _start(self):
        ucon64 = self.ucon64_edit.text().strip() or None
        ucon64 = tu.find_ucon64(ucon64) if ucon64 else tu.find_ucon64()
        rom = self.file_edit.text().strip() or None
        copier = self._current_copier()
        port = self._port_value()

        result = tu.preflight(ucon64, rom, copier, port, sending=True)
        if result.warnings:
            texto = "\n\n".join(result.warnings)
            respuesta = QMessageBox.warning(
                self, "Transferencia", f"{texto}\n\n¿Continuar de todos modos?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if respuesta != QMessageBox.Yes:
                return
        if not result.ok:
            QMessageBox.critical(self, "Transferencia", "\n\n".join(result.errors))
            return

        cmd = tu.build_command(ucon64, copier, rom, port=port,
                                sram=self.sram_chk.isChecked())
        self.console.clear()
        self._log("$ " + " ".join(cmd))
        self._log("")

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_output)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._process.start(cmd[0], cmd[1:])

        self._set_running(True)

    def _cancel(self):
        if self._process is not None:
            self._log("\n[cancelando…]")
            self._process.terminate()
            if not self._process.waitForFinished(3000):
                self._process.kill()

    def _set_running(self, running: bool):
        self.send_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.progress.setVisible(running)
        for w in (self.copier_combo, self.file_btn, self.file_edit,
                  self.port_combo, self.sram_chk, self.ucon64_edit):
            w.setEnabled(not running)

    def _on_output(self):
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput())
        text = data.decode("utf-8", errors="replace")
        # uCON64 usa \r para actualizar la línea de progreso en su sitio;
        # lo convertimos en saltos de línea para que se vea el avance.
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
            self._log("\n[Transferencia finalizada correctamente]")
        else:
            self._log(f"\n[uCON64 terminó con código {exit_code}]")
            self._log(
                "Si el copión no responde: comprueba que está encendido, que el cable es "
                "bidireccional, que el puerto es correcto y que tienes permisos sobre él."
            )

    def closeEvent(self, event):
        if self._process is not None:
            self._cancel()
        super().closeEvent(event)
