"""Animación visual de la transferencia por puerto paralelo.

En vez de limitarse a volcar como texto plano la salida de uCON64 (líneas
de progreso en bloques de 16 KB, poco legibles de un vistazo), este widget
dibuja el envío como lo que es: paquetes de datos viajando del PC al
copión, con las fotos reales del propio cartucho (Super Wild Card / Super
Magic Drive), tomadas de la documentación original de uCON64.

El progreso real llega desde fuera (ver transfer_dialog.py, que activa el
modo --frontend de uCON64: con él, en vez de una barra ASCII decorativa,
uCON64 imprime solo el porcentaje numérico en cada línea, mucho más fácil
y fiable de leer que parsear su barra de progreso normal).
"""
from __future__ import annotations

import os
import random

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QConicalGradient, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

# Una imagen por sistema; si no se encuentra ninguna (por ejemplo, MSX, que
# no tiene transferencia por puerto paralelo en este proyecto) se dibuja
# solo un rectángulo con el nombre, sin foto.
IMAGEN_COPIER = {
    "snes": "swc.png",
    "genesis": "smd.png",
}
NOMBRE_COPIER = {
    "snes": "Super Wild Card",
    "genesis": "Super Magic Drive",
}
# Icono de la propia consola (no del copión), para integrar dentro de la
# "pantalla" del equipo: deja claro de un vistazo a qué sistema pertenece
# la ROM que se está enviando, no solo a qué copión.
ICONO_CONSOLA = {
    "snes": "snes.svg",
    "genesis": "genesis.svg",
}

COLOR_FONDO_1 = QColor("#1c212c")
COLOR_FONDO_2 = QColor("#262c3a")
COLOR_BORDE = QColor("#3a4254")
COLOR_ACENTO = QColor("#3ef29a")
COLOR_ACENTO_TENUE = QColor(62, 242, 154, 60)
COLOR_TEXTO = QColor("#dde3ef")
COLOR_TEXTO_TENUE = QColor("#8892a8")
COLOR_TUBERIA = QColor("#2c3342")

# Mientras hay una transferencia en marcha, el fondo pasa a un tono
# anaranjado cálido (ámbar/cobre, no un naranja chillón, para no romper
# la estética general oscura) y el marco se ilumina con un halo del mismo
# tono — la señal visual de "ahora mismo está pasando algo" que se pedía.
COLOR_FONDO_1_ACTIVO = QColor("#2b1a0f")
COLOR_FONDO_2_ACTIVO = QColor("#3d2814")
COLOR_BORDE_ACTIVO = QColor("#ff9d42")
COLOR_HALO_ACTIVO = QColor(255, 157, 66, 70)


class _Paquete:
    """Un dígito binario (0 o 1) viajando por la tubería, con su propia
    posición y tamaño ligeramente aleatorios para que la animación no se
    vea mecánica — el "flujo de datos" real que representa la
    transferencia, en vez de un simple bloque de color.
    """
    __slots__ = ("pos", "vel", "alto", "y_offset", "digito")

    def __init__(self, vel: float):
        self.pos = 0.0
        self.vel = vel
        self.alto = random.uniform(0.75, 1.0)
        self.y_offset = random.uniform(-5, 5)
        self.digito = random.choice("01")


