"""Ventana grande de trabajo con los archivos de una carpeta.

Sustituye a la lista estrecha de la ventana principal, que se quedaba corta
en cuanto una carpeta tenía muchos archivos. Aquí se trabaja con comodidad:

  - Rejilla de iconos con todos los archivos de la carpeta, filtrable.
  - Las herramientas del sistema activo (añadir cabecera, dividir en
    disquetes, byte swap...) están en esta misma ventana, aplicadas a lo que
    haya seleccionado.
  - Si lo seleccionado son imágenes de disco, se puede abrir el extractor
    directamente.

Las acciones no se implementan aquí: se reciben ya listas desde el panel
principal, que es quien sabe hacer cada operación. Esta ventana solo se
ocupa de mostrar y seleccionar.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

import rom_formats as rf

ESTILO = """
QDialog { background: #0f111a; }
QLabel { color: #dde3ef; }
QLabel#Titulo { font-size: 15px; font-weight: 700; }
QLabel#Ruta {
    color: #8892a8; font-family: "IBM Plex Mono", monospace; font-size: 11px;
}
QLineEdit, QComboBox {
    background: #0a0b10; color: #dde3ef;
    border: 1px solid #2c3342; border-radius: 5px; padding: 7px 10px;
}
QLineEdit:focus { border-color: #3ef29a; }
QListWidget {
    background: #0a0b10; color: #dde3ef;
    border: 1px solid #2c3342; border-radius: 6px; outline: none;
}
QListWidget::item { border-radius: 8px; padding: 6px; margin: 3px; color: #c8d0e0; }
QListWidget::item:hover { background: #161c28; }
QListWidget::item:selected { background: #22304a; color: #ffffff; }
QPushButton {
    background: #1f2330; color: #dde3ef;
    border: 1px solid #39404f; border-radius: 5px;
    padding: 8px 13px; font-weight: 600; text-align: left;
}
QPushButton:hover { border-color: #8892a8; background: #262b38; }
QPushButton#Principal {
    background: rgba(62,242,154,0.16); color: #3ef29a;
    border: 2px solid #3ef29a; text-align: center;
}
QPushButton#Principal:hover { background: rgba(62,242,154,0.30); }
QFrame#Panel {
    background: #161a24; border: 1px solid #2c3342; border-radius: 8px;
}
QLabel#Seccion { color: #8892a8; font-size: 10px; font-weight: 700; }
"""

EXT_IMAGENES = (".dsk", ".img", ".di1", ".di2")

# Extensiones características de cada sistema, para deducir con qué
# herramientas trabajar según lo que haya en la carpeta.
EXT_SISTEMA = {
    "snes":    (".sfc", ".smc", ".swc", ".fig", ".ufo"),
    "genesis": (".smd", ".gen", ".md", ".bin"),
    "msx":     (".rom", ".mx1", ".mx2", ".dsk", ".di1", ".di2",
                ".cas", ".tsx", ".wav"),
}

NOMBRE_SISTEMA = {
    "snes": "Super Nintendo",
    "genesis": "Mega Drive",
    "msx": "MSX",
}


def detectar_sistema(carpeta: str, por_defecto: str = "snes") -> str:
    """Deduce a qué sistema pertenece el contenido de una carpeta.

    Cuenta las extensiones de los archivos y devuelve el sistema con más
    coincidencias. Es lo que evita que, estando en la pestaña de MSX, al
    abrir una carpeta de ROMs de SNES aparezcan las herramientas de MSX.

    La extensión .img es ambigua (imagen de disco MSX o disquete de Super
    Wild Card), así que no cuenta para decidir.
    """
    votos = {clave: 0 for clave in EXT_SISTEMA}
    try:
        for nombre in os.listdir(carpeta):
            if not os.path.isfile(os.path.join(carpeta, nombre)):
                continue
            ext = os.path.splitext(nombre)[1].lower()
            if ext == ".img":
                continue
            for clave, exts in EXT_SISTEMA.items():
                if ext in exts:
                    votos[clave] += 1
    except OSError:
        return por_defecto

    mejor = max(votos, key=lambda k: votos[k])
    return mejor if votos[mejor] > 0 else por_defecto


class FileWorkbench(QDialog):
    """Ventana de trabajo sobre los archivos de una carpeta."""

    analizar = Signal(str)               # ver un archivo en el panel de detalle
    accion = Signal(str, list)           # (clave de acción, rutas seleccionadas)
    comprobar_discos = Signal(list)      # revisar un lote de imágenes de disco

    sistema_cambiado = Signal(str)

    def __init__(self, carpeta: str, sistema: str, acciones_por_sistema: dict,
                 icon_dir: str = "", parent=None):
        """`acciones_por_sistema` es {clave_sistema: [(clave, texto, desc)]}."""
        super().__init__(parent)
        self._titulo_base = os.path.basename(carpeta) or carpeta
        self.setMinimumSize(1060, 680)
        self.setStyleSheet(ESTILO)

        self._carpeta = carpeta
        self._acciones_por_sistema = acciones_por_sistema
        # El sistema se deduce del CONTENIDO de la carpeta, no de la pestaña
        # desde la que se abrió: si exploras ROMs de SNES tienen que salir las
        # herramientas de SNES aunque estuvieras en la pestaña de MSX.
        self._sistema = detectar_sistema(carpeta, sistema)
        self._icon_dir = icon_dir
        self._archivos: list = []

        raiz = QVBoxLayout(self)
        raiz.setSpacing(10)

        self.titulo_lbl = QLabel("")
        self.titulo_lbl.setObjectName("Titulo")
        raiz.addWidget(self.titulo_lbl)
        ruta = QLabel(carpeta)
        ruta.setObjectName("Ruta")
        ruta.setWordWrap(True)
        raiz.addWidget(ruta)

        # --- barra de filtro ---
        barra = QHBoxLayout()
        barra.addWidget(QLabel("Filtrar:"))
        self.filtro = QLineEdit()
        self.filtro.setPlaceholderText("escribe parte del nombre…")
        self.filtro.textChanged.connect(self._poblar)
        barra.addWidget(self.filtro, 1)

        barra.addWidget(QLabel("Tipo:"))
        self.tipo_combo = QComboBox()
        self.tipo_combo.addItem("Todos los archivos", None)
        self.tipo_combo.addItem("Imágenes de disco", EXT_IMAGENES)
        self.tipo_combo.addItem("ROMs SNES", (".sfc", ".smc", ".swc", ".fig", ".ufo"))
        self.tipo_combo.addItem("ROMs Mega Drive", (".smd", ".bin", ".md", ".gen"))
        self.tipo_combo.addItem("ROMs / archivos MSX", (".rom", ".mx1", ".mx2"))
        self.tipo_combo.addItem("Cintas", (".cas", ".tsx", ".wav"))
        self.tipo_combo.currentIndexChanged.connect(self._poblar)
        barra.addWidget(self.tipo_combo)

        self.todos_btn = QPushButton("Seleccionar todo")
        self.todos_btn.clicked.connect(lambda: self.lista.selectAll())
        barra.addWidget(self.todos_btn)
        raiz.addLayout(barra)

        # --- cuerpo: archivos a la izquierda, acciones a la derecha ---
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)

        self.lista = QListWidget()
        self.lista.setViewMode(QListView.IconMode)
        self.lista.setIconSize(QSize(56, 56))
        self.lista.setGridSize(QSize(180, 104))
        self.lista.setResizeMode(QListView.Adjust)
        self.lista.setMovement(QListView.Static)
        self.lista.setWordWrap(True)
        self.lista.setSelectionMode(QListWidget.ExtendedSelection)
        self.lista.itemSelectionChanged.connect(self._actualizar_estado)
        self.lista.itemDoubleClicked.connect(self._doble_clic)
        cuerpo.addWidget(self.lista, 1)

        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(310)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(7)

        et = QLabel("HERRAMIENTAS")
        et.setObjectName("Seccion")
        pl.addWidget(et)

        # Selector de sistema: se rellena con el detectado, pero se puede
        # cambiar a mano si la carpeta mezcla archivos de varios.
        self.sistema_combo = QComboBox()
        for clave, nombre in NOMBRE_SISTEMA.items():
            self.sistema_combo.addItem(nombre, clave)
        i = self.sistema_combo.findData(self._sistema)
        if i >= 0:
            self.sistema_combo.setCurrentIndex(i)
        self.sistema_combo.currentIndexChanged.connect(self._cambiar_sistema)
        pl.addWidget(self.sistema_combo)

        self.detectado_lbl = QLabel("")
        self.detectado_lbl.setWordWrap(True)
        self.detectado_lbl.setStyleSheet("color: #8892a8; font-size: 10px;")
        pl.addWidget(self.detectado_lbl)

        self._contenedor_acciones = QVBoxLayout()
        self._contenedor_acciones.setSpacing(7)
        pl.addLayout(self._contenedor_acciones)
        self._botones = []
        self._construir_acciones()

        pl.addStretch(1)
        self.ver_btn = QPushButton("Analizar la selección")
        self.ver_btn.setObjectName("Principal")
        self.ver_btn.setCursor(Qt.PointingHandCursor)
        self.ver_btn.clicked.connect(self._analizar_seleccion)
        pl.addWidget(self.ver_btn)
        cuerpo.addWidget(panel)
        raiz.addLayout(cuerpo, 1)

        self.estado = QLabel("")
        self.estado.setStyleSheet("color: #8892a8; font-size: 11px;")
        self.estado.setWordWrap(True)
        raiz.addWidget(self.estado)

        self._poblar()

    def _construir_acciones(self):
        """Rehace los botones de herramientas para el sistema activo."""
        while self._contenedor_acciones.count():
            item = self._contenedor_acciones.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._botones = []

        for clave, texto, descripcion in self._acciones_por_sistema.get(self._sistema, []):
            b = QPushButton(texto)
            if descripcion:
                b.setToolTip(descripcion)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _checked=False, c=clave: self._lanzar(c))
            self._contenedor_acciones.addWidget(b)
            self._botones.append(b)

        nombre = NOMBRE_SISTEMA.get(self._sistema, self._sistema)
        self.detectado_lbl.setText(
            f"Herramientas de {nombre}, elegidas según el contenido de la carpeta. "
            "Cámbialo arriba si no es lo que esperabas.")
        # Que se vea también en el título, para no dudar de qué se está usando
        self.setWindowTitle(f"Trabajar con archivos — {self._titulo_base}  ·  {nombre}")
        if hasattr(self, "titulo_lbl"):
            self.titulo_lbl.setText(f"{self._titulo_base}   —   herramientas de {nombre}")

    def _cambiar_sistema(self):
        nuevo = self.sistema_combo.currentData()
        if nuevo and nuevo != self._sistema:
            self._sistema = nuevo
            self._construir_acciones()
            self.sistema_cambiado.emit(nuevo)

    def sistema(self) -> str:
        return self._sistema

    # -- contenido ---------------------------------------------------------
    def _icono(self, nombre: str) -> QIcon:
        ext = os.path.splitext(nombre)[1].lower()
        mapa = {
            EXT_IMAGENES: "floppy.svg",
            (".cas", ".tsx", ".wav"): "msx.svg",
            (".sfc", ".smc", ".swc", ".fig", ".ufo"): "snes.svg",
            (".smd", ".gen", ".md", ".bin"): "genesis.svg",
            (".rom", ".mx1", ".mx2"): "msx.svg",
        }
        for exts, archivo in mapa.items():
            if ext in exts:
                ruta = os.path.join(self._icon_dir, archivo)
                if os.path.isfile(ruta):
                    return QIcon(ruta)
        return QIcon()

    def _poblar(self):
        self.lista.clear()
        texto = self.filtro.text().strip().lower()
        exts = self.tipo_combo.currentData()

        try:
            entradas = sorted(os.listdir(self._carpeta), key=str.lower)
        except OSError as e:
            self.estado.setText(f"No se pudo leer la carpeta: {e}")
            return

        mostrados = 0
        for nombre in entradas:
            ruta = os.path.join(self._carpeta, nombre)
            if not os.path.isfile(ruta) or nombre.startswith("."):
                continue
            if nombre == "LEEME.txt":
                continue
            if exts and os.path.splitext(nombre)[1].lower() not in exts:
                continue
            if texto and texto not in nombre.lower():
                continue
            try:
                tam = rf.fmt_bytes(os.path.getsize(ruta))
            except OSError:
                tam = "?"
            corto = nombre if len(nombre) <= 26 else nombre[:23] + "…"
            item = QListWidgetItem(self._icono(nombre), f"{corto}\n{tam}")
            item.setData(Qt.UserRole, ruta)
            item.setToolTip(f"{nombre}\n{tam}")
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.lista.addItem(item)
            mostrados += 1

        self._actualizar_estado(total=mostrados)

    def _actualizar_estado(self, total: int | None = None):
        if total is None:
            total = self.lista.count()
        seleccionados = len(self.lista.selectedItems())
        texto = f"{total} archivo(s) visibles"
        if seleccionados:
            bytes_totales = 0
            for i in self.lista.selectedItems():
                try:
                    bytes_totales += os.path.getsize(i.data(Qt.UserRole))
                except OSError:
                    pass
            texto += f"   ·   {seleccionados} seleccionado(s), {rf.fmt_bytes(bytes_totales)}"
        else:
            texto += "   ·   selecciona archivos para aplicarles una herramienta"
        self.estado.setText(texto)

        # El botón indica qué va a hacer según lo que haya seleccionado
        if hasattr(self, "ver_btn"):
            imagenes = [i for i in self.lista.selectedItems()
                        if os.path.splitext(i.data(Qt.UserRole))[1].lower() in EXT_IMAGENES]
            if imagenes:
                self.ver_btn.setText(f"Comprobar {len(imagenes)} imagen(es) de disco")
                self.ver_btn.setToolTip(
                    "Muestra en dos columnas cuáles se pueden extraer y cuáles no, "
                    "con el motivo")
            else:
                self.ver_btn.setText("Analizar la selección")
                self.ver_btn.setToolTip("")

    # -- acciones ----------------------------------------------------------
    def seleccion(self) -> list:
        return [i.data(Qt.UserRole) for i in self.lista.selectedItems()]

    def _lanzar(self, clave: str):
        rutas = self.seleccion()
        if not rutas:
            self.estado.setText(
                "Selecciona primero uno o varios archivos: las herramientas se "
                "aplican a lo que esté seleccionado.")
            return
        self.accion.emit(clave, rutas)

    def _analizar_seleccion(self):
        """Analiza lo seleccionado.

        Si son imágenes de disco, abre la comprobación en dos columnas (las
        que se pueden extraer y las que no). Mandar la información al panel de
        la ventana principal no servía de nada aquí: esa ventana queda detrás
        y no es accesible.
        """
        rutas = self.seleccion()
        if not rutas:
            self.estado.setText("Selecciona antes uno o varios archivos.")
            return

        imagenes = [r for r in rutas
                    if os.path.splitext(r)[1].lower() in EXT_IMAGENES]
        if imagenes:
            self.comprobar_discos.emit(imagenes)
            return
        self.analizar.emit(rutas[0])

    def _doble_clic(self, item: QListWidgetItem):
        self.analizar.emit(item.data(Qt.UserRole))

    def refrescar(self):
        self._poblar()
