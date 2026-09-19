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
import shutil
import subprocess
import sys

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap,
)
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListView, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QStyle, QVBoxLayout, QWidget,
)

import game_genie as gg
import rom_formats as rf
import system_detect as sd
import transfer_ucon64 as tu
import workspace as ws


def _app_base_dir() -> str:
    """Carpeta base de la app: la del ejecutable si PyInstaller la ha
    empaquetado (sys._MEIPASS), o la del propio script en ejecución
    normal. Duplicado de main.py/transfer_ucon64.py — mismo motivo: no
    crear una dependencia circular entre módulos por una sola función."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


# Sello grande superpuesto sobre el icono de carpeta, para que el tipo de
# archivos que contiene se vea de un vistazo sin tener que entrar ni leer
# el nombre completo. Se evalúa por palabras clave (en orden, la primera
# que encaje) en vez de por un mapeo exacto de nombre de carpeta completo,
# para que funcione igual en cualquier sistema sin tener que mantener una
# lista aparte por cada uno.
SELLOS_CARPETA: list[tuple[str, str, str]] = [
    ("sin cabecera", "ROM",  "#5aa0ff"),  # antes que "cabecera" a secas
    ("hfe",         "HFE",  "#5aa0ff"),
    ("swc",         "SWC",  "#3ef29a"),
    ("magic drive", "SMD",  "#ffb454"),  # "discos Super Magic Drive"
    ("smd",         "SMD",  "#ffb454"),  # "roms con formato SMD"
    ("dsk",         "DSK",  "#3ef29a"),
    ("cabecera",    "HDR",  "#c9a227"),
    ("checksum",    "CHK",  "#e06c75"),
    ("hirom",       "BANK", "#a48cff"),
    ("bancos",      "BANK", "#a48cff"),
    ("byte swap",   "SWAP", "#a48cff"),
    ("dividid",     "PART", "#8892a8"),
    ("8.3",         "8.3",  "#8892a8"),
    ("extraido",    "EXT",  "#8892a8"),
    ("cintas",      "TAPE", "#d4af37"),
    ("catálogo",    "CAT",  "#5aa0ff"),
    ("sistema",     "SYS",  "#d4af37"),
]


def _sello_para_carpeta(nombre: str) -> tuple[str, str] | None:
    """(texto, color) del sello a dibujar, o None si el nombre no encaja
    con ninguna palabra clave conocida."""
    bajo = nombre.lower()
    for clave, texto, color in SELLOS_CARPETA:
        if clave in bajo:
            return texto, color
    return None


def _icono_carpeta_con_sello(icono_base: QIcon, nombre: str) -> QIcon:
    """Dibuja el icono estándar de carpeta con el sello del tipo de
    contenido superpuesto en grande, para que se distinga de un vistazo."""
    sello = _sello_para_carpeta(nombre)
    if sello is None:
        return icono_base

    texto, color = sello
    tam = 56
    pixmap = icono_base.pixmap(tam, tam)
    lienzo = QPixmap(tam, tam)
    lienzo.fill(Qt.transparent)
    pintor = QPainter(lienzo)
    pintor.setRenderHint(QPainter.Antialiasing)
    pintor.drawPixmap(0, 0, pixmap)

    fuente = QFont()
    fuente.setBold(True)
    fuente.setPixelSize(15 if len(texto) <= 3 else 12)
    pintor.setFont(fuente)

    # Fondo semiopaco tras el texto, para que se lea bien sobre cualquier
    # parte del icono de carpeta, sea clara u oscura.
    metrica = pintor.fontMetrics()
    ancho_texto = metrica.horizontalAdvance(texto) + 8
    alto_texto = metrica.height() + 2
    x = (tam - ancho_texto) // 2
    y = tam - alto_texto - 6
    pintor.setBrush(QColor(color))
    pintor.setPen(Qt.NoPen)
    pintor.drawRoundedRect(x, y, ancho_texto, alto_texto, 4, 4)

    pintor.setPen(QColor("#0a0d14"))
    pintor.drawText(x, y, ancho_texto, alto_texto, Qt.AlignCenter, texto)
    pintor.end()

    return QIcon(lienzo)

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
QFrame#MarcoDestacadas {
    background: rgba(62,242,154,0.05);
    border: 1px solid #2c3342; border-radius: 8px;
}
QLabel#Seccion { color: #8892a8; font-size: 10px; font-weight: 700; }
"""

# Botones de "seleccionar todo" / "deseleccionar todo": marco de color
# grueso para que resalten frente al resto de botones neutros de la barra.
ESTILO_TODO = """
QPushButton {
    background: rgba(62,242,154,0.14); color: #3ef29a;
    border: 2px solid #3ef29a; border-radius: 5px;
    padding: 6px 12px; font-weight: 700;
}
QPushButton:hover { background: rgba(62,242,154,0.28); }
"""
ESTILO_NINGUNO = """
QPushButton {
    background: rgba(255,180,84,0.14); color: #ffb454;
    border: 2px solid #ffb454; border-radius: 5px;
    padding: 6px 12px; font-weight: 700;
}
QPushButton:hover { background: rgba(255,180,84,0.28); }
"""

