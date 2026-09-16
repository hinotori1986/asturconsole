"""Diálogo de selección de una carpeta de 'Sistema' — el contenido que se
inyectará dentro del disco recién creado. Ventana grande y con lista, para
poder ver de un vistazo qué carpetas hay preparadas y cuántos archivos
contiene cada una, sin ninguna restricción de a qué familia de disco
pertenecen (aplicable a MSX, SNES/Genesis o PC por igual — la aplicación no
juzga si el contenido tiene sentido para el destino elegido).
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)

import workspace as ws


# Nombres reconocidos como "archivos de sistema" cuando se activa el modo
# mínimo: solo estos (más el propio sector de arranque) pasan al disco
# generado, se descarta cualquier otra cosa que traiga el .dsk/carpeta
# origen — incluidas utilidades, documentos, etc.
#
# Separados por familia en vez de un único conjunto combinado: así, si
# eliges MSX pero por error metes una carpeta con archivos de PC (o al
# revés), esos archivos ajenos no se cuelan solo por casualidad de
# nombre — se descartan igual que cualquier otro archivo que no sea de
# sistema para lo que estás generando.
NOMBRES_SISTEMA_MSX = {
    "MSXDOS.SYS", "COMMAND.COM", "MSXDOS2.SYS", "COMMAND2.COM",
}

# No puede cubrir cada variante histórica que haya existido (hay bastantes:
# distintos fabricantes de PC-DOS licenciaron su propio DOS con nombres de
# archivo propios). Si tu copia concreta usa otros nombres y el modo mínimo
# se los deja fuera, desactívalo para esa carpeta y cópiala en modo completo.
NOMBRES_SISTEMA_PC = {
    # MS-DOS / PC-DOS modernos (7.x en adelante, incluida la base de Windows 9x)
    "IO.SYS", "MSDOS.SYS", "COMMAND.COM",
    # PC-DOS / MS-DOS clásicos (IBM, 1.x-6.x, y muchos OEM que copiaron el nombre)
    "IBMBIO.COM", "IBMDOS.COM",
    # DR-DOS
    "DRBIOS.SYS", "DRBDOS.SYS",
    # FreeDOS
    "KERNEL.SYS",
}


def nombres_sistema_para_familia(familia: str) -> set[str]:
    """Qué nombres cuentan como 'archivo de sistema' en modo mínimo, según
    la familia de disco elegida en el Estudio. 'smd' (discos de los
    copiones de SNES/Genesis) usa el mismo conjunto que MSX, ya que esos
    discos los lee un MSX real a través del cartucho copión — no un PC."""
    return NOMBRES_SISTEMA_PC if familia == "pc" else NOMBRES_SISTEMA_MSX


class SystemFolderDialog(QDialog):
    """Lista las subcarpetas de ASTURCONSOLE/Sistema/ y deja elegir una
    (o ninguna) para inyectar su contenido en el disco que se va a crear."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Elegir contenido de sistema")
        self.setMinimumSize(560, 520)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)

        t = QLabel("Elegir contenido de sistema")
        t.setStyleSheet("font-size: 16px; font-weight: 700; color: #f2f4f8;")
        lay.addWidget(t)

        info = QLabel(
            "El contenido de la carpeta que elijas se copiará dentro del disco, "
            "tal cual. No se comprueba que tenga sentido para el tipo de disco "
            "elegido — por ejemplo, nada impide aplicar una carpeta con archivos "
            "de MSX-DOS a un disco de PC: es responsabilidad de quien elige.\n\n"
            "Consejo: si quieres que el disco arranque, lo más simple es meter "
            "en la carpeta una copia del propio .dsk que ya arranca en tu "
            "máquina — se detecta solo y se usa su sector de arranque."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #8892a8; font-size: 11px;")
        lay.addWidget(info)

        self.chk_minimo = QCheckBox(
            "Disco mínimo de arranque: solo los archivos de sistema reconocidos")
        self.chk_minimo.setChecked(True)
        self.chk_minimo.setToolTip(
            "Si el contenido viene de una imagen .dsk completa (un disco con "
            "decenas de utilidades, por ejemplo), esta opción descarta todo "
            "salvo los archivos de sistema reconocidos para la familia que "
            "hayas elegido en el Estudio: MSXDOS.SYS/COMMAND.COM o "
            "MSXDOS2.SYS/COMMAND2.COM para MSX y SNES/Genesis; IO.SYS/MSDOS.SYS, "
            "IBMBIO.COM/IBMDOS.COM u otras variantes de PC-DOS/DR-DOS/FreeDOS "
            "para PC. Desactívala si tu copia concreta usa otros nombres, o si "
            "de verdad quieres copiar TODO el contenido del disco — aunque "
            "para clonar un disco entero suele ser más directo grabar esa "
            "imagen tal cual, sin pasar por aquí.")
        self.chk_minimo.setStyleSheet("color: #dde3ef; font-size: 11.5px;")
        lay.addWidget(self.chk_minimo)

        self.lista = QListWidget()
        self.lista.setStyleSheet(
            "QListWidget { background: #10141c; border: 1.5px solid #2c3342; "
            "border-radius: 8px; color: #dde3ef; font-size: 12.5px; padding: 4px; } "
            "QListWidget::item { padding: 8px; border-radius: 5px; } "
            "QListWidget::item:selected { background: #2a2210; color: #e8c877; }"
        )
        lay.addWidget(self.lista, 1)
        self._cargar_lista()

        fila_botones = QHBoxLayout()
        btn_ninguna = QPushButton("No usar ninguna")
        btn_ninguna.clicked.connect(self._elegir_ninguna)
        fila_botones.addWidget(btn_ninguna)
        fila_botones.addStretch(1)
        btn_abrir_carpeta = QPushButton("Abrir carpeta \"Sistema\"…")
        btn_abrir_carpeta.setToolTip(
            "Para crear una carpeta nueva aquí dentro: usa el explorador de "
            "archivos de tu sistema operativo, esta ventana solo lee lo que ya "
            "exista.")
        btn_abrir_carpeta.clicked.connect(self._abrir_carpeta_sistema)
        fila_botones.addWidget(btn_abrir_carpeta)
        lay.addLayout(fila_botones)

        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

        self._carpeta_elegida = ""

    def _cargar_lista(self):
        self.lista.clear()
        raiz = ws.system_content_dir()
        nombres = ws.list_system_content_folders()
        if not nombres:
            item = QListWidgetItem(
                "(vacío — no hay ninguna carpeta preparada todavía; usa el "
                "botón de abajo para crear una)")
            item.setFlags(Qt.NoItemFlags)
            self.lista.addItem(item)
            return
        for nombre in nombres:
            ruta = os.path.join(raiz, nombre)
            try:
                n_archivos = sum(
                    len(f) for _r, _d, f in os.walk(ruta))
            except OSError:
                n_archivos = 0
            item = QListWidgetItem(f"{nombre}   —   {n_archivos} archivo(s)")
            item.setData(Qt.UserRole, nombre)
            self.lista.addItem(item)

    def _elegir_ninguna(self):
        self._carpeta_elegida = ""
        self.accept()

    def _abrir_carpeta_sistema(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(ws.system_content_dir()))

    def carpeta_elegida(self) -> str:
        """Nombre de la subcarpeta elegida (vacío = ninguna)."""
        item = self.lista.currentItem()
        if item is None or not (item.flags() & Qt.ItemIsEnabled):
            return self._carpeta_elegida
        return item.data(Qt.UserRole) or ""

    def modo_minimo(self) -> bool:
        """True si se debe descartar todo salvo los archivos de sistema
        reconocidos (ver nombres_sistema_para_familia)."""
        return self.chk_minimo.isChecked()
