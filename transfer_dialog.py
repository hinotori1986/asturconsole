"""Interfaz de transferencia por puerto paralelo a copiones de época.

Ejecuta uCON64 como proceso externo y muestra su salida en tiempo real.
La lógica de comandos y validaciones está en `transfer_ucon64.py`.
"""
from __future__ import annotations

import os
import re
import subprocess

from PySide6.QtCore import QProcess, QSettings, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QVBoxLayout,
)

import transfer_ucon64 as tu
from file_browser import elegir_archivo
from transfer_animation_widget import TransferAnimationWidget

# Estilos del diálogo. Sin esto, sobre fondo oscuro las casillas de
# verificación de Qt se dibujan como un cuadro negro sobre negro y no se
# distingue si están marcadas.
# Cada opción se colorea al seleccionarse, para que se vea de un vistazo qué
# se va a transferir: es la diferencia entre mandar el juego o las partidas.
ESTILO_OPCION_ROM = """
QRadioButton:checked {
    color: #3ef29a; font-weight: 700;
    border-color: #3ef29a; background: rgba(62,242,154,0.12);
}
QRadioButton::indicator:checked { border-color: #3ef29a; background: #3ef29a; }
"""

ESTILO_OPCION_SRAM = """
QRadioButton:checked {
    color: #ffb454; font-weight: 700;
    border-color: #ffb454; background: rgba(255,180,84,0.14);
}
QRadioButton::indicator:checked { border-color: #ffb454; background: #ffb454; }
"""

def _settings() -> QSettings:
    return QSettings("ASTURCONSOLE", "asturconsole")


ESTILO_DIALOGO = """
QDialog { background: #0f111a; }
QLabel { color: #dde3ef; }

QCheckBox {
    color: #dde3ef;
    spacing: 10px;
    padding: 4px;
}
QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border-radius: 4px;
    border: 2px solid #5a6478;
    background: #12141c;
}
QCheckBox::indicator:hover { border-color: #8892a8; }
QCheckBox::indicator:checked {
    border-color: #3ef29a;
    background: #3ef29a;
    image: none;
}
QCheckBox:checked { color: #3ef29a; font-weight: 700; }

QComboBox, QLineEdit {
    background: #12141c;
    color: #dde3ef;
    border: 1px solid #39404f;
    border-radius: 5px;
    padding: 6px 8px;
    selection-background-color: #3ef29a;
    selection-color: #0a0b10;
}
QComboBox:hover, QLineEdit:hover { border-color: #5a6478; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #12141c;
    color: #dde3ef;
    border: 1px solid #39404f;
    selection-background-color: #263043;
}

QPushButton {
    background: #1f2330;
    color: #dde3ef;
    border: 1px solid #39404f;
    border-radius: 5px;
    padding: 7px 14px;
    font-weight: 600;
}
QPushButton:hover { border-color: #8892a8; background: #262b38; }
QPushButton:disabled { color: #4d5468; border-color: #2c3342; }

QPlainTextEdit {
    background: #05070c;
    color: #b6c0d4;
    border: 1px solid #39404f;
    border-radius: 5px;
}
QProgressBar {
    background: #12141c;
    border: 1px solid #39404f;
    border-radius: 5px;
    height: 8px;
}
QProgressBar::chunk { background: #3ef29a; border-radius: 4px; }

QFrame#Tarjeta {
    background: #161a24;
    border: 1px solid #2c3342;
    border-radius: 8px;
}
QRadioButton {
    color: #dde3ef;
    spacing: 10px;
    padding: 8px 10px;
    border: 2px solid #2c3342;
    border-radius: 6px;
    background: #12141c;
}
QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid #5a6478;
    background: #0a0b10;
}
QRadioButton:hover { border-color: #5a6478; }

QLabel#Seccion {
    color: #8892a8;
    font-size: 10px;
    font-weight: 700;
}
"""