EXT_IMAGENES = (".dsk", ".img", ".di1", ".di2")

# Extensiones características de cada sistema, para deducir con qué
# herramientas trabajar según lo que haya en la carpeta.
EXT_SISTEMA = {
    # Extensiones que sí identifican un sistema por sí solas, sin ambigüedad.
    # .rom, .bin y .dsk NO están aquí a propósito: son genéricas (las usan
    # varios sistemas en la práctica) y detectar_sistema() las resuelve
    # mirando el contenido real de un archivo de ejemplo, no por extensión.
    "snes":    (".sfc", ".smc", ".swc", ".fig", ".ufo"),
    "genesis": (".smd", ".gen", ".md"),
    "msx":     (".mx1", ".mx2", ".di1", ".di2", ".cas", ".tsx", ".wav"),
}

NOMBRE_SISTEMA = {
    "snes": "Super Nintendo",
    "genesis": "Mega Drive",
    "msx": "MSX",
}

# Las 4 acciones más usadas de cada sistema, destacadas arriba del todo del
# panel de herramientas con botones más grandes y coloreados — el resto de
# opciones (todas siguen disponibles) va debajo, en la lista normal de
# siempre. El orden de la lista decide la posición en el grid 2×2:
# [arriba-izquierda, arriba-derecha, abajo-izquierda, abajo-derecha].
# MSX no tiene una entrada aquí a propósito: no comparte este patrón de
# "cabecera + copión + HFE", así que para MSX el panel se queda tal cual
# estaba, sin ninguna sección destacada.
ACCIONES_DESTACADAS = {
    "snes":    ["prep_swc", "export_hfe", "swc", "rebuild_disks"],
    "genesis": ["prep_smd", "export_hfe", "bin2smd", "rebuild_disks"],
}

# Un color por posición del grid 2×2 — mismo criterio en los dos sistemas,
# para que quien pase de trabajar en SNES a Genesis reconozca el patrón
# visual ("lo de arriba-izquierda es siempre la acción todo-en-uno") en
# vez de tener que releer los botones cada vez.
_COLORES_DESTACADOS = ["#3ef29a", "#5aa0ff", "#ffb454", "#c9a8ff"]

# Salto de línea explícito para los textos largos de los botones
# destacados — un QPushButton normal no ajusta su texto automáticamente
# a varias líneas, así que sin esto el texto largo queda cortado en vez
# de leerse completo. Solo hace falta para las claves que de verdad no
# caben en una línea con el ancho actual del panel.
_SALTOS_TEXTO_DESTACADO = {
    "★ Añadir cabecera y dividir SWC": "★ Añadir cabecera\ny dividir SWC",
    "Exportar a HFE (HxC / FlashFloppy)": "Exportar a HFE\n(HxC / FlashFloppy)",
    "Añadir cabecera Super Wild Card": "Añadir cabecera\nSuper Wild Card",
    "↩ Reconstruir desde discos divididos": "↩ Reconstruir desde\ndiscos divididos",
    "★ Añadir cabecera SMD y guardar en disco": "★ Añadir cabecera SMD\ny guardar en disco",
    "★ Convertir a formato SMD (un solo archivo)": "★ Convertir a formato SMD\n(un solo archivo)",
}


def _estilo_boton_destacado(color: str) -> str:
    return f"""
QPushButton {{
    background: rgba({_hex_a_rgb(color)},0.14); color: {color};
    border: 2px solid {color}; border-radius: 8px;
    padding: 14px 12px; font-weight: 700; font-size: 12.5px;
    text-align: center;
}}
QPushButton:hover {{ background: rgba({_hex_a_rgb(color)},0.26); }}
"""


def _hex_a_rgb(color: str) -> str:
    color = color.lstrip("#")
    return f"{int(color[0:2], 16)},{int(color[2:4], 16)},{int(color[4:6], 16)}"


def _destellar(boton):
    """Da un destello visual breve al pulsar un botón: confirma que el
    clic se registró aunque la acción tarde un poco en notarse, o —si
    algo fallara en silencio— que al menos el botón respondió, para
    descartar de un vistazo que el problema sea "el clic no llegó".
    """
    estilo_original = boton.styleSheet()
    boton.setStyleSheet(estilo_original + " background-color: #3ef29a; color: #0d1117;")
    QTimer.singleShot(150, lambda: boton.setStyleSheet(estilo_original))


