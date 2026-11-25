"""Vista previa del contenido de un archivo MSX, para la ventana de trabajo.

Al marcar un archivo en la ventana grande de trabajo (sistema MSX) este panel
muestra, sin abrir nada más:

  - Imagen de disco (.dsk/.img): su contenido completo, con carpetas, y para
    cada archivo el nombre, el tipo, el tamaño y —si es un binario— las
    direcciones de inicio, fin y ejecución.
  - ROM de cartucho (.rom): la cabecera interpretada (INIT, STATEMENT,
    DEVICE, TEXT) y el mapper probable.
  - Binario con cabecera BLOAD: inicio, fin y ejecución.
  - Cinta (.cas): los programas que contiene, con los mismos datos.

El análisis (`analizar`) no depende de Qt, para poder probarlo aparte.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton,
    QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout,
)

import msx_disk_edit as me
import msx_disk_edit_ui as meu
import rom_formats as rf

EXT_DISCO = (".dsk", ".img", ".di1", ".di2")
MAX_ARCHIVO = 8 * 1024 * 1024      # no se analiza nada mayor (ROMs enormes, etc.)
MAX_ENTRADAS = 400                 # tope de archivos listados por disco

COLUMNAS = ["Nombre", "Tipo", "Tamaño", "Inicio", "Fin", "Ejecución"]

COLOR_TIPO = {
    "BIN": "#3ef29a", "ROM": "#5aa0ff", "BASIC": "#ffd166", "ASCII": "#ffb454",
    "Datos": "#dfe5f2", "Carpeta": "#c792ff",
}


@dataclass
class Fila:
    nombre: str
    tipo: str
    tamano: str
    inicio: str = "—"
    fin: str = "—"
    ejecucion: str = "—"
    nota: str = ""
    hijos: list = field(default_factory=list)
    camino: tuple = ()        # carpetas que lo contienen dentro del disco


@dataclass
class Vista:
    titulo: str
    resumen: list = field(default_factory=list)   # [(etiqueta, valor)]
    filas: list = field(default_factory=list)     # [Fila]
    aviso: str = ""
    espacio: tuple | None = None                  # (libre, total) en bytes
    editable: bool = False                        # se pueden añadir/quitar archivos


def _hex16(v: int) -> str:
    return f"0x{v:04X}"


def _es_texto(data: bytes) -> bool:
    if not data:
        return False
    muestra = data[:512]
    return all(b in (9, 10, 13, 26) or 32 <= b < 127 or b >= 160 for b in muestra)


def clasificar_contenido(nombre: str, data: bytes) -> Fila:
    """Fila de la tabla para un archivo cualquiera, deducida de su contenido."""
    tam = rf.fmt_bytes(len(data))
    if len(data) >= 7 and data[0] == 0xFE:
        h = rf.parse_msx_bin_header(data)
        return Fila(nombre, "BIN", tam, _hex16(h.start), _hex16(h.end),
                    _hex16(h.exec_addr), rf.build_preview(nombre, data))
    if len(data) >= 10 and data[:2] == b"AB":
        h = rf.parse_msx_rom_header(data)
        ej = h.init if h.init else h.statement
        return Fila(nombre, "ROM", tam, "0x4000", _hex16(0x4000 + len(data) - 1)
                    if len(data) <= 0x8000 else "—", _hex16(ej) if ej else "—",
                    rf.build_preview(nombre, data))
    if data[:1] == b"\xff":
        return Fila(nombre, "BASIC", tam, nota=rf.build_preview(nombre, data))
    if _es_texto(data):
        return Fila(nombre, "ASCII", tam, nota=rf.build_preview(nombre, data))
    return Fila(nombre, "Datos", tam, nota=rf.build_preview(nombre, data))


def _filas_disco(dsk: rf.DskImage, entradas: list, contador: list, camino: tuple = ()) -> list:
    filas = []
    for e in entradas:
        if contador[0] >= MAX_ENTRADAS:
            break
        contador[0] += 1
        if e.is_dir:
            hijos = _filas_disco(dsk, e.children, contador, camino + (e.name,))
            filas.append(Fila(e.name, "Carpeta", f"{len(hijos)} elem.", hijos=hijos, camino=camino))
            continue
        try:
            datos = rf.reconstruct_dsk_file(dsk, e)
            f = clasificar_contenido(e.name, datos)
        except Exception as exc:  # noqa: BLE001
            f = Fila(e.name, "Datos", rf.fmt_bytes(e.size), nota=f"No se pudo leer: {exc}")
        f.camino = camino
        filas.append(f)
    return filas


def analizar(ruta: str) -> Vista:
    """Analiza un archivo y devuelve lo que hay que mostrar."""
    nombre = os.path.basename(ruta)
    ext = os.path.splitext(nombre)[1].lower()
    try:
        tam = os.path.getsize(ruta)
    except OSError as e:
        return Vista(nombre, aviso=f"No se puede leer: {e}")
    if tam > MAX_ARCHIVO:
        return Vista(nombre, [("Tamaño", rf.fmt_bytes(tam))],
                     aviso="Archivo demasiado grande para la vista previa.")
    try:
        with open(ruta, "rb") as fh:
            datos = fh.read()
    except OSError as e:
        return Vista(nombre, aviso=f"No se puede leer: {e}")

    # --- imagen de disco ---
    if ext in EXT_DISCO:
        resumen = [("Tipo", "Imagen de disco"), ("Tamaño", rf.fmt_bytes(len(datos)))]
        editable = True
        # volcado de COPIA720 en cara simple: se muestra recortado (y no se edita)
        if rf.detect_copia720_single_sided(datos):
            datos = rf.copia720_to_single_sided(datos)
            editable = False
            resumen.append(("COPIA720", "cara simple (/1): mostrado como 360 KB; "
                                         "conviértela para poder editarla"))
        valido, motivo = rf.validate_dsk(datos)
        if not valido:
            return Vista(nombre, resumen,
                         aviso=f"Sin sistema de archivos legible: {motivo}")
        try:
            dsk = rf.parse_dsk(datos)
        except Exception as e:  # noqa: BLE001
            return Vista(nombre, resumen, aviso=f"No se pudo leer el disco: {e}")
        contador = [0]
        filas = _filas_disco(dsk, dsk.entries, contador)
        archivos, carpetas = rf.count_entries(dsk.entries)
        resumen.append(("Contenido", f"{archivos} archivo(s), {carpetas} carpeta(s)"))
        aviso = ""
        if contador[0] >= MAX_ENTRADAS:
            aviso = f"Se muestran solo los primeros {MAX_ENTRADAS} elementos."
        espacio = None
        try:
            espacio = me.DiscoFat(datos).espacio()
            resumen.append(("Espacio", f"{rf.fmt_bytes(espacio[0])} libres de "
                                        f"{rf.fmt_bytes(espacio[1])}"))
        except me.ErrorDisco:
            editable = False
        return Vista(nombre, resumen, filas, aviso, espacio, editable)

    # --- cinta CAS ---
    if ext == ".cas":
        import tape_catalog as tc
        try:
            entradas = tc.parse_tape(datos)
        except Exception as e:  # noqa: BLE001
            return Vista(nombre, [("Tipo", "Cinta CAS")], aviso=f"No se pudo leer: {e}")
        filas = []
        for e in entradas:
            filas.append(Fila(e.display_name, e.kind_label, rf.fmt_bytes(e.size),
                              tc.hex16(e.start).replace("&H", "0x"),
                              tc.hex16(e.end).replace("&H", "0x"),
                              tc.hex16(e.exec_addr).replace("&H", "0x"),
                              "\n".join(e.notes)))
        return Vista(nombre, [("Tipo", "Cinta CAS"), ("Tamaño", rf.fmt_bytes(len(datos))),
                              ("Programas", str(len(entradas)))], filas)

    # --- ROM / binario ---
    kind, payload = rf.classify_msx(nombre, datos)
    if kind == "rom":
        h = payload
        resumen = [("Tipo", "ROM de cartucho MSX"), ("Tamaño", rf.fmt_bytes(len(datos))),
                   ("INIT", _hex16(h.init)), ("STATEMENT", _hex16(h.statement)),
                   ("DEVICE", _hex16(h.device)), ("TEXT", _hex16(h.text))]
        try:
            g = rf.guess_msx_mapper(datos)
            resumen.append(("Mapper", f"{g.name} (confianza {g.confidence})"))
        except Exception:  # noqa: BLE001
            pass
        return Vista(nombre, resumen)
    if kind == "bin":
        h = payload
        return Vista(nombre, [("Tipo", "Binario con cabecera (BLOAD)"),
                              ("Tamaño", rf.fmt_bytes(len(datos))),
                              ("Inicio", _hex16(h.start)), ("Fin", _hex16(h.end)),
                              ("Ejecución", _hex16(h.exec_addr)),
                              ("Datos", rf.fmt_bytes(h.end - h.start + 1))])
    return Vista(nombre, [("Tamaño", rf.fmt_bytes(len(datos)))],
                 aviso="Sin vista previa para este tipo de archivo.")


ESTILO = """
QFrame#VistaMsx { background: #0b0d13; border: 2px solid #39404f; border-radius: 8px; }
QLabel { color: #ffffff; background: transparent; }
QLabel#VTitulo { color: #ffd166; font-size: 11px; font-weight: 800; }
QLabel#VNombre { color: #ffffff; font-size: 14px; font-weight: 800; }
QLabel#VResumen { color: #f4f7fc; font-size: 12px; }
QLabel#VAviso { color: #ffb454; font-size: 12px; font-weight: 700; }
QTreeWidget {
    background: #0b0d13; alternate-background-color: #171b27; color: #ffffff;
    border: 1px solid #39404f; font-size: 12px; outline: 0;
}
QTreeWidget::item { padding: 3px; }
QTreeWidget::item:selected { background: #ffffff; color: #000000; font-weight: 700; }
QProgressBar {
    background: #141824; color: #ffffff; border: 2px solid #39404f; border-radius: 6px;
    text-align: center; font-weight: 800; font-size: 12px; min-height: 20px;
}
QPushButton {
    background: #1b202d; color: #ffffff; border: 2px solid #8892a8; border-radius: 7px;
    padding: 8px 12px; font-weight: 800; font-size: 12px;
}
QPushButton:hover { border-color: #ffffff; }
QPushButton:disabled { color: #6b7389; border-color: #2c3342; }
QPushButton#Anadir { border-color: #3ef29a; }
QPushButton#Anadir:hover { background: #3ef29a; color: #000000; }
QPushButton#Carpeta { border-color: #c792ff; }
QPushButton#Carpeta:hover { background: #c792ff; color: #000000; }
QPushButton#Quitar { border-color: #ff6b81; }
QPushButton#Quitar:hover:enabled { background: #ff6b81; color: #000000; }
QHeaderView::section {
    background: #232a3b; color: #ffffff; font-weight: 700; border: none;
    padding: 4px; font-size: 11px;
}
"""


class MsxPreviewPanel(QFrame):
    """Panel con la vista previa del archivo MSX marcado. Si es una imagen de
    disco editable permite añadir (botón o arrastrando archivos) y quitar."""

    modificado = Signal(str)    # ruta de la imagen que se acaba de modificar

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VistaMsx")
        self.setStyleSheet(ESTILO)
        self.setAcceptDrops(True)
        self._ruta_actual: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        t = QLabel("VISTA PREVIA DEL ARCHIVO MARCADO")
        t.setObjectName("VTitulo")
        lay.addWidget(t)
        self.nombre = QLabel("")
        self.nombre.setObjectName("VNombre")
        self.nombre.setWordWrap(True)
        lay.addWidget(self.nombre)
        self.resumen = QLabel("")
        self.resumen.setObjectName("VResumen")
        self.resumen.setWordWrap(True)
        self.resumen.setTextFormat(Qt.RichText)
        lay.addWidget(self.resumen)
        self.barra = QProgressBar()
        self.barra.setTextVisible(True)
        self.barra.setVisible(False)
        lay.addWidget(self.barra)
        self.aviso = QLabel("")
        self.aviso.setObjectName("VAviso")
        self.aviso.setWordWrap(True)
        lay.addWidget(self.aviso)

        self.arbol = QTreeWidget()
        self.arbol.setColumnCount(len(COLUMNAS))
        self.arbol.setHeaderLabels(COLUMNAS)
        self.arbol.setAlternatingRowColors(True)
        self.arbol.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.arbol.itemSelectionChanged.connect(self._seleccion_cambio)
        self.arbol.setRootIsDecorated(True)
        self.arbol.setUniformRowHeights(True)
        cab = self.arbol.header()
        cab.setStretchLastSection(False)
        cab.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(COLUMNAS)):
            cab.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        lay.addWidget(self.arbol, 1)

        fila = QGridLayout()
        fila.setSpacing(8)
        self.btn_anadir = QPushButton("➕  Añadir archivos al disco…")
        self.btn_anadir.setObjectName("Anadir")
        self.btn_anadir.setToolTip("Añade archivos a la imagen. También puedes arrastrarlos "
                                   "encima de este panel.")
        self.btn_anadir.clicked.connect(self._anadir)
        self.btn_quitar = QPushButton("🗑  Quitar los marcados")
        self.btn_quitar.setObjectName("Quitar")
        self.btn_quitar.setToolTip("Quita del disco los archivos o carpetas marcados en la tabla.")
        self.btn_quitar.clicked.connect(self._quitar)
        self.btn_carpeta = QPushButton("📁  Nueva carpeta…")
        self.btn_carpeta.setObjectName("Carpeta")
        self.btn_carpeta.setToolTip("Crea una carpeta vacía en el disco (o dentro de la carpeta "
                                    "marcada en la tabla).")
        self.btn_carpeta.clicked.connect(self._nueva_carpeta)
        fila.addWidget(self.btn_anadir, 0, 0, 1, 2)
        fila.addWidget(self.btn_carpeta, 1, 0)
        fila.addWidget(self.btn_quitar, 1, 1)
        self._fila_botones = [self.btn_anadir, self.btn_quitar, self.btn_carpeta]
        lay.addLayout(fila)
        self._edicion(False)

        self._pendiente: list[str] = []
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.setInterval(120)
        self._temporizador.timeout.connect(self._aplicar)
        self._vaciar("Marca un archivo de la lista para ver aquí su contenido: "
                     "nombres, tipos y direcciones de inicio, fin y ejecución.")

    # -- API ---------------------------------------------------------------
    def mostrar(self, rutas: list):
        """Pide mostrar lo marcado (se aplica con un pequeño retardo para no
        analizar discos a cada cambio al marcar muchos de golpe)."""
        self._pendiente = list(rutas)
        self._temporizador.start()

    # -- interno -----------------------------------------------------------
    def _vaciar(self, mensaje: str):
        self.nombre.setText("")
        self.resumen.setText("")
        self.aviso.setText(mensaje)
        self.arbol.clear()
        self.arbol.setVisible(False)
        self.barra.setVisible(False)
        self._ruta_actual = None
        self._edicion(False)

    def _edicion(self, activa: bool):
        for b in self._fila_botones:
            b.setVisible(activa)
        self.btn_quitar.setEnabled(False)

    def _aplicar(self):
        rutas = [r for r in self._pendiente if os.path.isfile(r)]
        if not rutas:
            self._vaciar("Marca un archivo de la lista para ver aquí su contenido: "
                         "nombres, tipos y direcciones de inicio, fin y ejecución.")
            return
        v = analizar(rutas[0])
        self.nombre.setText(v.titulo + (
            f"   (+{len(rutas) - 1} más marcados: se muestra el primero)"
            if len(rutas) > 1 else ""))
        self.resumen.setText("<br>".join(
            f"<span style='color:#ffd166;font-weight:700'>{k}:</span> {val}"
            for k, val in v.resumen))
        self.aviso.setText(v.aviso)
        self.arbol.clear()
        self.arbol.setVisible(bool(v.filas) or v.editable)
        self._poblar(None, v.filas)
        self.arbol.expandToDepth(0)
        self._ruta_actual = rutas[0] if v.editable else None
        self._edicion(v.editable)
        self._barra_espacio(v.espacio)

    def _barra_espacio(self, espacio):
        if not espacio:
            self.barra.setVisible(False)
            return
        libre, total = espacio
        usado = total - libre
        pct = int(round(usado * 100 / total)) if total else 0
        color = "#3ef29a" if pct < 70 else ("#ffd166" if pct < 90 else "#ff6b81")
        self.barra.setRange(0, 100)
        self.barra.setValue(pct)
        self.barra.setFormat(f"Libre {rf.fmt_bytes(libre)} de {rf.fmt_bytes(total)}  ·  {pct}% ocupado")
        self.barra.setStyleSheet(
            "QProgressBar { background: #141824; color: #ffffff; border: 2px solid #39404f; "
            "border-radius: 6px; text-align: center; font-weight: 800; font-size: 12px; "
            f"min-height: 20px; }} QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}")
        self.barra.setVisible(True)

    # -- edición -----------------------------------------------------------
    def _carpeta_inicial(self) -> str | None:
        try:
            import workspace as ws
            inicio = ws.folder("extracted", "msx")
            return inicio if os.listdir(inicio) else ws.source_folder()
        except Exception:  # noqa: BLE001
            return None

    def _carpeta_destino(self) -> tuple:
        """Carpeta del disco donde se añadirá o creará algo: la carpeta marcada
        en la tabla si hay una sola marcada y es una carpeta; si no, la raíz."""
        sel = self.arbol.selectedItems()
        if len(sel) == 1 and sel[0].text(1) == "Carpeta":
            camino, nombre = sel[0].data(0, Qt.UserRole)
            return tuple(camino) + (nombre,)
        return ()

    def _anadir(self, rutas: list | None = None):
        if not self._ruta_actual:
            return
        ruta = self._ruta_actual
        if meu.anadir_archivos(self.window(), ruta, rutas=rutas, camino=self._carpeta_destino(),
                               carpeta_inicial=self._carpeta_inicial()):
            self._aplicar()
            self.modificado.emit(ruta)

    def _nueva_carpeta(self):
        if not self._ruta_actual:
            return
        ruta = self._ruta_actual
        if meu.crear_carpeta(self.window(), ruta, self._carpeta_destino()):
            self._aplicar()
            self.modificado.emit(ruta)

    def _quitar(self):
        if not self._ruta_actual:
            return
        elementos = []
        for it in self.arbol.selectedItems():
            dato = it.data(0, Qt.UserRole)
            if dato:
                elementos.append(dato)
        if not elementos:
            return
        # si se marca una carpeta y algo de dentro, basta con la carpeta
        carpetas = [c + (n,) for c, n in elementos]
        elementos = [(c, n) for c, n in elementos
                     if not any(c[:len(k)] == k and len(c) >= len(k) for k in carpetas
                                if k != c + (n,))]
        ruta = self._ruta_actual
        if meu.quitar_elementos(self.window(), ruta, elementos):
            self._aplicar()
            self.modificado.emit(ruta)

    def _seleccion_cambio(self):
        self.btn_quitar.setEnabled(bool(self.arbol.selectedItems()))
        dest = self._carpeta_destino()
        if dest:
            self.btn_anadir.setText(f"➕  Añadir archivos a «{dest[-1]}»…")
            self.btn_carpeta.setText(f"📁  Nueva carpeta en «{dest[-1]}»…")
        else:
            self.btn_anadir.setText("➕  Añadir archivos al disco…")
            self.btn_carpeta.setText("📁  Nueva carpeta…")
        sel = set(map(id, self.arbol.selectedItems()))
        it = QTreeWidgetItemIterator(self.arbol)
        while it.value():
            item = it.value()
            tipo = item.text(1)
            color = "#000000" if id(item) in sel else COLOR_TIPO.get(tipo, "#ffffff")
            item.setForeground(1, QColor(color))
            it += 1

    # -- arrastrar y soltar --------------------------------------------------
    def dragEnterEvent(self, ev):
        if self._ruta_actual and ev.mimeData().hasUrls():
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dropEvent(self, ev):
        if not self._ruta_actual:
            return
        rutas = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        rutas = [r for r in rutas if os.path.isfile(r)]
        if rutas:
            ev.acceptProposedAction()
            QTimer.singleShot(0, lambda: self._anadir(rutas))

    def _poblar(self, padre, filas):
        for f in filas:
            it = QTreeWidgetItem([("📁 " if f.tipo == "Carpeta" else "") + f.nombre,
                                  f.tipo, f.tamano, f.inicio, f.fin, f.ejecucion])
            if f.nota:
                it.setToolTip(0, f.nota)
            it.setData(0, Qt.UserRole, (f.camino, f.nombre))
            it.setForeground(1, QColor(COLOR_TIPO.get(f.tipo, "#ffffff")))
            for c in (2, 3, 4, 5):
                it.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
            if padre is None:
                self.arbol.addTopLevelItem(it)
            else:
                padre.addChild(it)
            if f.hijos:
                self._poblar(it, f.hijos)
