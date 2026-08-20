"""Escritura y formateo de disquetes en una unidad real.

Ofrece las mismas opciones que COPIA720 bajo DOS:

  - Copia directa por sectores (comportamiento por defecto).
  - Formatear cada pista justo antes de grabarla (su opción /F), que es lo
    que permite reutilizar disquetes viejos o de formato distinto.
  - Verificar releyendo cada pista (su opción /V).

Y añade el formateo completo del disquete, a 360, 720 o 1.44 MB.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame,
    QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QRadioButton,
    QVBoxLayout,
)

import rom_formats as rf
import volumes as vol

ESTILO = """
QDialog { background: #0f111a; }
QLabel { color: #dde3ef; }
QRadioButton, QCheckBox { color: #dde3ef; spacing: 9px; padding: 5px; }
QRadioButton::indicator, QCheckBox::indicator {
    width: 17px; height: 17px; border: 2px solid #5a6478; background: #12141c;
}
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:checked { background: #ffb454; border-color: #ffb454; }
QRadioButton::indicator:checked { background: #ffb454; border-color: #ffb454; }
QCheckBox:checked, QRadioButton:checked { color: #ffb454; font-weight: 700; }
QComboBox {
    background: #12141c; color: #dde3ef; border: 1px solid #39404f;
    border-radius: 5px; padding: 6px 8px;
}
QFrame#Bloque {
    background: #161a24; border: 1px solid #2c3342; border-radius: 8px;
}
QLabel#Seccion { color: #8892a8; font-size: 10px; font-weight: 700; }
QProgressBar {
    background: #12141c; border: 1px solid #39404f; border-radius: 5px; height: 10px;
}
QProgressBar::chunk { background: #ffb454; border-radius: 4px; }
"""


class _Worker(QThread):
    progreso = Signal(int, int, int)
    terminado = Signal(bool, list, list, str)

    def __init__(self, modo, device, geometria, datos=None,
                 formatear=False, verificar=False, parent=None):
        super().__init__(parent)
        self._modo = modo            # "escribir" | "formatear"
        self._device = device
        self._geometria = geometria
        self._datos = datos
        self._formatear = formatear
        self._verificar = verificar

    def run(self):
        try:
            if self._modo == "formatear":
                fallos = vol.format_floppy(
                    self._device, self._geometria,
                    progreso=lambda p, t, f: self.progreso.emit(p, t, f))
                self.terminado.emit(True, fallos, [], "")
            else:
                fallos, reform = vol.write_floppy(
                    self._device, self._datos, self._geometria,
                    formatear=self._formatear, verificar=self._verificar,
                    progreso=lambda p, t, f: self.progreso.emit(p, t, f))
                self.terminado.emit(True, fallos, reform, "")
        except Exception as e:  # noqa: BLE001
            self.terminado.emit(False, [], [], str(e))


class FloppyWriteDialog(QDialog):
    def __init__(self, parent=None, image_path: str | None = None,
                 modo: str = "escribir"):
        super().__init__(parent)
        self._modo = modo
        self._image_path = image_path
        self._datos = None
        self._hilo: _Worker | None = None

        self.setWindowTitle("Grabar en disquete real" if modo == "escribir"
                            else "Formatear disquete")
        self.setMinimumWidth(620)
        self.setStyleSheet(ESTILO)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        if modo == "escribir" and image_path:
            try:
                with open(image_path, "rb") as fh:
                    self._datos = fh.read()
            except OSError as e:
                QMessageBox.warning(self, "Grabar", f"No se pudo leer la imagen: {e}")
            cab = QLabel(
                f"<b>Imagen:</b> {os.path.basename(image_path)}<br>"
                f"<b>Tamaño:</b> {rf.fmt_bytes(len(self._datos or b''))}")
            cab.setWordWrap(True)
            lay.addWidget(cab)

        # --- unidad ---
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Unidad:"))
        self.dev_combo = QComboBox()
        for d in vol.list_floppy_drives():
            self.dev_combo.addItem(d, d)
        if self.dev_combo.count() == 0:
            self.dev_combo.addItem("(no se detectó ninguna disquetera)", None)
        fila.addWidget(self.dev_combo, 1)
        lay.addLayout(fila)

        # --- formato ---
        fila2 = QHBoxLayout()
        fila2.addWidget(QLabel("Formato:"))
        self.fmt_combo = QComboBox()
        for clave, info in vol.FLOPPY_GEOMETRIES.items():
            self.fmt_combo.addItem(info["etiqueta"], clave)
        fila2.addWidget(self.fmt_combo, 1)
        lay.addLayout(fila2)

        # El formato se deduce del tamaño de la imagen: es lo correcto y evita
        # que el usuario elija uno incompatible por descuido.
        if self._datos:
            for i in range(self.fmt_combo.count()):
                clave = self.fmt_combo.itemData(i)
                if vol.FLOPPY_GEOMETRIES[clave]["bytes"] == len(self._datos):
                    self.fmt_combo.setCurrentIndex(i)
                    self.fmt_combo.setEnabled(False)
                    break

        if modo == "escribir":
            bloque = QFrame()
            bloque.setObjectName("Bloque")
            bl = QVBoxLayout(bloque)
            bl.setContentsMargins(14, 10, 14, 12)
            bl.setSpacing(6)
            et = QLabel("CÓMO GRABAR")
            et.setObjectName("Seccion")
            bl.addWidget(et)

            self.directo_radio = QRadioButton("Copia directa por sectores (rápido)")
            self.directo_radio.setChecked(True)
            self.formato_radio = QRadioButton(
                "Formatear cada pista antes de grabarla (lento, más fiable)")
            grupo = QButtonGroup(self)
            grupo.addButton(self.directo_radio)
            grupo.addButton(self.formato_radio)
            bl.addWidget(self.directo_radio)
            bl.addWidget(self.formato_radio)

            nota = QLabel(
                "Formatear cada pista es el equivalente a la opción /F de COPIA720. "
                "Es bastante más lento, pero permite reutilizar disquetes viejos, con "
                "otro formato o con la superficie deteriorada, que de otro modo dan "
                "error de escritura."
            )
            nota.setWordWrap(True)
            nota.setStyleSheet("color: #8892a8; font-size: 11px;")
            bl.addWidget(nota)

            self.verificar_chk = QCheckBox(
                "Verificar releyendo cada pista (opción /V de COPIA720)")
            bl.addWidget(self.verificar_chk)
            lay.addWidget(bloque)

        aviso = QLabel(
            "⚠ Se borrará todo el contenido del disquete. Comprueba que no tiene la "
            "pestaña de protección abierta."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color: #ff8a7a;")
        lay.addWidget(aviso)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        lay.addWidget(self.progress)

        self.estado = QLabel("Introduce el disquete y pulsa el botón.")
        self.estado.setWordWrap(True)
        lay.addWidget(self.estado)

        botones = QDialogButtonBox(QDialogButtonBox.Close)
        texto = "Grabar disquete" if modo == "escribir" else "Formatear disquete"
        self.go_btn = QPushButton(texto)
        self.go_btn.setStyleSheet(
            "QPushButton { background: rgba(255,180,84,0.16); color: #ffb454;"
            " border: 2px solid #ffb454; border-radius: 6px; padding: 8px 16px;"
            " font-weight: 700; }"
            "QPushButton:hover { background: rgba(255,180,84,0.30); }"
            "QPushButton:disabled { color: #4d5468; border-color: #2c3342;"
            " background: transparent; }")
        self.go_btn.setCursor(Qt.PointingHandCursor)
        self.go_btn.clicked.connect(self._empezar)
        botones.addButton(self.go_btn, QDialogButtonBox.ActionRole)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

    # -- ejecución ---------------------------------------------------------
    def _empezar(self):
        dev = self.dev_combo.currentData()
        if not dev:
            QMessageBox.warning(self, "Disquete",
                                "No hay ninguna disquetera detectada.")
            return
        geo = self.fmt_combo.currentData()
        nodo = vol.floppy_device_for(dev, geo)

        if self._modo == "escribir":
            if not self._datos:
                QMessageBox.warning(self, "Disquete", "No hay ninguna imagen cargada.")
                return
            esperado = vol.FLOPPY_GEOMETRIES[geo]["bytes"]
            if len(self._datos) != esperado:
                QMessageBox.warning(
                    self, "Disquete",
                    f"La imagen mide {rf.fmt_bytes(len(self._datos))} y un disquete de "
                    f"{geo} KB necesita exactamente {rf.fmt_bytes(esperado)}.\n\n"
                    "Elige el formato correcto o convierte la imagen antes.")
                return

        confirmacion = QMessageBox.warning(
            self, "Confirmar",
            f"Se va a BORRAR todo el contenido del disquete en {nodo}.\n\n"
            "¿Continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirmacion != QMessageBox.Yes:
            return

        self.go_btn.setEnabled(False)
        self.dev_combo.setEnabled(False)
        self.estado.setText("Trabajando… no extraigas el disquete.")

        formatear = (self._modo == "escribir" and self.formato_radio.isChecked())
        verificar = (self._modo == "escribir" and self.verificar_chk.isChecked())
        self._hilo = _Worker(self._modo, nodo, geo, self._datos,
                             formatear, verificar, self)
        self._hilo.progreso.connect(self._on_progreso)
        self._hilo.terminado.connect(self._on_terminado)
        self._hilo.start()

    def _on_progreso(self, pista: int, total: int, fallos: int):
        self.progress.setValue(int(pista / total * 100))
        t = f"Pista {pista} de {total}  (cilindro {pista // 2}, cara {pista % 2})"
        if fallos:
            t += f"   ·   {fallos} con errores"
        self.estado.setText(t)

    def _on_terminado(self, ok: bool, fallos: list, reform: list, mensaje: str):
        self.go_btn.setEnabled(True)
        self.dev_combo.setEnabled(True)
        self._hilo = None

        if not ok:
            self.estado.setText("Operación interrumpida.")
            QMessageBox.warning(self, "Disquete", mensaje)
            return

        self.progress.setValue(100)
        if not fallos:
            resumen = ("Disquete grabado correctamente."
                       if self._modo == "escribir" else "Disquete formateado.")
            if reform:
                resumen += (f"\n\n{len(reform)} pista(s) hubo que formatearlas para "
                            "poder grabarlas: el disquete está algo gastado, pero el "
                            "resultado es correcto.")
            self.estado.setText("Completado.")
            QMessageBox.information(self, "Disquete", resumen)
        else:
            cil = sorted({p // 2 for p in fallos})
            self.estado.setText(f"Terminado con {len(fallos)} error(es).")
            QMessageBox.warning(
                self, "Disquete",
                f"{len(fallos)} pista(s) fallaron.\nCilindros afectados: "
                + ", ".join(str(c) for c in cil[:20])
                + ("…" if len(cil) > 20 else "")
                + ("\n\nPrueba a marcar «Formatear cada pista antes de grabarla», "
                   "que suele recuperar disquetes con errores de escritura."
                   if self._modo == "escribir" and not self.formato_radio.isChecked()
                   else "\n\nEs probable que el disquete esté dañado. Prueba con otro."))

    def closeEvent(self, event):
        if self._hilo is not None and self._hilo.isRunning():
            QMessageBox.information(
                self, "Disquete",
                "Hay una operación en curso. Espera a que termine antes de cerrar.")
            event.ignore()
            return
        super().closeEvent(event)
