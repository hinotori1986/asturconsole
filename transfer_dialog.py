"""Interfaz de transferencia por puerto paralelo a copiones de época.

Ejecuta uCON64 como proceso externo y muestra su salida en tiempo real.
La lógica de comandos y validaciones está en `transfer_ucon64.py`.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import zlib

from PySide6.QtCore import QProcess, QSettings, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QScrollArea, QVBoxLayout, QWidget,
)

import genesis_tools as gt
import parches_conocidos as pc
import rom_formats as rf
import snes_crack as crk
import snes_tools as st
import system_check as sc
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

# Mismo patrón que ROM/SRAM de arriba (un solo color de acento, ya que
# aquí las 2 opciones no necesitan distinguirse por color, solo por cuál
# está marcada) -- usado por el interruptor "Consola de destino".
ESTILO_OPCION_DESTINO = """
QRadioButton:checked {
    color: #4e9ef6; font-weight: 700;
    border-color: #4e9ef6; background: rgba(78,158,246,0.14);
}
QRadioButton::indicator:checked { border-color: #4e9ef6; background: #4e9ef6; }
"""

def _settings() -> QSettings:
    return QSettings("ASTURCONSOLE", "asturconsole")


class DiagnosticoDialog(QDialog):
    """Comprueba de una vez los problemas más comunes que impiden que la
    transferencia por puerto paralelo funcione en Linux (permisos de
    grupo, dispositivo parport, CUPS acaparando el puerto, uCON64
    instalado), con instrucciones concretas para cada uno — en vez de que
    cada usuario nuevo tenga que descubrirlos por su cuenta a base de
    "le doy al botón y no pasa nada, sin ningún error visible"."""

    def __init__(self, parent=None, ucon64_path: str | None = None):
        super().__init__(parent)
        self._ucon64_path = ucon64_path   # el que se va a usar de verdad (ver system_check.ucon64_efectivo)
        self.setWindowTitle("Comprobar requisitos del puerto paralelo")
        self.setMinimumSize(760, 850)
        self.setStyleSheet(ESTILO_DIALOGO)

        lay = QVBoxLayout(self)
        intro = QLabel(
            "Comprobación de los problemas más habituales que hacen que la "
            "transferencia por puerto paralelo no funcione en Linux, sin dar "
            "ningún error visible."
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        lay.addWidget(self.scroll, 1)

        fila_botones = QHBoxLayout()
        self.repetir_btn = QPushButton("↻ Volver a comprobar")
        self.repetir_btn.clicked.connect(self._ejecutar)
        fila_botones.addWidget(self.repetir_btn)
        fila_botones.addStretch(1)
        cerrar_btn = QPushButton("Cerrar")
        cerrar_btn.clicked.connect(self.accept)
        fila_botones.addWidget(cerrar_btn)
        lay.addLayout(fila_botones)

        self._ejecutar()

    def _ejecutar(self):
        diagnostico = sc.diagnosticar(self._ucon64_path)

        contenedor = QWidget()
        clay = QVBoxLayout(contenedor)
        clay.setSpacing(10)

        for c in diagnostico.comprobaciones:
            marco = QFrame()
            marco.setObjectName("TarjetaDiagnostico")
            marco.setStyleSheet(
                "#TarjetaDiagnostico { border: 2px solid %s; border-radius: 8px; "
                "background: %s; padding: 4px; }"
                % (("#2e7d4f", "rgba(46,125,79,0.10)") if c.ok
                   else ("#c0392b", "rgba(192,57,43,0.10)"))
            )
            mlay = QVBoxLayout(marco)

            cabecera = QLabel(f"{'✓' if c.ok else '✗'}  {c.titulo}")
            cabecera.setStyleSheet(
                f"font-weight: 700; font-size: 14px; color: {'#3ef29a' if c.ok else '#ff6b5e'};")
            mlay.addWidget(cabecera)

            detalle = QLabel(c.detalle)
            detalle.setWordWrap(True)
            mlay.addWidget(detalle)

            if c.solucion:
                solucion = QPlainTextEdit(c.solucion)
                solucion.setReadOnly(True)
                f = QFont("monospace")
                f.setStyleHint(QFont.Monospace)
                solucion.setFont(f)
                solucion.setMaximumHeight(110)
                mlay.addWidget(solucion)

            if not c.ok and c.accion_id:
                # Algunas soluciones son un único comando que necesita
                # privilegios de administrador (como descargar el módulo
                # "lp") — en vez de obligar a abrir una terminal para una
                # sola línea, se ofrece resolverlo aquí mismo: pkexec pide
                # la contraseña con el diálogo gráfico nativo del sistema,
                # y tras ejecutarlo se refresca todo el diagnóstico para
                # confirmar que ya quedó en orden.
                accion_btn = QPushButton("⚡ Solucionar ahora (pedirá tu contraseña)")
                accion_btn.setCursor(Qt.PointingHandCursor)
                accion_btn.setStyleSheet(
                    "QPushButton { background: rgba(62,242,154,0.12); color: #3ef29a;"
                    " border: 2px solid #2e7d4f; border-radius: 6px; padding: 8px 12px;"
                    " font-weight: 700; }"
                    "QPushButton:hover { background: rgba(62,242,154,0.20); }"
                    "QPushButton:disabled { color: #6b7280; border-color: #3a4048;"
                    " background: transparent; }"
                )
                accion_id = c.accion_id
                accion_btn.clicked.connect(
                    lambda _checked=False, aid=accion_id, btn=accion_btn: self._resolver(aid, btn))
                mlay.addWidget(accion_btn)

            clay.addWidget(marco)

        clay.addStretch(1)
        self.scroll.setWidget(contenedor)

        if diagnostico.todo_ok:
            self.setWindowTitle("Comprobar requisitos del puerto paralelo — todo en orden")

    def _resolver(self, accion_id: str, boton: QPushButton):
        boton.setEnabled(False)
        boton.setText("Pidiendo contraseña…")
        QApplication.processEvents()
        exito, mensaje = sc.ejecutar_accion(accion_id)
        if exito:
            QMessageBox.information(self, "Solucionado", mensaje)
            self._ejecutar()  # refresca todas las tarjetas para confirmar el nuevo estado
        else:
            QMessageBox.warning(self, "No se pudo completar", mensaje)
            boton.setEnabled(True)
            boton.setText("⚡ Solucionar ahora (pedirá tu contraseña)")


ESTILO_DIALOGO = """
QDialog { background: #0f111a; }
QLabel { color: #dde3ef; }

QScrollArea { background: #0f111a; border: none; }
QScrollArea > QWidget > QWidget { background: #0f111a; }

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
    background: #12141c;
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

# Botones de selección de puerto y su campo manual — ver el comentario en
# __init__ sobre por qué se sustituyó el QComboBox por esto. El estado
# "elegido" (:checked para los botones, [activo="true"] para el campo de
# texto, ya que QLineEdit no tiene un :checked nativo) usa el mismo verde
# de acento que el resto de la interfaz para resaltar cuál está activo.
ESTILO_BOTON_PUERTO = """
QPushButton {
    background: #12141c;
    color: #dde3ef;
    border: 1px solid #39404f;
    border-radius: 5px;
    padding: 6px 12px;
}
QPushButton:hover { border-color: #5a6478; }
QPushButton:checked {
    background: #17351f;
    border: 2px solid #3ef29a;
    color: #3ef29a;
    font-weight: 700;
}
QLineEdit {
    background: #12141c;
    color: #dde3ef;
    border: 1px solid #39404f;
    border-radius: 5px;
    padding: 6px 8px;
}
QLineEdit[activo="true"] {
    background: #17351f;
    border: 2px solid #3ef29a;
    color: #3ef29a;
    font-weight: 700;
}
"""


class TransferDialog(QDialog):
    def __init__(self, parent=None, system: str = "snes", initial_rom: str | None = None,
                 icon_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Transferir al copión (puerto paralelo)")
        self.setMinimumWidth(1040)
        self.setStyleSheet(ESTILO_DIALOGO)
        # La marca de verificación del checkbox necesita saber la ruta de
        # los iconos, que solo se conoce en tiempo de ejecución (varía
        # según cómo se instaló la aplicación) — por eso se añade aparte,
        # en vez de venir ya incluida en ESTILO_DIALOGO, que es una
        # constante fija de módulo sin acceso a icon_dir.
        if icon_dir:
            ruta_check = os.path.join(icon_dir, "checkmark.svg").replace("\\", "/")
            self.setStyleSheet(
                self.styleSheet()
                + f"\nQCheckBox::indicator:checked {{ image: url({ruta_check}); }}"
            )

        self._process: QProcess | None = None
        self._popen: subprocess.Popen | None = None
        self._poll_timer: QTimer | None = None
        self._reset_en_curso = False  # ver _reset_port / _on_finished
        self._system = system
        self._rom_temporal: str | None = None  # ver _preparar_rom_para_envio
        # Prioridad: primero la ruta que el usuario haya elegido a mano
        # (persiste entre sesiones vía QSettings) — solo si ya no fuera
        # válida (se movió, se borró el archivo) se cae al autodetectado
        # (la copia incluida en la propia carpeta de la app, o el PATH del
        # sistema). Antes era al revés: el autodetectado ganaba siempre
        # que existiera, así que elegir otra versión a mano no tenía
        # ningún efecto real mientras la copia incluida siguiera ahí —
        # que es siempre, ya que se distribuye con la propia app.
        ruta_guardada = _settings().value("transfer/ucon64_path", "")
        self._ucon64 = tu.find_ucon64(ruta_guardada) if ruta_guardada else None
        if not self._ucon64:
            self._ucon64 = tu.find_ucon64()
        self._bytes_totales = 0

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # Layout de dos columnas: antes todo se apilaba en una sola
        # columna vertical, y con las nuevas secciones (parches al vuelo)
        # la ventana ya no podía crecer más en altura sin salirse de
        # pantallas normales — el ancho, en cambio, sí tenía margen. La
        # izquierda lleva lo imprescindible para CUALQUIER transferencia
        # (archivo, puerto, qué enviar); la derecha, lo más específico o
        # menos usado en el día a día (parches, ruta a uCON64,
        # diagnóstico, notas de hardware). La consola queda fuera de
        # ambas, a lo ancho completo, porque es donde más espacio hace
        # falta para leer la salida de uCON64 con comodidad.
        columnas = QHBoxLayout()
        columnas.setSpacing(16)
        col_izq = QVBoxLayout()
        col_izq.setSpacing(10)
        col_der_widget = QWidget()
        col_der_widget.setFixedWidth(360)
        col_der = QVBoxLayout(col_der_widget)
        col_der.setContentsMargins(0, 0, 0, 0)
        col_der.setSpacing(10)
        columnas.addLayout(col_izq, 1)
        columnas.addWidget(col_der_widget)
        lay.addLayout(columnas)

        # --- animación de la transferencia (icono del PC, foto real del
        # copión, y paquetes de datos viajando entre ambos según el
        # progreso real) — sustituye a la barra indeterminada de antes,
        # que no reflejaba ningún avance real, solo que el proceso seguía vivo.
        self.animacion = TransferAnimationWidget(system, icon_dir=icon_dir)
        col_izq.addWidget(self.animacion)

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
        col_izq.addLayout(row)

        self.notes_lbl = QLabel("")
        self.notes_lbl.setWordWrap(True)
        self.notes_lbl.setStyleSheet("color: #727a90; font-size: 11px;")
        col_izq.addWidget(self.notes_lbl)

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
        col_izq.addLayout(file_row)

        # --- puerto ---
        # Antes era un QComboBox editable. En Windows, con un valor
        # guardado de sesiones anteriores aplicado al abrir la ventana,
        # el desplegable dejaba de responder a los clics — probado con
        # dos enfoques distintos (aplicar el valor tras el primer show,
        # diferirlo al siguiente ciclo del bucle de eventos) sin éxito
        # ninguno de los dos. En vez de seguir adivinando comportamientos
        # de Qt/Windows que no se pueden reproducir ni depurar desde
        # aquí, se sustituye el desplegable por botones — un mecanismo
        # mucho más simple, sin ningún popup nativo de por medio que
        # pueda fallar de esta forma.
        port_col = QVBoxLayout()
        port_label_row = QHBoxLayout()
        port_label_row.addWidget(QLabel("Puerto:"))
        self.reset_port_btn = QPushButton("⟲ Resetear puerto")
        self.reset_port_btn.setToolTip(
            "Ejecuta ucon64 --xreset con el puerto elegido arriba, sin hacer "
            "ninguna transferencia — útil para comprobaciones sueltas del "
            "estado del puerto.")
        self.reset_port_btn.clicked.connect(self._reset_port)
        port_label_row.addWidget(self.reset_port_btn)
        port_label_row.addStretch(1)
        port_col.addLayout(port_label_row)

        botones_row = QHBoxLayout()
        self._puerto_grupo = QButtonGroup(self)
        self._puerto_grupo.setExclusive(True)
        self._puerto_btns: dict[str, QPushButton] = {}
        opciones_puerto = ["(automático)"] + list(tu.list_parallel_devices()) + \
            ["0x378", "0x278", "0x3bc", "0xFFF0", "0xFFF8"]
        for valor in opciones_puerto:
            btn = QPushButton(valor)
            btn.setCheckable(True)
            btn.setStyleSheet(ESTILO_BOTON_PUERTO)
            btn.clicked.connect(lambda _chk=False, v=valor: self._elegir_puerto_boton(v))
            self._puerto_grupo.addButton(btn)
            self._puerto_btns[valor] = btn
            botones_row.addWidget(btn)
        botones_row.addStretch(1)
        port_col.addLayout(botones_row)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Otro (manual):"))
        self.port_custom_edit = QLineEdit()
        self.port_custom_edit.setPlaceholderText("p. ej. 0x2F8")
        self.port_custom_edit.setStyleSheet(ESTILO_BOTON_PUERTO)
        self.port_custom_edit.editingFinished.connect(self._elegir_puerto_manual)
        manual_row.addWidget(self.port_custom_edit, 1)
        port_col.addLayout(manual_row)

        # Restaura la elección de la sesión anterior — sin ningún
        # QComboBox de por medio, esto ya no tiene el problema de antes:
        # son solo un texto y un estilo, se aplica directamente.
        puerto_guardado = _settings().value("transfer/port", "")
        if puerto_guardado and puerto_guardado in self._puerto_btns:
            self._puerto_btns[puerto_guardado].setChecked(True)
            self._resaltar_puerto_elegido(puerto_guardado)
        elif puerto_guardado:
            self.port_custom_edit.setText(puerto_guardado)
            self._resaltar_puerto_elegido(None)
        else:
            self._puerto_btns["(automático)"].setChecked(True)
            self._resaltar_puerto_elegido("(automático)")
        col_izq.addLayout(port_col)

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
        # --- consola de destino (solo SNES) — tarjeta grande, mismo
        # patrón visual que "¿QUÉ QUIERES TRANSFERIR?" justo debajo: aquí
        # SÍ hay sitio de sobra (a diferencia de la columna derecha,
        # angosta), y es una decisión igual de importante para saber qué
        # se va a enviar. Ver el comentario extenso junto a
        # self._variante_dual_actual (arriba, en la sección de parches)
        # para la lógica completa de qué hace este interruptor.
        if self._system == "snes":
            destino_card = QFrame()
            destino_card.setObjectName("Tarjeta")
            destl = QVBoxLayout(destino_card)
            destl.setContentsMargins(14, 10, 14, 12)
            destl.setSpacing(8)
            destino_etiqueta = QLabel("CONSOLA DE DESTINO")
            destino_etiqueta.setObjectName("Seccion")
            destl.addWidget(destino_etiqueta)
            fila_destino = QHBoxLayout()
            fila_destino.setSpacing(10)
            self.btn_destino_ntsc = QRadioButton("NTSC (USA / Japón)")
            self.btn_destino_ntsc.setChecked(True)
            self.btn_destino_ntsc.setStyleSheet(ESTILO_OPCION_DESTINO)
            self.btn_destino_pal = QRadioButton("PAL (Europa)")
            self.btn_destino_pal.setStyleSheet(ESTILO_OPCION_DESTINO)
            self._grupo_destino = QButtonGroup(self)
            self._grupo_destino.addButton(self.btn_destino_ntsc)
            self._grupo_destino.addButton(self.btn_destino_pal)
            self.btn_destino_ntsc.toggled.connect(self._actualizar_parches_segun_destino)
            self.btn_destino_ntsc.toggled.connect(self._guardar_preferencia_destino)
            fila_destino.addWidget(self.btn_destino_ntsc, 1)
            fila_destino.addWidget(self.btn_destino_pal, 1)
            destl.addLayout(fila_destino)
            self.destino_nota_lbl = QLabel("")
            self.destino_nota_lbl.setWordWrap(True)
            self.destino_nota_lbl.setStyleSheet("color: #8892a8; font-size: 11px;")
            destl.addWidget(self.destino_nota_lbl)
            col_izq.addWidget(destino_card)

        col_izq.addWidget(qué)
        col_izq.addStretch(1)

        # --- parches al vuelo (solo SNES, solo para ROM) ---
        # Deliberadamente distinto de "Añadir cabecera" en la ventana de
        # trabajo: aquello genera un archivo nuevo en disco; esto se aplica
        # en memoria justo antes de enviar, sin guardar nada — para poder
        # probar combinaciones rápidamente sin acumular archivos de
        # prueba. Las casillas se pre-marcan según lo que se detecte en el
        # propio ROM (ver _analizar_candidatos_parches), pero SIEMPRE
        # quedan editables: el usuario tiene la última palabra, incluso
        # para forzar un parche que la detección no encontró necesario, o
        # lo contrario.
        self.parches_card = QFrame()
        self.parches_card.setObjectName("Tarjeta")
        pl = QVBoxLayout(self.parches_card)
        pl.setContentsMargins(14, 10, 14, 12)
        pl.setSpacing(6)

        titulo_parches = QLabel("🧪 PARCHES AL VUELO (solo para este envío)")
        titulo_parches.setObjectName("Seccion")
        pl.addWidget(titulo_parches)

        nota_parches = QLabel(
            "Se aplican en memoria justo antes de enviar, sin guardar "
            "ningún archivo nuevo."
        )
        nota_parches.setWordWrap(True)
        nota_parches.setFixedWidth(320)  # ver el comentario en la definición de col_der_widget
        nota_parches.setStyleSheet("color: #727a90; font-size: 11px;")
        pl.addWidget(nota_parches)

        # --- consola de destino (solo SNES) ---
        # La mayoría de parches de esta app son "arreglos para consola
        # PAL" de ROMs nativas NTSC (USA) — aplicarlos tiene sentido solo
        # si la consola de destino es PAL; en una consola NTSC el ROM
        # original ya funciona tal cual, sin tocar nada. Unos pocos casos
        # (ver parches_conocidos.VarianteDual) son justo al revés: dumps
        # PAL nativos, o casos donde el parche "universal" resultó ser en
        # realidad una inversión y no una neutralización (ver RoboCop
        # versus The Terminator, encontrado con pruebas reales en
        # hardware) — para esos, aplicar el parche sin más en destino
        # nativo rompería el juego. Este interruptor unifica ambos casos:
        # el usuario dice a qué consola va, y de ahí se decide sola qué
        # aplicar y qué dejar intacto.
        #
        # El widget visual en sí NO va aquí (en la columna derecha,
        # estrecha) sino en col_izq, como una tarjeta grande — ver más
        # abajo, justo antes de "¿QUÉ QUIERES TRANSFERIR?". La primera
        # versión lo tenía aquí como un QPushButton pequeño ad-hoc, y
        # salía prácticamente ilegible (columna de 360px ya muy ocupada,
        # sin espacio para mostrar el texto de los botones) — reportado
        # por el usuario con una captura real.
        self._variante_dual_actual: pc.VarianteDual | None = None
        self._region_nativa_actual: str = "NTSC"
        self._conocidos_actual: pc.ParchesConocidos = pc.ParchesConocidos()

        self.chk_crack = QCheckBox("Quitar protección anti-copia (-k)")
        self.chk_pal = QCheckBox("Corregir NTSC/PAL (-f)")
        self.chk_slowrom = QCheckBox("Quitar comprobación SlowROM (-l)")
        self.chk_checksum = QCheckBox("Corregir checksum (--chk)")
        self.chk_region_genesis = QCheckBox("Quitar protección regional (-f)")
        # -k, -f y -l son específicos de SNES (los patrones de protección
        # están recogidos para ese sistema); el checksum existe igual en
        # ambos. La protección regional (-f) también existe en Genesis,
        # pero es un mecanismo distinto al de SNES (decide sola entre
        # NTSC/PAL según lo que declare el propio ROM), así que tiene su
        # propia casilla en vez de compartir chk_pal.
        self.chk_crack.setVisible(system == "snes")
        self.chk_pal.setVisible(system == "snes")
        self.chk_slowrom.setVisible(system == "snes")
        self.chk_region_genesis.setVisible(system == "genesis")
        for chk in (self.chk_crack, self.chk_pal, self.chk_slowrom,
                    self.chk_checksum, self.chk_region_genesis):
            pl.addWidget(chk)
        # Guardado automático en tiempo real (solo SNES, donde hay una
        # ficha distinta por consola de destino): cada vez que el USUARIO
        # marca o desmarca una casilla se guarda al instante lo marcado
        # para la consola de destino elegida. Va a `clicked` y no a
        # `toggled`/`stateChanged` a propósito: `clicked` solo se emite por
        # una acción del usuario, nunca por los setChecked() programáticos
        # con los que se rellenan las casillas al elegir ROM o cambiar de
        # destino -- así no hay bucles ni guardados fantasma al cargar.
        for chk in (self.chk_crack, self.chk_pal, self.chk_slowrom, self.chk_checksum):
            chk.clicked.connect(self._casilla_cambiada)

        # Estado de compatibilidad conocido para el juego cargado ahora
        # mismo (ver parches_conocidos.py) — se actualiza cada vez que se
        # elige/analiza una ROM distinta, en _analizar_candidatos_parches.
        self._crc_actual: str | None = None
        self._nombre_actual: str = ""
        self.estado_compat_lbl = QLabel("")
        self.estado_compat_lbl.setWordWrap(True)
        self.estado_compat_lbl.setStyleSheet("font-size: 11px; font-weight: 700;")
        pl.addWidget(self.estado_compat_lbl)

        pl.addSpacing(4)
        cat_titulo = QLabel(
            "Lo que marques arriba se guarda solo para la consola de destino "
            "elegida (NTSC y PAL por separado). Si no necesita ningún parche, "
            "indícalo aquí:")
        cat_titulo.setWordWrap(True)
        cat_titulo.setStyleSheet("color: #727a90; font-size: 10px;")
        pl.addWidget(cat_titulo)

        fila_cat = QHBoxLayout()
        fila_cat.setSpacing(4)
        # Cada botón lleva su propio color para el estado "marcado" (fondo
        # sólido de ese color, texto oscuro) -- así, en cuanto se elige un
        # ROM ya catalogado, el botón correspondiente a SU estado actual
        # queda resaltado de un vistazo, sin tener que leer el texto de
        # abajo para saberlo. setCheckable + un QButtonGroup exclusivo
        # hace que, al marcar uno, los otros 2 se desmarquen solos.
        def _estilo_btn_cat(color: str) -> str:
            return (
                f"QPushButton {{ font-size: 10px; padding: 4px 2px; color: {color}; "
                f"border: 1px solid {color}; }}"
                f"QPushButton:checked {{ background: {color}; color: #0f111a; font-weight: 700; }}"
            )
        self.btn_marcar_compatible = QPushButton("Compatible")
        self.btn_marcar_compatible.setToolTip("Funciona tal cual, sin ningún parche")
        self.btn_marcar_compatible.setStyleSheet(_estilo_btn_cat("#3ef29a"))
        self.btn_marcar_compatible.clicked.connect(self._marcar_compatible)
        self.btn_marcar_necesita_parche = QPushButton("Necesita\nparche")
        self.btn_marcar_necesita_parche.setToolTip(
            "Se marca solo al activar cualquier casilla de arriba (para la consola de "
            "destino elegida); si las desmarcas todas, vuelve al estado inicial")
        self.btn_marcar_necesita_parche.setStyleSheet(_estilo_btn_cat("#4e9ef6"))
        self.btn_marcar_necesita_parche.clicked.connect(self._marcar_necesita_parche)
        self.btn_marcar_incompatible = QPushButton("No funciona")
        self.btn_marcar_incompatible.setToolTip(
            "No funciona en el copión con ningún parche conocido todavía")
        self.btn_marcar_incompatible.setStyleSheet(_estilo_btn_cat("#f2673e"))
        self.btn_marcar_incompatible.clicked.connect(self._marcar_incompatible)
        self._grupo_estado_cat = QButtonGroup(self)
        self._grupo_estado_cat.setExclusive(True)
        for b in (self.btn_marcar_compatible, self.btn_marcar_necesita_parche,
                  self.btn_marcar_incompatible):
            b.setCursor(Qt.PointingHandCursor)
            b.setCheckable(True)
            self._grupo_estado_cat.addButton(b)
            fila_cat.addWidget(b)
        pl.addLayout(fila_cat)

        col_der.addWidget(self.parches_card)
        self.parches_card.setVisible(system in ("snes", "genesis"))

        # --- ruta a ucon64 ---
        uc_card = QFrame()
        uc_card.setObjectName("Tarjeta")
        ucl = QVBoxLayout(uc_card)
        ucl.setContentsMargins(14, 10, 14, 12)
        ucl.setSpacing(6)
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
        ucl.addLayout(uc_row)

        if not self._ucon64:
            missing = QLabel(
                "No se ha encontrado uCON64 en el sistema. Instálalo (en Debian/Ubuntu: "
                "<code>sudo apt install ucon64</code>, o compílalo desde ucon64.sourceforge.io) "
                "e indica aquí su ruta."
            )
            missing.setWordWrap(True)
            missing.setStyleSheet("color: #ffb454; font-size: 11px;")
            ucl.addWidget(missing)
        col_der.addWidget(uc_card)

        if os.name != "nt":
            # El diagnóstico de permisos de grupo/CUPS/dispositivo parport solo
            # tiene sentido en Linux — en Windows los problemas de esta misma
            # transferencia son de otra naturaleza por completo (drivers de
            # terceros, chipsets concretos), ya avisados aparte más abajo.
            diag_btn = QPushButton("🩺  Comprobar requisitos del sistema")
            diag_btn.setCursor(Qt.PointingHandCursor)
            diag_btn.setToolTip(
                "Revisa los problemas más habituales que hacen que la transferencia "
                "no funcione sin dar ningún error visible: permisos de grupo, "
                "dispositivo de puerto paralelo, impresoras CUPS que lo acaparen…")
            diag_btn.setStyleSheet(
                "QPushButton { background: rgba(78,158,246,0.10); color: #4e9ef6;"
                " border: 2px solid #2b4d6b; border-radius: 6px; padding: 10px 14px;"
                " font-weight: 700; font-size: 13px; }"
                "QPushButton:hover { border-color: #4e9ef6; background: rgba(78,158,246,0.18); }"
            )
            diag_btn.clicked.connect(lambda: DiagnosticoDialog(self, self._ucon64_diagnostico()).exec())
            col_der.addWidget(diag_btn)

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
        hw.setFixedWidth(320)  # ver el comentario en la definición de col_der_widget
        hw.setStyleSheet("color: #8892a8; font-size: 11px;")
        hwl.addWidget(hw)
        col_der.addWidget(hw_card)

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
        if initial_rom:
            self._analizar_candidatos_parches(initial_rom)

        if os.name != "nt":
            # Aviso automático la primera vez, solo si de verdad hay algo que
            # corregir — no cada vez que se abre el diálogo, y no si ya está
            # todo en orden (eso sería ruido, no ayuda). QSettings recuerda
            # que ya se avisó, así que no vuelve a insistir en próximas
            # sesiones aunque el problema siga sin solucionarse: se puede
            # repetir la comprobación manualmente con el botón de arriba
            # cuando se quiera.
            ya_avisado = _settings().value("transfer/diagnostico_avisado", False, type=bool)
            if not ya_avisado:
                diagnostico = sc.diagnosticar(self._ucon64_diagnostico())
                if diagnostico.hay_problemas_accionables:
                    QTimer.singleShot(200, lambda: DiagnosticoDialog(self, self._ucon64_diagnostico()).exec())
                _settings().setValue("transfer/diagnostico_avisado", True)

        # Se deja que Qt recalcule el tamaño óptimo del diálogo completo
        # ahora que todos los widgets existen y sus anchos definitivos ya
        # se conocen: solo fijar un ancho mínimo no bastaba, porque el
        # texto con salto de línea de las tarjetas de la columna derecha
        # (parches al vuelo, requisitos de hardware) se calculaba con un
        # sizeHint inicial que no correspondía al ancho real que acabarían
        # teniendo dentro de su columna — el resultado era texto cortado a
        # media frase, con la ventana quedándose más baja de lo que su
        # propio contenido necesitaba. adjustSize() no bastaba aquí (no
        # recalculaba correctamente en un QDialog con este layout);
        # resize(sizeHint()) sí obtiene el tamaño real que hace falta.
        self.resize(self.sizeHint())

    # -- interfaz ---------------------------------------------------------
    def _on_tipo_changed(self, *_args):
        c = self._current_copier()
        if self.sram_radio.isChecked():
            self.tipo_lbl.setText(
                "Se transferirá el contenido de la SRAM: las partidas guardadas del "
                f"cartucho, no el juego. uCON64 usará la opción {c.sram_option}."
            )
            self.parches_card.setVisible(False)  # los parches solo tienen sentido para la ROM
        else:
            self.tipo_lbl.setText(
                "Se transferirá la ROM completa del juego al copión. "
                f"uCON64 usará la opción {c.rom_option}."
            )
            self.parches_card.setVisible(self._system in ("snes", "genesis"))

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

    def _ucon64_diagnostico(self) -> str | None:
        """El uCON64 que se usará de verdad, para que el diagnóstico juzgue ese
        y no la primera copia que haya en el PATH (ver system_check)."""
        try:
            txt = self.ucon64_edit.text().strip()
        except AttributeError:
            txt = ""
        return (tu.find_ucon64(txt) if txt else None) or self._ucon64

    def _puerto_argumento(self, ucon64: str | None, port: str | None) -> str | None:
        """Valor a pasar en --port. uCON64 IGNORA --port=/dev/parportN (solo
        entiende direcciones numéricas o usb0); el dispositivo se elige en
        ~/.ucon64rc. Por eso, si se eligió un /dev/parportN, se guarda ahí y
        no se pasa --port. Antes los botones /dev/parportN pasaban una opción
        ignorada y la transferencia usaba siempre el dispositivo del rc."""
        if not port or not port.startswith("/dev/"):
            return port
        ok, msg = tu.fijar_parport_dev(port, ucon64)
        self._log(("# " if ok else "# ERROR: ") + msg)
        return None

    def _port_value(self) -> str | None:
        for valor, btn in self._puerto_btns.items():
            if btn.isChecked():
                return None if valor == "(automático)" else valor
        txt = self.port_custom_edit.text().strip()
        return txt or None

    def _resaltar_puerto_elegido(self, valor: str | None):
        """Marca visualmente cuál de los botones o el campo manual es el
        activo — necesario aparte del propio :checked de los botones,
        porque el campo manual no tiene un estado "marcado" nativo."""
        self.port_custom_edit.setProperty("activo", valor is None)
        self.port_custom_edit.style().unpolish(self.port_custom_edit)
        self.port_custom_edit.style().polish(self.port_custom_edit)

    def _elegir_puerto_boton(self, valor: str):
        self.port_custom_edit.blockSignals(True)
        self.port_custom_edit.clear()
        self.port_custom_edit.blockSignals(False)
        self._resaltar_puerto_elegido(valor)
        _settings().setValue("transfer/port", valor)

    def _elegir_puerto_manual(self):
        texto = self.port_custom_edit.text().strip()
        if not texto:
            return
        self._puerto_grupo.setExclusive(False)
        for btn in self._puerto_btns.values():
            btn.setChecked(False)
        self._puerto_grupo.setExclusive(True)
        self._resaltar_puerto_elegido(None)
        _settings().setValue("transfer/port", texto)

    def _reset_port(self):
        """Ejecuta ucon64 --xreset con el puerto elegido, sin ninguna
        transferencia de por medio — para comprobaciones sueltas del
        estado del puerto mientras se investiga un problema de hardware.
        Usa el mismo mecanismo asíncrono que _start() (subprocess.Popen +
        QTimer en Windows, QProcess en el resto) en vez de una llamada
        bloqueante: un subprocess.run() con CREATE_NEW_CONSOLE congela por
        completo el bucle de eventos de Qt mientras la consola de uCON64
        está abierta — nada de ratón, teclado ni repintado en toda la
        aplicación, no solo en esta ventana — y una aplicación que Windows
        marca como "no responde" durante un rato puede quedar con el foco
        de sus ventanas hijas (como el desplegable de este combo) en un
        estado extraño después, aunque el bloqueo en sí ya haya pasado."""
        if self._process is not None or self._popen is not None:
            return  # ya hay algo en marcha (transferencia o reset previo)
        ucon64 = self.ucon64_edit.text().strip() or None
        ucon64 = tu.find_ucon64(ucon64) if ucon64 else tu.find_ucon64()
        if not ucon64:
            QMessageBox.warning(self, "Resetear puerto",
                                 "No se encontró ucon64 — indica su ruta arriba.")
            return
        port = self._port_value()
        if not port:
            QMessageBox.warning(self, "Resetear puerto",
                                 "Elige primero un puerto concreto arriba — "
                                 "\"(automático)\" no vale para esto, hace "
                                 "falta indicar la dirección exacta.")
            return
        arg_puerto = self._puerto_argumento(ucon64, port)
        cmd = [ucon64, "--xreset"] + ([f"--port={arg_puerto}"] if arg_puerto else [])
        self._log("$ " + " ".join(cmd))
        working_dir = os.path.dirname(ucon64) or "."

        self._reset_en_curso = True
        self._popen = None
        self._process = None
        self._poll_timer = None

        if os.name == "nt":
            CREATE_NEW_CONSOLE = 0x00000010
            self._log(
                "Se abre una ventana de consola aparte para uCON64 (misma "
                "limitación que en una transferencia normal) — se cierra "
                "sola en cuanto --xreset termina.")
            try:
                self._popen = subprocess.Popen(
                    cmd, cwd=working_dir, creationflags=CREATE_NEW_CONSOLE)
            except OSError as e:
                self._log(f"[ERROR] no se pudo iniciar el proceso: {e}")
                self._reset_en_curso = False
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
            self._process.closeWriteChannel()

        self._set_running(True)

    def _log(self, text: str):
        self.console.appendPlainText(text.rstrip())

    # -- ejecución --------------------------------------------------------
    def _guardar_temporal(self, datos: bytes, extension: str) -> str:
        tmp = tempfile.NamedTemporaryFile(
            prefix="asturconsole_envio_", suffix=extension, delete=False)
        tmp.write(datos)
        tmp.close()
        self._rom_temporal = tmp.name
        return tmp.name

    def _analizar_candidatos_parches(self, rom_path: str):
        """Pre-marca las casillas de parches al vuelo según una lista
        curada de juegos conocidos (ver parches_conocidos.py), identificada
        por el CRC32 exacto del ROM — NO ejecutando los patrones de
        búsqueda binaria a ciegas sobre el archivo para ver qué "coincide":
        eso puede dar falsos positivos (un patrón corto que coincide por
        pura casualidad en algún punto de un ROM de varios megabytes, sin
        que el juego tenga relación real con esa protección — ocurrió con
        el patrón de SlowROM sobre Donkey Kong Country durante las
        pruebas). Mientras el juego no esté en la lista, todo empieza
        desmarcado: es preferible no proponer nada a proponer algo por una
        coincidencia casual. El usuario conserva siempre el control manual
        completo sobre cada casilla, la haya marcado la detección o no.

        También deja constancia del estado de compatibilidad conocido
        (self._crc_actual + el texto de estado_compat_lbl), para que
        _start() pueda avisar antes de enviar un juego ya confirmado como
        incompatible, y para que los tres botones de catalogación rápida
        sepan sobre qué CRC32 están guardando. self._nombre_actual guarda
        también un nombre legible del juego (título interno del ROM, o el
        nombre de archivo si no se puede leer la cabecera) — sin esto, el
        catálogo solo tendría CRC32 como clave y sería ilegible para
        cualquiera que lo abra a consultar qué es cada entrada.
        """
        self._crc_actual = None
        # Sin ROM válida no debe quedar nada del ROM anterior (si no, mover
        # el interruptor de destino volvería a pre-marcar sus casillas).
        self._variante_dual_actual = None
        self._region_nativa_actual = "NTSC"
        self._conocidos_actual = pc.ParchesConocidos()
        self._nombre_actual = os.path.splitext(os.path.basename(rom_path))[0] if rom_path else ""
        self.estado_compat_lbl.setText("")
        if self._system not in ("snes", "genesis") or not rom_path or not os.path.isfile(rom_path):
            return
        try:
            with open(rom_path, "rb") as fh:
                datos = fh.read()
        except OSError:
            return

        if self._system == "genesis":
            info = gt.detect_smd_header(datos)
            cuerpo = datos[info.size:] if info.present else datos
            if info.present:
                # El cuerpo de un archivo SMD está entrelazado (bytes pares
                # e impares separados en dos mitades) — el checksum (y el
                # CRC32 con el que se identifica el juego) se calculan
                # sobre el ROM plano, así que hay que desentrelazar antes.
                cuerpo = gt._convert(cuerpo, first_half_is_odd=True, deinterleave=True)
            crc = f"{zlib.crc32(cuerpo) & 0xFFFFFFFF:08x}"
            conocidos = pc.buscar("genesis", crc)
            self.chk_checksum.setChecked(conocidos.checksum)
            self.chk_region_genesis.setChecked(conocidos.region)
            self._crc_actual = crc
            header_gen, _err = rf.parse_genesis(cuerpo)
            if header_gen:
                nombre_interno = (header_gen.overseas or header_gen.domestic).strip()
                if nombre_interno:
                    self._nombre_actual = nombre_interno
            self._mostrar_estado_compat(conocidos)
            return

        ya_tiene_cabecera = st.detect_copier_header(datos).present
        cuerpo = datos[512:] if ya_tiene_cabecera else datos
        crc = f"{zlib.crc32(cuerpo) & 0xFFFFFFFF:08x}"
        self._variante_dual_actual = pc.buscar_variante_dual("snes", crc)
        conocidos = self._variante_dual_actual.base if self._variante_dual_actual else pc.buscar_sugerencia("snes", crc)
        self._conocidos_actual = conocidos
        header_snes, _err = rf.parse_snes(cuerpo)
        if header_snes and header_snes.valid and header_snes.title.strip():
            self._nombre_actual = header_snes.title.strip()
        # Región nativa: prioridad a VarianteDual (curada y verificada a
        # mano para el puñado de casos especiales) — si no hay, se lee el
        # destination code de la propia cabecera del ROM (ver
        # rf.region_video). Solo si ninguna de las 2 fuentes da nada
        # (cabecera inválida, o destination code ambiguo/fuera de tabla)
        # se cae a "NTSC" como último recurso, ya que es la región de la
        # inmensa mayoría del catálogo con el que se ha trabajado hasta
        # ahora. Antes de esto SIEMPRE se asumía NTSC salvo para los 2
        # casos en VARIANTES_DUALES_SNES -- bug real encontrado por el
        # usuario con Actraiser 2 (Europe): con consola NTSC elegida (no
        # coincide con la región real PAL del ROM) el parche no se
        # marcaba, y con PAL elegida (si coincidía "por casualidad" con
        # lo que el catálogo esperaba) sí -- exactamente al revés de lo
        # que debía pasar, porque el ROM nunca llegaba a decir cuál era
        # su propia región real.
        if self._variante_dual_actual is not None:
            self._region_nativa_actual = self._variante_dual_actual.region_nativa
        elif header_snes and header_snes.valid:
            self._region_nativa_actual = rf.region_video(header_snes.dest_code) or "NTSC"
        else:
            self._region_nativa_actual = "NTSC"
        # Preseleccionar el interruptor: si el usuario ya eligió alguna
        # vez su consola real a mano, esa elección es un hecho sobre SU
        # hardware (no cambia de un ROM a otro) y tiene prioridad sobre
        # la región nativa del ROM que se acaba de cargar — sin esto,
        # cada ROM PAL que se carga reinicia el interruptor a PAL aunque
        # el usuario ya haya dicho antes que su consola real es NTSC,
        # obligando a re-marcarlo a mano en cada ROM distinto (bug real
        # reportado por el usuario probando el catálogo PAL entero: "el
        # interruptor siempre se va a PAL"). Solo si nunca se ha
        # guardado ninguna preferencia (primer uso) se cae a la región
        # nativa del ROM como mejor suposición de partida.
        preferencia_guardada = _settings().value("transfer/consola_destino", "")
        if preferencia_guardada in ("PAL", "NTSC"):
            destino_inicial = preferencia_guardada
        else:
            destino_inicial = self._region_nativa_actual
        if destino_inicial == "PAL":
            self.btn_destino_pal.setChecked(True)
        else:
            self.btn_destino_ntsc.setChecked(True)
        # Las 4 casillas las rellena _actualizar_parches_segun_destino
        # (ficha propia del usuario para ese destino si la hay, o la
        # sugerencia del catálogo si no).
        self._crc_actual = crc
        self._actualizar_parches_segun_destino()

    def _guardar_preferencia_destino(self):
        """Guarda en QSettings qué consola de destino ha dejado marcada
        el usuario (NTSC o PAL), para que sea el valor de partida en
        cualquier otro ROM que cargue después — ver el comentario en
        _analizar_candidatos_parches sobre por qué esto tiene prioridad
        sobre la región nativa detectada del propio ROM."""
        destino = "PAL" if self.btn_destino_pal.isChecked() else "NTSC"
        _settings().setValue("transfer/consola_destino", destino)

    # -- fichas de parches por consola de destino (SNES) --------------------
    # Un mismo juego puede necesitar cosas distintas según a qué consola
    # vaya (un dump PAL en consola NTSC: -k y -f; en consola PAL: solo -k),
    # así que lo que el usuario marca se guarda POR DESTINO: NTSC y PAL
    # tienen cada una su propia ficha, con sus propias casillas, y se
    # guardan solas en cuanto se marca o desmarca algo (ver _casilla_cambiada).
    def _clave_destino(self) -> str:
        return "PAL" if self.btn_destino_pal.isChecked() else "NTSC"

    def _sugerencia_destino(self, destino: str) -> pc.ParchesConocidos:
        """Lo que sugiere el catálogo OFICIAL (o una ficha antigua de
        formato plano) para este destino, sin contar las fichas por destino
        del usuario. Para el -f solo tiene sentido sugerirlo cuando el
        destino NO es la región nativa del dump (si lo es, el ROM ya
        funciona tal cual)."""
        nativo = (destino == self._region_nativa_actual)
        if self._variante_dual_actual is not None:
            base = self._variante_dual_actual.base
            return pc.ParchesConocidos(
                estado=base.estado, crack=base.crack, pal=not nativo,
                slowrom=base.slowrom, checksum=base.checksum, notas=base.notas)
        c = self._conocidos_actual
        return pc.ParchesConocidos(
            estado=c.estado, crack=c.crack, pal=(not nativo) and c.pal,
            slowrom=c.slowrom, checksum=c.checksum, notas=c.notas)

    def _ficha_efectiva(self, destino: str) -> tuple[pc.ParchesConocidos, bool]:
        """(ficha, es_del_usuario): 1) lo que el usuario marcó a mano para
        este juego y destino -- manda sobre todo, porque es lo que ha
        comprobado él en hardware real --; 2) la ficha del catálogo que
        instala la aplicación (parches-snes-asturconsole.json); 3) la
        sugerencia oficial. Solo el caso 1 cuenta como "propia"."""
        if self._crc_actual:
            ficha = pc.buscar_destino("snes", self._crc_actual, destino)
            if ficha is not None:
                return ficha, ficha.usuario
        return self._sugerencia_destino(destino), False

    def _estado_catalogo_actual(self) -> str:
        if self._system == "snes":
            return self._ficha_efectiva(self._clave_destino())[0].estado
        return pc.buscar(self._system, self._crc_actual).estado

    def _poner_casillas(self, ficha: pc.ParchesConocidos):
        """Rellena las casillas SNES desde una ficha. setChecked no emite
        `clicked`, así que esto nunca dispara el guardado automático."""
        self.chk_crack.setChecked(ficha.crack)
        self.chk_pal.setChecked(ficha.pal)
        self.chk_slowrom.setChecked(ficha.slowrom)
        self.chk_checksum.setChecked(ficha.checksum)

    def _ficha_desde_casillas(self) -> pc.ParchesConocidos:
        return pc.ParchesConocidos(
            crack=self.chk_crack.isChecked(), pal=self.chk_pal.isChecked(),
            slowrom=self.chk_slowrom.isChecked(), checksum=self.chk_checksum.isChecked(),
            notas=self._nombre_actual)

    def _guardar_ficha_destino(self, destino: str, ficha: pc.ParchesConocidos) -> bool:
        """Guarda la ficha de un destino. Si el juego tenía una ficha
        antigua de formato plano (válida para cualquier destino), lo que
        significaba para el OTRO destino se conserva sembrándolo, para no
        perder lo que ya estaba guardado al pasar al formato por destino."""
        otro = "NTSC" if destino == "PAL" else "PAL"
        try:
            pc.guardar_destino_usuario(
                "snes", self._crc_actual, destino, ficha, self._nombre_actual,
                sembrar={otro: self._sugerencia_destino(otro)})
        except OSError as e:
            self.estado_compat_lbl.setText(f"✗ No se pudo guardar en tu catálogo: {e}")
            self.estado_compat_lbl.setStyleSheet(
                "font-size: 11px; font-weight: 700; color: #f2673e;")
            return False
        return True

    def _reiniciar_destino(self, destino: str):
        """Todas las casillas desmarcadas a mano: este destino vuelve a su
        estado inicial (ninguno de los 3 botones de estado marcado). Si el
        catálogo (el oficial o el de la aplicación) tenía algo para este juego/destino, se guarda
        una ficha vacía como marca de "vaciado a propósito" -- si no, la
        sugerencia volvería a aparecer sola al reabrir el juego y parecería
        que el cambio no se guardó. Si no sugería nada, simplemente se
        borra la ficha del usuario."""
        sug = pc.buscar_destino_app("snes", self._crc_actual, destino) \
            or self._sugerencia_destino(destino)
        hay_sugerencia = (not sug.vacio()) or sug.estado in (
            pc.ESTADO_COMPATIBLE, pc.ESTADO_INCOMPATIBLE)
        if hay_sugerencia:
            self._guardar_ficha_destino(
                destino, pc.ParchesConocidos(estado=pc.ESTADO_DESCONOCIDO,
                                              notas=self._nombre_actual))
        else:
            pc.borrar_destino_usuario("snes", self._crc_actual, destino)
        self.destino_nota_lbl.setText("")
        self._mostrar_estado_compat(pc.ParchesConocidos(), True)

    def _casilla_cambiada(self, _checked: bool = False):
        """El usuario ha marcado o desmarcado una casilla de parche: se
        guarda en el acto lo marcado para la consola de destino elegida, y
        el estado pasa solo a "Necesita parche". Si deja TODAS
        desmarcadas, ese destino vuelve al estado inicial."""
        if self._system != "snes" or not self._crc_actual:
            return
        destino = self._clave_destino()
        ficha = self._ficha_desde_casillas()
        if ficha.vacio():
            self._reiniciar_destino(destino)
            return
        ficha.estado = pc.ESTADO_NECESITA_PARCHE
        if self._guardar_ficha_destino(destino, ficha):
            self.destino_nota_lbl.setText(self._nota_ficha_propia(destino, ficha))
            self._mostrar_estado_compat(ficha, True)

    @staticmethod
    def _nota_ficha_propia(destino: str, ficha: pc.ParchesConocidos) -> str:
        if ficha.estado == pc.ESTADO_NECESITA_PARCHE:
            return f"Parches guardados por ti para consola {destino}."
        if ficha.estado == pc.ESTADO_COMPATIBLE:
            return f"Marcado por ti como compatible con consola {destino}."
        if ficha.estado == pc.ESTADO_INCOMPATIBLE:
            return f"Marcado por ti como que no funciona en consola {destino}."
        return ""

    def _actualizar_parches_segun_destino(self):
        """Rellena las casillas de "parches al vuelo" para el ROM cargado
        y la consola de destino elegida en el interruptor. Se llama tanto
        al cambiar de ROM como al mover el propio interruptor.

        Orden de prioridad: 1) la ficha que el USUARIO guardó para este
        juego y ESTE destino (cada destino tiene la suya, ver
        _ficha_efectiva); 2) si no hay, la sugerencia del catálogo
        (_sugerencia_destino).

        Las casillas quedan SIEMPRE editables a mano, sea cual sea el
        tipo de juego (normal o de doble variante) -- lo que cambia aquí
        es solo con qué se pre-marcan, nunca si el usuario puede tocarlas.
        (La primera versión las deshabilitaba para los juegos de doble
        variante y, si el usuario discrepaba de la sugerencia, no había
        forma de marcarlas a mano: bug real.)"""
        if self._system != "snes":
            return
        destino = self._clave_destino()
        ficha, es_propia = self._ficha_efectiva(destino)
        self._poner_casillas(ficha)
        self.chk_pal.setEnabled(True)
        self.chk_crack.setEnabled(True)
        destino_es_nativo = (destino == self._region_nativa_actual)
        if es_propia:
            self.destino_nota_lbl.setText(self._nota_ficha_propia(destino, ficha))
        elif self._variante_dual_actual is not None:
            self.destino_nota_lbl.setText(
                f"Región nativa de este dump: {self._region_nativa_actual}. "
                f"{'No hace falta tocar nada de región.' if destino_es_nativo else 'Se invertirá la comprobación de región si la casilla sigue marcada.'}")
        else:
            self.destino_nota_lbl.setText(
                "" if destino_es_nativo or not ficha.pal else
                "Fix de región marcado automáticamente para este destino.")
        self._mostrar_estado_compat(ficha, es_propia)

    def _mostrar_estado_compat(self, conocidos: pc.ParchesConocidos, es_propia: bool = False):
        # El flag "pal" (y, para juegos de doble variante, la propia
        # necesidad de invertir la comprobación) es DIRECCIONAL: solo
        # hace falta cuando la consola elegida es la región CONTRARIA a
        # la nativa del juego -- a diferencia de crack/slowrom/checksum,
        # que no dependen de qué consola se haya elegido. Sin esto, un
        # juego catalogado como "necesita_parche" por el flag pal
        # mostraba siempre ese aviso, incluso con la consola de la misma
        # región que el juego, donde en realidad no hace falta nada (bug
        # real reportado por el usuario con Maui Mallard in Cold
        # Shadow). Solo aplica a sugerencias del catálogo: una ficha
        # guardada por el usuario para este destino (es_propia) se
        # muestra tal cual, es exactamente lo que él ha marcado.
        # Genesis no tiene este interruptor, así que se muestra tal cual.
        estado_mostrado = conocidos.estado
        sufijo = ""
        if self._system == "snes" and not es_propia and \
                conocidos.estado == pc.ESTADO_NECESITA_PARCHE:
            destino = self._clave_destino()
            destino_es_nativo = (destino == self._region_nativa_actual)
            if self._variante_dual_actual is not None:
                necesita_region = not destino_es_nativo
            else:
                necesita_region = conocidos.pal and not destino_es_nativo
            necesita_algo_mas = conocidos.crack or conocidos.slowrom or conocidos.checksum
            if not necesita_region and not necesita_algo_mas:
                estado_mostrado = pc.ESTADO_COMPATIBLE
                sufijo = " (consola misma región que el juego)"
        if self._system == "snes" and es_propia and estado_mostrado != pc.ESTADO_DESCONOCIDO:
            sufijo += f" · consola {self._clave_destino()}"
        textos = {
            pc.ESTADO_COMPATIBLE: (f"✓ Compatible — funciona tal cual, sin parches{sufijo}", "#3ef29a"),
            pc.ESTADO_NECESITA_PARCHE: (f"🔧 Necesita parche — revisa las casillas de abajo{sufijo}", "#4e9ef6"),
            pc.ESTADO_INCOMPATIBLE: (f"✗ No funciona en el copión — se avisará al enviar{sufijo}", "#f2673e"),
        }
        texto, color = textos.get(estado_mostrado, ("", "#8892a8"))
        self.estado_compat_lbl.setText(texto)
        self.estado_compat_lbl.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {color};")
        # Además del texto, resaltar el propio botón que corresponde al
        # estado actual de este ROM -- de un vistazo, sin tener que leer
        # nada, ya se ve si está marcado como compatible/con parche/roto.
        # Para "desconocido" (ROM aún sin catalogar) no se resalta
        # ninguno: setChecked(False) en un QButtonGroup exclusivo sí
        # permite dejarlo así, solo impide que 2 queden marcados a la vez.
        botones_por_estado = {
            pc.ESTADO_COMPATIBLE: self.btn_marcar_compatible,
            pc.ESTADO_NECESITA_PARCHE: self.btn_marcar_necesita_parche,
            pc.ESTADO_INCOMPATIBLE: self.btn_marcar_incompatible,
        }
        boton_activo = botones_por_estado.get(estado_mostrado)
        # setExclusive(False) un instante: en un grupo exclusivo Qt no deja
        # desmarcar el botón que está marcado, y hace falta poder dejar
        # los tres sin marcar (estado inicial).
        self._grupo_estado_cat.setExclusive(False)
        for b in (self.btn_marcar_compatible, self.btn_marcar_necesita_parche,
                  self.btn_marcar_incompatible):
            b.setChecked(b is boton_activo)
        self._grupo_estado_cat.setExclusive(True)

    def _guardar_estado_actual(self, estado: str, con_casillas: bool):
        if not self._crc_actual:
            QMessageBox.information(
                self, "Transferencia",
                "Elige primero una ROM para poder guardar su estado.")
            self._mostrar_estado_compat(pc.ParchesConocidos())
            return
        if self._system == "snes":
            # Cada botón guarda SOLO la ficha de la consola de destino
            # elegida; la del otro destino no se toca.
            destino = self._clave_destino()
            if con_casillas:
                ficha = self._ficha_desde_casillas()
                if ficha.vacio():
                    # "Necesita parche" sin ninguna casilla marcada no
                    # dice qué parche hace falta: no se guarda nada.
                    ficha_actual, propia = self._ficha_efectiva(destino)
                    self._mostrar_estado_compat(ficha_actual, propia)
                    self.estado_compat_lbl.setText(
                        "Marca primero las casillas de parche que necesita "
                        "con esta consola — se guardan solas.")
                    self.estado_compat_lbl.setStyleSheet(
                        "font-size: 11px; font-weight: 700; color: #e8b84a;")
                    return
                ficha.estado = estado
            else:
                # Compatible / No funciona = sin ningún parche: las
                # casillas se desmarcan para que lo que se ve sea lo que
                # se ha guardado.
                ficha = pc.ParchesConocidos(estado=estado, notas=self._nombre_actual)
                self._poner_casillas(ficha)
            if self._guardar_ficha_destino(destino, ficha):
                self.destino_nota_lbl.setText(self._nota_ficha_propia(destino, ficha))
                self._mostrar_estado_compat(ficha, True)
            return
        if con_casillas and self._system == "genesis":
            parches = pc.ParchesConocidos(
                estado=estado, checksum=self.chk_checksum.isChecked(),
                region=self.chk_region_genesis.isChecked(), notas=self._nombre_actual)
        else:
            parches = pc.ParchesConocidos(estado=estado, notas=self._nombre_actual)
        pc.guardar_en_catalogo_usuario(self._system, self._crc_actual, parches)
        self._mostrar_estado_compat(parches)

    def _marcar_compatible(self):
        self._guardar_estado_actual(pc.ESTADO_COMPATIBLE, con_casillas=False)

    def _marcar_necesita_parche(self):
        self._guardar_estado_actual(pc.ESTADO_NECESITA_PARCHE, con_casillas=True)

    def _marcar_incompatible(self):
        self._guardar_estado_actual(pc.ESTADO_INCOMPATIBLE, con_casillas=False)

    def _preparar_rom_para_envio(self, rom_path: str) -> str | None:
        """Aplica automáticamente, sobre una copia temporal, lo que haga
        falta antes de enviar — cabecera de copión, y en SNES el crack/fix
        PAL si hay algún patrón conocido aplicable — para no exigir que el
        usuario haya pasado antes por "Añadir cabecera" como paso manual
        aparte: elige la ROM tal cual la tenga (incluso sin cabecera, sin
        corregir) y esta función deja lista una versión preparada. El
        archivo ORIGINAL nunca se toca. Si ya estaba completo (cabecera ya
        puesta, sin ningún patrón conocido pendiente), devuelve la MISMA
        ruta sin generar nada. Devuelve None solo si no se pudo leer el
        archivo en absoluto.
        """
        if self._system not in ("snes", "genesis"):
            return rom_path  # MSX no pasa por este diálogo

        try:
            with open(rom_path, "rb") as fh:
                datos = fh.read()
        except OSError as e:
            QMessageBox.critical(self, "Transferencia", f"No se pudo leer el archivo: {e}")
            return None

        if self._system == "genesis":
            info = gt.detect_smd_header(datos)
            ya_tiene_cabecera = info.present
            cuerpo = datos[info.size:] if ya_tiene_cabecera else datos

            # Se trabaja siempre sobre el cuerpo PLANO (desentrelazando una
            # sola vez aquí si el archivo ya viene en SMD, y volviendo a
            # entrelazar una sola vez al final) — todos los parches de
            # Genesis (región y checksum) necesitan el ROM plano, y hacerlo
            # de una vez es más simple y menos propenso a errores que
            # desentrelazar/entrelazar por separado para cada uno.
            cuerpo_plano = (
                gt._convert(cuerpo, first_half_is_odd=True, deinterleave=True)
                if ya_tiene_cabecera else cuerpo
            )

            cambios_txt = []
            if self.chk_region_genesis.isChecked():
                header_g, _e = rf.parse_genesis(cuerpo_plano)
                es_ntsc = gt.es_region_ntsc(header_g.region) if header_g else True
                cuerpo_plano, cambios_region = gt.aplicar_fix_region(cuerpo_plano, es_ntsc)
                cambios_txt += cambios_region

            if self.chk_checksum.isChecked():
                try:
                    cuerpo_plano, checksum, ya_era_correcto = gt.fix_checksum(cuerpo_plano)
                except ValueError as e:
                    QMessageBox.critical(self, "Transferencia", str(e))
                    return None
                if not ya_era_correcto:
                    cambios_txt.append(f"checksum corregido (0x{checksum:04x})")

            cuerpo = (
                gt._convert(cuerpo_plano, first_half_is_odd=True, deinterleave=False)
                if ya_tiene_cabecera else cuerpo_plano
            )

            if not ya_tiene_cabecera:
                try:
                    resultado = gt.bin_to_smd(cuerpo, add_header=True)
                except ValueError as e:
                    QMessageBox.critical(self, "Transferencia", str(e))
                    return None
            else:
                resultado = datos[:info.size] + cuerpo

            if not ya_tiene_cabecera or cambios_txt:
                aviso = "Preparado para enviar, al vuelo (sin guardar ningún archivo)."
                if not ya_tiene_cabecera:
                    aviso += " Cabecera SMD añadida."
                if cambios_txt:
                    aviso += f" Parches aplicados: {', '.join(cambios_txt)}."
                self._log(aviso)
                return self._guardar_temporal(resultado, ".smd")

            return rom_path  # ya listo tal cual, nada que preparar

        # SNES
        ya_tiene_cabecera = st.detect_copier_header(datos).present
        cuerpo = datos[512:] if ya_tiene_cabecera else datos
        header, _err = rf.parse_snes(cuerpo)
        sram_size = st.sram_size_from_ram_size_n(header.ram_size_n) if header else 32 * 1024
        hirom = bool(header and "HiROM" in header.kind)

        # Los parches se aplican según lo que el usuario haya marcado en
        # las casillas "PARCHES AL VUELO" — no hay pregunta modal aquí:
        # las casillas ya están pre-marcadas según lo detectado en el ROM
        # (ver _analizar_candidatos_parches), pero la decisión final es
        # siempre la que el usuario tenga marcada en ese momento, lo haya
        # cambiado o no. Esto incluye los juegos de doble variante — sus
        # casillas son tan editables como las de cualquier otro juego
        # (ver el comentario extenso en _actualizar_parches_segun_destino
        # sobre el bug que esto corrigió).
        cuerpo_final = cuerpo
        cambios_txt = []
        if self._variante_dual_actual is not None:
            if self.chk_crack.isChecked():
                cuerpo_final, ck = crk.aplicar_crack(cuerpo_final, sram_size)
                cambios_txt += ck
            if self.chk_pal.isChecked():
                destino = "PAL" if self.btn_destino_pal.isChecked() else "NTSC"
                destino_es_nativo = (destino == self._variante_dual_actual.region_nativa)
                # Invertir la comprobación de región solo tiene sentido
                # (y es seguro) hacia el destino que NO es la región
                # nativa del dump -- invertirla "hacia" la propia región
                # nativa la rompería en su propia región (ver la lección
                # de RoboCop en la memoria del proyecto: una inversión no
                # es una neutralización universal, discrimina en una
                # dirección concreta). Si el usuario deja la casilla
                # marcada con el destino nativo elegido, simplemente no
                # hay nada seguro que aplicar -- se ignora sin avisar,
                # ya que no hacer nada ahí es exactamente lo correcto.
                if not destino_es_nativo:
                    cuerpo_final, ci = crk.aplicar_inversion_region(
                        cuerpo_final, self._variante_dual_actual.patron_descripcion)
                    cambios_txt += ci
        else:
            if self.chk_crack.isChecked():
                cuerpo_final, ck = crk.aplicar_crack(cuerpo_final, sram_size)
                cambios_txt += ck
            if self.chk_pal.isChecked():
                cuerpo_final, cf = crk.aplicar_fix_pal(cuerpo_final)
                cambios_txt += cf
        if self.chk_slowrom.isChecked():
            cuerpo_final, cl = crk.aplicar_fix_slowrom(cuerpo_final)
            cambios_txt += cl

        if not ya_tiene_cabecera:
            # La cabecera hace falta sí o sí para poder enviarlo.
            resultado = st.add_header(
                cuerpo_final, style=self._current_copier().key,
                hirom=hirom, sram_size=sram_size)
        else:
            resultado = datos[:512] + cuerpo_final

        if self.chk_checksum.isChecked():
            header_final, _e = rf.parse_snes(resultado)
            info_final = st.detect_copier_header(resultado)
            if header_final:
                resultado, checksum, _complemento = st.fix_checksum(
                    resultado, header_final.base,
                    info_final.size if info_final.present else 0)
                cambios_txt.append(f"checksum corregido ({rf.hexn(checksum, 4)})")

        if not ya_tiene_cabecera or cambios_txt:
            aviso = "Preparado para enviar, al vuelo (sin guardar ningún archivo)."
            if not ya_tiene_cabecera:
                aviso += " Cabecera de copión añadida."
            if cambios_txt:
                aviso += f" Parches aplicados: {', '.join(cambios_txt)}."
            self._log(aviso)
            return self._guardar_temporal(resultado, ".swc")

        return rom_path  # ya listo tal cual, nada que preparar

    def _limpiar_temporal(self):
        if self._rom_temporal and os.path.exists(self._rom_temporal):
            try:
                os.remove(self._rom_temporal)
            except OSError:
                pass
        self._rom_temporal = None

    def _start(self):
        ucon64 = self.ucon64_edit.text().strip() or None
        ucon64 = tu.find_ucon64(ucon64) if ucon64 else tu.find_ucon64()
        rom_original = self.file_edit.text().strip() or None
        copier = self._current_copier()
        port = self._port_value()

        # Aviso antes de enviar un juego que el catálogo (oficial o
        # personal) tiene marcado como incompatible con este copión — se
        # deja seguir si el usuario insiste, pero no en silencio: sin este
        # aviso, "no funciona" y "aún no se ha probado" se verían
        # exactamente igual desde fuera (una transferencia que arranca sin
        # más avisos).
        if (self.rom_radio.isChecked() and self._crc_actual
                and self._estado_catalogo_actual() == pc.ESTADO_INCOMPATIBLE):
            respuesta = QMessageBox.warning(
                self, "Transferencia",
                "Este juego está marcado en el catálogo como que NO funciona "
                "en este copión, y no hay ningún parche conocido todavía.\n\n"
                "¿Enviar de todos modos?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if respuesta != QMessageBox.Yes:
                return

        self._limpiar_temporal()  # por si quedó uno de un intento anterior
        rom = rom_original
        if rom_original and os.path.isfile(rom_original):
            rom = self._preparar_rom_para_envio(rom_original)
            if rom is None:
                return  # error ya mostrado dentro de _preparar_rom_para_envio

        result = tu.preflight(ucon64, rom, copier, port, sending=True)
        if result.warnings:
            texto = "\n\n".join(result.warnings)
            respuesta = QMessageBox.warning(
                self, "Transferencia", f"{texto}\n\n¿Continuar de todos modos?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if respuesta != QMessageBox.Yes:
                self._limpiar_temporal()
                return
        if not result.ok:
            QMessageBox.critical(self, "Transferencia", "\n\n".join(result.errors))
            self._limpiar_temporal()
            return

        self.console.clear()
        cmd = tu.build_command(ucon64, copier, rom, port=self._puerto_argumento(ucon64, port),
                                sram=self.sram_radio.isChecked())
        self._log("$ " + " ".join(cmd))
        if os.name != "nt":
            self._log("# Puerto paralelo: " + (tu.leer_parport_dev() or "/dev/parport0 (por defecto)"))
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
                  self.port_custom_edit, self.rom_radio, self.sram_radio,
                  self.ucon64_edit):
            if w is not None:
                w.setEnabled(not running)
        for btn in self._puerto_btns.values():
            btn.setEnabled(not running)

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
        # Leer cualquier dato pendiente ANTES de soltar la referencia al
        # proceso: si termina extremadamente rápido (por ejemplo, un error
        # inmediato como "permiso denegado" al abrir el puerto, seguido de
        # exit() en el mismo instante), la señal readyReadStandardOutput
        # puede no llegar a procesarse a tiempo, y el mensaje de error se
        # pierde sin más — exactamente lo que pasaba aquí: uCON64 SÍ
        # escribía el error correctamente (confirmado con strace), pero
        # nunca llegaba a verse en esta consola.
        if self._process is not None:
            datos_finales = bytes(self._process.readAllStandardOutput())
            if datos_finales:
                self._procesar_texto(datos_finales.decode("utf-8", errors="replace"))
        self._set_running(False)
        self._process = None
        self._popen = None
        self._limpiar_temporal()

        if exit_code == 0:
            if self._reset_en_curso:
                self._log("\n[Reset del puerto completado]")
            else:
                self._log("\n[Transferencia finalizada correctamente]")
        else:
            etiqueta = "uCON64" if not self._reset_en_curso else "El reset del puerto"
            self._log(f"\n[{etiqueta} terminó con código {exit_code}]")
            if not self._reset_en_curso:
                self._log(
                    "Si el copión no responde: comprueba que está encendido, que el cable es "
                    "bidireccional, que el puerto es correcto y que tienes permisos sobre él."
                )
        self._reset_en_curso = False

        if os.name == "nt":
            # En Windows, la ventana de consola aparte que se abrió para
            # uCON64 (ver _start) se lleva el foco del sistema operativo
            # mientras dura la transferencia. Al cerrarse esa consola, el
            # foco no siempre vuelve solo a esta ventana — a veces se
            # queda en un estado ambiguo en el que los clics del ratón no
            # llegan bien a los widgets (el desplegable del combo de
            # puerto no se abre, por ejemplo), hasta que la ventana se
            # reactiva explícitamente. Se fuerza aquí para que la próxima
            # vez que se abra esta ventana funcione con normalidad.
            self.raise_()
            self.activateWindow()

    def closeEvent(self, event):
        if self._process is not None or self._popen is not None:
            self._cancel()
        self._limpiar_temporal()
        super().closeEvent(event)
