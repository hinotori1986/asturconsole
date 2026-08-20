"""Ventana del reproductor de cintas MSX (interfaz).

La lógica de audio vive en `tape_player.py`; aquí solo está la interfaz.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout,
    QLabel, QMessageBox, QProgressBar, QPushButton, QSlider, QVBoxLayout,
)

import cas_tape as ct
import tsx_tape as tt
import workspace as ws
from folder_picker import choose_directory
from tape_deck_widget import TapeDeckWidget
from tape_player import (
    RECORD_SAMPLE_RATES, TapePlayer, TapeRecorder, available_output_devices,
)
from PySide6.QtMultimedia import QMediaDevices

SAMPLE_RATES = (96000, 48000, 44100)
DEFAULT_BAUD = 3000

# Los botones de carga son la puerta de entrada del reproductor y antes
# pasaban desapercibidos: se les da color, borde y algo de cuerpo.
BOTON_PRINCIPAL = """
QPushButton {
    background: rgba(62, 242, 154, 0.16);
    color: #3ef29a;
    border: 2px solid #3ef29a;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 700;
}
QPushButton:hover { background: rgba(62, 242, 154, 0.30); }
QPushButton:disabled { color: #4d5468; border-color: #2c3342; background: transparent; }
"""

BOTON_SECUNDARIO = """
QPushButton {
    background: rgba(90, 160, 255, 0.14);
    color: #5aa0ff;
    border: 2px solid #5aa0ff;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 700;
}
QPushButton:hover { background: rgba(90, 160, 255, 0.28); }
QPushButton:disabled { color: #4d5468; border-color: #2c3342; background: transparent; }
"""
DEFAULT_PILOT_SECONDS = 3.0


class TapePlayerDialog(QDialog):
    """Reproductor simple: carga un .CAS/.TSX y lo envía por la tarjeta de
    sonido para cargarlo en un MSX real."""

    def __init__(self, parent=None, initial_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Reproductor de cinta MSX")
        self.setMinimumSize(560, 620)

        self._cas_data: bytes | None = None
        self._source_name = ""
        self._pcm: bytes | None = None
        self._recorder = TapeRecorder(self)
        self._recorder.progress.connect(self._on_record_progress)
        self._recorder.state_changed.connect(self._on_record_state)

        self._player = TapePlayer(self)
        self._player.progress.connect(self._on_progress)
        self._player.finished.connect(self._on_finished)
        self._player.state_changed.connect(self._on_state)

        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        # --- archivo ---
        file_row = QHBoxLayout()
        self.file_btn = QPushButton("  📂  Abrir ubicación  ")
        self.file_btn.setToolTip(
            "Elegir la ubicación (carpetas de la aplicación, discos o USB, con "
            "opción de montarlos) y después el archivo"
        )
        self.file_btn.setStyleSheet(BOTON_PRINCIPAL)
        self.file_btn.setCursor(Qt.PointingHandCursor)
        self.file_btn.clicked.connect(self._choose_from_device)

        self.device_btn = QPushButton("  🎞  Examinar cintas  ")
        self.device_btn.setToolTip("Ir directamente al explorador de archivos")
        self.device_btn.setStyleSheet(BOTON_SECUNDARIO)
        self.device_btn.setCursor(Qt.PointingHandCursor)
        self.device_btn.clicked.connect(lambda: self._choose_file())
        self.file_lbl = QLabel("Ninguna cinta cargada")
        self.file_lbl.setWordWrap(True)
        file_row.addWidget(self.file_btn)
        file_row.addWidget(self.device_btn)
        file_row.addWidget(self.file_lbl, 1)
        lay.addLayout(file_row)

        # --- ajustes ---
        opts = QHBoxLayout()
        opts.addWidget(QLabel("Velocidad:"))
        self.baud_combo = QComboBox()
        for b in ct.SUPPORTED_BAUDS:
            etiqueta = f"{b} baudios" + ("" if b in ct.STANDARD_BAUDS else "  (no estándar)")
            self.baud_combo.addItem(etiqueta, b)
        if DEFAULT_BAUD in ct.SUPPORTED_BAUDS:
            self.baud_combo.setCurrentIndex(ct.SUPPORTED_BAUDS.index(DEFAULT_BAUD))
        self.baud_combo.currentIndexChanged.connect(self._invalidate_render)
        opts.addWidget(self.baud_combo)

        opts.addWidget(QLabel("Muestreo:"))
        self.rate_combo = QComboBox()
        for r in SAMPLE_RATES:
            self.rate_combo.addItem(f"{r} Hz", r)
        self.rate_combo.currentIndexChanged.connect(self._invalidate_render)
        opts.addWidget(self.rate_combo)
        opts.addStretch(1)
        lay.addLayout(opts)

        dev_row = QHBoxLayout()
        dev_row.addWidget(QLabel("Salida:"))
        self.device_combo = QComboBox()
        self._devices = available_output_devices()
        for d in self._devices:
            self.device_combo.addItem(d.description(), d)
        if not self._devices:
            self.device_combo.addItem("(sin dispositivos de audio)", None)
        dev_row.addWidget(self.device_combo, 1)
        lay.addLayout(dev_row)

        rec_row = QHBoxLayout()
        rec_row.addWidget(QLabel("Entrada (grabar):"))
        self.input_combo = QComboBox()
        self._inputs = QMediaDevices.audioInputs()
        for d in self._inputs:
            self.input_combo.addItem(d.description(), d)
        if not self._inputs:
            self.input_combo.addItem("(sin entradas de audio)", None)
        rec_row.addWidget(self.input_combo, 1)
        rec_row.addWidget(QLabel("Muestreo:"))
        self.rec_rate_combo = QComboBox()
        for r in RECORD_SAMPLE_RATES:
            etiqueta = f"{r} Hz" + ("  (múltiplo exacto de 1200)" if r == 43200 else "")
            self.rec_rate_combo.addItem(etiqueta, r)
        self.rec_rate_combo.setCurrentIndex(RECORD_SAMPLE_RATES.index(44100))
        rec_row.addWidget(self.rec_rate_combo)
        lay.addLayout(rec_row)

        self.invert_chk = QCheckBox(
            "Invertir fase (pruébalo si el MSX no reconoce la señal)"
        )
        self.invert_chk.stateChanged.connect(self._invalidate_render)
        lay.addWidget(self.invert_chk)

        # --- aviso de calidad de señal ---
        self.warn_lbl = QLabel("")
        self.warn_lbl.setWordWrap(True)
        self.warn_lbl.setStyleSheet("color: #ffb454;")
        lay.addWidget(self.warn_lbl)

        # --- pletina animada (contiene los propios controles) ---
        self.deck = TapeDeckWidget(accent="#3ef29a", parent=self)
        self.deck.button_pressed.connect(self._on_deck_button)
        lay.addWidget(self.deck, 1)

        # --- progreso y volumen, en una sola fila compacta ---
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        bottom.addWidget(self.progress, 1)

        self.time_lbl = QLabel("—")
        self.time_lbl.setMinimumWidth(96)
        self.time_lbl.setAlignment(Qt.AlignCenter)
        bottom.addWidget(self.time_lbl)

        bottom.addWidget(QLabel("Vol."))
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setFixedWidth(110)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(90)
        self.vol_slider.valueChanged.connect(
            lambda v: self._player.set_volume(v / 100.0)
        )
        bottom.addWidget(self.vol_slider)
        lay.addLayout(bottom)

        hint = QLabel(
            "Conecta la salida de audio del PC a la entrada de casete del MSX, teclea "
            "el comando de carga en el MSX (p. ej. BLOAD\"CAS:\",R o RUN\"CAS:\") y "
            "pulsa Reproducir. Desactiva ecualizadores y efectos del sistema: "
            "deforman la señal y suelen impedir la carga."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #727a90; font-size: 11px;")
        lay.addWidget(hint)

        self._update_warning()
        if initial_path:
            self._load_path(initial_path)

    # -- carga de archivo -------------------------------------------------
    TAPE_FILTER = ("Cintas MSX (*.cas *.tsx *.wav);;CAS (*.cas);;TSX (*.tsx);;"
                   "WAV (*.wav);;Todos (*)")

    def _choose_file(self, start_dir: str | None = None):
        # Defensa ante la señal `clicked`, que emite un booleano: si llega
        # cualquier cosa que no sea una ruta de carpeta usable, se ignora.
        if not isinstance(start_dir, str) or not os.path.isdir(start_dir):
            start_dir = None
        if start_dir is None:
            # Arrancar donde es probable que estén las cintas: primero la
            # carpeta de conversiones, y si está vacía, la de originales.
            start_dir = ws.folder("tapes")
            try:
                if not os.listdir(start_dir):
                    start_dir = ws.source_folder()
            except OSError:
                start_dir = ws.source_folder()
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir cinta MSX", start_dir, self.TAPE_FILTER)
        if path:
            self._load_path(path)

    @staticmethod
    def _tape_title(cas: bytes, fallback: str) -> str:
        """Nombre a mostrar: el que lleva la propia cinta si se puede leer.

        Las cabeceras MSX guardan un nombre de 6 caracteres tras los diez
        bytes de tipo; es más representativo que el nombre del archivo.
        """
        nombres = []
        for p in ct.find_sync_positions(cas):
            if p + 24 > len(cas):
                continue
            tipo = cas[p + 8]
            if tipo in (0xD0, 0xD3, 0xEA) and cas[p + 8:p + 18] == bytes([tipo]) * 10:
                crudo = cas[p + 18:p + 24]
                nombre = "".join(chr(b) if 32 <= b < 127 else " " for b in crudo).strip()
                if nombre:
                    nombres.append(nombre)
        base = os.path.splitext(fallback)[0]
        if not nombres:
            return base
        # Si hay varios archivos en la cinta, se muestran todos
        vistos = list(dict.fromkeys(nombres))
        return f"{base}   ·   " + "  ·  ".join(vistos)

    def _choose_from_device(self):
        """Selector de volúmenes y dispositivos USB, igual que en SNES: deja
        montar una unidad y después buscar la cinta dentro de ella."""
        directorio = choose_directory(self)
        if directorio:
            self._choose_file(start_dir=directorio)

    def _load_path(self, path: str):
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError as e:
            QMessageBox.warning(self, "Reproductor", f"No se pudo leer el archivo: {e}")
            return

        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".tsx" or raw[:8] == tt.TSX_MAGIC:
                cas = tt.tsx_to_cas(raw)
                origen = "TSX (convertido a CAS al vuelo)"
            elif ext == ".wav" or raw[:4] == b"RIFF":
                # Se decodifica midiendo la velocidad real de la grabación,
                # que en cintas auténticas no es una cifra redonda.
                _sr, _pa, _pg, medidos = ct.measure_signal(raw)
                cas = ct.wav_to_cas(raw)
                origen = f"WAV a {medidos:.0f} baudios (convertido a CAS al vuelo)"
            else:
                cas = raw
                origen = "CAS"
        except ValueError as e:
            QMessageBox.warning(self, "Reproductor", f"No se pudo interpretar la cinta:\n{e}")
            return

        self._cas_data = cas
        self._source_name = os.path.basename(path)
        n_blocks = len(ct.find_sync_positions(cas))
        self.file_lbl.setText(f"{self._source_name}  —  {origen}, {n_blocks} bloque(s)")
        self.deck.set_title(self._tape_title(cas, self._source_name))
        self.deck.set_finished(False)
        self._invalidate_render()

    # -- ajustes ----------------------------------------------------------
    def _invalidate_render(self):
        self._pcm = None
        self._update_warning()

    def _update_warning(self):
        baud = self.baud_combo.currentData()
        rate = self.rate_combo.currentData()
        if baud is None or rate is None:
            return
        msgs = []
        w = ct.check_sample_rate(baud, rate)
        if w:
            msgs.append(w)
        if baud not in ct.STANDARD_BAUDS:
            msgs.append(
                f"{baud} baudios no es una velocidad estándar de la ROM: el MSX debe "
                "haberse configurado antes para leer a esa velocidad, si no, no cargará."
            )
        self.warn_lbl.setText("  ".join(msgs))
        self.warn_lbl.setVisible(bool(msgs))

    # -- transporte -------------------------------------------------------
    def _on_deck_button(self, nombre: str):
        if nombre == "REC":
            if self._recorder.state() == "recording":
                self._finish_recording()
            else:
                self._start_recording()
            return
        if self._recorder.state() == "recording":
            # Durante la grabación, STOP la finaliza y el resto no aplica
            if nombre == "STOP":
                self._finish_recording()
            return
        if nombre == "PLAY":
            if self._player.state() != "playing":
                self._toggle_play()
        elif nombre == "PAUSE":
            estado = self._player.state()
            if estado == "playing":
                self._player.pause()
            elif estado == "paused":
                self._player.resume()
        elif nombre == "REW":
            self._rewind()
        elif nombre == "STOP":
            self._stop()

    def _toggle_play(self):
        state = self._player.state()
        if state == "playing":
            self._player.pause()
            return
        if state == "paused":
            self._player.resume()
            return

        if self._cas_data is None:
            QMessageBox.information(
                self, "Reproductor",
                "Primero abre una cinta (.cas o .tsx) con el botón «Abrir cinta…».",
            )
            return
        baud = self.baud_combo.currentData()
        rate = self.rate_combo.currentData()
        device = self.device_combo.currentData()
        if device is None and self._devices:
            device = self._devices[0]

        # Limpiar el aviso de la reproducción anterior
        self.warn_lbl.setStyleSheet("color: #ffb454;")
        self._update_warning()
        self.deck.set_finished(False)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if self._pcm is None:
                self._pcm, _dur = TapePlayer.render_pcm(
                    self._cas_data, baud=baud, sample_rate=rate,
                    pilot_seconds=DEFAULT_PILOT_SECONDS,
                    invert_phase=self.invert_chk.isChecked(),
                )
            self._player.play(self._pcm, rate, device=device,
                              volume=self.vol_slider.value() / 100.0)
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Reproductor", f"No se pudo reproducir:\n{e}")
            return
        QApplication.restoreOverrideCursor()

    # -- grabación ---------------------------------------------------------
    def _start_recording(self):
        if self._player.state() != "stopped":
            self._player.stop()
        device = self.input_combo.currentData()
        rate = self.rec_rate_combo.currentData()
        try:
            self._recorder.start(device=device, sample_rate=rate, bit_depth=16)
        except (ValueError, RuntimeError) as e:
            QMessageBox.warning(self, "Reproductor", f"No se pudo iniciar la grabación:\n{e}")
            return
        self.file_lbl.setText(f"● Grabando a {rate} Hz, mono…")

    def _finish_recording(self):
        datos = self._recorder.stop()
        duracion = self._recorder.duration()
        if not datos or duracion < 0.2:
            QMessageBox.information(
                self, "Reproductor",
                "No se capturó audio suficiente. Comprueba que la entrada elegida es "
                "la correcta y que la señal llega al PC.",
            )
            self.deck.set_state("stopped")
            return

        sugerido = os.path.join(ws.folder("tapes"), "grabacion.wav")
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar grabación", sugerido, "Audio WAV (*.wav)")
        if not path:
            self.deck.set_state("stopped")
            return
        try:
            self._recorder.save_wav(path)
        except OSError as e:
            QMessageBox.warning(self, "Reproductor", f"No se pudo guardar:\n{e}")
            return

        # Comprobar si lo grabado es una cinta MSX legible, que es el objetivo
        analisis = ""
        try:
            wav = self._recorder.wav_bytes()
            _sr, _pa, _pg, baudios = ct.measure_signal(wav)
            cas = ct.wav_to_cas(wav)
            bloques = len(ct.find_sync_positions(cas))
            if bloques:
                analisis = (f"\n\nSe reconoce como cinta MSX: {bloques} bloque(s) a "
                            f"{baudios:.0f} baudios. Ya puedes convertirla a CAS o TSX.")
            else:
                analisis = ("\n\nNo se han detectado bloques MSX válidos. Puede que el "
                            "nivel de entrada sea muy bajo o muy alto, o que la señal "
                            "esté saturada.")
        except Exception:  # noqa: BLE001
            analisis = ("\n\nNo se ha podido analizar la señal grabada; revisa el nivel "
                        "de entrada.")

        self.deck.set_state("stopped")
        self.file_lbl.setText(f"{os.path.basename(path)} — grabación de {duracion:.1f} s")
        QMessageBox.information(
            self, "Reproductor",
            f"Grabación guardada ({duracion:.1f} s).\n\n{path}{analisis}",
        )

    def _on_record_progress(self, seconds: float, level: int):
        self.deck.set_progress(seconds, 0)
        self.deck.set_input_level(level)
        self.time_lbl.setText(f"● {_fmt_time(seconds)}")
        aviso = ""
        if level >= 98:
            aviso = "  ¡SATURANDO! baja el volumen de entrada"
        elif level < 15:
            aviso = "  nivel muy bajo"
        self.warn_lbl.setText(f"Nivel de entrada: {level}%{aviso}")
        self.warn_lbl.setVisible(True)

    def _on_record_state(self, state: str):
        grabando = state == "recording"
        self.deck.set_state("recording" if grabando else "stopped")
        for w in (self.file_btn, self.device_btn, self.baud_combo, self.rate_combo,
                  self.input_combo, self.rec_rate_combo, self.invert_chk):
            w.setEnabled(not grabando)
        if not grabando:
            self._update_warning()

    def _rewind(self):
        """Vuelve al principio de la cinta, como el REW del aparato real."""
        self._player.stop()
        self.deck.set_finished(False)
        self.warn_lbl.setStyleSheet("color: #ffb454;")
        self._update_warning()
        self.progress.setValue(0)
        self.time_lbl.setText(f"{_fmt_time(0)} / {_fmt_time(self._player.duration())}"
                               if self._player.duration() else "—")
        self.deck.rewind()

    def _stop(self):
        self._player.stop()
        self.deck.set_finished(False)
        self.progress.setValue(0)
        self.time_lbl.setText("—")
        self.deck.set_state("stopped")
        self.warn_lbl.setStyleSheet("color: #ffb454;")
        self._update_warning()

    def _on_progress(self, elapsed: float, total: float):
        if total > 0:
            self.progress.setValue(int(elapsed / total * 1000))
        self.time_lbl.setText(f"{_fmt_time(elapsed)} / {_fmt_time(total)}")
        self.deck.set_progress(elapsed, total)

    def _on_finished(self):
        # Marcar el fin ANTES de cualquier otra cosa: así el cambio de estado
        # a "detenido" que viene a continuación no reinicia los indicadores.
        self.deck.set_finished(True)
        self.progress.setValue(1000)
        total = self._player.duration()
        self.time_lbl.setText(f"{_fmt_time(total)} / {_fmt_time(total)}")
        self.warn_lbl.setText(
            "✓ CARGA FINALIZADA — la cinta ha llegado al final. Si el MSX no ha "
            "cargado, prueba a cambiar el nivel de volumen, la fase o la velocidad."
        )
        self.warn_lbl.setStyleSheet("color: #3ef29a; font-weight: 700;")
        self.warn_lbl.setVisible(True)
        self._play_end_tone()

    def _play_end_tone(self):
        """Reproduce el aviso de fin por el mismo dispositivo de salida."""
        try:
            from tape_player import end_of_tape_tone
            rate = 44100
            wav = end_of_tape_tone(rate)
            idx = wav.find(b"data")
            if idx == -1:
                return
            pcm = wav[idx + 8:]
            device = self.device_combo.currentData()
            if device is None and self._devices:
                device = self._devices[0]
            self._tone_player = TapePlayer(self)
            self._tone_player.play(pcm, rate, device=device,
                                    volume=min(0.6, self.vol_slider.value() / 100.0))
        except Exception:  # noqa: BLE001
            # El aviso es un extra: si el dispositivo no admite este formato,
            # no debe impedir que la reproducción termine con normalidad.
            pass

    def _on_state(self, state: str):
        self.deck.set_state(state)
        for w in (self.baud_combo, self.rate_combo, self.device_combo, self.invert_chk):
            w.setEnabled(state == "stopped")

    def closeEvent(self, event):
        self._player.stop()
        super().closeEvent(event)


def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"