class TransferAnimationWidget(QWidget):
    """Icono de PC a la izquierda, foto real del copión a la derecha, y
    paquetes de datos animados viajando entre ambos por una tubería.

    set_progress(pct) actualiza el porcentaje mostrado y la velocidad de
    los paquetes (más rápido cuanto más queda por transferir, para dar
    sensación de "flujo constante" en vez de acelerar/frenar a golpes).
    set_running(bool) arranca o para la animación y el contador.
    """

    def __init__(self, sistema: str, icon_dir: str = "", parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self._sistema = sistema
        self._pct = 0
        self._bytes_actuales = 0
        self._bytes_totales = 0
        self._running = False
        self._paquetes: list[_Paquete] = []
        self._tick = 0

        self._pixmap_copier: QPixmap | None = None
        nombre_archivo = IMAGEN_COPIER.get(sistema)
        if nombre_archivo and icon_dir:
            ruta = os.path.join(icon_dir, "copiers", nombre_archivo)
            if os.path.isfile(ruta):
                pix = QPixmap(ruta)
                if not pix.isNull():
                    self._pixmap_copier = pix

        self._pixmap_consola: QPixmap | None = None
        nombre_consola = ICONO_CONSOLA.get(sistema)
        if nombre_consola and icon_dir:
            ruta_consola = os.path.join(icon_dir, nombre_consola)
            if os.path.isfile(ruta_consola):
                pix_c = QIcon(ruta_consola).pixmap(96, 96)
                if not pix_c.isNull():
                    self._pixmap_consola = pix_c

        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._avanzar)

    def set_running(self, running: bool):
        self._running = running
        if running:
            self._paquetes.clear()
            self._tick = 0
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_progress(self, pct: int, bytes_actuales: int = 0, bytes_totales: int = 0):
        self._pct = max(0, min(100, pct))
        self._bytes_actuales = bytes_actuales
        self._bytes_totales = bytes_totales
        self.update()

    def _avanzar(self):
        self._tick += 1
        # Un paquete nuevo cada pocos ticks: con esto la "densidad" de
        # paquetes en la tubería se ve constante, no depende de a qué
        # velocidad esté llegando el progreso real (que en uCON64 llega en
        # ráfagas por bloque, no de forma perfectamente continua).
        if self._running and self._tick % 6 == 0:
            self._paquetes.append(_Paquete(vel=random.uniform(0.018, 0.026)))

        vivos = []
        for p in self._paquetes:
            p.pos += p.vel
            if p.pos < 1.05:
                vivos.append(p)
        self._paquetes = vivos
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        ancho, alto = self.width(), self.height()

        # --- fondo, con marco para no verse tan plano sobre el resto del diálogo ---
        # Tonos cálidos (ámbar) mientras hay transferencia en marcha, fríos
        # (los de siempre) en reposo — la señal visual de "está pasando
        # algo ahora mismo" que se echaba en falta.
        color_fondo_1 = COLOR_FONDO_1_ACTIVO if self._running else COLOR_FONDO_1
        color_fondo_2 = COLOR_FONDO_2_ACTIVO if self._running else COLOR_FONDO_2
        color_borde = COLOR_BORDE_ACTIVO if self._running else COLOR_BORDE

        grad = QLinearGradient(0, 0, ancho, 0)
        grad.setColorAt(0, color_fondo_1)
        grad.setColorAt(1, color_fondo_2)
        radio_marco = 10
        rect_marco = self.rect().adjusted(1, 1, -1, -1)

        # Halo sutil alrededor del marco cuando está transfiriendo: un
        # segundo contorno, más ancho y translúcido, "detrás" del marco
        # real — simula el resplandor sin necesitar efectos de sombra.
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
            # Marco más grueso, con un degradado cónico que gira sobre sí
            # mismo — da sensación de "energía" recorriendo el borde
            # mientras la transferencia está en marcha, en vez de un
            # simple color plano. El ángulo avanza con cada tick del
            # temporizador de la animación (_avanzar), así que gira al
            # mismo ritmo que los dígitos que viajan por la tubería.
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

        margen = 18
        lado = min(84, alto - 2 * margen)
        cy = alto * 0.42

        pc_rect = QRectF(margen, cy - lado / 2, lado, lado)
        cop_rect = QRectF(ancho - margen - lado, cy - lado / 2, lado, lado)

        # --- tubería entre los dos extremos ---
        tuberia_y = cy
        x1, x2 = pc_rect.right() + 14, cop_rect.left() - 14
        painter.setPen(Qt.NoPen)
        painter.setBrush(COLOR_TUBERIA)
        painter.drawRoundedRect(QRectF(x1, tuberia_y - 5, max(0, x2 - x1), 10), 5, 5)

        # relleno de la tubería hasta el punto de progreso, como una barra
        # de progreso integrada en el propio dibujo, no aparte
        if x2 > x1:
            relleno_ancho = (x2 - x1) * (self._pct / 100)
            painter.setBrush(COLOR_ACENTO_TENUE)
            painter.drawRoundedRect(QRectF(x1, tuberia_y - 5, relleno_ancho, 10), 5, 5)

        # --- dígitos binarios viajando por la tubería: el "flujo de datos" ---
        if x2 > x1:
            fuente_digito = QFont("IBM Plex Mono")
            fuente_digito.setBold(True)
            for p in self._paquetes:
                px = x1 + (x2 - x1) * p.pos
                tam = max(9, int(14 * p.alto))
                fuente_digito.setPointSize(tam)
                painter.setFont(fuente_digito)
                # se desvanecen justo al llegar, como si "entraran" en el copión
                opacidad = 1.0 if p.pos < 0.92 else max(0.0, (1.0 - p.pos) / 0.08)
                color = QColor(COLOR_ACENTO)
                color.setAlphaF(0.95 * opacidad)
                painter.setPen(color)
                rect_digito = QRectF(px - 8, tuberia_y - 10 + p.y_offset, 16, 20)
                painter.drawText(rect_digito, Qt.AlignCenter, p.digito)

        # --- icono del PC (dibujado, no hace falta una foto para esto) ---
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2c3342"))
        pantalla = QRectF(pc_rect.x(), pc_rect.y(), pc_rect.width(), pc_rect.height() * 0.72)
        painter.drawRoundedRect(pantalla, 6, 6)
        painter.setBrush(QColor(30, 130, 90) if self._running else QColor("#1a1f2a"))
        pantalla_interior = pantalla.adjusted(6, 6, -6, -6)
        painter.drawRoundedRect(pantalla_interior, 3, 3)
        # Icono de la propia consola (SNES/Mega Drive) dentro de la
        # pantalla: dice de un vistazo para qué sistema es la ROM que se
        # está enviando, no solo a qué copión se envía.
        if self._pixmap_consola is not None:
            lado_icono = min(pantalla_interior.width(), pantalla_interior.height()) * 0.75
            escalado_consola = self._pixmap_consola.scaled(
                int(lado_icono), int(lado_icono), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            cx = pantalla_interior.x() + (pantalla_interior.width() - escalado_consola.width()) / 2
            cy2 = pantalla_interior.y() + (pantalla_interior.height() - escalado_consola.height()) / 2
            painter.drawPixmap(int(cx), int(cy2), escalado_consola)
        base = QRectF(pc_rect.x() + pc_rect.width() * 0.3, pantalla.bottom() + 4,
                       pc_rect.width() * 0.4, pc_rect.height() * 0.12)
        painter.setBrush(QColor("#2c3342"))
        painter.drawRoundedRect(base, 2, 2)

        # --- foto real del copión, o un rectángulo con su nombre si no hay imagen ---
        if self._pixmap_copier is not None:
            escalado = self._pixmap_copier.scaled(
                int(cop_rect.width()), int(cop_rect.height()),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            px = cop_rect.x() + (cop_rect.width() - escalado.width()) / 2
            py = cop_rect.y() + (cop_rect.height() - escalado.height()) / 2
            painter.drawPixmap(int(px), int(py), escalado)
        else:
            painter.setBrush(QColor("#2c3342"))
            painter.drawRoundedRect(cop_rect, 8, 8)

        # --- etiquetas y contador ---
        painter.setPen(COLOR_TEXTO_TENUE)
        f_pequena = QFont()
        f_pequena.setPointSize(9)
        painter.setFont(f_pequena)
        painter.drawText(QRectF(pc_rect.x() - 10, pc_rect.bottom() + 6, pc_rect.width() + 20, 18),
                         Qt.AlignHCenter, "Este equipo")
        nombre = NOMBRE_COPIER.get(self._sistema, self._sistema.upper())
        painter.drawText(QRectF(cop_rect.x() - 20, cop_rect.bottom() + 6, cop_rect.width() + 40, 18),
                         Qt.AlignHCenter, nombre)

        f_grande = QFont()
        f_grande.setPointSize(20)
        f_grande.setBold(True)
        painter.setFont(f_grande)
        painter.setPen(COLOR_ACENTO if self._running else COLOR_TEXTO)
        porcentaje_txt = f"{self._pct}%"
        painter.drawText(QRectF(0, alto - 46, ancho, 30), Qt.AlignHCenter, porcentaje_txt)

        if self._bytes_totales:
            f_detalle = QFont()
            f_detalle.setPointSize(9)
            painter.setFont(f_detalle)
            painter.setPen(COLOR_TEXTO_TENUE)
            from rom_formats import fmt_bytes
            detalle = f"{fmt_bytes(self._bytes_actuales)} / {fmt_bytes(self._bytes_totales)}"
            painter.drawText(QRectF(0, alto - 18, ancho, 16), Qt.AlignHCenter, detalle)
