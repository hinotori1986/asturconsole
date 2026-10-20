"""Ventana del reproductor de cintas MSX (interfaz).

La lógica de audio vive en `tape_player.py`; aquí solo está la interfaz.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

import cas_tape as ct
import tape_decoder as td
import tsx_tape as tt
import workspace as ws
from file_browser import elegir_archivo, elegir_archivo_guardar
from folder_picker import choose_directory
from tape_deck_widget import TapeDeckWidget
from tape_player import TapePlayer, TapeRecorder, available_output_devices
from tape_recorder_panel import RecorderPanel

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

# Selector de modo. El de grabar lleva el rojo típico del REC.
MODE_PLAY_STYLE = """
QPushButton {
    background: transparent; color: #8892a8;
    border: 2px solid #39404f; border-radius: 8px; font-weight: 700; font-size: 13px;
}
QPushButton:hover { color: #c3cadb; border-color: #5a6378; }
QPushButton:checked { background: rgba(62, 242, 154, 0.16); color: #3ef29a; border-color: #3ef29a; }
"""
MODE_REC_STYLE = """
QPushButton {
    background: transparent; color: #ff6b5e;
    border: 2px solid #6b2a26; border-radius: 8px; font-weight: 700; font-size: 13px;
}
QPushButton:hover { background: rgba(255, 59, 48, 0.12); border-color: #ff3b30; }
QPushButton:checked { background: rgba(255, 59, 48, 0.22); color: #ff3b30; border-color: #ff3b30; }
"""


class TapePlayerDialog(QDialog):
    """Reproductor y grabador de cintas MSX en una sola ventana.

    Reproducir: carga un .CAS/.TSX/.WAV y lo envía por la tarjeta de sonido
    para cargarlo en un MSX real. Grabar: captura una cinta real o lo que el
    MSX envía con CSAVE/BSAVE «CAS:» y la convierte en CAS/TSX/archivos."""

    def __init__(self, parent=None, initial_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Cinta MSX — reproducir y grabar")
        self.setMinimumSize(600, 600)
        try:
            geo = QApplication.primaryScreen().availableGeometry()
            self.resize(min(820, geo.width() - 40), min(940, geo.height() - 60))
        except Exception:  # noqa: BLE001 - sin pantalla (pruebas): tamaño por defecto
            pass

        self._cas_data: bytes | None = None
        self._source_name = ""
        self._pcm: bytes | None = None
        self._recorder = TapeRecorder(self)

        self._player = TapePlayer(self)
        self._player.progress.connect(self._on_progress)
        self._player.finished.connect(self._on_finished)
        self._player.state_changed.connect(self._on_state)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # --- selector de modo: reproducir / grabar ---
        mode_row = QHBoxLayout()
        self.play_mode_btn = QPushButton("▶   Reproducir cinta")
        self.rec_mode_btn = QPushButton("●   Grabar cinta")
        for b in (self.play_mode_btn, self.rec_mode_btn):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(38)
            mode_row.addWidget(b, 1)
        self.play_mode_btn.setStyleSheet(MODE_PLAY_STYLE)
        self.rec_mode_btn.setStyleSheet(MODE_REC_STYLE)
        self.play_mode_btn.setChecked(True)
        self.play_mode_btn.clicked.connect(lambda: self._show_mode("play"))
        self.rec_mode_btn.clicked.connect(lambda: self._show_mode("rec"))
        lay.addLayout(mode_row)

        # --- pletina animada (compartida; contiene los propios controles) ---
        self.deck = TapeDeckWidget(accent="#3ef29a", parent=self)
        self.deck.button_pressed.connect(self._on_deck_button)
        lay.addWidget(self.deck, 1)

        # --- páginas ---
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.stack, 0)

        # ===== página de reproducción =====
        play_page = QWidget()
        pl = QVBoxLayout(play_page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)

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
        pl.addLayout(file_row)

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

        opts.addWidget(QLabel("Onda:"))
        self.wave_combo = QComboBox()
        self.wave_combo.addItem("Senoidal (recomendada)", "sine")
        self.wave_combo.addItem("Cuadrada", "square")
        self.wave_combo.setToolTip(
            "Senoidal es la forma de las grabaciones de cinta reales y no se deforma "
            "por el cable o la tarjeta de sonido. Cuadrada solo si la senoidal no carga.")
        self.wave_combo.currentIndexChanged.connect(self._invalidate_render)
        opts.addWidget(self.wave_combo)
        opts.addStretch(1)
        pl.addLayout(opts)

        dev_row = QHBoxLayout()
        dev_row.addWidget(QLabel("Salida:"))
        self.device_combo = QComboBox()
        self._devices = available_output_devices()
        for d in self._devices:
            self.device_combo.addItem(d.description(), d)
        if not self._devices:
            self.device_combo.addItem("(sin dispositivos de audio)", None)
        dev_row.addWidget(self.device_combo, 1)
        pl.addLayout(dev_row)

        self.invert_chk = QCheckBox(
            "Invertir fase (pruébalo si el MSX no reconoce la señal)"
        )
        self.invert_chk.stateChanged.connect(self._invalidate_render)
        pl.addWidget(self.invert_chk)

        # --- aviso de calidad de señal ---
        self.warn_lbl = QLabel("")
        self.warn_lbl.setWordWrap(True)
        self.warn_lbl.setStyleSheet("color: #ffb454;")
        pl.addWidget(self.warn_lbl)

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
        pl.addLayout(bottom)

        hint = QLabel(
            "Conecta la salida de audio del PC a la entrada de casete del MSX, teclea "
            "el comando de carga en el MSX (p. ej. BLOAD\"CAS:\",R o RUN\"CAS:\") y "
            "pulsa Reproducir. Desactiva ecualizadores y efectos del sistema: "
            "deforman la señal y suelen impedir la carga."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #727a90; font-size: 11px;")
        pl.addWidget(hint)
        pl.addStretch(1)
        self.stack.addWidget(play_page)

        # ===== página de grabación =====
        self.rec_panel = RecorderPanel(self._recorder, self)
        self.rec_panel.cas_ready.connect(self._on_recorded_cas)
        self.rec_panel.recorder_state.connect(self._on_record_state)
        self.rec_panel.live_update.connect(self._on_record_live)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.rec_panel)
        self.stack.addWidget(scroll)

        self._lay = lay
        self._update_warning()
        self._show_mode("play")
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
        path = elegir_archivo(
            self, carpeta_inicial=start_dir, extensiones=(".cas", ".tsx", ".wav"),
            titulo="Abrir cinta MSX")
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
        if base.strip().upper() == vistos[0].strip().upper():
            return "  ·  ".join(vistos)
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
                resultado = td.decode_wav(raw)
                cas = resultado.cas
                if not cas:
                    raise ValueError("; ".join(resultado.warnings) or
                                     "no hay señal de cinta MSX en el audio")
                origen = (f"WAV a {resultado.baud:.0f} baudios (convertido a CAS al vuelo"
                          + ("" if resultado.framing_errors == 0 else
                             f", {resultado.framing_errors} errores de lectura") + ")")
            else:
                cas = raw
                origen = "CAS"
        except (ValueError, Exception) as e:  # noqa: BLE001
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
        grabando = self._recorder.state() in ("armed", "recording")
        if nombre == "REC":
            # La tecla REC de la pletina lleva a la pantalla de grabación y
            # arma la grabación (o la detiene si ya está en marcha).
            self._show_mode("rec")
            self.rec_panel.toggle_recording()
            return
        if grabando:
            # Durante la grabación, STOP la finaliza y el resto no aplica
            if nombre == "STOP":
                self.rec_panel.stop_recording()
            return
        if nombre in ("PLAY", "PAUSE", "REW") and self.stack.currentIndex() != 0:
            self._show_mode("play")
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
                    waveform=self.wave_combo.currentData(),
                )
            self._player.play(self._pcm, rate, device=device,
                              volume=self.vol_slider.value() / 100.0)
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Reproductor", f"No se pudo reproducir:\n{e}")
            return
        QApplication.restoreOverrideCursor()

    # -- modo reproducir / grabar -----------------------------------------
    def _show_mode(self, mode: str):
        grabar = mode == "rec"
        if not grabar and self.rec_panel.is_busy():
            # No se cambia de pantalla en mitad de una grabación
            self.play_mode_btn.setChecked(False)
            self.rec_mode_btn.setChecked(True)
            return
        if grabar and self._player.state() != "stopped":
            self._player.stop()
        self.play_mode_btn.setChecked(not grabar)
        self.rec_mode_btn.setChecked(grabar)
        self.stack.setCurrentIndex(1 if grabar else 0)
        # En grabación manda el panel; en reproducción, la pletina
        self._lay.setStretchFactor(self.deck, 0 if grabar else 1)
        self._lay.setStretchFactor(self.stack, 1 if grabar else 0)
        self.deck.set_accent("#ff5340" if grabar else "#3ef29a")
        self.deck.setMinimumHeight(190 if grabar else 230)

    def _on_record_state(self, state: str):
        grabando = state == "recording"
        self.deck.set_state("recording" if grabando else "stopped")
        if state == "armed":
            self.deck.set_title("Esperando señal…")
        elif state == "recording":
            self.deck.set_title("Grabando…")
        elif state == "stopped":
            self.deck.set_input_level(0)
        busy = state in ("armed", "recording")
        self.play_mode_btn.setEnabled(not busy)

    def _on_record_live(self, seconds: float, level: int, title: str):
        self.deck.set_input_level(level)
        if self._recorder.state() == "recording":
            self.deck.set_progress(seconds, 0)
            if title:
                self.deck.set_title(title)

    def _on_recorded_cas(self, cas: bytes, base: str, baud: int = 0):
        """El grabador entrega la cinta decodificada: queda cargada en el
        reproductor, lista para volver a enviarla a un MSX."""
        self._cas_data = cas
        self._source_name = base + ".cas"
        n_blocks = len(ct.find_sync_positions(cas))
        self.file_lbl.setText(f"{self._source_name}  —  grabación, {n_blocks} bloque(s)")
        self.deck.set_title(self._tape_title(cas, self._source_name))
        self.deck.set_finished(False)
        # El reproductor se ajusta a la velocidad con la que se grabó
        idx = self.baud_combo.findData(baud)
        if idx >= 0:
            self.baud_combo.setCurrentIndex(idx)
        self._invalidate_render()
        self._show_mode("play")

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
        for w in (self.baud_combo, self.rate_combo, self.wave_combo, self.device_combo,
                  self.invert_chk):
            w.setEnabled(state == "stopped")

    def _confirm_close(self) -> bool:
        if self.rec_panel.is_busy():
            texto = ("Hay una grabación en curso. Si cierras la ventana se detendrá y se "
                     "perderá lo que no se haya guardado.\n\n¿Cerrar de todos modos?")
        elif self.rec_panel.has_unsaved():
            texto = ("El audio grabado todavía no está guardado y se perderá al cerrar "
                     "(usa el botón «WAV» del grabador).\n\n¿Cerrar de todos modos?")
        else:
            return True
        r = QMessageBox.question(self, "Cinta MSX", texto)
        return r == QMessageBox.Yes

    def reject(self):
        if self._confirm_close():
            self._shutdown()
            super().reject()

    def closeEvent(self, event):
        if not self._confirm_close():
            event.ignore()
            return
        self._shutdown()
        super().closeEvent(event)

    def _shutdown(self):
        self._player.stop()
        self.rec_panel.shutdown()


def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"