class TransferDialog(QDialog):
    def __init__(self, parent=None, system: str = "snes", initial_rom: str | None = None,
                 icon_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Transferir al copión (puerto paralelo)")
        self.setMinimumWidth(680)
        self.setStyleSheet(ESTILO_DIALOGO)

        self._process: QProcess | None = None
        self._popen: subprocess.Popen | None = None
        self._poll_timer: QTimer | None = None
        self._ucon64 = tu.find_ucon64()
        if not self._ucon64:
            # No se encontró automáticamente (habitual en Windows: uCON64
            # suele vivir en una carpeta cualquiera, no en el PATH del
            # sistema) — se recupera la última ruta que el usuario indicó
            # a mano, para no tener que volver a teclearla en cada sesión.
            ruta_guardada = _settings().value("transfer/ucon64_path", "")
            if ruta_guardada:
                self._ucon64 = tu.find_ucon64(ruta_guardada)
        self._bytes_totales = 0

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # --- animación de la transferencia (icono del PC, foto real del
        # copión, y paquetes de datos viajando entre ambos según el
        # progreso real) — sustituye a la barra indeterminada de antes,
        # que no reflejaba ningún avance real, solo que el proceso seguía vivo.
        self.animacion = TransferAnimationWidget(system, icon_dir=icon_dir)
        lay.addWidget(self.animacion)

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
        # Si initial_rom viene dado (siempre que se abre desde la ventana de
        # trabajo, con el archivo ya seleccionado ahí), no se ofrece volver a
        # elegirlo aquí: el botón usaba QFileDialog.getOpenFileName, el
        # selector NATIVO del sistema operativo, que en instalaciones Linux
        # mínimas (típico en equipos con hardware antiguo, sin el entorno de
        # escritorio completo) puede no funcionar o no mostrar contenido —
        # a diferencia del resto de la aplicación, que nunca depende de
        # diálogos nativos para elegir archivos, siempre usa el explorador
        # propio. Sin archivo ya decidido, se mantiene el botón por si en el
        # futuro se reutiliza este diálogo desde otro contexto sin selección
        # previa.
        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("Archivo de ROM a enviar al copión")
        if initial_rom:
            self.file_edit.setText(initial_rom)
            self.file_edit.setReadOnly(True)
            self.file_btn = None
        else:
            self.file_btn = QPushButton("Elegir ROM…")
            self.file_btn.clicked.connect(self._choose_file)
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
        lay.addLayout(port_row)

        # --- qué se transfiere: elección destacada, no una casilla perdida ---
        qué = QFrame()
        qué.setObjectName("Tarjeta")
        ql = QVBoxLayout(qué)
        ql.setContentsMargins(14, 10, 14, 12)
        ql.setSpacing(8)

        etiqueta = QLabel("¿QUÉ QUIERES TRANSFERIR?")
        etiqueta.setObjectName("Seccion")
        ql.addWidget(etiqueta)

        fila = QHBoxLayout()
        fila.setSpacing(10)
        self.rom_radio = QRadioButton("ROM del juego")
        self.rom_radio.setChecked(True)
        self.rom_radio.setStyleSheet(ESTILO_OPCION_ROM)
        self.sram_radio = QRadioButton("SRAM (partidas guardadas)")
        self.sram_radio.setStyleSheet(ESTILO_OPCION_SRAM)
        grupo = QButtonGroup(self)
        grupo.addButton(self.rom_radio)
        grupo.addButton(self.sram_radio)
        self.rom_radio.toggled.connect(self._on_tipo_changed)
        fila.addWidget(self.rom_radio, 1)
        fila.addWidget(self.sram_radio, 1)
        ql.addLayout(fila)

        self.tipo_lbl = QLabel("")
        self.tipo_lbl.setWordWrap(True)
        self.tipo_lbl.setStyleSheet("color: #8892a8; font-size: 11px;")
        ql.addWidget(self.tipo_lbl)
        lay.addWidget(qué)

        # --- ruta a ucon64 ---
        uc_row = QHBoxLayout()
        uc_row.addWidget(QLabel("uCON64:"))
        self.ucon64_edit = QLineEdit(self._ucon64 or "")
        self.ucon64_edit.setPlaceholderText("ruta al ejecutable de uCON64")
        self.ucon64_edit.editingFinished.connect(self._guardar_ucon64_manual)
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

        # --- aviso de hardware, en tarjeta aparte ---
        hw_card = QFrame()
        hw_card.setObjectName("Tarjeta")
        hwl = QVBoxLayout(hw_card)
        hwl.setContentsMargins(14, 10, 14, 12)
        hwl.setSpacing(6)
        hw_tit = QLabel("REQUISITOS DE HARDWARE")
        hw_tit.setObjectName("Seccion")
        hwl.addWidget(hw_tit)
        hw = QLabel(tu.HARDWARE_NOTICE)
        hw.setWordWrap(True)
        hw.setStyleSheet("color: #8892a8; font-size: 11px;")
        hwl.addWidget(hw)
        lay.addWidget(hw_card)

        # --- transporte ---
        btn_row = QHBoxLayout()
        self.send_btn = QPushButton("▶  Iniciar transferencia")
        self.send_btn.setStyleSheet(
            "QPushButton { background: rgba(62,242,154,0.16); color: #3ef29a;"
            " border: 2px solid #3ef29a; border-radius: 6px; padding: 9px 18px;"
            " font-weight: 700; }"
            "QPushButton:hover { background: rgba(62,242,154,0.30); }"
            "QPushButton:disabled { color: #4d5468; border-color: #2c3342;"
            " background: transparent; }"
        )
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self._start)
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

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
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

        if os.name == "nt":
            # Aviso preventivo, no reactivo: mejor que el usuario lo vea
            # ANTES de intentar transferir, que descubrirlo tras varios
            # intentos fallidos sin ningún error visible (ver README,
            # sección "Fiabilidad por plataforma", para el detalle
            # completo de por qué ocurre esto).
            self._log(
                "⚠ Aviso: en Windows, la transferencia por puerto paralelo depende de "
                "un driver de terceros (InpOut32.dll/giveio64) y puede no completarse "
                "de forma fiable con algunas tarjetas PCIe modernas, aunque no dé "
                "ningún error visible. Si tienes acceso a Linux, es la vía más fiable "
                "para esta función concreta — ver el README del proyecto para más detalle."
            )
            self._log("")

        self._on_copier_changed()
        self._on_tipo_changed()

    # -- interfaz ---------------------------------------------------------
    def _on_tipo_changed(self, *_args):
        c = self._current_copier()
        if self.sram_radio.isChecked():
            self.tipo_lbl.setText(
                "Se transferirá el contenido de la SRAM: las partidas guardadas del "
                f"cartucho, no el juego. uCON64 usará la opción {c.sram_option}."
            )
        else:
            self.tipo_lbl.setText(
                "Se transferirá la ROM completa del juego al copión. "
                f"uCON64 usará la opción {c.rom_option}."
            )

    def _current_copier(self) -> tu.CopierProfile:
        return self.copier_combo.currentData()

    def _on_copier_changed(self):
        self.notes_lbl.setText(self._current_copier().notes)
        if hasattr(self, "tipo_lbl"):
            self._on_tipo_changed()

    def _choose_file(self):
        c = self._current_copier()
        path = elegir_archivo(self, extensiones=c.extensions, titulo="Elegir ROM")
        if path:
            self.file_edit.setText(path)

    def _guardar_ucon64_manual(self):
        """Guarda la ruta si el usuario la escribió/pegó a mano en el
        campo, sin pasar por el selector de archivo (que ya la guarda
        por su cuenta en _choose_ucon64)."""
        path = self.ucon64_edit.text().strip()
        if path and tu.find_ucon64(path):
            _settings().setValue("transfer/ucon64_path", path)

    def _choose_ucon64(self):
        path = elegir_archivo(self, titulo="Localizar el ejecutable de uCON64")
        if path:
            self.ucon64_edit.setText(path)
            _settings().setValue("transfer/ucon64_path", path)

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
                                sram=self.sram_radio.isChecked())
        self.console.clear()
        self._log("$ " + " ".join(cmd))
        self._log("")

        self._process = None
        self._popen = None
        self._poll_timer = None
        self._bytes_totales = 0
        self.animacion.set_progress(0)
        working_dir = os.path.dirname(ucon64) or "."

        if os.name == "nt":
            # CAUSA REAL, confirmada tras una serie larga de pruebas
            # aisladas con hardware real (sin ningún Python/PyInstaller de
            # por medio, usando .bat sueltos): uCON64.exe, al comunicarse
            # con el puerto paralelo a través del driver de E/S
            # (InpOut32.dll), necesita que su salida esté conectada a una
            # consola real. En el momento en que se redirige — a un pipe
            # (lo que hace QProcess de forma normal), a un archivo con
            # setStandardOutputFile, o a través de cmd.exe con o sin
            # redirección — el proceso se cuelga silenciosamente justo
            # antes de tocar el puerto, sin ningún mensaje de error. Se
            # confirmó ejecutando exactamente el mismo comando sin NINGUNA
            # redirección (ni pipe ni archivo): ahí sí aparece "Using I/O
            # port base..." y el envío se completa con éxito. No importa
            # si la consola la creó Explorer, un .bat, o se escribió a
            # mano: lo único que importa es que la salida no esté
            # redirigida en absoluto.
            #
            # La solución es, por tanto, dejar de intentar capturar la
            # salida de ninguna manera en Windows: se lanza uCON64.exe con
            # su PROPIA ventana de consola real (CREATE_NEW_CONSOLE), con
            # su propio stdin/stdout/stderr (no heredados ni redirigidos),
            # y ASTURCONSOLE simplemente espera a que el proceso termine.
            # El progreso se ve en esa ventana aparte, no dentro de
            # ASTURCONSOLE — una limitación real de esta combinación
            # concreta (uCON64 + InpOut32.dll + Windows), no de nuestro
            # código, pero al menos la transferencia funciona igual que a
            # mano.
            #
            # QProcess no sirve para esto: Qt define
            # setCreateProcessArgumentsModifier() para ajustar los flags
            # de creación, pero PySide6 no expone ese método (falla con
            # AttributeError) — se usa subprocess.Popen en su lugar, que
            # sí soporta creationflags=CREATE_NEW_CONSOLE de forma nativa
            # en Windows, con un QTimer para vigilar cuándo termina, ya
            # que Popen no tiene ninguna señal propia de "terminado".
            CREATE_NEW_CONSOLE = 0x00000010
            self._log(
                "La transferencia por puerto paralelo en Windows necesita su "
                "propia ventana de consola (una limitación del driver de E/S, "
                "no de ASTURCONSOLE) — el progreso real se ve ahí, no aquí. "
                "Esta ventana solo avisará cuando el proceso termine."
            )
            self.progress.setMinimum(0)
            self.progress.setMaximum(0)  # barra indeterminada: no hay % real que leer
            try:
                self._popen = subprocess.Popen(
                    cmd, cwd=working_dir, creationflags=CREATE_NEW_CONSOLE)
            except OSError as e:
                self._log(f"\n[ERROR] no se pudo iniciar el proceso: {e}")
                return
            self._poll_timer = QTimer(self)
            self._poll_timer.timeout.connect(self._verificar_popen)
            self._poll_timer.start(300)
        else:
            self._process = QProcess(self)
            self._process.finished.connect(self._on_finished)
            self._process.errorOccurred.connect(self._on_error)
            self._process.setWorkingDirectory(working_dir)
            self._process.readyReadStandardOutput.connect(self._on_output)
            self._process.setProcessChannelMode(QProcess.MergedChannels)
            self._process.start(cmd[0], cmd[1:])
            # uCON64 en Windows puede quedarse esperando indefinidamente si
            # su entrada estándar (stdin) queda abierta sin cerrar; en
            # Linux no hace falta, pero tampoco molesta.
            self._process.closeWriteChannel()

        self._set_running(True)

    def _verificar_popen(self):
        """Vigila periódicamente si el proceso lanzado con subprocess.Popen
        (mecanismo de Windows, ver _start) ya terminó — Popen no tiene
        ninguna señal propia que avise de esto, a diferencia de QProcess."""
        if self._popen is None:
            return
        codigo = self._popen.poll()
        if codigo is not None:
            self._poll_timer.stop()
            self._poll_timer = None
            self._on_finished(codigo, None)

    def _cancel(self):
        if self._process is not None:
            self._log("\n[cancelando…]")
            self._process.terminate()
            if not self._process.waitForFinished(3000):
                self._process.kill()
        elif self._popen is not None:
            self._log("\n[cancelando…]")
            self._popen.terminate()
            try:
                self._popen.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._popen.kill()

    def _set_running(self, running: bool):
        self.send_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.progress.setVisible(running)
        self.animacion.set_running(running)
        for w in (self.copier_combo, self.file_btn, self.file_edit,
                  self.port_combo, self.rom_radio, self.sram_radio,
                  self.ucon64_edit):
            if w is not None:
                w.setEnabled(not running)

    def _procesar_texto(self, text: str):
        """Interpreta un bloque de texto de salida de uCON64: actualiza
        el progreso y escribe el resto en la consola. Solo se usa fuera
        de Windows — ver _start para la explicación de por qué en
        Windows no se captura la salida en absoluto."""
        for chunk in text.replace("\r", "\n").split("\n"):
            chunk = chunk.strip()
            if not chunk:
                continue
            # Antes de empezar a transferir, uCON64 imprime el tamaño total
            # ("Send: 2097152 Bytes (16.0000 Mb)" / "Receive: ..."): esta
            # línea es un printf directo, no pasa por el "gauge" de progreso,
            # así que aparece igual con o sin --frontend. Se aprovecha para
            # saber el total y poder mostrar bytes reales, no solo el %.
            m = re.match(r"(?:Send|Receive):\s+(\d+)\s+Bytes", chunk)
            if m:
                self._bytes_totales = int(m.group(1))
                self._log(chunk)
                continue
            # Con --frontend activo (ver transfer_ucon64.build_command),
            # uCON64 imprime SOLO el porcentaje en cada línea de progreso,
            # en vez de la barra ASCII decorativa habitual — mucho más
            # fácil y fiable de interpretar que parsear esa barra.
            if chunk.isdigit() and 0 <= int(chunk) <= 100:
                pct = int(chunk)
                bytes_actuales = int(self._bytes_totales * pct / 100)
                self.animacion.set_progress(pct, bytes_actuales, self._bytes_totales)
                self.progress.setValue(pct)
                continue
            self._log(chunk)

    def _on_output(self):
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput())
        text = data.decode("utf-8", errors="replace")
        self._procesar_texto(text)

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
        self.progress.setMaximum(100)  # por si quedó en modo indeterminado (Windows)
        self._set_running(False)
        self._process = None
        self._popen = None

        if exit_code == 0:
            self._log("\n[Transferencia finalizada correctamente]")
        else:
            self._log(f"\n[uCON64 terminó con código {exit_code}]")
            self._log(
                "Si el copión no responde: comprueba que está encendido, que el cable es "
                "bidireccional, que el puerto es correcto y que tienes permisos sobre él."
            )

    def closeEvent(self, event):
        if self._process is not None or self._popen is not None:
            self._cancel()
        super().closeEvent(event)
