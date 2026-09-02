"""Panel de disquetera de la pestaña MSX.

Reorganiza en tres áreas claras lo que antes eran botones sueltos:

  1. Manipulador de disquete — trabajar con imágenes: crearlas vacías,
     analizar su contenido, extraer e inyectar archivos, convertir formatos.
  2. Unidad de disquete real — leer y escribir disquetes en una disquetera
     conectada a la controladora, al estilo de COPIA720.
  3. Unidad de disquete USB — lo mismo con adaptadores USB, que funcionan
     como dispositivos de almacenamiento genéricos.

La distinción entre las dos últimas no es un capricho: una disquetera real
permite fijar la geometría (720 o 360 KB) usando los nodos /dev/fdNuXXX del
kernel, mientras que un adaptador USB se presenta como disco genérico y solo
admite la escritura de la imagen tal cual.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)


TARJETA_QSS = """
QFrame#TarjetaDisco {
    background: #161a24;
    border: 2px solid %(borde)s;
    border-radius: 10px;
}
QFrame#TarjetaDisco:hover { border-color: %(color)s; background: #1a1f2b; }
QLabel#TituloTarjeta { color: %(color)s; font-size: 13px; font-weight: 700; }
QLabel#DescTarjeta   { color: #8892a8; font-size: 11px; }
QPushButton#AccionTarjeta {
    background: rgba(0,0,0,0.25);
    color: #dde3ef;
    border: 1px solid #39404f;
    border-radius: 5px;
    padding: 6px 10px;
    text-align: left;
    font-size: 11px;
}
QPushButton#AccionTarjeta:hover {
    border-color: %(color)s; color: %(color)s;
    background: rgba(0,0,0,0.45);
}
QPushButton#AccionTarjeta:disabled { color: #4d5468; border-color: #2c3342; }
"""


class DiskCard(QFrame):
    """Una de las tres áreas: icono grande, título, descripción y acciones."""

    def __init__(self, titulo: str, descripcion: str, icono: str,
                 color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("TarjetaDisco")
        self.setStyleSheet(TARJETA_QSS % {"color": color, "borde": "#2c3342"})
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(9)

        cabecera = QHBoxLayout()
        cabecera.setSpacing(12)
        self.icon_lbl = QLabel()
        if icono and os.path.isfile(icono):
            self.icon_lbl.setPixmap(QIcon(icono).pixmap(QSize(64, 64)))
        self.icon_lbl.setFixedSize(64, 64)
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        cabecera.addWidget(self.icon_lbl)

        textos = QVBoxLayout()
        textos.setSpacing(3)
        t = QLabel(titulo)
        t.setObjectName("TituloTarjeta")
        t.setWordWrap(True)
        d = QLabel(descripcion)
        d.setObjectName("DescTarjeta")
        d.setWordWrap(True)
        textos.addWidget(t)
        textos.addWidget(d)
        textos.addStretch(1)
        cabecera.addLayout(textos, 1)
        lay.addLayout(cabecera)

        self._acciones = QVBoxLayout()
        self._acciones.setSpacing(5)
        lay.addLayout(self._acciones)

        self.aviso = QLabel("")
        self.aviso.setObjectName("DescTarjeta")
        self.aviso.setWordWrap(True)
        self.aviso.setVisible(False)
        lay.addWidget(self.aviso)

    def add_action(self, texto: str, callback, tooltip: str = "",
                   enabled: bool = True) -> QPushButton:
        b = QPushButton(texto)
        b.setObjectName("AccionTarjeta")
        b.setCursor(Qt.PointingHandCursor)
        if tooltip:
            b.setToolTip(tooltip)
        b.setEnabled(enabled)
        b.clicked.connect(callback)
        self._acciones.addWidget(b)
        return b

    def set_aviso(self, texto: str, color: str = "#ffb454"):
        self.aviso.setText(texto)
        self.aviso.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.aviso.setVisible(bool(texto))


def build_disk_panel(panel, icon_path) -> QWidget:
    """Construye el panel completo. `panel` es el SystemPanel de MSX, del que
    se toman los métodos que ya existen para cada acción."""
    caja = QFrame()
    caja.setObjectName("FieldChip")
    lay = QVBoxLayout(caja)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(10)

    titulo = QLabel("DISQUETERA MSX")
    titulo.setObjectName("SectionLabel")
    lay.addWidget(titulo)

    rejilla = QGridLayout()
    rejilla.setSpacing(12)

    # --- 1. Manipulador de disquete ---
    manip = DiskCard(
        "Manipulador de disquete",
        "Trabajar con imágenes de disco: crearlas, ver su contenido, extraer "
        "e inyectar archivos y convertir entre formatos.",
        icon_path("disk_toolbox.svg"), "#3ef29a",
    )
    manip.add_action("Crear disquetes vacíos…", panel._create_blank_disks,
                     "Genera imágenes .dsk de 720 o 360 KB, con o sin MSX-DOS")
    manip.add_action("Extraer archivos del disco", panel._dsk_extract_all,
                     "Abre la ventana para elegir qué archivos extraer (hasta 3 discos)")
    manip.add_action("★  Extraer varias imágenes de golpe", panel._msx_extract_many,
                     "Extrae el contenido completo de todas las imágenes "
                     "seleccionadas, cada una en su propia subcarpeta")
    manip.add_action("Inyectar archivos en el disco…", panel._dsk_inject_files,
                     "Copia archivos de tu equipo dentro de la imagen abierta")
    manip.add_action("Recortar imagen COPIA720 (720→360)", panel._copia720_trim,
                     "Quita la cara vacía de un volcado de cara simple")
    manip.add_action("Expandir para COPIA720 (360→720)", panel._copia720_expand,
                     "Añade la cara de relleno que COPIA720 espera con /1")
    rejilla.addWidget(manip, 0, 0)

    # --- 2. Unidad de disquete real ---
    real = DiskCard(
        "Unidad de disquete real",
        "Disquetera conectada a la controladora del equipo. Permite fijar la "
        "geometría de 720 y 360 KB, como hace COPIA720 bajo DOS.",
        icon_path("disk_real.svg"), "#ffb454",
    )
    real.add_action("Leer disquete → imagen…", panel._read_floppy,
                    "Vuelca el disquete pista a pista, con reintentos")
    real.add_action("Escribir imagen → disquete…", panel._write_floppy_real,
                    "Graba la imagen seleccionada, con opción de formatear cada "
                    "pista antes (como la opción /F de COPIA720)")
    real.add_action("Crear disquetes vacíos…", panel._smd_blank_disk,
                    "Genera imágenes .img ya formateadas en cualquiera de los cuatro "
                    "formatos (720/800/1440/1600 KB), sin necesidad de disquetera")
    real.add_action("Formatear disquete…", panel._format_floppy_real,
                    "Formateo a bajo nivel, pista a pista, a 360, 720 KB o 1.44 MB")
    rejilla.addWidget(real, 0, 1)

    # --- 3. Unidad de disquete USB ---
    usb = DiskCard(
        "Unidad de disquete USB",
        "Adaptadores USB de disquete y otras unidades extraíbles. Escriben la "
        "imagen tal cual, sin control de geometría.",
        icon_path("disk_usb.svg"), "#5aa0ff",
    )
    usb.add_action("Escribir imagen en unidad USB…", panel._write_image_usb,
                   "Graba la imagen seleccionada en una unidad extraíble")
    usb.add_action("Formatear (grabando imagen vacía)…", panel._format_usb_media,
                   "Los adaptadores USB no admiten formateo a bajo nivel: se "
                   "consigue el mismo efecto grabando una imagen ya formateada")
    usb.set_aviso(
        "Sin formateo a bajo nivel: un adaptador USB se presenta como disco "
        "genérico y no permite formatear pista a pista ni fijar la geometría.")
    rejilla.addWidget(usb, 0, 2)

    # --- 4. Greaseweazle (USB) ---
    greaseweazle = DiskCard(
        "Greaseweazle (USB)",
        "Dispositivo USB independiente que se conecta a una disquetera física "
        "por su cable de 34 pines. Para equipos sin puerto paralelo ni "
        "controladora de disquetera integrada — más fiable que un adaptador "
        "USB genérico, ya que lee y escribe a nivel de flujo magnético.",
        icon_path("disk_greaseweazle.svg"), "#4ee6d8",
    )
    greaseweazle.add_action("Abrir Greaseweazle…", panel._open_greaseweazle,
                            "Leer disco → imagen, o escribir imagen → disco (360/720 KB)")
    greaseweazle.set_aviso(
        "Requiere su herramienta \"gw\" instalada aparte. Se detecta solo por "
        "USB, sin configurar puerto.")
    rejilla.addWidget(greaseweazle, 0, 3)

    for c in range(4):
        rejilla.setColumnStretch(c, 1)
    lay.addLayout(rejilla)

    panel._card_manip = manip
    panel._card_real = real
    panel._card_usb = usb
    return caja


def build_floppy_writer_panel(panel, icon_path, sistema_label: str) -> QWidget:
    """Versión reducida del panel de disquetera, sin el "Manipulador" (que es
    específico de MSX-DOS/COPIA720): solo "Unidad real" y "Unidad USB", para
    poder grabar en disquetera física o USB las imágenes que ya se generan en
    las secciones de SNES y Mega Drive (discos SWC / Super Magic Drive).

    Antes esto solo estaba disponible en la pestaña de MSX, así que no había
    forma de grabar un disco SWC o SMD en una disquetera real ni en un
    adaptador USB desde la propia interfaz, aunque la lógica de bajo nivel
    (volumes.py) ya soportaba esas geometrías.
    """
    caja = QFrame()
    caja.setObjectName("FieldChip")
    lay = QVBoxLayout(caja)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(10)

    titulo = QLabel(f"GRABAR EN DISQUETERA ({sistema_label})")
    titulo.setObjectName("SectionLabel")
    lay.addWidget(titulo)

    rejilla = QGridLayout()
    rejilla.setSpacing(12)

    real = DiskCard(
        "Unidad de disquete real",
        "Disquetera conectada a la controladora del equipo. Admite fijar "
        "cualquier geometría, incluidas las \"superformateadas\" (1600/800 KB).",
        icon_path("disk_real.svg"), "#ffb454",
    )
    real.add_action("Leer disquete → imagen…", panel._read_floppy,
                    "Vuelca el disquete pista a pista, con reintentos")
    real.add_action("Escribir imagen → disquete…", panel._write_floppy_real,
                    "Graba la imagen seleccionada (720/800/1440/1600 KB)")
    real.add_action("Crear disquetes vacíos…", panel._smd_blank_disk,
                    "Genera imágenes .img ya formateadas en cualquiera de los cuatro "
                    "formatos (720/800/1440/1600 KB), sin necesidad de disquetera")
    real.add_action("Formatear disquete…", panel._format_floppy_real,
                    "Formateo a bajo nivel, pista a pista. Para 1600/800 KB, "
                    "el hueco entre sectores es una estimación: si da errores, "
                    "formatea antes con «superformat» y usa aquí solo la escritura")
    rejilla.addWidget(real, 0, 0)

    usb = DiskCard(
        "Unidad de disquete USB",
        "Adaptadores USB de disquete. Escriben la imagen tal cual, sin control "
        "de geometría: solo admiten los formatos estándar (720 KB y 1.44 MB).",
        icon_path("disk_usb.svg"), "#5aa0ff",
    )
    usb.add_action("Escribir imagen en unidad USB…", panel._write_image_usb,
                   "Graba la imagen seleccionada en una unidad extraíble")
    usb.set_aviso(
        "Sin formateo a bajo nivel ni geometría personalizada: un adaptador "
        "USB no puede escribir los formatos \"superformateados\" (1600/800 KB) "
        "— usa una disquetera real para esos, o quédate con 720 KB/1.44 MB.")
    rejilla.addWidget(usb, 0, 1)

    greaseweazle = DiskCard(
        "Greaseweazle (USB)",
        "Dispositivo USB independiente que se conecta a una disquetera física "
        "por su cable de 34 pines. Lee y escribe a nivel de flujo magnético: "
        "admite cualquier geometría, incluidas las \"superformateadas\" "
        "(1600/800 KB) — para equipos sin puerto paralelo ni controladora de "
        "disquetera integrada.",
        icon_path("disk_greaseweazle.svg"), "#4ee6d8",
    )
    greaseweazle.add_action("Abrir Greaseweazle…", panel._open_greaseweazle,
                            "Leer disco → imagen, o escribir imagen → disco")
    greaseweazle.set_aviso(
        "Requiere su herramienta \"gw\" instalada aparte. Se detecta solo por "
        "USB, sin configurar puerto.")
    rejilla.addWidget(greaseweazle, 0, 2)

    for c in range(3):
        rejilla.setColumnStretch(c, 1)
    lay.addLayout(rejilla)
    return caja
