"""Panel del grabador de cintas MSX (interfaz).

Va dentro de la ventana del reproductor (``TapePlayerDialog``). Graba desde
cualquier entrada de audio —casete real, salida de un MSX con CSAVE/BSAVE
«CAS:», o un adaptador USB— y convierte lo grabado en una lista de programas
con su nombre, tipo y direcciones, que se puede guardar como WAV, CAS o TSX,
o extraer como archivos de MSX.

La lógica de captura vive en ``tape_capture`` (sin Qt) y la de decodificación
en ``tape_decoder``; aquí solo está la interfaz.
"""
from __future__ import annotations

import math
import os
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QCheckBox, QComboBox, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSizePolicy, QSlider, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import tape_catalog as tc
import tape_decoder as td
import tsx_tape as tt
import workspace as ws
from file_browser import elegir_archivo_guardar
from folder_picker import choose_directory
from tape_player import (
    DEFAULT_RECORD_RATE, RECORD_SAMPLE_RATES, TapeRecorder, available_input_devices,
)

UNSAVED_MSG = ("El audio aún no está guardado: usa el botón «WAV» antes de cerrar "
               "o de grabar otra vez.")
DEFAULT_INPUT_VOLUME = 50       # % de partida: al 100 % casi cualquier entrada satura


def _settings() -> QSettings:
    return QSettings("ASTURCONSOLE", "asturconsole")


REC_RED = QColor("#ff3b30")
REC_RED_DARK = QColor("#8f1414")
OK_GREEN = "#3ef29a"
WARN_AMBER = "#ffb454"

BOTON_ACCION = """
QPushButton {
    background: rgba(90, 160, 255, 0.14);
    color: #5aa0ff;
    border: 2px solid #5aa0ff;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 700;
}
QPushButton:hover { background: rgba(90, 160, 255, 0.28); }
QPushButton:disabled { color: #4d5468; border-color: #2c3342; background: transparent; }
"""

BOTON_VERDE = BOTON_ACCION.replace("90, 160, 255", "62, 242, 154").replace("#5aa0ff", "#3ef29a")
BOTON_SUAVE = """
QPushButton {
    background: transparent; color: #8892a8;
    border: 1px solid #39404f; border-radius: 6px; padding: 6px 12px;
}
QPushButton:hover { color: #c3cadb; border-color: #5a6378; }
QPushButton:disabled { color: #4d5468; border-color: #2c3342; }
QPushButton:checked { color: #ffb454; border-color: #ffb454; }
"""


# ---------------------------------------------------------------------------
# Botón REC redondo y llamativo
# ---------------------------------------------------------------------------

