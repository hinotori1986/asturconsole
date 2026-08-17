"""Pletina de casete animada para el reproductor de cintas MSX.

Inspirada en los data recorders de la época (NEC PC-6081 / DR-310 y
similares): ventana de casete con las dos bobinas girando, cuentavueltas
mecánico de tres dígitos, botonera tipo piano donde la tecla activa se queda
hundida e iluminada, y piloto de actividad.

Detalle cuidado: el diámetro del rollo de cinta cambia según el avance —la
bobina emisora se vacía y la receptora se llena—, y la velocidad angular
aumenta a medida que una bobina adelgaza, igual que en un casete real.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QWidget

# Paleta coherente con el resto de la aplicación
COL_FONDO = QColor("#0f111a")
COL_CARCASA = QColor("#1c2029")
COL_CARCASA_ALTA = QColor("#262b36")
COL_BORDE = QColor("#39404f")
COL_VENTANA = QColor("#080a10")
COL_CINTA = QColor("#3a2c22")
COL_CINTA_BORDE = QColor("#5a4636")
COL_TEXTO = QColor("#8892a8")

BOTONES = ["REC", "PLAY", "REW", "FF", "STOP", "PAUSE"]
# Teclas que hacen algo. Las demás son decorativas: se dibujan porque el
# aparato original las tenía, pero no tienen función aquí.
HABILITADOS = {"REC", "PLAY", "REW", "STOP", "PAUSE"}

# Cada cuántos segundos se anima el rótulo del juego, y cuánto dura el efecto
EFFECT_PERIOD = 20.0
EFFECT_DURATION = 1.6


class TapeDeckWidget(QWidget):
    """Pletina animada e interactiva.

    Las teclas dibujadas son los controles reales: al pulsarlas se emite
    `button_pressed` con el nombre ("PLAY", "STOP", "PAUSE"). Así no hace
    falta duplicar los botones fuera del widget, que además tapaban la
    propia pletina.
    """

    button_pressed = Signal(str)

    def __init__(self, accent: str = "#3ef29a", parent=None):
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.setMinimumWidth(520)
        self.setCursor(Qt.PointingHandCursor)
        self._button_rects: dict[str, QRectF] = {}
        self._hover: str | None = None
        self.setMouseTracking(True)
        self._accent = QColor(accent)
        self._state = "stopped"          # stopped | playing | paused | recording
        self._elapsed = 0.0
        self._total = 0.0
        self._angle = 0.0                # ángulo de giro acumulado (grados)
        self._counter = 0                # cuentavueltas de tres dígitos
        self._blink = False
        self._input_level = 0        # nivel real de entrada al grabar (0-100)
        self._title = ""             # nombre del juego bajo las bobinas
        self._scroll = 0.0           # desplazamiento del rótulo
        self._effect_t = 0.0         # tiempo para los efectos periódicos
        self._effect_phase = 0.0     # 0 = sin efecto; >0 efecto en curso
        self._finished = False       # cinta llegada al final
        self._rewinding = False
        self._rewind_from = 0
        self._rewind_steps = 0
        self._rewind_step = 0

        self._timer = QTimer(self)
        self._timer.setInterval(50)      # 20 fotogramas por segundo
        self._timer.timeout.connect(self._tick)

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_blink)

    # -- API ---------------------------------------------------------------
    def set_accent(self, color: str):
        self._accent = QColor(color)
        self.update()

    def rewind(self, duration_ms: int = 900):
        """Animación breve de rebobinado: las bobinas giran al revés y el
        cuentavueltas cae hasta cero, como al pulsar REW en el aparato."""
        self._rewinding = True
        self._rewind_from = self._counter
        self._rewind_steps = max(1, duration_ms // 50)
        self._rewind_step = 0
        self._timer.start()
        self.update()

    def set_state(self, state: str):
        self._rewinding = False
        if state in ("playing", "recording"):
            self._finished = False
        self._state = state
        if state in ("playing", "recording"):
            self._timer.start()
            self._blink_timer.start()
        else:
            self._timer.stop()
            self._blink_timer.stop()
            self._blink = False
            # Si la cinta ha llegado al final, se conserva la imagen del
            # final (contador al máximo, bobina derecha llena). Solo se
            # reinicia cuando se detiene a mitad o se rebobina.
            if state == "stopped" and not self._finished:
                self._angle = 0.0
                self._counter = 0
                self._elapsed = 0.0
        self.update()

    def set_title(self, title: str):
        """Nombre del archivo o juego que se muestra bajo las bobinas."""
        self._title = title or ""
        self._scroll = 0.0
        self.update()

    def set_finished(self, finished: bool = True):
        """Marca que la cinta ha llegado al final: las bobinas se detienen,
        el contador se queda al máximo y aparece el cartel de fin."""
        self._finished = finished
        if finished:
            self._timer.stop()
            self._blink_timer.stop()
            self._blink = False
            if self._total > 0:
                self._elapsed = self._total
            self._counter = 999
        self.update()

    def set_input_level(self, level: int):
        """Nivel de la señal de entrada durante la grabación (0-100)."""
        self._input_level = max(0, min(100, level))
        self.update()

    def set_progress(self, elapsed: float, total: float):
        self._elapsed = elapsed
        self._total = total
        if total > 0:
            # El cuentavueltas avanza de forma no lineal, como el mecánico
            # real: gira más despacio al principio (bobina receptora vacía).
            frac = max(0.0, min(1.0, elapsed / total))
            self._counter = int(999 * (frac ** 0.85)) % 1000
        else:
            # Grabando no se conoce la duración total: el contador avanza con
            # el tiempo, a un ritmo parecido al de un contador mecánico.
            self._counter = int(elapsed * 4.2) % 1000
        self.update()

    # -- animación ---------------------------------------------------------
    def _tick(self):
        if self._rewinding:
            # Giro rápido en sentido contrario mientras se rebobina
            self._angle = (self._angle - 900 * 0.05) % 360
            self._rewind_step += 1
            avance = self._rewind_step / self._rewind_steps
            self._counter = max(0, int(self._rewind_from * (1 - avance)))
            self._elapsed = max(0.0, self._elapsed * (1 - avance))
            if self._rewind_step >= self._rewind_steps:
                self._rewinding = False
                self._counter = 0
                self._elapsed = 0.0
                self._angle = 0.0
                self._timer.stop()
            self.update()
            return
        # La velocidad de giro sube conforme la bobina emisora adelgaza
        frac = self._fraction()
        velocidad = 220 + 160 * frac
        self._angle = (self._angle + velocidad * 0.05) % 360

        # Rótulo del juego: desplazamiento continuo y un efecto cada 20 s
        self._scroll += 0.9
        self._effect_t += 0.05
        if self._effect_t >= EFFECT_PERIOD:
            self._effect_t = 0.0
            self._effect_phase = 1.0
        if self._effect_phase > 0:
            self._effect_phase = max(0.0, self._effect_phase - 0.05 / EFFECT_DURATION)
        self.update()

    def _toggle_blink(self):
        self._blink = not self._blink
        self.update()

    def _fraction(self) -> float:
        if self._total <= 0:
            # Sin duración conocida (grabación): media carga, para que las
            # bobinas giren a un ritmo constante y creíble.
            return 0.5 if self._state == "recording" else 0.0
        return max(0.0, min(1.0, self._elapsed / self._total))

    # -- dibujo ------------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, COL_FONDO)

        # --- carcasa ---
        carcasa = QRectF(4, 4, w - 8, h - 8)
        grad = QLinearGradient(0, carcasa.top(), 0, carcasa.bottom())
        grad.setColorAt(0, COL_CARCASA_ALTA)
        grad.setColorAt(1, COL_CARCASA)
        p.setBrush(QBrush(grad))
        p.setPen(QPen(COL_BORDE, 1.5))
        p.drawRoundedRect(carcasa, 8, 8)

        margen = 16
        alto_botones = 40
        alto_rotulo = 20
        ventana = QRectF(margen, 40, w - 2 * margen - 108,
                          h - 40 - alto_botones - 16 - alto_rotulo)
        self._draw_cassette(p, ventana)
        if self._finished:
            self._draw_finished_banner(p, ventana)
        self._draw_title(p, QRectF(ventana.left(), ventana.bottom() + 3,
                                    ventana.width(), alto_rotulo - 4))
        self._draw_counter(p, QRectF(margen, 12, 92, 24))
        self._draw_progress(p, QRectF(margen + 100, 12, w - margen - 100 - 116, 24))
        self._draw_led(p, QPointF(w - 78, 26))
        self._draw_level(p, QRectF(w - margen - 96, 46, 96, h - 46 - alto_botones - 16))
        self._draw_buttons(p, QRectF(margen, h - alto_botones - 10, w - 2 * margen, alto_botones))
        p.end()

    # -- piezas ------------------------------------------------------------
    def _draw_cassette(self, p: QPainter, r: QRectF):
        p.setBrush(COL_VENTANA)
        p.setPen(QPen(COL_BORDE, 1.4))
        p.drawRoundedRect(r, 5, 5)

        cy = r.center().y()
        radio_max = min(r.height() * 0.34, r.width() * 0.17)
        sep = r.width() * 0.24
        izq = QPointF(r.center().x() - sep, cy)
        der = QPointF(r.center().x() + sep, cy)

        frac = self._fraction()
        # Radio de cinta en cada bobina: la emisora se vacía, la receptora crece
        r_min = radio_max * 0.42
        r_izq = radio_max - (radio_max - r_min) * frac
        r_der = r_min + (radio_max - r_min) * frac

        # Tramo de cinta visible entre bobinas
        p.setPen(QPen(COL_CINTA_BORDE, 2))
        p.drawLine(QPointF(izq.x(), cy - r_izq), QPointF(der.x(), cy - r_der))
        p.drawLine(QPointF(izq.x(), cy + r_izq), QPointF(der.x(), cy + r_der))

        self._draw_reel(p, izq, r_izq, radio_max, self._angle)
        self._draw_reel(p, der, r_der, radio_max, -self._angle)

    def _draw_reel(self, p: QPainter, centro: QPointF, radio: float,
                   radio_max: float, angulo: float):
        # rollo de cinta
        p.setBrush(COL_CINTA)
        p.setPen(QPen(COL_CINTA_BORDE, 1.2))
        p.drawEllipse(centro, radio, radio)

        # núcleo dentado, que es lo que hace visible el giro
        nucleo = radio_max * 0.42
        p.save()
        p.translate(centro)
        p.rotate(angulo)
        p.setBrush(QColor("#12141c"))
        p.setPen(QPen(self._accent, 1.4))
        p.drawEllipse(QPointF(0, 0), nucleo, nucleo)

        p.setBrush(self._accent)
        p.setPen(Qt.NoPen)
        dientes = 6
        for i in range(dientes):
            ang = math.radians(i * 360 / dientes)
            x = math.cos(ang) * nucleo * 0.62
            y = math.sin(ang) * nucleo * 0.62
            p.drawEllipse(QPointF(x, y), nucleo * 0.16, nucleo * 0.16)
        p.restore()

        # marca de referencia sobre el rollo: refuerza la sensación de giro
        p.save()
        p.translate(centro)
        p.rotate(angulo * 0.35)
        p.setPen(QPen(COL_CINTA_BORDE, 1.6))
        p.drawLine(QPointF(0, -radio * 0.94), QPointF(0, -radio * 0.62))
        p.restore()

    def _draw_counter(self, p: QPainter, r: QRectF):
        p.setBrush(QColor("#05070c"))
        p.setPen(QPen(COL_BORDE, 1.2))
        p.drawRoundedRect(r, 3, 3)

        texto = f"{self._counter:03d}"
        ancho = r.width() / 3
        f = QFont("monospace")
        f.setStyleHint(QFont.Monospace)
        f.setPointSizeF(max(9.0, r.height() * 0.62))
        f.setBold(True)
        p.setFont(f)
        for i, ch in enumerate(texto):
            celda = QRectF(r.left() + i * ancho, r.top(), ancho, r.height())
            p.setPen(QPen(COL_BORDE.darker(120), 1))
            if i:
                p.drawLine(celda.left(), celda.top() + 3, celda.left(), celda.bottom() - 3)
            p.setPen(self._accent if self._state != "stopped" else COL_TEXTO)
            p.drawText(celda, Qt.AlignCenter, ch)

    def _draw_finished_banner(self, p: QPainter, r: QRectF):
        """Cartel sobre la ventana del casete al terminar la reproducción."""
        texto = "CARGA FINALIZADA"
        f = QFont("monospace")
        f.setStyleHint(QFont.Monospace)
        f.setPointSizeF(max(10.0, r.height() * 0.17))
        f.setBold(True)
        p.setFont(f)

        ancho = p.fontMetrics().horizontalAdvance(texto) + 34
        alto = p.fontMetrics().height() + 16
        caja = QRectF(r.center().x() - ancho / 2, r.center().y() - alto / 2, ancho, alto)

        p.setBrush(QColor(10, 11, 16, 225))
        p.setPen(QPen(self._accent, 2))
        p.drawRoundedRect(caja, 6, 6)
        p.setPen(self._accent)
        p.drawText(caja, Qt.AlignCenter, texto)

    def _draw_title(self, p: QPainter, r: QRectF):
        """Rótulo con el nombre del juego. Si no cabe, se desplaza en bucle;
        cada cierto tiempo hace un destello de color, como los marcadores de
        las máquinas de la época."""
        if not self._title:
            return

        p.save()
        p.setClipRect(r)

        f = QFont("monospace")
        f.setStyleHint(QFont.Monospace)
        f.setPointSizeF(max(8.0, r.height() * 0.66))
        f.setBold(True)
        p.setFont(f)

        ancho_texto = p.fontMetrics().horizontalAdvance(self._title)
        color = self._active_color()
        if self._effect_phase > 0:
            # Destello: alterna entre el acento y un blanco brillante, y da un
            # leve latido de intensidad
            fase = self._effect_phase
            if int(fase * 8) % 2 == 0:
                color = QColor("#ffffff")
            else:
                color = QColor(color).lighter(140)
        p.setPen(color)

        if ancho_texto <= r.width():
            p.drawText(r, Qt.AlignCenter, self._title)
        else:
            # Desplazamiento continuo con separador, para que el bucle no corte
            texto = self._title + "     ·     "
            paso = p.fontMetrics().horizontalAdvance(texto)
            x = r.left() - (self._scroll % paso)
            while x < r.right():
                p.drawText(QRectF(x, r.top(), paso, r.height()),
                           Qt.AlignVCenter | Qt.AlignLeft, texto)
                x += paso
        p.restore()

    def _draw_progress(self, p: QPainter, r: QRectF):
        """Barra de avance con un pequeño personaje que camina sobre ella."""
        if r.width() < 60:
            return
        carril = QRectF(r.left(), r.center().y() + 2, r.width(), 6)
        p.setBrush(QColor("#0a0b10"))
        p.setPen(QPen(COL_BORDE, 1))
        p.drawRoundedRect(carril, 3, 3)

        frac = self._fraction() if self._total > 0 else 0.0
        if frac > 0:
            hecho = QRectF(carril.left(), carril.top(), carril.width() * frac, carril.height())
            p.setBrush(self._active_color())
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(hecho, 3, 3)

        # El personaje avanza con el progreso, sobre el carril
        x = carril.left() + carril.width() * frac
        self._draw_penguin(p, QPointF(x, carril.top() - 2), caminando=(self._state == "playing"))

    def _draw_penguin(self, p: QPainter, base: QPointF, caminando: bool):
        """Pingüino diminuto, guiño a los juegos de pingüinos de MSX."""
        alto = 13.0
        ancho = alto * 0.72
        x = base.x() - ancho / 2
        y = base.y() - alto

        # el balanceo al caminar se deriva del ángulo de las bobinas
        paso = math.sin(math.radians(self._angle * 3)) if caminando else 0.0

        p.save()
        p.setPen(Qt.NoPen)

        # patas
        p.setBrush(QColor("#ffb454"))
        p.drawRoundedRect(QRectF(x + ancho * 0.16 + paso * 0.8, y + alto - 2.4,
                                  ancho * 0.28, 2.4), 1, 1)
        p.drawRoundedRect(QRectF(x + ancho * 0.56 - paso * 0.8, y + alto - 2.4,
                                  ancho * 0.28, 2.4), 1, 1)

        # cuerpo
        p.setBrush(QColor("#101218"))
        p.drawEllipse(QRectF(x, y, ancho, alto - 2))

        # barriga
        p.setBrush(QColor("#f2f5fa"))
        p.drawEllipse(QRectF(x + ancho * 0.22, y + alto * 0.28,
                              ancho * 0.56, alto * 0.55))

        # pico
        p.setBrush(QColor("#ffb454"))
        pico = QPainterPath()
        pico.moveTo(x + ancho * 0.5, y + alto * 0.30)
        pico.lineTo(x + ancho * 0.5 + 3.2, y + alto * 0.38)
        pico.lineTo(x + ancho * 0.5, y + alto * 0.46)
        pico.closeSubpath()
        p.drawPath(pico)

        # ojo
        p.setBrush(QColor("#f2f5fa"))
        p.drawEllipse(QPointF(x + ancho * 0.62, y + alto * 0.24), 1.5, 1.5)
        p.setBrush(QColor("#101218"))
        p.drawEllipse(QPointF(x + ancho * 0.66, y + alto * 0.24), 0.7, 0.7)
        p.restore()

    def _draw_led(self, p: QPainter, centro: QPointF):
        encendido = self._state in ("playing", "recording") and not self._blink
        color = self._active_color() if encendido else QColor("#1e2430")
        p.setBrush(color)
        p.setPen(QPen(COL_BORDE, 1.2))
        p.drawEllipse(centro, 5, 5)
        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        p.setPen(COL_TEXTO)
        p.drawText(QRectF(centro.x() - 22, centro.y() + 7, 44, 12),
                   Qt.AlignCenter, "BUSY")

    def _draw_level(self, p: QPainter, r: QRectF):
        """Indicador de nivel, guiño al LOAD LEVEL de los data recorders."""
        p.setBrush(QColor("#151922"))
        p.setPen(QPen(COL_BORDE, 1.2))
        p.drawRoundedRect(r, 4, 4)

        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        p.setPen(COL_TEXTO)
        p.drawText(QRectF(r.left(), r.top() + 3, r.width(), 12),
                   Qt.AlignCenter, "LOAD LEVEL")

        n = 10
        barra_h = 6
        hueco = 3
        total = n * barra_h + (n - 1) * hueco
        y0 = r.center().y() - total / 2 + 6
        activo = self._state in ("playing", "recording")
        # Al grabar se muestra el nivel REAL de la señal de entrada; al
        # reproducir, un nivel simulado que da sensación de señal viva.
        nivel = 0
        if self._state == "recording":
            nivel = round(self._input_level / 100 * n)
        elif activo:
            nivel = int(6 + 3 * abs(math.sin(math.radians(self._angle * 2))))
        for i in range(n):
            y = y0 + i * (barra_h + hueco)
            encendida = activo and (n - i) <= nivel
            p.setBrush(self._active_color() if encendida else QColor("#222836"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(r.left() + 12, y, r.width() - 24, barra_h), 2, 2)

    def _active_color(self) -> QColor:
        """Durante la grabación, el color activo es el rojo del REC."""
        return QColor("#ff5340") if self._state == "recording" else self._accent

    def _draw_buttons(self, p: QPainter, r: QRectF):
        n = len(BOTONES)
        hueco = 6
        ancho = (r.width() - hueco * (n - 1)) / n
        if self._rewinding:
            activo = "REW"
        else:
            activo = {"playing": "PLAY", "paused": "PAUSE", "stopped": "STOP",
                      "recording": "REC"}.get(self._state)

        f = QFont()
        f.setPointSize(7)
        f.setBold(True)
        p.setFont(f)

        self._button_rects = {}
        for i, nombre in enumerate(BOTONES):
            x = r.left() + i * (ancho + hueco)
            self._button_rects[nombre] = QRectF(x, r.top(), ancho, r.height() - 8)
            pulsado = nombre == activo
            resaltado = nombre == self._hover and nombre in HABILITADOS
            # La tecla hundida se dibuja desplazada y con menos altura,
            # como una tecla de piano de las pletinas mecánicas.
            desplazamiento = 3 if pulsado else 0
            cuerpo = QRectF(x, r.top() + desplazamiento, ancho, r.height() - 8 - desplazamiento)

            grad = QLinearGradient(0, cuerpo.top(), 0, cuerpo.bottom())
            if pulsado:
                grad.setColorAt(0, QColor("#2b3242"))
                grad.setColorAt(1, QColor("#1a1f29"))
            else:
                grad.setColorAt(0, QColor("#39404f"))
                grad.setColorAt(1, QColor("#242a35"))
            p.setBrush(QBrush(grad))
            if pulsado:
                borde, grosor = self._active_color(), 1.6
            elif resaltado:
                borde, grosor = self._accent.lighter(140), 1.3
            else:
                borde, grosor = COL_BORDE, 1.0
            p.setPen(QPen(borde, grosor))
            p.drawRoundedRect(cuerpo, 3, 3)

            # franja superior de color: roja en REC, acento en la tecla activa
            franja = QRectF(cuerpo.left() + 3, cuerpo.top() + 3, cuerpo.width() - 6, 3)
            if nombre == "REC":
                p.setBrush(QColor("#ff5340"))
            elif pulsado:
                p.setBrush(self._active_color())
            else:
                p.setBrush(QColor("#4a5262"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(franja, 1.5, 1.5)

            if pulsado:
                color_texto = self._active_color()
            elif nombre in HABILITADOS:
                color_texto = COL_TEXTO.lighter(130) if resaltado else COL_TEXTO
            else:
                color_texto = COL_TEXTO.darker(140)     # tecla decorativa
            p.setPen(color_texto)
            p.drawText(QRectF(cuerpo.left(), cuerpo.bottom() - 14, cuerpo.width(), 12),
                       Qt.AlignCenter, nombre)

    # -- interacción -------------------------------------------------------
    def _button_at(self, pos) -> str | None:
        for nombre, rect in self._button_rects.items():
            if rect.contains(pos):
                return nombre if nombre in HABILITADOS else None
        return None

    def mouseMoveEvent(self, event):
        nombre = self._button_at(event.position())
        if nombre != self._hover:
            self._hover = nombre
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        nombre = self._button_at(event.position())
        if nombre:
            self.button_pressed.emit(nombre)
        super().mousePressEvent(event)
