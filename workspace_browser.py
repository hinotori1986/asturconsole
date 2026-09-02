"""Explorador de la carpeta de trabajo de ASTURCONSOLE.

Se abre con el botón «Carpeta Asturconsole» y muestra, en iconos grandes, la
estructura de carpetas que crea la aplicación. Cada carpeta conocida tiene su
icono propio; las que haya creado el usuario llevan todas el mismo icono
genérico, para distinguir de un vistazo lo que es de la aplicación y lo que
has añadido tú.

Es una ventana propia y no una llamada al explorador del sistema: así
funciona igual en cualquier equipo, sin depender de que haya un escritorio
instalado ni de que xdg-open esté disponible.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from PySide6.QtCore import QSize, Qt, Signal, QSettings
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QVBoxLayout,
)

import rom_formats as rf
import workspace as ws


def _guardar_ultima_ruta_explorador(raiz: str, ruta: str) -> None:
    """Recuerda la última subcarpeta visitada dentro de "Carpeta
    Asturconsole", para volver directamente ahí la próxima vez que se abra,
    en vez de empezar siempre desde el inicio.

    Se guarda la ruta RELATIVA a la raíz de trabajo, no la absoluta: la
    carpeta base puede vivir en un sitio distinto según el equipo o el
    usuario, pero la subcarpeta dentro de ella (p. ej. "MEGA DRIVE/discos
    Super Magic Drive") es estable de una sesión a otra.
    """
    rel = os.path.relpath(ruta, raiz)
    QSettings("ASTURCONSOLE", "asturconsole").setValue(
        "workspace_browser/ultima_ruta_rel", rel)


def _cargar_ultima_ruta_explorador() -> str:
    return str(QSettings("ASTURCONSOLE", "asturconsole").value(
        "workspace_browser/ultima_ruta_rel", ""))

ESTILO = """
QDialog { background: #0f111a; }
QLabel { color: #dde3ef; }
QLabel#Ruta {
    color: #8892a8; font-family: "IBM Plex Mono", monospace; font-size: 11px;
    background: #0a0b10; border: 1px solid #2c3342; border-radius: 5px; padding: 7px 10px;
}
QListWidget {
    background: #0a0b10; color: #dde3ef;
    border: 1px solid #2c3342; border-radius: 6px;
    outline: none;
}
QListWidget::item {
    border-radius: 8px; padding: 8px; margin: 4px;
    color: #c8d0e0;
}
QListWidget::item:hover { background: #161c28; }
QListWidget::item:selected { background: #22304a; color: #ffffff; }
QPushButton {
    background: #1f2330; color: #dde3ef;
    border: 1px solid #39404f; border-radius: 5px;
    padding: 7px 13px; font-weight: 600;
}
QPushButton:hover { border-color: #8892a8; background: #262b38; }
QPushButton#Principal {
    background: rgba(62,242,154,0.16); color: #3ef29a; border: 2px solid #3ef29a;
}
QPushButton#Principal:hover { background: rgba(62,242,154,0.30); }
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

# Extensiones que la aplicación sabe abrir, para ofrecerlo al hacer doble clic
EXT_IMAGENES = (".dsk", ".img", ".di1", ".di2")


class WorkspaceBrowser(QDialog):
    """Explorador propio de la carpeta de trabajo."""

    abrir_archivo = Signal(str)          # el usuario quiere analizar un archivo
    abrir_imagenes = Signal(list)        # abrir imágenes de disco en el extractor
    abrir_carpeta = Signal(str)          # trabajar con el contenido de una carpeta

    def __init__(self, parent=None, icon_dir: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Carpeta Asturconsole")
        self.setMinimumSize(940, 620)
        self.setStyleSheet(ESTILO)

        self._raiz = ws.ensure_workspace()
        self._actual = self._raiz
        self._icon_dir = icon_dir or ""

        # La última carpeta visitada NO se usa para saltar automáticamente
        # aquí (eso ya se hizo así una vez, y salía sin avisar de la vista
        # principal con las 3 secciones por sistema, algo mucho más
        # sorprendente de lo que merece la pena): se guarda en
        # self._ultima_rel_valida para ofrecerla como acceso rápido más
        # abajo, igual que en FolderPickerDialog — el usuario decide si
        # quiere ir ahí, nunca se le lleva sin más.
        self._ultima_rel_valida: str | None = None
        ultima_rel = _cargar_ultima_ruta_explorador()
        if ultima_rel and ultima_rel != ".":
            candidata = os.path.normpath(os.path.join(self._raiz, ultima_rel))
            raiz_abs = os.path.abspath(self._raiz)
            if (os.path.isdir(candidata)
                    and os.path.commonpath([os.path.abspath(candidata), raiz_abs]) == raiz_abs):
                self._ultima_rel_valida = ultima_rel

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        cabecera = QLabel(
            "Carpetas de trabajo de ASTURCONSOLE. Las que crea la aplicación tienen "
            "su propio icono; las que hayas creado tú llevan el icono de usuario."
        )
        cabecera.setWordWrap(True)
        lay.addWidget(cabecera)

        nav = QHBoxLayout()
        self.subir_btn = QPushButton("↑  Subir")
        self.subir_btn.clicked.connect(self._subir)
        self.raiz_btn = QPushButton("Inicio")
        self.raiz_btn.clicked.connect(lambda: self._ir(self._raiz))
        self.ultima_btn: QPushButton | None = None
        if self._ultima_rel_valida:
            self.ultima_btn = QPushButton(f"⭐ Última: {self._ultima_rel_valida}")
            self.ultima_btn.setToolTip(
                "La última subcarpeta con la que trabajaste. Un solo clic para "
                "volver directamente, sin tener que navegar de nuevo.")
            self.ultima_btn.clicked.connect(
                lambda: self._ir(os.path.join(self._raiz, self._ultima_rel_valida)))
        self.refrescar_btn = QPushButton("Actualizar")
        self.refrescar_btn.clicked.connect(self._poblar)
        self.copiar_btn = QPushButton("Copiar ruta")
        self.copiar_btn.setToolTip("Copia la ruta actual al portapapeles")
        self.copiar_btn.clicked.connect(self._copiar_ruta)
        self.trabajar_btn = QPushButton("Trabajar con esta carpeta")
        self.trabajar_btn.setToolTip(
            "Abre la ventana de trabajo con los archivos de la carpeta actual y "
            "las herramientas que correspondan a su contenido")
        self.trabajar_btn.setObjectName("Principal")
        self.trabajar_btn.clicked.connect(
            lambda: self._ir_a_trabajar(self._actual))
        self.todos_btn = QPushButton("Seleccionar todo")
        self.todos_btn.setToolTip("Selecciona todo lo visible en esta carpeta (Ctrl+A)")
        self.todos_btn.setStyleSheet(ESTILO_TODO)
        self.todos_btn.clicked.connect(lambda: self.lista.selectAll())
        self.ninguno_btn = QPushButton("Deseleccionar")
        self.ninguno_btn.setStyleSheet(ESTILO_NINGUNO)
        self.ninguno_btn.clicked.connect(lambda: self.lista.clearSelection())

        nav.addWidget(self.subir_btn)
        nav.addWidget(self.raiz_btn)
        if self.ultima_btn is not None:
            nav.addWidget(self.ultima_btn)
        nav.addWidget(self.refrescar_btn)
        nav.addWidget(self.todos_btn)
        nav.addWidget(self.ninguno_btn)
        nav.addStretch(1)
        nav.addWidget(self.copiar_btn)
        nav.addWidget(self.trabajar_btn)
        lay.addLayout(nav)

        self.ruta_lbl = QLabel("")
        self.ruta_lbl.setObjectName("Ruta")
        self.ruta_lbl.setWordWrap(True)
        lay.addWidget(self.ruta_lbl)

        self.lista = QListWidget()
        self.lista.setViewMode(QListView.IconMode)
        self.lista.setIconSize(QSize(72, 72))
        self.lista.setGridSize(QSize(150, 128))
        self.lista.setResizeMode(QListView.Adjust)
        self.lista.setMovement(QListView.Static)
        self.lista.setWordWrap(True)
        self.lista.setSpacing(4)
        self.lista.setSelectionMode(QListWidget.ExtendedSelection)
        self.lista.itemDoubleClicked.connect(self._doble_clic)
        self.lista.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu_contextual)
        lay.addWidget(self.lista, 1)

        self.estado = QLabel("")
        self.estado.setStyleSheet("color: #8892a8; font-size: 11px;")
        self.estado.setWordWrap(True)
        lay.addWidget(self.estado)

        atajo_todo = QShortcut(QKeySequence.SelectAll, self)
        atajo_todo.activated.connect(lambda: self.lista.selectAll())

        self._poblar()

    # -- iconos ------------------------------------------------------------
    def _icono_carpeta(self, nombre: str) -> QIcon:
        """Icono propio si es una carpeta de la aplicación; genérico si no."""
        conocidas = ws.nombres_de_carpetas()
        archivo = (nombre.replace(" ", "_") + ".svg") if nombre in conocidas else "_usuario.svg"
        ruta = os.path.join(self._icon_dir, "folders", archivo)
        if not os.path.isfile(ruta):
            ruta = os.path.join(self._icon_dir, "folders", "_usuario.svg")
        return QIcon(ruta) if os.path.isfile(ruta) else QIcon()

    def _icono_archivo(self, nombre: str) -> QIcon:
        ext = os.path.splitext(nombre)[1].lower()
        mapa = {
            (".dsk", ".img", ".di1", ".di2"): "floppy.svg",
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

    # -- navegación --------------------------------------------------------
    def _ir(self, ruta: str):
        if os.path.isdir(ruta):
            self._actual = os.path.abspath(ruta)
            _guardar_ultima_ruta_explorador(self._raiz, self._actual)
            self._poblar()

    def _subir(self):
        # No se sale de la carpeta de trabajo: es un explorador de ESA carpeta
        if os.path.abspath(self._actual) == os.path.abspath(self._raiz):
            return
        self._ir(os.path.dirname(self._actual))

    def _poblar(self):
        self.lista.clear()
        rel = os.path.relpath(self._actual, self._raiz)
        self.ruta_lbl.setText(self._actual if rel == "." else f"{self._raiz}  ›  {rel}")
        self.subir_btn.setEnabled(os.path.abspath(self._actual) != os.path.abspath(self._raiz))

        try:
            entradas = sorted(os.listdir(self._actual), key=str.lower)
        except OSError as e:
            self.estado.setText(f"No se pudo leer la carpeta: {e}")
            return

        carpetas = [e for e in entradas if os.path.isdir(os.path.join(self._actual, e))]
        archivos = [e for e in entradas
                    if os.path.isfile(os.path.join(self._actual, e)) and not e.startswith(".")]

        conocidas = ws.nombres_de_carpetas()
        propias = 0
        for nombre in carpetas:
            ruta = os.path.join(self._actual, nombre)
            try:
                n = len([f for f in os.listdir(ruta)
                         if not f.startswith(".") and f != "LEEME.txt"])
            except OSError:
                n = 0
            item = QListWidgetItem(self._icono_carpeta(nombre),
                                    f"{nombre}\n{n} elemento(s)" if n else f"{nombre}\nvacía")
            item.setData(Qt.UserRole, ("dir", ruta))
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            if nombre in conocidas:
                propias += 1
            else:
                item.setToolTip("Carpeta creada por ti")
            self.lista.addItem(item)

        for nombre in archivos:
            ruta = os.path.join(self._actual, nombre)
            try:
                tam = rf.fmt_bytes(os.path.getsize(ruta))
            except OSError:
                tam = "?"
            corto = nombre if len(nombre) <= 22 else nombre[:19] + "…"
            item = QListWidgetItem(self._icono_archivo(nombre), f"{corto}\n{tam}")
            item.setData(Qt.UserRole, ("file", ruta))
            item.setToolTip(f"{nombre}\n{tam}")
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.lista.addItem(item)

        self.estado.setText(
            f"{len(carpetas)} carpeta(s) ({propias} de la aplicación, "
            f"{len(carpetas) - propias} tuyas) · {len(archivos)} archivo(s). "
            "Doble clic en una carpeta para trabajar con ella; clic derecho para "
            "solo ver su contenido."
        )

    # -- acciones ----------------------------------------------------------
    def _ir_a_trabajar(self, ruta: str):
        """Pasa a la ventana de trabajo, cerrando antes este explorador.

        Este explorador es modal (se abre con .exec()); la ventana de trabajo
        NO lo es, precisamente para que sus avisos y diálogos se vean bien.

        Importante: la señal que abre la ventana de trabajo se emite con un
        pequeño retraso (QTimer.singleShot), DESPUÉS de cerrar este diálogo,
        en vez de emitirla y cerrar en el mismo instante. Emitir y cerrar a la
        vez deja ambas acciones corriendo dentro del bucle de eventos anidado
        de este diálogo modal, y en la práctica eso podía dejar la ventana de
        trabajo con el agarre de ratón/teclado "heredado" del diálogo que se
        está cerrando: se veía, pero ningún botón respondía a los clics.
        """
        from PySide6.QtCore import QTimer
        self.accept()
        QTimer.singleShot(0, lambda: self.abrir_carpeta.emit(ruta))

    def _tiene_subcarpetas(self, ruta: str) -> bool:
        try:
            return any(os.path.isdir(os.path.join(ruta, e)) for e in os.listdir(ruta))
        except OSError:
            return False

    def _doble_clic(self, item: QListWidgetItem):
        tipo, ruta = item.data(Qt.UserRole)
        if tipo == "dir":
            # Si la carpeta contiene a su vez subcarpetas (como "SNES" o
            # "MSX", que agrupan las de cada proceso), doble clic ENTRA en
            # ella para seguir navegando: si en su lugar saltara directo a
            # la ventana de trabajo, esta se vería vacía, porque solo lista
            # archivos sueltos y ahí no los hay. Solo cuando la carpeta ya
            # es una carpeta "hoja" (sin subcarpetas) tiene sentido ir
            # directo a trabajar con su contenido.
            if self._tiene_subcarpetas(ruta):
                self._ir(ruta)
            else:
                self._ir_a_trabajar(ruta)
            return
        if os.path.splitext(ruta)[1].lower() in EXT_IMAGENES:
            self.abrir_imagenes.emit([ruta])
            return
        self.abrir_archivo.emit(ruta)

    def _seleccion(self) -> list:
        return [i.data(Qt.UserRole)[1] for i in self.lista.selectedItems()]

    def _menu_contextual(self, pos):
        item = self.lista.itemAt(pos)
        if item is None:
            return
        tipo, ruta = item.data(Qt.UserRole)
        menu = QMenu(self.lista)

        act_imagenes = act_analizar = act_entrar = act_trabajar = None
        if tipo == "dir":
            act_trabajar = menu.addAction("Trabajar con esta carpeta")
            act_entrar = menu.addAction("Solo ver el contenido")
        else:
            if os.path.splitext(ruta)[1].lower() in EXT_IMAGENES:
                act_imagenes = menu.addAction(
                    "Abrir en el extractor de archivos (hasta 3 seleccionadas)")
            act_analizar = menu.addAction("Analizar este archivo")
        menu.addSeparator()
        act_copiar = menu.addAction("Copiar la ruta")

        elegido = menu.exec(self.lista.viewport().mapToGlobal(pos))
        if elegido is None:
            return
        if elegido is act_trabajar:
            self._ir_a_trabajar(ruta)
        elif elegido is act_entrar:
            self._ir(ruta)
        elif elegido is act_copiar:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(ruta)
            self.estado.setText(f"Ruta copiada:  {ruta}")
        elif elegido is act_imagenes:
            imagenes = [p for p in self._seleccion()
                        if os.path.splitext(p)[1].lower() in EXT_IMAGENES]
            self.abrir_imagenes.emit(imagenes or [ruta])
        elif elegido is act_analizar:
            self.abrir_archivo.emit(ruta)

    def _abrir_en_sistema(self, ruta: str | None = None):
        """Intenta abrir la carpeta en el explorador del sistema.

        Se comprueba el resultado de verdad en vez de dar por hecho que
        funcionó: lanzar el proceso puede tener éxito y aun así no abrirse
        nada (falta de escritorio, xdg-open mal configurado...). Si no se
        consigue, se muestra la ruta en un cuadro del que se puede copiar.
        """
        destino = ruta if isinstance(ruta, str) else self._actual
        intentos = []

        # 1) La vía de Qt
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            if QDesktopServices.openUrl(QUrl.fromLocalFile(destino)):
                return
            intentos.append("QDesktopServices: devolvió fallo")
        except Exception as e:  # noqa: BLE001
            intentos.append(f"QDesktopServices: {e}")

        # 2) Los abridores habituales, comprobando el código de salida.
        #    Se incluyen los de Trinity (el escritorio de Q4OS) y los de
        #    escritorios ligeros, no solo los de GNOME y KDE.
        candidatos = (
            "xdg-open", "gio", "kfmclient", "kioclient5", "kioclient",
            "kde-open", "exo-open", "thunar", "nautilus", "dolphin",
            "konqueror", "pcmanfm", "nemo", "caja", "spacefm", "krusader",
        )
        for programa in candidatos:
            ejecutable = shutil.which(programa)
            if not ejecutable:
                continue
            if programa == "gio":
                args = [ejecutable, "open", destino]
            elif programa == "kfmclient":
                args = [ejecutable, "exec", destino]
            elif programa in ("kioclient5", "kioclient"):
                args = [ejecutable, "exec", destino]
            else:
                args = [ejecutable, destino]
            try:
                proceso = subprocess.Popen(
                    args, start_new_session=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                try:
                    # Si termina enseguida con error, es que no ha abierto nada
                    _salida, err = proceso.communicate(timeout=1.5)
                    if proceso.returncode == 0:
                        self.estado.setText(
                            f"Se ha pedido a «{programa}» que abra la carpeta. Si no "
                            "aparece ninguna ventana, usa «Copiar ruta».")
                        return
                    intentos.append(
                        f"{programa}: código {proceso.returncode} "
                        f"{(err or b'').decode(errors='replace').strip()[:60]}")
                except subprocess.TimeoutExpired:
                    # Sigue vivo: señal de que ha abierto la ventana
                    self.estado.setText(
                        f"Se ha pedido a «{programa}» que abra la carpeta. Si no "
                        "aparece ninguna ventana, usa «Copiar ruta» para pegarla "
                        "en tu explorador de archivos.")
                    return
            except OSError as e:
                intentos.append(f"{programa}: {e}")

        self._mostrar_ruta(destino, intentos)

    def _copiar_ruta(self):
        """Copia la ruta actual al portapapeles: funciona siempre, haya o no
        explorador de archivos en el sistema."""
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._actual)
        self.estado.setText(f"Ruta copiada al portapapeles:  {self._actual}")

    def _mostrar_ruta(self, destino: str, intentos: list):
        """Cuadro con la ruta seleccionable, para poder copiarla."""
        from PySide6.QtWidgets import (QDialogButtonBox, QLineEdit, QPlainTextEdit,
                                       QVBoxLayout as VB)
        dlg = QDialog(self)
        dlg.setWindowTitle("Abrir en el sistema")
        dlg.setMinimumWidth(620)
        dlg.setStyleSheet(ESTILO)
        v = VB(dlg)
        etiqueta = QLabel(
            "No se pudo abrir el explorador de archivos del sistema. Es habitual en "
            "escritorios ligeros o instalaciones sin xdg-utils.\n\n"
            "Puedes copiar la ruta desde aquí:")
        etiqueta.setWordWrap(True)
        v.addWidget(etiqueta)

        campo = QLineEdit(destino)
        campo.setReadOnly(True)
        campo.selectAll()
        campo.setStyleSheet(
            "background:#0a0b10; color:#3ef29a; border:1px solid #2c3342;"
            "border-radius:5px; padding:8px; font-family:'IBM Plex Mono',monospace;")
        v.addWidget(campo)

        pista = QLabel(
            "Para que funcione el botón, instala las herramientas de escritorio:\n"
            "    sudo apt install xdg-utils")
        pista.setWordWrap(True)
        pista.setStyleSheet("color:#8892a8; font-size:11px;")
        v.addWidget(pista)

        if intentos:
            detalle = QPlainTextEdit("\n".join(intentos))
            detalle.setReadOnly(True)
            detalle.setMaximumHeight(110)
            detalle.setStyleSheet(
                "background:#05070c; color:#8892a8; border:1px solid #2c3342;"
                "border-radius:5px; font-size:11px;")
            v.addWidget(QLabel("Detalle de los intentos:"))
            v.addWidget(detalle)

        botones = QDialogButtonBox(QDialogButtonBox.Close)
        botones.rejected.connect(dlg.reject)
        v.addWidget(botones)
        dlg.exec()
