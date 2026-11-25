"""Interfaz para añadir y quitar archivos de una imagen de disco.

Usa la edición en el sitio de msx_disk_edit. Flujo de «añadir»:

  1. Se eligen los archivos (o llegan ya elegidos, por arrastrar y soltar).
  2. Se comprueba si caben. Si NO caben, un aviso grande dice cuánto falta y
     recomienda qué archivo del disco quitar primero (el mínimo que baste);
     desde ahí se puede elegir qué quitar y se vuelve a comprobar.
  3. Si hay nombres repetidos se pregunta si reemplazarlos.
  4. Se confirma, se guarda una copia de seguridad (`<imagen>.bak`, el estado
     anterior a la última edición) y se escribe la imagen.

Nada se escribe hasta el último paso: cancelar en cualquier punto deja el
disco como estaba.
"""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

import msx_disk_edit as me
import rom_formats as rf

APP_TITLE = "ASTURCONSOLE"

ESTILO = """
QDialog { background: #0b0d13; }
QLabel { color: #ffffff; background: transparent; }
QLabel#Titulo { font-size: 18px; font-weight: 800; }
QLabel#Texto { font-size: 13px; color: #f4f7fc; }
QLabel#Rojo {
    font-size: 14px; font-weight: 800; color: #ffffff; background: #8f1d2c;
    border: 2px solid #ff6b81; border-radius: 8px; padding: 10px 14px;
}
QLabel#Verde {
    font-size: 14px; font-weight: 800; color: #000000; background: #3ef29a;
    border-radius: 8px; padding: 8px 14px;
}
QLabel#Ambar {
    font-size: 14px; font-weight: 800; color: #000000; background: #ffd166;
    border-radius: 8px; padding: 8px 14px;
}
QLabel#Sugerencia {
    font-size: 13px; font-weight: 700; color: #000000; background: #ffd166;
    border-radius: 8px; padding: 10px 14px;
}
QCheckBox { color: #ffffff; font-size: 13px; spacing: 10px; padding: 5px 4px; }
QCheckBox::indicator { width: 20px; height: 20px; border: 2px solid #ffffff;
                       border-radius: 4px; background: #141824; }
QCheckBox::indicator:checked { background: #ff6b81; border-color: #ffffff; }
QPushButton { background: #1f2330; color: #ffffff; border: 2px solid #8892a8;
              border-radius: 7px; padding: 9px 20px; font-weight: 700; }
QPushButton:hover { border-color: #ffffff; }
QPushButton#Principal { background: #3ef29a; color: #000000; border-color: #ffffff; }
QPushButton#Principal:hover { background: #7dffc0; }
QPushButton#Peligro { background: #ff6b81; color: #000000; border-color: #ffffff; }
QPushButton#Peligro:hover { background: #ff9aa9; }
QScrollArea { border: 2px solid #39404f; border-radius: 6px; background: #0b0d13; }
"""


def kb(n: int) -> str:
    return rf.fmt_bytes(n)


# ---------------------------------------------------------------------------
# Elegir qué quitar
# ---------------------------------------------------------------------------
class QuitarArchivosDialog(QDialog):
    """Lista los archivos del disco con casillas y dice, al vuelo, cuánto
    espacio se liberaría y si ya basta. `sugeridos` vienen premarcados."""

    def __init__(self, elementos: list, falta: int = 0, sugeridos: list | None = None,
                 parent=None, titulo: str = "Elegir qué quitar del disco"):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_TITLE} — {titulo}")
        self.setStyleSheet(ESTILO)
        self.setMinimumSize(640, 520)
        self._falta = falta
        sug = {(e.camino, e.nombre) for e in (sugeridos or [])}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        t = QLabel("Marca lo que quieres quitar del disco")
        t.setObjectName("Titulo")
        lay.addWidget(t)
        if falta > 0:
            n = QLabel(f"Para que quepa lo que quieres añadir hay que liberar al menos {kb(falta)}. "
                       "Ya te he marcado lo recomendado.")
            n.setObjectName("Texto")
            n.setWordWrap(True)
            lay.addWidget(n)

        cont = QWidget()
        cl = QVBoxLayout(cont)
        cl.setContentsMargins(8, 6, 8, 6)
        cl.setSpacing(0)
        self._checks: list[tuple[QCheckBox, me.Elemento]] = []
        archivos = sorted((e for e in elementos if not e.es_dir),
                          key=lambda e: e.ocupa, reverse=True)
        for e in archivos:
            ruta = "/".join(e.camino + (e.nombre,))
            c = QCheckBox(f"{ruta}      —  {kb(e.ocupa)}")
            c.setChecked((e.camino, e.nombre) in sug)
            c.toggled.connect(self._actualizar)
            cl.addWidget(c)
            self._checks.append((c, e))
        cl.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(cont)
        lay.addWidget(sc, 1)

        self.resumen = QLabel("")
        lay.addWidget(self.resumen)

        fila = QHBoxLayout()
        fila.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        fila.addWidget(cancelar)
        self.ok = QPushButton("Quitar los marcados")
        self.ok.setObjectName("Peligro")
        self.ok.clicked.connect(self.accept)
        fila.addWidget(self.ok)
        lay.addLayout(fila)
        self._actualizar()

    def seleccion(self) -> list:
        return [e for c, e in self._checks if c.isChecked()]

    def _actualizar(self, *_):
        libera = sum(e.ocupa for e in self.seleccion())
        n = len(self.seleccion())
        self.ok.setEnabled(n > 0)
        if self._falta > 0:
            if libera >= self._falta:
                self.resumen.setObjectName("Verde")
                self.resumen.setText(f"✔  Liberarías {kb(libera)}: ya cabe lo que quieres añadir.")
            else:
                self.resumen.setObjectName("Ambar")
                self.resumen.setText(f"Liberarías {kb(libera)}; aún faltan {kb(self._falta - libera)}.")
        else:
            self.resumen.setObjectName("Ambar")
            self.resumen.setText(f"{n} marcado(s): liberarías {kb(libera)}.")
        self.resumen.style().unpolish(self.resumen)
        self.resumen.style().polish(self.resumen)


