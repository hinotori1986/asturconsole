"""Animación visual de las operaciones de Greaseweazle (leer/escribir un
disquete físico real).

En vez de una barra de progreso indeterminada sin más información (la
que había antes: Greaseweazle no informa de un porcentaje único como sí
hace uCON64 con --frontend), este widget dibuja un disquete de 3,5" con
el disco interior girando mientras hay actividad, un LED parpadeante, y
un contador digital estilo LCD con la cara y el sector que se está
leyendo o escribiendo en cada momento — la misma información que ya
aparece en la salida de texto de "gw" línea a línea, parseada aquí (ver
greaseweazle_dialog.py, _parsear_progreso) en vez de mostrada como texto
plano difícil de seguir de un vistazo.

gw imprime una línea por cada pista procesada, con el formato:
    T{cilindro}.{cara}: {códec} ({sectores_ok}/{sectores_total} sectors) ...
(confirmado en el código fuente real de Greaseweazle, codec/ibm/ibm.py,
summary_string() — el mismo formato IBM MFM que usan MSX, PC/MS-DOS,
Atari ST, Amiga, etc.) El cilindro no se muestra en el contador porque
no aporta nada útil de un vistazo; cara y sector sí.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QConicalGradient, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

COLOR_FONDO_1 = QColor("#1c212c")
COLOR_FONDO_2 = QColor("#262c3a")
COLOR_BORDE = QColor("#3a4254")
COLOR_ACENTO = QColor("#3ef29a")
COLOR_TEXTO_TENUE = QColor("#8892a8")

# Mismos tonos "activo" que ya usa transfer_animation_widget.py, para que
# ambos diálogos compartan el mismo lenguaje visual de "está pasando algo
# ahora mismo" en toda la aplicación.
COLOR_FONDO_1_ACTIVO = QColor("#2b1a0f")
COLOR_FONDO_2_ACTIVO = QColor("#3d2814")
COLOR_BORDE_ACTIVO = QColor("#ff9d42")
COLOR_HALO_ACTIVO = QColor(255, 157, 66, 70)

COLOR_CARCASA = QColor("#3a4254")
COLOR_CARCASA_BORDE = QColor("#5a6478")
COLOR_ETIQUETA = QColor("#262c3a")
COLOR_DISCO = QColor("#12141c")
COLOR_LED_ACTIVO = QColor("#ff9d42")
COLOR_LED_INACTIVO = QColor("#5a4a3a")

COLOR_LCD_FONDO = QColor("#0a0c12")
COLOR_LCD_BORDE = QColor("#2c3342")
COLOR_LCD_TEXTO = QColor("#3ef29a")
COLOR_LCD_TEXTO_ERROR = QColor("#ff8a7a")  # mismo rojo que usa el botón "Cancelar" del resto de la app


class GreaseweazleAnimationWidget(QWidget):
    """Disquete de 3,5" con el disco interior girando mientras hay
    actividad, LED parpadeante, y contador digital de cara/sector.

    set_running(bool) arranca o para el giro y el parpadeo.
    set_progreso(cara, sector_actual, sector_total) actualiza el
    contador — se llama cada vez que se parsea una nueva línea "T.C.H:"
    de la salida de gw. Antes de la primera línea (o si el formato no es
    reconocible, como con --format=raw) el contador muestra guiones en
    vez de un dato inventado.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self._running = False
        self._tick = 0
        self._cara: int | None = None
        self._sector_actual: int | None = None
        self._sector_total: int | None = None
        self._pista: int | None = None
        self._pista_total: int | None = None
        self._ok = True

        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._avanzar)

    def set_running(self, running: bool):
        self._running = running
        if running:
            self._tick = 0
        else:
            self._cara = None
            self._sector_actual = None
            self._sector_total = None
            self._pista = None
            self._pista_total = None
            self._ok = True
        if running:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_progreso(self, pista: int, pista_total: int, cara: int,
                      sector_actual: int, sector_total: int, ok: bool):
        """pista/pista_total SIEMPRE avanza (nunca se repite ni retrocede,
        una por cada pista distinta procesada) — es lo que da la
        sensación de progreso constante en la interfaz. sector_actual/
        sector_total, en cambio, es el recuento de ESA pista en concreto,
        y puede perfectamente repetirse igual varias veces seguidas (una
        racha de pistas sin ningún problema, o varios reintentos de la
        misma pista) sin que eso sea ningún fallo — de ahí que se muestre
        junto al color (verde si esa pista se leyó completa, rojo si le
        faltó algún sector) en vez de como única fuente de "sensación de
        avance".
        """
        self._pista = pista
        self._pista_total = pista_total
        self._cara = cara
        self._sector_actual = sector_actual
        self._sector_total = sector_total
        self._ok = ok
        self.update()

    def _avanzar(self):
        self._tick += 1
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        ancho, alto = self.width(), self.height()

        # --- fondo con marco, mismo lenguaje visual que la transferencia
        # por puerto paralelo: tonos cálidos mientras hay actividad, fríos
        # en reposo ---
        color_fondo_1 = COLOR_FONDO_1_ACTIVO if self._running else COLOR_FONDO_1
        color_fondo_2 = COLOR_FONDO_2_ACTIVO if self._running else COLOR_FONDO_2
        color_borde = COLOR_BORDE_ACTIVO if self._running else COLOR_BORDE

        grad = QLinearGradient(0, 0, ancho, 0)
        grad.setColorAt(0, color_fondo_1)
        grad.setColorAt(1, color_fondo_2)
        radio_marco = 10
        rect_marco = self.rect().adjusted(1, 1, -1, -1)

        if self._running:
            halo_pen = QPen(COLOR_HALO_ACTIVO)
            halo_pen.setWidth(9)
            painter.setPen(halo_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect_marco, radio_marco, radio_marco)

        painter.setPen(Qt.NoPen)
        painter.setBrush(grad)
        painter.drawRoundedRect(rect_marco, radio_marco, radio_marco)

        if self._running:
            centro_x, centro_y = rect_marco.center().x(), rect_marco.center().y()
            angulo = (self._tick * 3) % 360
            marco_grad = QConicalGradient(centro_x, centro_y, angulo)
            marco_grad.setColorAt(0.00, QColor("#ffd9a8"))
            marco_grad.setColorAt(0.15, COLOR_BORDE_ACTIVO)
            marco_grad.setColorAt(0.50, QColor("#7a3d10"))
            marco_grad.setColorAt(0.85, COLOR_BORDE_ACTIVO)
            marco_grad.setColorAt(1.00, QColor("#ffd9a8"))
            marco_pen = QPen(marco_grad, 4)
        else:
            marco_pen = QPen(color_borde)
            marco_pen.setWidth(1)
        painter.setPen(marco_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect_marco, radio_marco, radio_marco)

        # --- disquete, centrado en la mitad izquierda ---
        lado = min(100, alto - 40)
        cx = ancho * 0.28
        cy = alto / 2
        carc_rect = QRectF(cx - lado / 2, cy - lado / 2, lado, lado)

        painter.setPen(QPen(COLOR_CARCASA_BORDE, 1.5))
        painter.setBrush(COLOR_CARCASA)
        painter.drawRoundedRect(carc_rect, 8, 8)

        # etiqueta rectangular arriba, como en cualquier disquete real
        etiqueta_rect = QRectF(
            carc_rect.left() + lado * 0.12, carc_rect.top() + lado * 0.06,
            lado * 0.52, lado * 0.20)
        painter.setPen(Qt.NoPen)
        painter.setBrush(COLOR_ETIQUETA)
        painter.drawRoundedRect(etiqueta_rect, 2, 2)

        # disco interior, girando mientras hay actividad
        disco_radio = lado * 0.32
        disco_cy = cy + lado * 0.10
        painter.setPen(Qt.NoPen)
        painter.setBrush(COLOR_DISCO)
        painter.drawEllipse(QRectF(cx - disco_radio, disco_cy - disco_radio,
                                    disco_radio * 2, disco_radio * 2))

        if self._running:
            painter.save()
            painter.translate(cx, disco_cy)
            painter.rotate((self._tick * 6) % 360)
            radio_pen = QPen(COLOR_CARCASA_BORDE, 1)
            painter.setPen(radio_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QRectF(-disco_radio, -disco_radio,
                                        disco_radio * 2, disco_radio * 2))
            # marca de referencia para que el giro se perciba (si no, un
            # círculo perfecto girando es indistinguible de uno quieto)
            painter.setPen(QPen(COLOR_ACENTO, 2))
            painter.drawLine(0, 0, 0, int(-disco_radio * 0.85))
            painter.restore()
        else:
            painter.setPen(QPen(COLOR_CARCASA_BORDE, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QRectF(cx - disco_radio, disco_cy - disco_radio,
                                        disco_radio * 2, disco_radio * 2))

        # cubo central
        cubo_radio = lado * 0.06
        painter.setPen(Qt.NoPen)
        painter.setBrush(COLOR_CARCASA_BORDE)
        painter.drawEllipse(QRectF(cx - cubo_radio, disco_cy - cubo_radio,
                                    cubo_radio * 2, cubo_radio * 2))

        # LED de actividad, esquina superior derecha de la carcasa
        led_color = COLOR_LED_ACTIVO if (self._running and (self._tick // 15) % 2 == 0) \
            else COLOR_LED_INACTIVO
        led_radio = lado * 0.035
        led_cx = carc_rect.right() - lado * 0.10
        led_cy = carc_rect.top() + lado * 0.10
        painter.setPen(Qt.NoPen)
        painter.setBrush(led_color)
        painter.drawEllipse(QRectF(led_cx - led_radio, led_cy - led_radio,
                                    led_radio * 2, led_radio * 2))

        # --- contador digital estilo LCD, a la derecha del disquete ---
        lcd_x = ancho * 0.36
        lcd_w = ancho * 0.60
        lcd_h = 56
        lcd_rect = QRectF(lcd_x, cy - lcd_h / 2, lcd_w, lcd_h)
        painter.setPen(QPen(COLOR_LCD_BORDE, 1))
        painter.setBrush(COLOR_LCD_FONDO)
        painter.drawRoundedRect(lcd_rect, 6, 6)

        fuente_grande = QFont("monospace")
        fuente_grande.setStyleHint(QFont.Monospace)
        fuente_grande.setPointSize(13)
        fuente_grande.setBold(True)
        painter.setFont(fuente_grande)
        # Verde si la última pista procesada se leyó completa, rojo si le
        # faltó algún sector — el color lleva la información de "bien/
        # mal"; el número de pista, que SIEMPRE avanza, lleva la
        # sensación de progreso.
        painter.setPen(COLOR_LCD_TEXTO if self._ok else COLOR_LCD_TEXTO_ERROR)

        if self._pista is not None and self._pista_total:
            texto = (f"Pista {self._pista}/{self._pista_total} · Cara {self._cara} · "
                     f"Sector {self._sector_actual}/{self._sector_total}")
        else:
            texto = "Pista –/– · Cara – · Sector –/–"
        painter.drawText(lcd_rect.adjusted(0, -8, 0, -8), Qt.AlignCenter, texto)

        fuente_pequena = QFont("monospace")
        fuente_pequena.setStyleHint(QFont.Monospace)
        fuente_pequena.setPointSize(9)
        painter.setFont(fuente_pequena)
        painter.setPen(COLOR_TEXTO_TENUE)
        etiqueta_txt = "leyendo disco…" if self._running else "en espera"
        painter.drawText(lcd_rect.adjusted(0, 16, 0, 16), Qt.AlignCenter, etiqueta_txt)
