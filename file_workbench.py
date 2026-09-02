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

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView,
    QListWidget, QListWidgetItem, QPushButton, QStyle, QVBoxLayout,
)

import rom_formats as rf
import system_detect as sd

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
    return mejor if votos[mejor] > 0 else por_defecto


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
        self.setMinimumSize(1400, 860)
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

        # Botón para volver directamente a la carpeta raíz de ASTURCONSOLE:
        # sin esto, si el usuario navega desde ahí hasta una carpeta
        # profunda (p. ej. "roms con formato SMD") y luego quiere ir a
        # otra carpeta distinta, no tenía más remedio que cerrar toda esta
        # ventana y volver a empezar desde cero.
        self.volver_btn = QPushButton(" Carpeta Asturconsole")
        self.volver_btn.setIcon(QIcon(os.path.join(self._icon_dir, "asturias.svg")) if self._icon_dir else QIcon())
        self.volver_btn.setIconSize(QSize(20, 20))
        self.volver_btn.setCursor(Qt.PointingHandCursor)
        self.volver_btn.setToolTip("Volver a la carpeta raíz para elegir otra carpeta distinta")
        self.volver_btn.setStyleSheet(
            "QPushButton { background: rgba(78,158,246,0.10); color: #4e9ef6;"
            " border: 2px solid #2b4d6b; border-radius: 6px; padding: 9px 14px;"
            " font-weight: 700; }"
            "QPushButton:hover { border-color: #4e9ef6; background: rgba(78,158,246,0.18); }"
        )
        self.volver_btn.clicked.connect(
            lambda: (_destellar(self.volver_btn), self.volver_a_asturconsole.emit()))
        pl.addWidget(self.volver_btn)

        # Transferencia por puerto paralelo: botón propio y destacado, no
        # mezclado entre las demás herramientas — es la acción que de
        # verdad requiere hardware conectado (copión + puerto paralelo
        # real), así que merece más presencia que "una más de la lista".
        # Sin texto fijo: cambia entre Super Wild Card / SMD según el
        # sistema activo, y se oculta del todo para MSX (sin transferencia
        # por puerto paralelo en este proyecto).
        self.transferir_btn = QPushButton("")
        self.transferir_btn.setCursor(Qt.PointingHandCursor)
        self.transferir_btn.setStyleSheet(
            "QPushButton { background: rgba(62,242,154,0.10); color: #3ef29a;"
            " border: 2px solid #2b6b52; border-radius: 6px; padding: 9px 14px;"
            " font-weight: 700; }"
            "QPushButton:hover { border-color: #3ef29a; background: rgba(62,242,154,0.18); }"
        )
        self.transferir_btn.clicked.connect(
            lambda: (_destellar(self.transferir_btn), self._lanzar("send")))
        pl.addWidget(self.transferir_btn)
        self._actualizar_boton_transferencia()

        self.ver_btn = QPushButton("Analizar la selección")
        self.ver_btn.setObjectName("Principal")
        self.ver_btn.setCursor(Qt.PointingHandCursor)
        self.ver_btn.clicked.connect(
            lambda: (_destellar(self.ver_btn), self._analizar_seleccion()))
        pl.addWidget(self.ver_btn)
        cuerpo.addWidget(panel)
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

        for clave, texto, descripcion in self._acciones_por_sistema.get(self._sistema, []):
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
            self.transferir_btn.setText("⇄  Enviar a Super Wild Card (puerto paralelo)")
            self.transferir_btn.setVisible(True)
        elif self._sistema == "genesis":
            self.transferir_btn.setText("⇄  Enviar a SMD (puerto paralelo)")
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
            item = QListWidgetItem(icono_carpeta, f"{corto}")
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