# ---------------------------------------------------------------------------
# Aviso de capacidad
# ---------------------------------------------------------------------------
class AvisoCapacidadDialog(QDialog):
    """«No caben»: dice cuánto falta y recomienda qué quitar. Resultado:
    `quitar` True si el usuario quiere elegir qué quitar."""

    def __init__(self, plan: me.Plan, sugeridos: list, hay_archivos: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_TITLE} — No caben en el disco")
        self.setStyleSheet(ESTILO)
        self.setMinimumWidth(640)
        self.quitar = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        t = QLabel("⚠  Los archivos no caben en el disquete")
        t.setObjectName("Titulo")
        lay.addWidget(t)
        if plan.entradas_faltan > 0 and plan.falta <= 0:
            msg = ("El directorio raíz del disco está lleno: no admite más archivos "
                   f"(faltan {plan.entradas_faltan} entradas).")
        else:
            msg = (f"Hacen falta {kb(plan.necesario)} y el disco solo tiene {kb(plan.libre)} libres.\n"
                   f"Faltan {kb(plan.falta)}.")
        r = QLabel(msg)
        r.setObjectName("Rojo")
        r.setWordWrap(True)
        lay.addWidget(r)

        if plan.entradas_faltan > 0 and plan.falta <= 0:
            x = QLabel("💡  Quita algún archivo del disco para dejar sitio en el directorio.")
            x.setObjectName("Sugerencia")
            lay.addWidget(x)
        elif sugeridos:
            nombres = "\n".join(f"   •  {'/'.join(e.camino + (e.nombre,))}  ({kb(e.ocupa)})"
                                for e in sugeridos)
            s = QLabel("💡  Te recomiendo quitar primero del disco:\n" + nombres)
            s.setObjectName("Sugerencia")
            s.setWordWrap(True)
            lay.addWidget(s)
        elif hay_archivos:
            x = QLabel("💡  Ni quitando archivos sueltos se llegaría al espacio necesario: "
                       "usa un disco más grande (720 KB en vez de 360 KB) o añade menos archivos.")
            x.setObjectName("Sugerencia")
            x.setWordWrap(True)
            lay.addWidget(x)
        else:
            x = QLabel("💡  El disco ya está vacío: usa uno más grande o añade menos archivos.")
            x.setObjectName("Sugerencia")
            x.setWordWrap(True)
            lay.addWidget(x)

        fila = QHBoxLayout()
        fila.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        fila.addWidget(cancelar)
        if hay_archivos:
            b = QPushButton("🗑  Elegir qué quitar del disco…")
            b.setObjectName("Principal")
            b.clicked.connect(self._pedir_quitar)
            fila.addWidget(b)
        lay.addLayout(fila)

    def _pedir_quitar(self):
        self.quitar = True
        self.accept()


# ---------------------------------------------------------------------------
# Guardado seguro
# ---------------------------------------------------------------------------
def guardar_imagen(ruta: str, datos: bytes) -> str:
    """Guarda la copia de seguridad `<ruta>.bak` (estado anterior) y escribe la
    imagen de forma atómica. Devuelve la ruta de la copia."""
    copia = ruta + ".bak"
    with open(ruta, "rb") as fh:
        anterior = fh.read()
    with open(copia, "wb") as fh:
        fh.write(anterior)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ruta) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(datos)
        os.replace(tmp, ruta)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return copia