def detectar_sistema(carpeta: str, por_defecto: str = "snes") -> str:
    """Deduce a qué sistema pertenece el contenido de una carpeta.

    Cuenta las extensiones de los archivos y devuelve el sistema con más
    coincidencias. Es lo que evita que, estando en la pestaña de MSX, al
    abrir una carpeta de ROMs de SNES aparezcan las herramientas de MSX.

    Hay extensiones que NO se cuentan a ciegas, porque son ambiguas —las
    usan varios sistemas en la práctica, aunque aquí solo estuvieran
    mapeadas a uno—, y para ellas se mira el contenido real de un archivo
    de ejemplo en su lugar (con system_detect.detectar, que sí reconoce
    firmas reales: checksum de SNES, cabecera SEGA, etc.):

      - .dsk: imagen de disco MSX o del Super Magic Drive/Super Wild Card
        (se distingue por la estructura del propio sistema de archivos:
        nfat=1 en los discos SMD/SWC, nfat=2 en los de MSX).
      - .rom / .bin: extensión genérica de ROM, nada exclusivo de un
        sistema — antes se contaban siempre como MSX/Genesis sin más
        (según cuál), haciendo que una carpeta de ROMs de SNES con
        extensión .rom abriera las herramientas de MSX por error.
      - .img: igual de ambigua, y con un problema añadido — antes ni
        siquiera se miraba (se ignoraba sin más), así que una carpeta
        llena de discos SWC/SMD ya divididos (todos con extensión .img,
        sin ningún otro archivo con extensión reconocible) no aportaba
        NINGÚN voto a ningún sistema y el resultado caía siempre en la
        pestaña activa, aunque fuera la equivocada. Aquí, a diferencia de
        .dsk, la estructura del disco en sí no sirve de pista (todos son
        FAT12 estándar de 1.44 MB): se abre el disco, se extrae el
        archivo de dentro, y se analiza SU contenido — es la propia ROM
        (con o sin cabecera de copiador), así que la firma real sigue
        estando ahí para reconocerla.
    """
    votos = {clave: 0 for clave in EXT_SISTEMA}
    ejemplo_dsk = None
    ejemplo_generico = None
    ejemplo_img = None
    try:
        for nombre in os.listdir(carpeta):
            ruta = os.path.join(carpeta, nombre)
            if not os.path.isfile(ruta):
                continue
            ext = os.path.splitext(nombre)[1].lower()
            if ext == ".img":
                if ejemplo_img is None:
                    ejemplo_img = ruta
                continue  # se decide más abajo, tras revisar el contenido
            if ext == ".dsk":
                if ejemplo_dsk is None:
                    ejemplo_dsk = ruta
                continue  # se decide más abajo, tras revisar el contenido
            if ext in (".rom", ".bin"):
                if ejemplo_generico is None:
                    ejemplo_generico = ruta
                continue  # igual: se decide por contenido, no por extensión
            for clave, exts in EXT_SISTEMA.items():
                if ext in exts:
                    votos[clave] += 1
    except OSError:
        return por_defecto

    if ejemplo_dsk is not None:
        try:
            with open(ejemplo_dsk, "rb") as fh:
                cabecera = fh.read(512)
            deteccion = sd._detectar_disco_smd(cabecera)
            votos["genesis" if deteccion else "msx"] += 1
        except OSError:
            votos["msx"] += 1  # si no se puede ni leer, se asume MSX por ser lo más común

    if ejemplo_generico is not None:
        try:
            with open(ejemplo_generico, "rb") as fh:
                datos = fh.read(1024 * 1024)
            sistema = sd.detectar(datos, os.path.basename(ejemplo_generico)).sistema
            votos[sistema or "msx"] += 1
        except OSError:
            votos["msx"] += 1

    if ejemplo_img is not None:
        try:
            with open(ejemplo_img, "rb") as fh:
                datos_disco = fh.read()
            dsk = rf.parse_dsk(datos_disco)
            if dsk.entries:
                contenido = rf.reconstruct_dsk_file(dsk, dsk.entries[0])
                sistema = sd.detectar(contenido, dsk.entries[0].name).sistema
                if sistema:
                    votos[sistema] += 1
        except (OSError, ValueError):
            pass  # un .img que no se puede interpretar simplemente no vota

    mejor = max(votos, key=lambda k: votos[k])
    if votos[mejor] > 0:
        return mejor

    # Sin ningún archivo reconocible directamente en la carpeta (el caso
    # típico: la raíz de un sistema recién creada por esta misma
    # aplicación, que solo tiene subcarpetas dentro como "roms
    # originales"/"con cabecera", sin ningún archivo suelto todavía). Antes
    # de caer al valor por defecto —que es el sistema de la pestaña DESDE
    # LA QUE se abrió el explorador, que puede no tener nada que ver con
    # la carpeta elegida: navegar desde "Carpeta Asturconsole" estando en
    # la pestaña de MSX hasta la raíz de "MEGA DRIVE" abría las
    # herramientas de MSX por error—, se comprueba si el propio nombre de
    # la carpeta, o el de alguna carpeta contenedora, coincide con la raíz
    # de un sistema conocido (los mismos nombres que usa workspace.py:
    # "SNES", "MEGA DRIVE", "MSX").
    segmentos = {p.upper() for p in os.path.normpath(carpeta).split(os.sep)}
    for nombre_raiz, clave in (("SNES", "snes"), ("MEGA DRIVE", "genesis"), ("MSX", "msx")):
        if nombre_raiz in segmentos:
            return clave

    return por_defecto