class RecButton(QAbstractButton):
    """El típico botón de grabación: disco rojo brillante con aro metálico.

    ``idle``: rojo sereno. ``armed``: parpadea despacio (esperando señal).
    ``recording``: late con un halo rojo y muestra un cuadradito de STOP.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "idle"
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(132, 150)
        self.setToolTip("Grabar / parar la grabación")

    def set_mode(self, mode: str):
        self._mode = mode
        if mode == "idle":
            self._timer.stop()
            self._phase = 0.0
        else:
            self._timer.start()
        self.update()

    def _tick(self):
        step = 0.045 if self._mode == "armed" else 0.10
        self._phase = (self._phase + step) % (2 * math.pi)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        c = QPointF(w / 2, 66)
        r = 52.0
        pulse = 0.5 + 0.5 * math.sin(self._phase)

        # halo
        if self._mode == "recording":
            for k, a in ((1.0, 60), (0.66, 40), (0.33, 25)):
                rr = r + 4 + 14 * pulse * k
                halo = QRadialGradient(c, rr)
                halo.setColorAt(0.6, QColor(255, 59, 48, int(a * (0.5 + 0.5 * pulse))))
                halo.setColorAt(1.0, QColor(255, 59, 48, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(halo))
                p.drawEllipse(c, rr, rr)
        elif self._mode == "armed":
            halo = QRadialGradient(c, r + 14)
            halo.setColorAt(0.7, QColor(255, 180, 84, int(70 * pulse)))
            halo.setColorAt(1.0, QColor(255, 180, 84, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(halo))
            p.drawEllipse(c, r + 14, r + 14)

        # aro metálico
        ring = QLinearGradient(c.x(), c.y() - r, c.x(), c.y() + r)
        ring.setColorAt(0, QColor("#5b6275"))
        ring.setColorAt(0.5, QColor("#2a2f3b"))
        ring.setColorAt(1, QColor("#454c5e"))
        p.setPen(QPen(QColor("#10131b"), 1.5))
        p.setBrush(QBrush(ring))
        p.drawEllipse(c, r, r)

        # disco rojo
        base = 1.0
        if self._mode == "armed":
            base = 0.45 + 0.55 * pulse
        elif self._mode == "recording":
            base = 0.85 + 0.15 * pulse
        if self.isDown():
            base *= 0.85
        rin = r - 8
        disc = QRadialGradient(QPointF(c.x() - rin * 0.25, c.y() - rin * 0.35), rin * 1.35)
        hi = QColor("#ff7a6b")
        mid = QColor("#ff3b30")
        lo = QColor("#a81212")
        for col in (hi, mid, lo):
            col.setAlphaF(1.0)
        disc.setColorAt(0.0, _mix(hi, QColor("#2a1010"), base))
        disc.setColorAt(0.55, _mix(mid, QColor("#2a1010"), base))
        disc.setColorAt(1.0, _mix(lo, QColor("#1a0808"), base))
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.setBrush(QBrush(disc))
        p.drawEllipse(c, rin, rin)

        # brillo superior
        gloss = QLinearGradient(c.x(), c.y() - rin, c.x(), c.y())
        gloss.setColorAt(0, QColor(255, 255, 255, 110))
        gloss.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(gloss))
        p.drawEllipse(QRectF(c.x() - rin * 0.72, c.y() - rin * 0.92, rin * 1.44, rin * 0.9))

        # cuadrado de parada cuando graba
        if self._mode == "recording":
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawRoundedRect(QRectF(c.x() - 15, c.y() - 15, 30, 30), 4, 4)

        # rótulo
        f = QFont()
        f.setBold(True)
        f.setPointSize(11)
        p.setFont(f)
        texto = {"idle": "GRABAR", "armed": "ARMADO", "recording": "PARAR"}[self._mode]
        color = {"idle": QColor("#ff6b5e"), "armed": QColor("#ffb454"),
                 "recording": QColor("#ff6b5e")}[self._mode]
        p.setPen(color)
        p.drawText(QRectF(0, h - 30, w, 24), Qt.AlignCenter, texto)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() * t + b.red() * (1 - t)),
                  int(a.green() * t + b.green() * (1 - t)),
                  int(a.blue() * t + b.blue() * (1 - t)))


# ---------------------------------------------------------------------------
# Vúmetro
# ---------------------------------------------------------------------------

class LevelMeter(QWidget):
    """Barra de nivel de entrada en dBFS con retención del pico y aviso de
    saturación. El tramo ideal (verde) va de -24 a -6 dB."""

    DB_MIN = -48.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._level = 0.0
        self._hold = 0.0
        self._hold_t = 0.0
        self._clip = False
        self._clip_t = 0.0
        self._active = False

    def set_active(self, active: bool):
        self._active = active
        if not active:
            self._level = 0.0
            self._hold = 0.0
        self.update()

    def feed(self, peak: float, clipped: bool):
        now = time.monotonic()
        # el pico baja suavemente
        self._level = max(peak, self._level * 0.82)
        if peak >= self._hold or now - self._hold_t > 1.2:
            self._hold = max(peak, self._hold * 0.9 if now - self._hold_t > 1.2 else self._hold)
            self._hold_t = now
        if clipped or peak >= 0.985:
            self._clip = True
            self._clip_t = now
        elif now - self._clip_t > 1.5:
            self._clip = False
        self.update()

    @staticmethod
    def to_db(v: float) -> float:
        return 20.0 * math.log10(v) if v > 1e-6 else -120.0

    def _x(self, v: float, left: float, width: float) -> float:
        db = max(self.DB_MIN, self.to_db(v))
        return left + (db - self.DB_MIN) / (-self.DB_MIN) * width

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        track = QRectF(0, 2, w - 64, h - 14)
        p.setPen(QPen(QColor("#39404f"), 1))
        p.setBrush(QColor("#0a0c12"))
        p.drawRoundedRect(track, 4, 4)

        n = 48
        gap = 2.0
        seg_w = (track.width() - 6 - gap * (n - 1)) / n
        lvl_x = self._x(self._level, track.left() + 3, track.width() - 6)
        for i in range(n):
            x = track.left() + 3 + i * (seg_w + gap)
            db = self.DB_MIN + (i + 0.5) / n * (-self.DB_MIN)
            if db < -24:
                col = QColor("#2e9b6b")
            elif db < -6:
                col = QColor("#3ef29a")
            elif db < -2:
                col = QColor("#ffb454")
            else:
                col = QColor("#ff3b30")
            lit = self._active and x + seg_w / 2 <= lvl_x
            if not lit:
                col = QColor(col.red(), col.green(), col.blue(), 38)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, track.top() + 3, seg_w, track.height() - 6), 1.5, 1.5)

        if self._active and self._hold > 0.001:
            hx = self._x(self._hold, track.left() + 3, track.width() - 6)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawLine(QPointF(hx, track.top() + 2), QPointF(hx, track.bottom() - 2))

        # escala
        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        p.setPen(QColor("#727a90"))
        for db in (-48, -36, -24, -12, -6, 0):
            x = track.left() + 3 + (db - self.DB_MIN) / (-self.DB_MIN) * (track.width() - 6)
            p.drawText(QRectF(x - 16, track.bottom() + 1, 32, 11), Qt.AlignCenter, str(db))

        # lectura numérica + LED de saturación
        db_now = self.to_db(self._hold if self._active else 0.0)
        txt = "—" if not self._active or db_now < -90 else f"{db_now:.0f} dB"
        f2 = QFont()
        f2.setBold(True)
        f2.setPointSize(10)
        p.setFont(f2)
        p.setPen(QColor("#c3cadb"))
        p.drawText(QRectF(w - 62, 0, 46, h - 12), Qt.AlignVCenter | Qt.AlignRight, txt)
        led = QPointF(w - 8, (h - 12) / 2 + 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ff3b30") if self._clip else QColor("#3a1717"))
        p.drawEllipse(led, 5, 5)


# ---------------------------------------------------------------------------
# Tarea en segundo plano con progreso
# ---------------------------------------------------------------------------

class _Job:
    def __init__(self, fn):
        self.progress = 0.0
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._fut = self._pool.submit(lambda: fn(self._set))

    def _set(self, f: float):
        self.progress = f

    def done(self) -> bool:
        return self._fut.done()

    def result(self):
        r = self._fut.result()
        self._pool.shutdown(wait=False)
        return r


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

COLUMNS = ("#", "Nombre", "Tipo", "Tamaño", "Inicio", "Fin", "Ejecución", "Baudios", "Estado")


class RecorderPanel(QWidget):
    """Contenido de la pestaña «Grabar» de la ventana de cintas."""

    cas_ready = Signal(bytes, str, int)  # (CAS decodificado, título, baudios) -> reproductor
    recorder_state = Signal(str)        # monitoring | armed | recording | stopped
    live_update = Signal(float, int, str)   # (segundos, nivel 0-100, título para la pletina)

    def __init__(self, recorder: TapeRecorder, parent=None):
        super().__init__(parent)
        self._rec = recorder
        self._rec.status_changed.connect(self._on_status)
        self._rec.state_changed.connect(self._on_state)
        self._rec.rate_adjusted.connect(self._on_rate_adjusted)

        self._result: td.DecodeResult | None = None
        self._entries: list[tc.TapeEntry] = []
        self._cas = b""
        self._wav_path = ""
        self._job: _Job | None = None
        self._job_timer = QTimer(self)
        self._job_timer.setInterval(120)
        self._job_timer.timeout.connect(self._poll_job)
        self._was_recording = False
        self._auto_stopped = False
        self._gain_ignored = False
        self._unsaved = False
        self._guardando_wav = False
        self._shown_entries = -1
        self._last_adjusted_msg = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # --- fila superior: botón REC + ajustes ---
        top = QHBoxLayout()
        top.setSpacing(16)
        self.rec_btn = RecButton()
        self.rec_btn.clicked.connect(self.toggle_recording)
        top.addWidget(self.rec_btn, 0, Qt.AlignTop)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        grid.addWidget(QLabel("Entrada:"), 0, 0)
        self.input_combo = QComboBox()
        self.input_combo.setMinimumWidth(200)
        self.input_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        grid.addWidget(self.input_combo, 0, 1, 1, 3)
        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setFixedWidth(34)
        self.refresh_btn.setToolTip("Buscar de nuevo las entradas de audio (por ejemplo, "
                                    "tras conectar un adaptador USB)")
        self.refresh_btn.setStyleSheet(BOTON_SUAVE)
        self.refresh_btn.clicked.connect(self.refresh_devices)
        grid.addWidget(self.refresh_btn, 0, 4)

        grid.addWidget(QLabel("Canal:"), 1, 0)
        self.channel_combo = QComboBox()
        self.channel_combo.addItem("Automático (el que lleve señal)", "auto")
        self.channel_combo.addItem("Izquierdo", "left")
        self.channel_combo.addItem("Derecho", "right")
        self.channel_combo.addItem("Mezcla de los dos", "mix")
        self.channel_combo.setToolTip(
            "La cinta es una sola señal (mono). Automático elige el canal de la "
            "entrada que recibe señal; así un cable mono no pierde nivel.")
        grid.addWidget(self.channel_combo, 1, 1)
        grid.addWidget(QLabel("Muestreo:"), 1, 2)
        self.rate_combo = QComboBox()
        for r in RECORD_SAMPLE_RATES:
            etiqueta = f"{r} Hz" + ("  (múltiplo de 1200)" if r == 43200 else "")
            self.rate_combo.addItem(etiqueta, r)
        self.rate_combo.setCurrentIndex(RECORD_SAMPLE_RATES.index(DEFAULT_RECORD_RATE))
        grid.addWidget(self.rate_combo, 1, 3, 1, 2)

        grid.addWidget(QLabel("Parar tras:"), 2, 0)
        self.autostop_combo = QComboBox()
        for etiqueta, valor in (("silencio de 5 s", 5.0), ("silencio de 10 s", 10.0),
                                ("silencio de 20 s", 20.0), ("silencio de 30 s", 30.0),
                                ("(no parar solo)", 0.0)):
            self.autostop_combo.addItem(etiqueta, valor)
        self.autostop_combo.setCurrentIndex(1)
        self.autostop_combo.setToolTip(
            "Cuando se acaba la cinta o el MSX termina de enviar, la grabación se "
            "detiene sola tras este tiempo sin señal.")
        grid.addWidget(self.autostop_combo, 2, 1, 1, 2)
        self.arm_chk = QCheckBox("Empezar al detectar señal")
        self.arm_chk.setChecked(True)
        self.arm_chk.setToolTip(
            "Pulsa GRABAR, dale al play del casete (o escribe CSAVE en el MSX) y la "
            "grabación arranca sola justo antes de la señal, sin perder el principio.")
        grid.addWidget(self.arm_chk, 2, 3, 1, 2)

        self.monitor_btn = QPushButton("🎚  Probar nivel")
        self.monitor_btn.setCheckable(True)
        self.monitor_btn.setStyleSheet(BOTON_SUAVE)
        self.monitor_btn.setToolTip("Mide la señal de entrada sin grabar, para ajustar el "
                                    "volumen antes de empezar")
        self.monitor_btn.clicked.connect(self._toggle_monitor)
        grid.addWidget(self.monitor_btn, 3, 0, 1, 2)

        gain_row = QHBoxLayout()
        gain_row.setSpacing(6)
        gain_row.addWidget(QLabel("Nivel de entrada:"))
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setRange(0, 100)
        self.gain_slider.setValue(DEFAULT_INPUT_VOLUME)
        self.gain_slider.setToolTip(
            "Volumen de captura de la entrada. Si el vúmetro llega al rojo, bájalo; si la "
            "señal es muy baja, súbelo. Se puede mover mientras se prueba o se graba. "
            "Se recuerda para cada entrada hasta que lo cambies.")
        self.gain_lbl = QLabel(f"{DEFAULT_INPUT_VOLUME} %")
        self.gain_lbl.setMinimumWidth(44)
        self.gain_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gain_row.addWidget(self.gain_slider, 1)
        gain_row.addWidget(self.gain_lbl)
        grid.addLayout(gain_row, 3, 2, 1, 3)
        self.gain_slider.valueChanged.connect(self._on_gain_changed)
        self.input_combo.currentIndexChanged.connect(self._load_gain_for_device)
        grid.setColumnStretch(1, 1)
        top.addLayout(grid, 1)
        lay.addLayout(top)

        # --- vúmetro y estado ---
        self.meter = LevelMeter()
        lay.addWidget(self.meter)

        self.state_lbl = QLabel("Listo para grabar")
        f = QFont()
        f.setBold(True)
        f.setPointSize(12)
        self.state_lbl.setFont(f)
        lay.addWidget(self.state_lbl)

        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet("color: #8892a8;")
        self.info_lbl.setWordWrap(True)
        lay.addWidget(self.info_lbl)

        self.advice_lbl = QLabel("")
        self.advice_lbl.setWordWrap(True)
        self.advice_lbl.setStyleSheet(f"color: {WARN_AMBER};")
        lay.addWidget(self.advice_lbl)

        self.busy = QProgressBar()
        self.busy.setRange(0, 1000)
        self.busy.setTextVisible(True)
        self.busy.setFormat("Analizando la grabación… %p%")
        self.busy.setFixedHeight(16)
        self.busy.hide()
        lay.addWidget(self.busy)

        # --- tabla de programas ---
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(110)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_select)
        lay.addWidget(self.table, 1)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(72)
        self.detail.setPlaceholderText(
            "Aquí aparecerán los programas de la cinta según se vayan leyendo. "
            "Selecciona uno para ver sus detalles.")
        mono = QFont("monospace")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(9)
        self.detail.setFont(mono)
        lay.addWidget(self.detail)

        # --- guardar ---
        row1 = QHBoxLayout()
        self.save_wav_btn = QPushButton("💾  WAV")
        self.save_cas_btn = QPushButton("💾  CAS")
        self.save_tsx_btn = QPushButton("💾  TSX")
        for b, tip in ((self.save_wav_btn, "Guarda el audio grabado tal cual"),
                       (self.save_cas_btn, "Guarda la cinta completa decodificada (formato CAS)"),
                       (self.save_tsx_btn, "Guarda la cinta completa en formato TSX")):
            b.setStyleSheet(BOTON_VERDE)
            b.setToolTip(tip)
            row1.addWidget(b)
        self.save_wav_btn.clicked.connect(self._save_wav)
        self.save_cas_btn.clicked.connect(lambda: self._save_cas(None))
        self.save_tsx_btn.clicked.connect(self._save_tsx)
        row1.addStretch(1)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        self.save_sel_cas_btn = QPushButton("CAS del programa")
        self.save_sel_file_btn = QPushButton("Extraer archivo MSX")
        self.save_all_btn = QPushButton("Extraer todos…")
        self.to_player_btn = QPushButton("▶  Pasar al reproductor")
        self.discard_btn = QPushButton("Descartar")
        for b in (self.save_sel_cas_btn, self.save_sel_file_btn, self.save_all_btn):
            b.setStyleSheet(BOTON_ACCION)
            row2.addWidget(b)
        self.to_player_btn.setStyleSheet(BOTON_ACCION)
        self.discard_btn.setStyleSheet(BOTON_SUAVE)
        row2.addWidget(self.to_player_btn)
        row2.addWidget(self.discard_btn)
        row2.addStretch(1)
        self.save_sel_cas_btn.setToolTip("Guarda como CAS solo el programa seleccionado")
        self.save_sel_file_btn.setToolTip(
            "Guarda el contenido del programa como archivo de MSX-DOS: .BIN (con su "
            "cabecera de BSAVE), .BAS (BASIC) o .ASC (texto)")
        self.save_all_btn.setToolTip("Guarda cada programa de la cinta como archivo MSX en una carpeta")
        self.save_sel_cas_btn.clicked.connect(self._save_selected_cas)
        self.save_sel_file_btn.clicked.connect(self._save_selected_file)
        self.save_all_btn.clicked.connect(self._save_all_files)
        self.to_player_btn.clicked.connect(self._send_to_player)
        self.discard_btn.clicked.connect(self._discard)
        lay.addLayout(row2)

        hint = QLabel(
            "<b>Conexión.</b> Salida de auriculares del casete (o del MSX) → entrada de "
            "<b>línea</b> del PC (mejor que la de micrófono), con un cable de audio. "
            "Para grabar desde el MSX: <code>CSAVE\"NOMBRE\"</code> (BASIC), "
            "<code>SAVE\"CAS:NOMBRE\"</code> (ASCII) o <code>BSAVE\"CAS:NOMBRE\",ini,fin,exec</code>. "
            "Ajusta el volumen para que el medidor llegue a la zona verde alta, "
            "sin tocar el rojo. Desactiva mejoras y ecualizadores del sistema.")
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)
        hint.setStyleSheet("color: #727a90; font-size: 11px;")
        self.hint_lbl = hint
        lay.addWidget(hint)

        self.refresh_devices()
        self._load_gain_for_device()
        self._set_buttons()

    # ------------------------------------------------------------------
    # Dispositivos
    # ------------------------------------------------------------------
    def refresh_devices(self):
        actual = self.input_combo.currentData()
        actual_id = bytes(actual.id()) if actual is not None else None
        self.input_combo.clear()
        self._inputs = available_input_devices()
        elegido = 0
        for i, d in enumerate(self._inputs):
            self.input_combo.addItem(d.description(), d)
            if actual_id is not None and bytes(d.id()) == actual_id:
                elegido = i
        if not self._inputs:
            self.input_combo.addItem("(sin entradas de audio)", None)
        else:
            self.input_combo.setCurrentIndex(elegido)

    def _device(self):
        return self.input_combo.currentData()

    # -- nivel de entrada (persistente) -----------------------------------
    def _device_key(self) -> str:
        d = self._device()
        if d is None:
            return ""
        try:
            return bytes(d.id()).hex()
        except Exception:  # noqa: BLE001
            return d.description()

    def _load_gain_for_device(self, *_):
        """Recupera el nivel que se dejó para esta entrada (o el último usado)."""
        st = _settings()
        key = self._device_key()
        valor = st.value(f"tape/input_volume/{key}", None) if key else None
        if valor is None:
            valor = st.value("tape/input_volume", DEFAULT_INPUT_VOLUME)
        try:
            valor = max(0, min(100, int(valor)))
        except (TypeError, ValueError):
            valor = DEFAULT_INPUT_VOLUME
        self.gain_slider.blockSignals(True)
        self.gain_slider.setValue(valor)
        self.gain_slider.blockSignals(False)
        self.gain_lbl.setText(f"{valor} %")
        self._apply_gain(valor)

    def _on_gain_changed(self, valor: int):
        self.gain_lbl.setText(f"{valor} %")
        st = _settings()
        st.setValue("tape/input_volume", valor)
        key = self._device_key()
        if key:
            st.setValue(f"tape/input_volume/{key}", valor)
        self._apply_gain(valor)

    def _apply_gain(self, valor: int):
        """Aplica el nivel a la entrada abierta (si la hay) y avisa si el
        sistema no lo respeta."""
        real = self._rec.set_volume(valor / 100.0)
        self._gain_ignored = real is not None and abs(real - valor / 100.0) > 0.03

    def input_volume(self) -> float:
        return self.gain_slider.value() / 100.0

    # ------------------------------------------------------------------
    # Grabación
    # ------------------------------------------------------------------
    def is_busy(self) -> bool:
        return self._rec.state() in ("armed", "recording") or self._job is not None

    def toggle_recording(self):
        st = self._rec.state()
        if st in ("armed", "recording"):
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if self._job is not None:
            return
        if self._device() is None:
            QMessageBox.warning(
                self, "Grabador",
                "No hay ninguna entrada de audio disponible. Conecta el cable o el "
                "adaptador USB y pulsa el botón ⟳.")
            return
        if not self._resolve_unsaved():
            return
        self._clear_result()
        self.monitor_btn.setChecked(False)
        try:
            self._rec.start(
                device=self._device(), sample_rate=self.rate_combo.currentData(),
                channel_mode=self.channel_combo.currentData(),
                armed=self.arm_chk.isChecked(),
                autostop_s=self.autostop_combo.currentData() or None,
                volume=self.input_volume())
        except (ValueError, RuntimeError) as e:
            QMessageBox.warning(self, "Grabador", f"No se pudo iniciar la grabación:\n{e}")
            return
        self._apply_gain(self.gain_slider.value())   # detecta si el sistema lo ignora

    def stop_recording(self):
        self._rec.stop()

    def _toggle_monitor(self, on: bool):
        if self._rec.state() in ("armed", "recording"):
            self.monitor_btn.setChecked(False)
            return
        if not on:
            self._rec.stop()
            return
        if self._device() is None or not self._resolve_unsaved():
            self.monitor_btn.setChecked(False)
            return
        try:
            self._rec.start(device=self._device(), sample_rate=self.rate_combo.currentData(),
                            channel_mode=self.channel_combo.currentData(), monitor_only=True,
                            volume=self.input_volume())
        except (ValueError, RuntimeError) as e:
            self.monitor_btn.setChecked(False)
            QMessageBox.warning(self, "Grabador", f"No se pudo abrir la entrada:\n{e}")
            return
        self._apply_gain(self.gain_slider.value())

    def shutdown(self):
        """Libera la entrada de audio (al cerrar la ventana)."""
        self._job_timer.stop()
        for sig, slot in ((self._rec.status_changed, self._on_status),
                          (self._rec.state_changed, self._on_state)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._rec.close()

    # ------------------------------------------------------------------
    # Señales del grabador
    # ------------------------------------------------------------------
    def _on_rate_adjusted(self, pedida: int, concedida: int):
        self._last_adjusted_msg = (
            f"La entrada no admite {pedida} Hz; se graba a {concedida} Hz.")

    def _on_state(self, state: str):
        self.recorder_state.emit(state)
        self.rec_btn.set_mode({"armed": "armed", "recording": "recording"}.get(state, "idle"))
        grabando = state in ("armed", "recording")
        self.meter.set_active(state in ("monitoring", "armed", "recording"))
        for w in (self.input_combo, self.channel_combo, self.rate_combo,
                  self.autostop_combo, self.arm_chk, self.refresh_btn):
            w.setEnabled(not grabando and state != "monitoring")
        if state == "armed":
            self.state_lbl.setText("● ARMADO — esperando señal de la cinta…")
            self.state_lbl.setStyleSheet(f"color: {WARN_AMBER};")
        elif state == "recording":
            self.state_lbl.setText("● GRABANDO")
            self.state_lbl.setStyleSheet(f"color: {REC_RED.name()};")
            self._was_recording = True
        elif state == "monitoring":
            self.state_lbl.setText("Probando nivel (no se está grabando)")
            self.state_lbl.setStyleSheet("color: #5aa0ff;")
        else:   # stopped
            self.monitor_btn.setChecked(False)
            self.info_lbl.setText("")
            if self._was_recording:
                self._was_recording = False
                self._finish_recording()
            else:
                self.state_lbl.setText("Listo para grabar")
                self.state_lbl.setStyleSheet("")
                self.advice_lbl.setText("")
        self._set_buttons()

    def _on_status(self, st):
        self.meter.feed(st.peak, st.clipped)
        state = st.state
        mins, secs = divmod(int(st.elapsed), 60)
        t = f"{mins}:{secs:02d}"

        # información en vivo
        senal = {"silence": "sin señal", "data": "datos", "pilot": "tono piloto"}[st.signal]
        if st.signal == "pilot" and st.baud_guess:
            senal += f" a {st.baud_guess} baudios"
        partes = [f"Canal: {st.channel}", f"Señal: {senal}"]
        if state == "recording":
            partes.insert(0, f"⏺ {t}")
            partes.append(f"Bloques: {st.segments}")
            if st.silence_s >= 1.0:
                partes.append(f"silencio {st.silence_s:.0f} s")
        elif state == "armed":
            partes.append(f"sin señal desde hace {st.silence_s:.0f} s" if st.silence_s >= 1 else "")
        self.info_lbl.setText("  ·  ".join(p for p in partes if p))

        # avisos de nivel
        aviso = ""
        peak_db = LevelMeter.to_db(st.peak)
        if st.clipped:
            aviso = ("⚠ La señal satura: baja el «Nivel de entrada» (o el volumen del "
                     "casete/MSX).")
        elif st.signal != "silence" and st.peak < 0.10:
            aviso = ("⚠ La señal es muy baja: sube el «Nivel de entrada» (o el volumen del "
                     "casete/MSX).")
        elif state in ("armed", "monitoring") and st.silence_s > 12 and peak_db < -50:
            aviso = ("No llega señal. Comprueba el cable, la entrada elegida "
                     "(línea mejor que micrófono) y que la cinta esté sonando.")
        if self._gain_ignored and state != "stopped" and (st.clipped or st.peak < 0.10):
            aviso = (aviso + "  " if aviso else "") + (
                "Esta entrada no deja ajustar el nivel desde la aplicación: usa el control "
                "de volumen de captura del sistema.")
        if self._last_adjusted_msg and state != "stopped":
            aviso = (aviso + "  " if aviso else "") + self._last_adjusted_msg
        self.advice_lbl.setText(aviso)

        if state == "recording":
            self.state_lbl.setText(f"● GRABANDO  {t}")
            self._update_live_table(st.entries)
        level = int(min(100, st.peak * 100))
        title = ""
        if st.entries:
            nombres = [e.name for e in st.entries if e.name]
            title = "  ·  ".join(dict.fromkeys(nombres))
        self.live_update.emit(st.elapsed if state == "recording" else 0.0, level, title)

    # ------------------------------------------------------------------
    # Final de la grabación
    # ------------------------------------------------------------------
    def _finish_recording(self):
        sess = self._rec.session()
        if sess is None or sess.duration() < 0.6:
            self.state_lbl.setText("No se grabó nada")
            self.state_lbl.setStyleSheet("")
            self.advice_lbl.setText(
                "No se capturó señal. Comprueba la entrada elegida, el cable y el volumen "
                "(el botón «Probar nivel» ayuda a ajustarlo).")
            return
        auto = sess.status().auto_stopped
        self.state_lbl.setText("Analizando la grabación…")
        self.state_lbl.setStyleSheet("color: #5aa0ff;")

        # El audio queda en memoria hasta que se le da nombre (se pregunta al
        # terminar el análisis, para poder proponer el título del programa).
        self._unsaved = True
        self._wav_path = ""

        nivel = sess.level_report()
        consejo = nivel.advice()
        if consejo:
            self.advice_lbl.setText("⚠ " + consejo)
        else:
            self.advice_lbl.setText("")
        self._auto_stopped = auto

        self.busy.setValue(0)
        self.busy.show()
        self._job = _Job(lambda cb: sess.decode(cb))
        self._job_timer.start()
        self._set_buttons()

    def _poll_job(self):
        if self._job is None:
            self._job_timer.stop()
            return
        self.busy.setValue(int(self._job.progress * 1000))
        if not self._job.done():
            return
        job, self._job = self._job, None
        self._job_timer.stop()
        self.busy.hide()
        try:
            self._result = job.result()
        except Exception as e:  # noqa: BLE001
            self._result = None
            self.state_lbl.setText("No se pudo analizar la grabación")
            self.advice_lbl.setText(f"Error: {e}")
            self._set_buttons()
            QTimer.singleShot(0, self._prompt_save_wav)
            return
        self._cas = self._result.cas
        self._entries = tc.parse_tape(self._cas)
        self._fill_table(self._entries, final=True)
        self._summarize()
        self._set_buttons()
        QTimer.singleShot(0, self._prompt_save_wav)

    def _mark_saved(self, path: str):
        self._wav_path = path
        self._unsaved = False
        self.advice_lbl.setText(self.advice_lbl.text().replace(UNSAVED_MSG, "").strip())

    def _resolve_unsaved(self) -> bool:
        """Antes de grabar otra vez: ofrece guardar el audio pendiente.
        Devuelve False si el usuario cancela."""
        if not self.has_unsaved():
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Grabador")
        box.setText("La grabación anterior no está guardada.")
        box.setInformativeText("Si grabas de nuevo se perderá el audio.")
        guardar = box.addButton("Guardar el audio…", QMessageBox.AcceptRole)
        descartar = box.addButton("Descartar", QMessageBox.DestructiveRole)
        box.addButton("Cancelar", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is guardar:
            self._prompt_save_wav()
            return not self.has_unsaved()
        if box.clickedButton() is descartar:
            self._unsaved = False
            return True
        return False

    def has_unsaved(self) -> bool:
        """True si hay una grabación en memoria a la que no se ha dado nombre."""
        sess = self._rec.session()
        return self._unsaved and sess is not None and sess.duration() > 0

    def _prompt_save_wav(self):
        """Pide el nombre del WAV recién grabado (propone el título del programa).

        Si se cancela, el audio sigue en memoria y se puede guardar con el
        botón «WAV»; al cerrar o grabar de nuevo se avisa antes de perderlo.
        """
        if not self.has_unsaved():
            return
        if self._guardando_wav:
            return
        self._guardando_wav = True
        try:
            path = self._ask_path("Guardar el audio grabado — ponle nombre",
                                  self._suggest_base() + ".wav")
            if path and self._write(path, self._rec.session().wav_bytes()):
                self._mark_saved(path)
                self.info_lbl.setText(
                    (self.info_lbl.text() + "  ·  " if self.info_lbl.text() else "")
                    + f"Audio guardado: {path}")
            else:
                self.advice_lbl.setText(
                    (self.advice_lbl.text() + "  " if self.advice_lbl.text() else "")
                    + UNSAVED_MSG)
        finally:
            self._guardando_wav = False
            self._set_buttons()

    def _summarize(self):
        r = self._result
        n = len(self._entries)
        dur = r.duration_s
        if not r.cas:
            self.state_lbl.setText("La grabación no se reconoce como cinta MSX")
            self.state_lbl.setStyleSheet(f"color: {WARN_AMBER};")
            self.advice_lbl.setText(
                (self.advice_lbl.text() + "  " if self.advice_lbl.text() else "")
                + " ".join(r.warnings))
            return
        baud = r.standard_baud
        calidad = "sin errores" if r.framing_errors == 0 else f"{r.framing_errors} errores de trama"
        self.state_lbl.setText(
            f"✔ {n} elemento(s) leídos a {baud} baudios — {calidad}")
        self.state_lbl.setStyleSheet(
            f"color: {OK_GREEN};" if r.framing_errors == 0 else f"color: {WARN_AMBER};")
        extra = []
        if getattr(self, "_auto_stopped", False):
            extra.append("La grabación se detuvo sola por el silencio.")
        if r.framing_errors:
            extra.append("Hay errores: repite la grabación con menos volumen o prueba otra "
                         "entrada; el programa puede no cargar.")
        self.info_lbl.setText(f"Duración {dur:.0f} s  ·  " + "  ·  ".join(extra))
        if r.framing_errors:
            self.advice_lbl.setText(
                (self.advice_lbl.text() + "  " if self.advice_lbl.text() else "")
                + "⚠ " + " ".join(r.warnings))
        if self._entries:
            self.table.selectRow(0)

    # ------------------------------------------------------------------
    # Tabla
    # ------------------------------------------------------------------
    def _update_live_table(self, entries):
        sig = (len(entries), entries[-1].size if entries else 0)
        if sig == self._shown_entries:
            return
        self._shown_entries = sig
        self._fill_table(entries, final=False)

    def _entry_errors(self, e: tc.TapeEntry) -> tuple[int, float]:
        """(errores, baudios) de los bloques del programa, según la decodificación final."""
        if self._result is None:
            return 0, 0.0
        errs = 0
        bauds = []
        for b in self._result.blocks:
            if e.cas_start <= b.cas_offset < e.cas_end:
                errs += b.framing_errors + (b.orphan_cycles if b.orphan_cycles > 2 else 0)
                bauds.append(b.baud)
        return errs, (sum(bauds) / len(bauds) if bauds else 0.0)

    def _fill_table(self, entries, final: bool):
        sel = self.table.currentRow()
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            errs, baud = self._entry_errors(e) if final else (0, 0.0)
            nombre = e.name if e.name else "(datos del cargador)"
            valores = [
                str(e.index + 1), nombre, e.kind_label, f"{e.size:,}".replace(",", "."),
                tc.hex16(e.start), tc.hex16(e.end), tc.hex16(e.exec_addr),
                f"{td.snap_baud(baud)}" if baud else "…",
                ("leyendo…" if not final else ("✔ limpio" if errs == 0 else f"⚠ {errs} errores")),
            ]
            for col, v in enumerate(valores):
                it = QTableWidgetItem(v)
                if col in (0, 3, 4, 5, 6, 7):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 8 and final:
                    it.setForeground(QColor(OK_GREEN if errs == 0 else WARN_AMBER))
                if e.notes and col == 1:
                    it.setToolTip("\n".join(e.notes))
                self.table.setItem(row, col, it)
        if sel >= 0 and sel < len(entries):
            self.table.selectRow(sel)

    def _selected_entry(self) -> tc.TapeEntry | None:
        row = self.table.currentRow()
        if self._entries and 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def _on_select(self):
        self._set_buttons()
        e = self._selected_entry()
        if e is None:
            return
        lines = [f"{e.display_name} — {e.kind_label}, {e.size} bytes"]
        if e.kind == "bin" and e.start is not None:
            lines.append(f"Carga en {tc.hex16(e.start)}–{tc.hex16(e.end)}, "
                         f"ejecución en {tc.hex16(e.exec_addr)}")
        if e.kind == "ascii":
            txt = e.body.decode("latin-1", errors="replace").replace("\r\n", "\n")
            lines.append("")
            lines.extend(txt.splitlines()[:6])
        else:
            lines.append("Primeros bytes: " + " ".join(f"{b:02X}" for b in e.body[:24]))
        lines.extend(e.notes)
        self.detail.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # Guardado
    # ------------------------------------------------------------------
    def _suggest_base(self) -> str:
        nombres = [e.name for e in self._entries if e.name]
        if nombres:
            return "".join(c for c in nombres[0] if c.isalnum() or c in "_- ").strip() or "cinta"
        return time.strftime("cinta_%Y%m%d_%H%M")

    def _ask_path(self, titulo: str, nombre: str, carpeta: str | None = None) -> str | None:
        carpeta = carpeta or ws.folder("tapes")
        os.makedirs(carpeta, exist_ok=True)
        return elegir_archivo_guardar(self, carpeta_inicial=carpeta,
                                      nombre_sugerido=nombre, titulo=titulo)

    def _write(self, path: str, data: bytes) -> bool:
        try:
            with open(path, "wb") as fh:
                fh.write(data)
        except OSError as e:
            QMessageBox.warning(self, "Grabador", f"No se pudo guardar:\n{e}")
            return False
        return True

    def _save_wav(self):
        sess = self._rec.session()
        if sess is None or sess.duration() <= 0:
            return
        path = self._ask_path("Guardar el audio grabado", self._suggest_base() + ".wav")
        if path and self._write(path, sess.wav_bytes()):
            self._mark_saved(path)
            self.info_lbl.setText(f"Guardado: {path}")

    def _save_cas(self, data: bytes | None, nombre: str | None = None):
        data = self._cas if data is None else data
        if not data:
            return
        path = self._ask_path("Guardar la cinta como CAS", (nombre or self._suggest_base()) + ".cas")
        if path and self._write(path, data):
            self.info_lbl.setText(f"Guardado: {path}")

    def _save_tsx(self):
        if not self._cas:
            return
        try:
            baud = self._result.standard_baud if self._result else 1200
            tsx = tt.cas_to_tsx(self._cas, baud=baud if baud in (1200, 2400) else 1200)
        except ValueError as e:
            QMessageBox.warning(self, "Grabador", str(e))
            return
        path = self._ask_path("Guardar la cinta como TSX", self._suggest_base() + ".tsx")
        if path and self._write(path, tsx):
            self.info_lbl.setText(f"Guardado: {path}")

    def _save_selected_cas(self):
        e = self._selected_entry()
        if e is None:
            QMessageBox.information(self, "Grabador", "Selecciona un programa de la lista.")
            return
        self._save_cas(tc.entry_cas(self._cas, e), e.name.strip() or f"programa{e.index + 1}")

    def _save_selected_file(self):
        e = self._selected_entry()
        if e is None:
            QMessageBox.information(self, "Grabador", "Selecciona un programa de la lista.")
            return
        nombre = tc.suggested_filename(e)
        path = self._ask_path("Extraer como archivo MSX", nombre)
        if path and self._write(path, tc.entry_file(e)):
            self.info_lbl.setText(f"Guardado: {path}")

    def _save_all_files(self):
        if not self._entries:
            return
        destino = choose_directory(self)
        if not destino:
            return
        usados: set[str] = set()
        n = 0
        for e in self._entries:
            if not e.body and e.kind != "bin":
                continue
            nombre = tc.suggested_filename(e, usados)
            if self._write(os.path.join(destino, nombre), tc.entry_file(e)):
                n += 1
        self.info_lbl.setText(f"{n} archivo(s) extraídos en {destino}")

    def _send_to_player(self):
        if not self._cas:
            return
        baud = self._result.standard_baud if self._result else 0
        self.cas_ready.emit(self._cas, self._suggest_base(), baud)

    def _discard(self):
        if self._cas or self.has_unsaved():
            aviso = ("¿Descartar el resultado?"
                     + ("\n\nEl audio grabado NO está guardado y se perderá."
                        if self.has_unsaved() else ""))
            r = QMessageBox.question(self, "Grabador", aviso)
            if r != QMessageBox.Yes:
                return
        self._clear_result()
        self.state_lbl.setText("Listo para grabar")
        self.state_lbl.setStyleSheet("")

    def _clear_result(self):
        self._result = None
        self._entries = []
        self._cas = b""
        self._wav_path = ""
        self._unsaved = False
        self._shown_entries = -1
        self._last_adjusted_msg = ""
        self.table.setRowCount(0)
        self.detail.clear()
        self.advice_lbl.setText("")
        self.info_lbl.setText("")
        self._set_buttons()

    def _set_buttons(self):
        grabando = self._rec.state() in ("armed", "recording")
        ocupado = grabando or self._job is not None
        sess = self._rec.session()
        hay_audio = sess is not None and sess.duration() > 0 and not grabando
        hay_cas = bool(self._cas) and not ocupado
        self.save_wav_btn.setEnabled(hay_audio and not ocupado)
        self.save_cas_btn.setEnabled(hay_cas)
        self.save_tsx_btn.setEnabled(hay_cas)
        sel = self._selected_entry() is not None
        self.save_sel_cas_btn.setEnabled(hay_cas and sel)
        self.save_sel_file_btn.setEnabled(hay_cas and sel)
        self.save_all_btn.setEnabled(hay_cas)
        self.to_player_btn.setEnabled(hay_cas)
        self.discard_btn.setEnabled(not ocupado and (hay_audio or hay_cas))
        self.monitor_btn.setEnabled(not ocupado)
        self.rec_btn.setEnabled(self._job is None)
        # la ayuda de conexión solo estorba cuando ya hay algo que mostrar
        self.hint_lbl.setVisible(not ocupado and not self._cas)
