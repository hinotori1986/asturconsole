"""Volcado de disquetes físicos a imagen, al estilo de COPIA720.

Equivalente en Linux de lo que COPIA720 hace bajo DOS: leer el disquete
pista a pista con reintentos, tolerando sectores defectuosos en vez de
abortar el volcado entero como haría `dd`.

Solo funciona con disqueteras REALES conectadas a la controladora del
sistema (/dev/fdN). Los adaptadores USB de disquete no sirven: se presentan
como dispositivos de almacenamiento genéricos y no permiten el control de
geometría que necesitan los formatos de 720 y 360 KB.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
)

import rom_formats as rf
import volumes as vol
import workspace as ws


class _ReadThread(QThread):
    """La lectura de un disquete es lenta; se hace fuera del hilo gráfico."""

    progreso = Signal(int, int, int)      # pista, total, fallos
    terminado = Signal(bool, object, list, str)   # ok, datos, fallos, mensaje

    def __init__(self, device: str, geometria: str, tolerar: bool, parent=None):
        super().__init__(parent)
        self._device = device
        self._geometria = geometria
        self._tolerar = tolerar

    def run(self):
        try:
            datos, fallos = vol.read_floppy(
                self._device, self._geometria,
                tolerar_errores=self._tolerar,
                progreso=lambda p, t, f: self.progreso.emit(p, t, f),
            )
            self.terminado.emit(True, datos, fallos, "")
        except Exception as e:  # noqa: BLE001
            self.terminado.emit(False, None, [], str(e))


class ReadFloppyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Volcar disquete a imagen")
        self.setMinimumWidth(600)
        self._hilo: _ReadThread | None = None

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        intro = QLabel(
            "Lee un disquete completo y lo guarda como imagen, pista a pista y "
            "con reintentos, al estilo de COPIA720. Solo funciona con "
            "<b>disqueteras reales</b> conectadas a la controladora: los "
            "adaptadores USB de disquete no permiten el control de geometría "
            "que necesitan los formatos de 720 y 360 KB."
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        # --- unidad ---
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Unidad:"))
        self.dev_combo = QComboBox()
        for d in vol.list_floppy_drives():
            self.dev_combo.addItem(d, d)
        if self.dev_combo.count() == 0:
            self.dev_combo.addItem("(no se detectó ninguna disquetera)", None)
        fila.addWidget(self.dev_combo, 1)
        self.refresh_btn = QPushButton("Actualizar")
        self.refresh_btn.clicked.connect(self._refrescar)
        fila.addWidget(self.refresh_btn)
        lay.addLayout(fila)

        # --- formato ---
        fila2 = QHBoxLayout()
        fila2.addWidget(QLabel("Formato:"))
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItem("Detectar automáticamente", "auto")
        for clave, info in vol.FLOPPY_GEOMETRIES.items():
            self.fmt_combo.addItem(info["etiqueta"], clave)
        self.fmt_combo.currentIndexChanged.connect(self._actualizar_nodo)
        fila2.addWidget(self.fmt_combo, 1)
        self.detect_btn = QPushButton("Detectar ahora")
        self.detect_btn.setToolTip(
            "Lee el sector de arranque del disquete y deduce si es de 360, 720 KB "
            "o 1.44 MB")
        self.detect_btn.clicked.connect(self._detectar)
        fila2.addWidget(self.detect_btn)
        lay.addLayout(fila2)

        self.nodo_lbl = QLabel("")
        self.nodo_lbl.setWordWrap(True)
        self.nodo_lbl.setStyleSheet("color: #8892a8; font-size: 11px;")
        lay.addWidget(self.nodo_lbl)

        self.tolerar_chk = QCheckBox(
            "Continuar aunque haya pistas ilegibles (rellenarlas y avisar)")
        self.tolerar_chk.setChecked(True)
        self.tolerar_chk.setToolTip(
            "Como la opción /! de COPIA720: permite recuperar la mayor parte de "
            "un disquete deteriorado en vez de abandonar al primer error."
        )
        lay.addWidget(self.tolerar_chk)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        lay.addWidget(self.progress)

        self.estado_lbl = QLabel("Introduce el disquete y pulsa «Volcar».")
        self.estado_lbl.setWordWrap(True)
        lay.addWidget(self.estado_lbl)

        botones = QDialogButtonBox(QDialogButtonBox.Close)
        self.read_btn = QPushButton("Volcar disquete")
        self.read_btn.setStyleSheet(
            "QPushButton { background: rgba(62,242,154,0.16); color: #3ef29a;"
            " border: 2px solid #3ef29a; border-radius: 6px; padding: 8px 16px;"
            " font-weight: 700; }"
            "QPushButton:hover { background: rgba(62,242,154,0.30); }"
        )
        self.read_btn.clicked.connect(self._volcar)
        botones.addButton(self.read_btn, QDialogButtonBox.ActionRole)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

        self._actualizar_nodo()

    # -- interfaz ---------------------------------------------------------
    def _refrescar(self):
        actual = self.dev_combo.currentData()
        self.dev_combo.clear()
        for d in vol.list_floppy_drives():
            self.dev_combo.addItem(d, d)
        if self.dev_combo.count() == 0:
            self.dev_combo.addItem("(no se detectó ninguna disquetera)", None)
        elif actual:
            i = self.dev_combo.findData(actual)
            if i >= 0:
                self.dev_combo.setCurrentIndex(i)
        self._actualizar_nodo()

    def _detectar(self):
        """Deduce el formato leyendo el sector de arranque del disquete."""
        dev = self.dev_combo.currentData()
        if not dev:
            QMessageBox.information(self, "Volcar disquete",
                                    "No hay ninguna disquetera seleccionada.")
            return
        # Se prueba primero con el nodo de 720 KB, que es el formato MSX más
        # habitual: si el disco fuera de otro tamaño, el BPB lo dirá igualmente.
        clave = vol.detect_floppy_geometry(vol.floppy_device_for(dev, "720"))
        if clave is None:
            clave = vol.detect_floppy_geometry(dev)
        if clave is None:
            QMessageBox.information(
                self, "Volcar disquete",
                "No se pudo deducir el formato: el disquete puede no tener un "
                "sector de arranque estándar (habitual en discos protegidos o de "
                "juegos), estar sin formatear, o no estar insertado.\n\n"
                "Elige el formato a mano.")
            return
        i = self.fmt_combo.findData(clave)
        if i >= 0:
            self.fmt_combo.setCurrentIndex(i)
        etiqueta = vol.FLOPPY_GEOMETRIES[clave]["etiqueta"]
        QMessageBox.information(self, "Volcar disquete",
                                f"Formato detectado: {etiqueta}")

    def _resolver_formato(self) -> str:
        """Formato efectivo: el elegido, o el detectado si está en automático."""
        fmt = self.fmt_combo.currentData()
        if fmt != "auto":
            return fmt
        dev = self.dev_combo.currentData()
        if dev:
            clave = (vol.detect_floppy_geometry(vol.floppy_device_for(dev, "720"))
                     or vol.detect_floppy_geometry(dev))
            if clave:
                return clave
        return "720"      # el formato MSX más común, como respaldo

    def _actualizar_nodo(self):
        dev = self.dev_combo.currentData()
        fmt = self.fmt_combo.currentData()
        if fmt == "auto":
            self.nodo_lbl.setText(
                "El formato se deducirá del sector de arranque al empezar el volcado. "
                "Si el disquete no tiene uno estándar, se usarán 720 KB.")
            return
        if not dev:
            self.nodo_lbl.setText(
                "No se detecta ninguna disquetera. Comprueba que está conectada y "
                "que el módulo está cargado:  sudo modprobe floppy"
            )
            return
        nodo = vol.floppy_device_for(dev, fmt)
        if nodo == dev and fmt != "1440":
            self.nodo_lbl.setText(
                f"Se leerá de {dev}. AVISO: no existe el nodo con geometría "
                f"({dev}{vol.FLOPPY_GEOMETRIES[fmt]['sufijo']}), así que el sistema "
                f"asumirá 1.44 MB y un disquete de {fmt} KB podría leerse mal. "
                f"Prueba a cargar el módulo: sudo modprobe floppy"
            )
        else:
            self.nodo_lbl.setText(f"Se leerá de: {nodo}")

    # -- volcado -----------------------------------------------------------
    def _volcar(self):
        dev = self.dev_combo.currentData()
        if not dev:
            QMessageBox.warning(self, "Volcar disquete",
                                "No hay ninguna disquetera seleccionada.")
            return
        fmt = self._resolver_formato()
        nodo = vol.floppy_device_for(dev, fmt)
        self._fmt_usado = fmt

        self.read_btn.setEnabled(False)
        self.dev_combo.setEnabled(False)
        self.fmt_combo.setEnabled(False)
        self.tolerar_chk.setEnabled(False)
        self.estado_lbl.setText("Leyendo… no extraigas el disquete.")

        self._hilo = _ReadThread(nodo, fmt, self.tolerar_chk.isChecked(), self)
        self._hilo.progreso.connect(self._on_progreso)
        self._hilo.terminado.connect(self._on_terminado)
        self._hilo.start()

    def _on_progreso(self, pista: int, total: int, fallos: int):
        self.progress.setValue(int(pista / total * 100))
        texto = f"Pista {pista} de {total}  (cilindro {pista // 2}, cara {pista % 2})"
        if fallos:
            texto += f"   ·   {fallos} pista(s) con errores"
        self.estado_lbl.setText(texto)

    def _on_terminado(self, ok: bool, datos, fallos: list, mensaje: str):
        self.read_btn.setEnabled(True)
        self.dev_combo.setEnabled(True)
        self.fmt_combo.setEnabled(True)
        self.tolerar_chk.setEnabled(True)
        self._hilo = None

        if not ok:
            self.estado_lbl.setText("Volcado interrumpido.")
            QMessageBox.warning(self, "Volcar disquete", mensaje)
            return

        fmt = getattr(self, "_fmt_usado", "720")

        # Un disco MSX de cara simple leído en una unidad de doble cara puede
        # venir con la segunda cara vacía: se detecta y se ofrece recortarlo.
        nota_extra = ""
        if fmt == "720" and rf.detect_copia720_single_sided(datos):
            respuesta = QMessageBox.question(
                self, "Volcar disquete",
                "La segunda cara del disquete está vacía: parece un disco de CARA "
                "SIMPLE (360 KB) leído en una unidad de doble cara.\n\n"
                "¿Guardarlo con su tamaño real de 360 KB?\n\n"
                "(Responde 'No' para conservar los 720 KB con la cara vacía, que "
                "es lo que hace COPIA720 con la opción /1.)",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if respuesta == QMessageBox.Yes:
                datos = rf.copia720_to_single_sided(datos)
                nota_extra = " (recortado a 360 KB)"

        destino = ws.unique_path(ws.folder("extracted"), "disquete.dsk")
        try:
            with open(destino, "wb") as fh:
                fh.write(datos)
        except OSError as e:
            QMessageBox.warning(self, "Volcar disquete", f"No se pudo guardar:\n{e}")
            return

        self.progress.setValue(100)
        resumen = f"Volcado completado{nota_extra}: {rf.fmt_bytes(len(datos))}\n\n{destino}"
        if fallos:
            cilindros = sorted({p // 2 for p in fallos})
            resumen += (
                f"\n\nATENCIÓN: {len(fallos)} pista(s) no se pudieron leer y se han "
                f"rellenado. Cilindros afectados: "
                + ", ".join(str(c) for c in cilindros[:20])
                + ("…" if len(cilindros) > 20 else "")
                + "\n\nLa imagen puede estar incompleta. Prueba a limpiar el cabezal "
                "de la unidad o a volcar el disquete otra vez: a veces una segunda "
                "lectura recupera pistas que fallaron."
            )
        self.estado_lbl.setText("Volcado completado.")
        QMessageBox.information(self, "Volcar disquete", resumen)

        parent = self.parent()
        if parent is not None and hasattr(parent, "register_generated"):
            parent.register_generated(destino)

    def closeEvent(self, event):
        if self._hilo is not None and self._hilo.isRunning():
            QMessageBox.information(
                self, "Volcar disquete",
                "Hay un volcado en curso. Espera a que termine antes de cerrar.")
            event.ignore()
            return
        super().closeEvent(event)