def _abrir_disco(parent, ruta: str):
    """DiscoFat de la imagen o None avisando del motivo."""
    try:
        with open(ruta, "rb") as fh:
            datos = fh.read()
    except OSError as e:
        QMessageBox.warning(parent, APP_TITLE, f"No se pudo leer {ruta}: {e}")
        return None
    if rf.detect_copia720_single_sided(datos):
        QMessageBox.information(
            parent, APP_TITLE,
            "Esta imagen es un volcado COPIA720 de cara simple: su disposición interna "
            "es distinta y no se puede editar directamente.\n\n"
            "Conviértela antes con «Recortar imagen COPIA720 (720→360)».")
        return None
    try:
        return me.DiscoFat(datos)
    except me.ErrorDisco as e:
        QMessageBox.warning(parent, APP_TITLE, f"No se puede editar este disco: {e}")
        return None


# ---------------------------------------------------------------------------
# Añadir
# ---------------------------------------------------------------------------
def anadir_archivos(parent, ruta_imagen: str, rutas: list | None = None,
                    camino: tuple = (), carpeta_inicial: str | None = None) -> bool:
    """Añade archivos a la imagen. Devuelve True si se modificó el disco."""
    disco = _abrir_disco(parent, ruta_imagen)
    if disco is None:
        return False

    if rutas is None:
        from file_browser import elegir_archivos
        rutas = elegir_archivos(
            parent, carpeta_inicial=carpeta_inicial,
            mensaje="Archivos a añadir al disco  —  puedes marcar varios")
    rutas = [r for r in (rutas or []) if os.path.isfile(r)]
    if not rutas:
        return False

    contenido: dict[str, bytes] = {}
    for r in rutas:
        try:
            with open(r, "rb") as fh:
                contenido[r] = fh.read()
        except OSError as e:
            QMessageBox.warning(parent, APP_TITLE, f"No se pudo leer {r}: {e}")
            return False

    quitados: list = []   # (camino, nombre) que se quitarán al confirmar
    reemplazar = True
    while True:
        lista = [(os.path.basename(r), len(contenido[r])) for r in rutas]
        try:
            plan = disco.planificar(lista, camino, reemplazar=reemplazar)
        except me.ErrorDisco as e:
            QMessageBox.warning(parent, APP_TITLE, str(e))
            return False
        if plan.cabe:
            break
        elementos = disco.listar(camino=(), recursivo=True)
        sug = me.sugerir_borrados(elementos, plan.falta) if plan.falta > 0 else []
        aviso = AvisoCapacidadDialog(plan, sug, any(not e.es_dir for e in elementos), parent)
        if aviso.exec() != QDialog.Accepted or not aviso.quitar:
            return False
        dlg = QuitarArchivosDialog(elementos, plan.falta, sug, parent)
        if dlg.exec() != QDialog.Accepted:
            continue                      # vuelve a avisar: sigue sin caber
        for e in dlg.seleccion():
            try:
                disco.borrar(e.nombre, e.camino)
                quitados.append((e.camino, e.nombre))
            except me.ErrorDisco as err:
                QMessageBox.warning(parent, APP_TITLE, str(err))
                return False

    # nombres repetidos
    if plan.duplicados and reemplazar:
        m = QMessageBox(parent)
        m.setWindowTitle(APP_TITLE)
        m.setIcon(QMessageBox.Question)
        m.setText("Ya hay archivos con el mismo nombre en el disco:\n\n  " +
                  "\n  ".join(plan.duplicados) + "\n\n¿Quieres reemplazarlos?")
        si = m.addButton("Reemplazar", QMessageBox.AcceptRole)
        no = m.addButton("Saltar esos", QMessageBox.DestructiveRole)
        m.addButton("Cancelar", QMessageBox.RejectRole)
        m.exec()
        if m.clickedButton() is no:
            repetidos = {d.upper() for d in plan.duplicados}

            def _final(r):
                n, e = me.nombre_83(os.path.basename(r))
                return (f"{n}.{e}" if e else n).upper()
            rutas = [r for r in rutas if _final(r) not in repetidos]
            reemplazar = False
            if not rutas:
                return False
            lista = [(os.path.basename(r), len(contenido[r])) for r in rutas]
            plan = disco.planificar(lista, camino, reemplazar=False)
            if not plan.cabe:
                QMessageBox.warning(parent, APP_TITLE, "Aun así no caben. No se ha cambiado nada.")
                return False
        elif m.clickedButton() is not si:
            return False

    # confirmación
    libre_final = plan.libre - plan.necesario
    donde = f" a la carpeta «{'/'.join(camino)}»" if camino else ""
    texto = (f"Se van a añadir {len(plan.nombres)} archivo(s){donde} ({kb(plan.necesario)}).\n"
             f"Quedarán {kb(libre_final)} libres en el disco.")
    if quitados:
        texto += "\n\nSe quitarán antes: " + ", ".join(n for _c, n in quitados)
    if plan.renombrados:
        texto += ("\n\nMSX-DOS usa nombres de 8 letras + 3 de extensión; se guardarán así:\n  " +
                  "\n  ".join(f"{a}  →  {b}" for a, b in plan.renombrados))
    texto += (f"\n\nSe guarda una copia de seguridad del estado actual "
              f"({os.path.basename(ruta_imagen)}.bak).")
    if QMessageBox.question(parent, APP_TITLE, texto,
                            QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
        return False

    # aplicar
    try:
        for r in rutas:
            disco.anadir(os.path.basename(r), contenido[r], camino, reemplazar=reemplazar)
        guardar_imagen(ruta_imagen, disco.imagen())
    except (me.ErrorDisco, OSError) as e:
        QMessageBox.warning(parent, APP_TITLE, f"No se pudo completar: {e}\n\nEl disco no se ha modificado.")
        return False
    return True


# ---------------------------------------------------------------------------
# Quitar
# ---------------------------------------------------------------------------
def quitar_elementos(parent, ruta_imagen: str, elementos: list | None = None) -> bool:
    """Quita archivos/carpetas de la imagen. `elementos` es una lista de
    (camino, nombre); sin ella se pregunta con la lista de casillas."""
    disco = _abrir_disco(parent, ruta_imagen)
    if disco is None:
        return False
    if elementos is None:
        todos = disco.listar(recursivo=True)
        if not any(not e.es_dir for e in todos):
            QMessageBox.information(parent, APP_TITLE, "El disco no tiene archivos que quitar.")
            return False
        dlg = QuitarArchivosDialog(todos, 0, None, parent)
        if dlg.exec() != QDialog.Accepted:
            return False
        elementos = [(e.camino, e.nombre) for e in dlg.seleccion()]
    if not elementos:
        return False

    nombres = [("/".join(c + (n,))) for c, n in elementos]
    lista = "\n  ".join(nombres[:12]) + (f"\n  … y {len(nombres) - 12} más" if len(nombres) > 12 else "")
    if QMessageBox.question(
            parent, APP_TITLE,
            f"¿Quitar del disco {len(elementos)} elemento(s)?\n\n  {lista}\n\n"
            "Las carpetas se quitan con todo lo que contienen. Se guarda una copia de "
            f"seguridad ({os.path.basename(ruta_imagen)}.bak).",
            QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
        return False
    try:
        libera = 0
        for camino, nombre in elementos:
            libera += disco.borrar(nombre, camino)
        guardar_imagen(ruta_imagen, disco.imagen())
    except (me.ErrorDisco, OSError) as e:
        QMessageBox.warning(parent, APP_TITLE, f"No se pudo completar: {e}\n\nEl disco no se ha modificado.")
        return False
    return True


# ---------------------------------------------------------------------------
# Crear carpeta
# ---------------------------------------------------------------------------
def crear_carpeta(parent, ruta_imagen: str, camino: tuple = ()) -> bool:
    """Pide un nombre y crea una carpeta vacía dentro de `camino`."""
    from PySide6.QtWidgets import QInputDialog
    disco = _abrir_disco(parent, ruta_imagen)
    if disco is None:
        return False
    dentro = f" dentro de «{'/'.join(camino)}»" if camino else " en el disco"
    nombre, ok = QInputDialog.getText(
        parent, APP_TITLE, f"Nombre de la carpeta nueva{dentro}\n"
        "(hasta 8 letras o números, sin extensión):")
    nombre = (nombre or "").strip()
    if not ok or not nombre:
        return False
    try:
        final = disco.crear_carpeta(nombre, camino)
        if final.upper() != nombre.upper():
            QMessageBox.information(
                parent, APP_TITLE,
                f"MSX-DOS usa nombres de hasta 8 caracteres, sin espacios: se llamará «{final}».")
        guardar_imagen(ruta_imagen, disco.imagen())
    except (me.ErrorDisco, OSError) as e:
        QMessageBox.warning(parent, APP_TITLE, f"{e}\n\nEl disco no se ha modificado.")
        return False
    return True