class FileWorkbench(QDialog):
    """Ventana de trabajo sobre los archivos de una carpeta."""

    analizar = Signal(str)               # ver un archivo en el panel de detalle
    accion = Signal(str, list, str)      # (clave de acción, rutas, sistema detectado)
    comprobar_discos = Signal(list)      # revisar un lote de imágenes de disco
    analizar_roms = Signal(list, str)    # (rutas, sistema) — cabeceras SNES/Genesis

    sistema_cambiado = Signal(str)
    volver_a_asturconsole = Signal()     # botón de "ir a la carpeta raíz de nuevo"

    def __init__(self, carpeta: str, sistema: str, acciones_por_sistema: dict,
                 icon_dir: str = "", parent=None):
        """`acciones_por_sistema` es {clave_sistema: [(clave, texto, desc)]}."""
        super().__init__(parent)
        self._titulo_base = os.path.basename(carpeta) or carpeta
        # Los 3 botones típicos de ventana (minimizar/maximizar/cerrar) —
        # antes solo tenía el de cerrar, propio de un QDialog normal. Y
        # se abre en tamaño normal, no maximizada — se puede agrandar a
        # mano si hace falta, pero de entrada no debería imponerse.
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint |
                            Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        self.setMinimumSize(1450, 780)
        self.resize(1900, 940)
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

        fila_ruta = QHBoxLayout()
        self.subir_btn = QPushButton("⬆")
        self.subir_btn.setToolTip("Subir a la carpeta contenedora")
        self.subir_btn.setFixedWidth(36)
        self.subir_btn.setCursor(Qt.PointingHandCursor)
        self.subir_btn.clicked.connect(self._subir)
        fila_ruta.addWidget(self.subir_btn)
        self.ruta_lbl = QLabel(carpeta)
        self.ruta_lbl.setObjectName("Ruta")
        self.ruta_lbl.setWordWrap(True)
        fila_ruta.addWidget(self.ruta_lbl, 1)
        raiz.addLayout(fila_ruta)

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
        self.todos_btn.setStyleSheet(ESTILO_TODO)
        self.todos_btn.clicked.connect(lambda: self.lista.selectAll())
        barra.addWidget(self.todos_btn)
        self.ninguno_btn = QPushButton("Deseleccionar todo")
        self.ninguno_btn.setStyleSheet(ESTILO_NINGUNO)
        self.ninguno_btn.clicked.connect(lambda: self.lista.clearSelection())
        barra.addWidget(self.ninguno_btn)
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
        panel.setFixedWidth(380)
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

        # Las 4 más usadas, en grid 2×2 con más presencia visual — el resto
        # de opciones (todas siguen ahí) va debajo, en la lista normal.
        self._marco_destacadas = QFrame()
        self._marco_destacadas.setObjectName("MarcoDestacadas")
        self._grid_destacadas = QGridLayout(self._marco_destacadas)
        self._grid_destacadas.setSpacing(8)
        self._grid_destacadas.setContentsMargins(10, 10, 10, 10)
        pl.addWidget(self._marco_destacadas)
        self._botones_destacados = []

        et_resto = QLabel("MÁS OPCIONES")
        et_resto.setObjectName("Seccion")
        self._et_resto = et_resto
        pl.addWidget(et_resto)

        self._contenedor_acciones = QVBoxLayout()
        self._contenedor_acciones.setSpacing(7)
        pl.addLayout(self._contenedor_acciones)
        self._botones = []
        self._construir_acciones()

        pl.addStretch(1)
        cuerpo.addWidget(panel)

        # Columna de Game Genie: por ahora solo el hueco preparado (la
        # funcionalidad completa —buscar códigos por juego y aplicarlos a
        # la ROM elegida— es una pieza grande aparte). No se muestra en
        # MSX, donde no aplica.
        self.panel_gg = QFrame()
        self.panel_gg.setObjectName("Panel")
        self.panel_gg.setFixedWidth(340)
        pl_gg = QVBoxLayout(self.panel_gg)
        pl_gg.setContentsMargins(12, 12, 12, 12)
        pl_gg.setSpacing(7)

        # Solo esta parte (título + aviso, con su propio stretch) se
        # oculta en MSX — el separador y los tres botones de abajo, no:
        # "Analizar la selección"/"Carpeta Asturconsole" hacen falta en
        # todos los sistemas, aunque MSX no tenga Game Genie ni
        # transferencia por puerto paralelo (ese botón sí se oculta aparte,
        # ver _actualizar_boton_transferencia).
        self._bloque_game_genie = QWidget()
        bloque_gg_lay = QVBoxLayout(self._bloque_game_genie)
        bloque_gg_lay.setContentsMargins(0, 0, 0, 0)
        bloque_gg_lay.setSpacing(6)
        et_gg = QLabel("GAME GENIE")
        et_gg.setObjectName("Seccion")
        bloque_gg_lay.addWidget(et_gg)

        # El índice (parseo de los .txt) se carga perezosamente, la
        # primera vez que se escribe algo en el buscador — no al abrir la
        # ventana, para no gastar tiempo en ello si el usuario no va a
        # tocar este panel en toda la sesión (ver diseño: pensado para no
        # molestar en absoluto a quien no usa trucos).
        self._gg_indice: tuple = ()
        self._gg_indice_cargado = False

        self._gg_buscar_edit = QLineEdit()
        self._gg_buscar_edit.setPlaceholderText("Buscar juego…")
        self._gg_buscar_edit.textChanged.connect(self._gg_buscar)
        bloque_gg_lay.addWidget(self._gg_buscar_edit)

        self._gg_resultados = QListWidget()
        self._gg_resultados.setMaximumHeight(110)
        self._gg_resultados.itemClicked.connect(self._gg_juego_elegido)
        bloque_gg_lay.addWidget(self._gg_resultados)

        et_codigos = QLabel("Trucos del juego elegido (marca los que quieras aplicar):")
        et_codigos.setWordWrap(True)
        et_codigos.setStyleSheet("color: #8892a8; font-size: 11px;")
        bloque_gg_lay.addWidget(et_codigos)

        self._gg_codigos = QListWidget()
        bloque_gg_lay.addWidget(self._gg_codigos, 1)

        fila_manual = QHBoxLayout()
        self._gg_manual_edit = QLineEdit()
        self._gg_manual_edit.setPlaceholderText("o pega un código a mano…")
        self._gg_manual_edit.returnPressed.connect(self._gg_anadir_manual)
        fila_manual.addWidget(self._gg_manual_edit, 1)
        btn_manual = QPushButton("+")
        btn_manual.setFixedWidth(28)
        btn_manual.setToolTip("Añadir este código a la lista, ya marcado")
        btn_manual.setCursor(Qt.PointingHandCursor)
        btn_manual.clicked.connect(self._gg_anadir_manual)
        fila_manual.addWidget(btn_manual)
        bloque_gg_lay.addLayout(fila_manual)

        self._gg_aplicar_btn = QPushButton("Aplicar a una copia")
        self._gg_aplicar_btn.setCursor(Qt.PointingHandCursor)
        self._gg_aplicar_btn.setToolTip(
            "Crea una copia de la ROM seleccionada con los códigos marcados "
            "ya aplicados — el archivo original nunca se toca")
        self._gg_aplicar_btn.clicked.connect(self._gg_aplicar)
        bloque_gg_lay.addWidget(self._gg_aplicar_btn)

        # Discreto a propósito: los otros tres sistemas (NES, Game Boy,
        # Game Gear) no tienen ROM en esta app, así que no hay ningún
        # sitio natural donde "aplicarlos" — se dejan solo como consulta,
        # sin ocupar más espacio que esta única línea.
        btn_ver_todos = QPushButton("Ver todos los códigos (incluye NES, Game Boy, Game Gear)")
        btn_ver_todos.setFlat(True)
        btn_ver_todos.setCursor(Qt.PointingHandCursor)
        btn_ver_todos.setStyleSheet(
            "QPushButton { color: #8892a8; font-size: 10px; border: none; "
            "text-align: left; padding: 2px 0; }"
            "QPushButton:hover { color: #b8c0d8; text-decoration: underline; }"
        )
        btn_ver_todos.clicked.connect(self._gg_abrir_carpeta_completa)
        bloque_gg_lay.addWidget(btn_ver_todos)

        pl_gg.addWidget(self._bloque_game_genie, 1)

        # Las tres acciones "globales" (no específicas de ninguna
        # herramienta de sistema) viven aquí abajo, separadas del hueco de
        # Game Genie por una línea — antes estaban en el panel izquierdo,
        # pero ahí competían por espacio con las herramientas propias de
        # SNES/Genesis, mientras que esta columna quedaba con mucho hueco
        # vacío arriba. Encajan bien aquí además por el propio flujo: se
        # busca/aplica un truco arriba, y justo debajo está transferir.
        separador_gg = QFrame()
        separador_gg.setFrameShape(QFrame.HLine)
        separador_gg.setStyleSheet("background: #2c3342; max-height: 1px; border: none;")
        pl_gg.addWidget(separador_gg)

        self.ver_btn = QPushButton("Analizar la selección")
        self.ver_btn.setObjectName("Principal")
        self.ver_btn.setCursor(Qt.PointingHandCursor)
        self.ver_btn.clicked.connect(
            lambda: (_destellar(self.ver_btn), self._analizar_seleccion()))
        pl_gg.addWidget(self.ver_btn)

        fila_destacados_abajo = QHBoxLayout()
        fila_destacados_abajo.setSpacing(8)

        self.volver_btn = QPushButton("📁  Carpeta\nAsturconsole")
        self.volver_btn.setCursor(Qt.PointingHandCursor)
        self.volver_btn.setToolTip("Volver a la carpeta raíz para elegir otra carpeta distinta")
        self.volver_btn.setMinimumHeight(64)
        self.volver_btn.setStyleSheet(_estilo_boton_destacado("#4e9ef6"))
        self.volver_btn.clicked.connect(
            lambda: (_destellar(self.volver_btn), self.volver_a_asturconsole.emit()))
        fila_destacados_abajo.addWidget(self.volver_btn, 1)

        # Transferencia por puerto paralelo: sin texto fijo, cambia entre
        # Super Wild Card / SMD según el sistema activo, y se oculta del
        # todo para MSX (sin transferencia por puerto paralelo en este
        # proyecto).
        self.transferir_btn = QPushButton("")
        self.transferir_btn.setCursor(Qt.PointingHandCursor)
        self.transferir_btn.setMinimumHeight(64)
        self.transferir_btn.setStyleSheet(_estilo_boton_destacado("#3ef29a"))
        self.transferir_btn.clicked.connect(
            lambda: (_destellar(self.transferir_btn), self._lanzar("send")))
        fila_destacados_abajo.addWidget(self.transferir_btn, 1)
        self._actualizar_boton_transferencia()

        pl_gg.addLayout(fila_destacados_abajo)
        self._bloque_game_genie.setVisible(bool(ACCIONES_DESTACADAS.get(self._sistema, [])))
        cuerpo.addWidget(self.panel_gg)

        raiz.addLayout(cuerpo, 1)

        self.estado = QLabel("")
        self.estado.setStyleSheet("color: #8892a8; font-size: 11px;")
        self.estado.setWordWrap(True)
        raiz.addWidget(self.estado)

        self._actualizar_boton_subir()
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

        while self._grid_destacadas.count():
            item = self._grid_destacadas.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._botones_destacados = []

        claves_destacadas = ACCIONES_DESTACADAS.get(self._sistema, [])
        acciones = self._acciones_por_sistema.get(self._sistema, [])
        por_clave = {clave: (texto, descripcion) for clave, texto, descripcion in acciones}
        bloque_gg = getattr(self, "_bloque_game_genie", None)
        if bloque_gg is not None:
            bloque_gg.setVisible(bool(claves_destacadas))

        # Las 4 destacadas, en el grid 2×2 — en el orden fijo de
        # ACCIONES_DESTACADAS, no en el orden en que aparezcan en la lista
        # general (para que la posición de cada una sea siempre la misma).
        if claves_destacadas:
            self._marco_destacadas.setVisible(True)
            self._et_resto.setVisible(True)
            for posicion, clave in enumerate(claves_destacadas):
                if clave not in por_clave:
                    continue
                texto, descripcion = por_clave[clave]
                b = QPushButton(_SALTOS_TEXTO_DESTACADO.get(texto, texto))
                if descripcion:
                    b.setToolTip(descripcion)
                b.setCursor(Qt.PointingHandCursor)
                b.setMinimumHeight(64)
                b.setStyleSheet(_estilo_boton_destacado(
                    _COLORES_DESTACADOS[posicion % len(_COLORES_DESTACADOS)]))
                b.clicked.connect(
                    lambda _checked=False, c=clave, btn=b: (_destellar(btn), self._lanzar(c)))
                self._grid_destacadas.addWidget(b, posicion // 2, posicion % 2)
                self._botones_destacados.append(b)
        else:
            # MSX no tiene destacadas propias: se oculta la sección entera
            # en vez de dejarla vacía con una etiqueta "MÁS OPCIONES" que
            # no estaría distinguiendo nada de nada.
            self._marco_destacadas.setVisible(False)
            self._et_resto.setVisible(False)

        for clave, texto, descripcion in acciones:
            if clave in claves_destacadas:
                continue  # ya está arriba, en el grid
            b = QPushButton(texto)
            if descripcion:
                b.setToolTip(descripcion)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _checked=False, c=clave, btn=b: (_destellar(btn), self._lanzar(c)))
            self._contenedor_acciones.addWidget(b)
            self._botones.append(b)

        nombre = NOMBRE_SISTEMA.get(self._sistema, self._sistema)
        self.detectado_lbl.setText(
            f"Herramientas de {nombre}, elegidas según el contenido de la carpeta. "
            "Cámbialo arriba si no es lo que esperabas.")
        # El botón de transferencia se crea DESPUÉS de la primera llamada a
        # este método (ver __init__): en esa primera vez todavía no existe,
        # así que se comprueba antes de tocarlo.
        if hasattr(self, "transferir_btn"):
            self._actualizar_boton_transferencia()

    def _actualizar_boton_transferencia(self):
        """Solo tiene sentido para SNES/Genesis (transferencia al copión
        por puerto paralelo); en MSX se oculta del todo."""
        if self._sistema == "snes":
            self.transferir_btn.setText("⇄  Enviar a Super Wild Card\n(puerto paralelo)")
            self.transferir_btn.setVisible(True)
        elif self._sistema == "genesis":
            self.transferir_btn.setText("⇄  Enviar a SMD\n(puerto paralelo)")
            self.transferir_btn.setVisible(True)
        else:
            self.transferir_btn.setVisible(False)

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

        # Carpetas primero, después archivos — mismo orden que cualquier
        # explorador. Se listan aunque haya un filtro de "Tipo" activo (ese
        # filtro es por extensión de archivo, no aplica a carpetas), pero sí
        # respetan el filtro de texto por nombre. No son seleccionables:
        # solo sirven para navegar con doble clic, así que no interfieren
        # con "Seleccionar todo" ni con aplicar herramientas por accidente.
        icono_carpeta = self.style().standardIcon(QStyle.SP_DirIcon)
        for nombre in entradas:
            ruta = os.path.join(self._carpeta, nombre)
            if not os.path.isdir(ruta) or nombre.startswith("."):
                continue
            if texto and texto not in nombre.lower():
                continue
            corto = nombre if len(nombre) <= 26 else nombre[:23] + "…"
            icono = _icono_carpeta_con_sello(icono_carpeta, nombre)
            item = QListWidgetItem(icono, f"{corto}")
            item.setData(Qt.UserRole, ruta)
            item.setToolTip(f"{nombre}  (carpeta — doble clic para entrar)")
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.lista.addItem(item)

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

    def _gg_buscar(self, texto: str):
        """Busca en el índice de Game Genie del sistema activo (solo
        SNES/Genesis tienen panel — MSX lo oculta por completo, ver
        _bloque_game_genie.setVisible en _construir_acciones)."""
        if not self._gg_indice_cargado:
            carpeta = os.path.join(_app_base_dir(), "data", "game_genie")
            self._gg_indice = gg.cargar_indice(self._sistema, carpeta)
            self._gg_indice_cargado = True
        self._gg_resultados.clear()
        self._gg_codigos.clear()
        if not self._gg_indice:
            return
        for juego in gg.buscar(self._gg_indice, texto):
            item = QListWidgetItem(juego.nombre)
            item.setData(Qt.UserRole, juego)
            self._gg_resultados.addItem(item)

    def _gg_juego_elegido(self, item: QListWidgetItem):
        juego = item.data(Qt.UserRole)
        self._gg_codigos.clear()
        for c in juego.codigos:
            it = QListWidgetItem(f"{c.codigo}\n{c.descripcion}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, c.codigo)
            self._gg_codigos.addItem(it)

    def _gg_anadir_manual(self):
        texto = self._gg_manual_edit.text().strip().upper()
        if not texto:
            return
        it = QListWidgetItem(f"{texto}\n(código introducido a mano)")
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked)
        it.setData(Qt.UserRole, texto)
        self._gg_codigos.addItem(it)
        self._gg_manual_edit.clear()

    def _gg_aplicar(self):
        """Copia la ROM seleccionada (nunca se toca el original) y le
        aplica, uno detrás de otro, todos los códigos marcados — cada
        código es una llamada aparte a ucon64 --gg=, que no admite varios
        códigos en una sola pasada (ver game_genie.separar_codigo para
        los que además vienen combinados con " + ", frecuente en
        Genesis: un solo efecto necesita más de un código a la vez)."""
        marcados = []
        for i in range(self._gg_codigos.count()):
            it = self._gg_codigos.item(i)
            if it.checkState() == Qt.Checked:
                marcados.append(it.data(Qt.UserRole))
        if not marcados:
            QMessageBox.information(
                self, "Game Genie", "Marca al menos un código antes de aplicar.")
            return

        seleccion = self.seleccion()
        if not seleccion:
            QMessageBox.information(
                self, "Game Genie",
                "Selecciona primero, en la lista de archivos, la ROM a la "
                "que quieres aplicar los códigos.")
            return
        origen = seleccion[0]

        ucon64 = tu.find_ucon64()
        if not ucon64:
            QMessageBox.critical(
                self, "Game Genie",
                "No se encontró uCON64 — no se puede aplicar el código.")
            return

        nombre, ext = os.path.splitext(os.path.basename(origen))
        destino_dir = ws.folder("game_genie", self._sistema)
        destino = ws.unique_path(destino_dir, f"{nombre}_GG{ext}")
        try:
            shutil.copy2(origen, destino)
        except OSError as e:
            QMessageBox.critical(self, "Game Genie", f"No se pudo crear la copia: {e}")
            return

        # Flags de ucon64 para forzar el reconocimiento de consola: "gen"
        # y "snes" son los nombres cortos reales (confirmados en el
        # propio código fuente, ucon64_defines.h) — no "genesis".
        flag_sistema = "--snes" if self._sistema == "snes" else "--gen"
        total_partes = sum(len(gg.separar_codigo(c)) for c in marcados)
        aplicados, errores = [], []
        for codigo_combinado in marcados:
            for codigo in gg.separar_codigo(codigo_combinado):
                cmd = [ucon64, flag_sistema, f"--gg={codigo}", "-nbak", destino]
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                except (OSError, subprocess.TimeoutExpired) as e:
                    errores.append(f"{codigo}: {e}")
                    continue
                salida = (r.stdout or "") + (r.stderr or "")
                if r.returncode != 0 or "ERROR" in salida.upper():
                    errores.append(f"{codigo}: {salida.strip()[:200] or 'fallo desconocido'}")
                else:
                    aplicados.append(codigo)

        mensaje = (f"Copia creada:\n{destino}\n\n"
                   f"Códigos aplicados: {len(aplicados)}/{total_partes}")
        if errores:
            mensaje += "\n\nErrores:\n" + "\n".join(errores[:10])
        if aplicados:
            QMessageBox.information(self, "Game Genie", mensaje)
        else:
            QMessageBox.warning(self, "Game Genie", mensaje)

    def _gg_abrir_carpeta_completa(self):
        carpeta = os.path.join(_app_base_dir(), "data", "game_genie")
        QDesktopServices.openUrl(QUrl.fromLocalFile(carpeta))

    def _lanzar(self, clave: str):
        rutas = self.seleccion()
        if not rutas:
            self.estado.setText(
                "Selecciona primero uno o varios archivos: las herramientas se "
                "aplican a lo que esté seleccionado.")
            return
        self.accion.emit(clave, rutas, self._sistema)

    def _analizar_seleccion(self):
        """Analiza lo seleccionado.

        - Si son imágenes de disco (MSX), abre la comprobación en dos
          columnas: las que se pueden extraer y las que no.
        - Si son ROMs de SNES o Mega Drive, abre la ventana de análisis con
          una pestaña por cada ROM seleccionada.
        Mandar el resultado al panel de la ventana principal (como se hacía
        antes) no servía de nada: esa ventana queda tapada detrás de esta y
        no es accesible mientras la ventana de trabajo está abierta.
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

        if self._sistema in ("snes", "genesis"):
            self.analizar_roms.emit(rutas, self._sistema)
            return

        self.analizar.emit(rutas[0])

    def _doble_clic(self, item: QListWidgetItem):
        ruta = item.data(Qt.UserRole)
        if os.path.isdir(ruta):
            self._navegar(ruta)
            return
        if (self._sistema in ("snes", "genesis")
                and os.path.splitext(ruta)[1].lower() not in EXT_IMAGENES):
            self.analizar_roms.emit([ruta], self._sistema)
            return
        self.analizar.emit(ruta)

    def _navegar(self, nueva_carpeta: str):
        """Cambia la carpeta de trabajo actual y refresca todo lo que
        depende de ella: el listado, la ruta mostrada, el sistema
        detectado (puede ser distinto en cada subcarpeta: por ejemplo,
        una carpeta con ROMs de SNES dentro de otra que solo tenía
        archivos .zip) y el botón de subir."""
        self._carpeta = nueva_carpeta
        self.ruta_lbl.setText(nueva_carpeta)
        self.filtro.clear()  # el filtro de texto no debe arrastrarse de la carpeta anterior
        # Tampoco el filtro de "Tipo": si quedaba en "ROMs SNES" (por ejemplo) desde la
        # carpeta anterior, ocultaba TODO el contenido de una subcarpeta con archivos de
        # otro tipo, dando la falsa impresión de que estaba vacía — visible solo aquí, no
        # al reabrir la ventana desde cero, porque ahí el combo siempre arranca en su
        # valor por defecto. blockSignals evita una doble llamada a _poblar (una por el
        # cambio de índice, otra explícita más abajo).
        self.tipo_combo.blockSignals(True)
        self.tipo_combo.setCurrentIndex(0)
        self.tipo_combo.blockSignals(False)

        nuevo_sistema = detectar_sistema(nueva_carpeta, self._sistema)
        if nuevo_sistema != self._sistema:
            self._sistema = nuevo_sistema
            i = self.sistema_combo.findData(self._sistema)
            if i >= 0:
                self.sistema_combo.blockSignals(True)
                self.sistema_combo.setCurrentIndex(i)
                self.sistema_combo.blockSignals(False)
            self._construir_acciones()

        self._actualizar_boton_subir()
        self._poblar()

    def _subir(self):
        padre = os.path.dirname(self._carpeta.rstrip(os.sep))
        if padre and padre != self._carpeta:
            self._navegar(padre)

    def _actualizar_boton_subir(self):
        padre = os.path.dirname(self._carpeta.rstrip(os.sep))
        self.subir_btn.setEnabled(
            bool(padre) and padre != self._carpeta and os.path.isdir(padre))

    def refrescar(self):
        self._poblar()
