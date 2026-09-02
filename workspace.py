"""Espacio de trabajo: carpetas fijas donde la aplicación lee y escribe.

En vez de preguntar por una carpeta de destino en cada operación, la
aplicación crea un árbol de carpetas junto al ejecutable y guarda cada tipo
de resultado en su sitio. Así el flujo habitual no requiere ningún diálogo:
se dejan las ROMs en "roms originales" y cada conversión aparece en su
carpeta correspondiente.

La carpeta base se crea junto al ejecutable (o junto a main.py si se
ejecuta desde el código fuente). Si esa ubicación no admite escritura -por
ejemplo si el binario está en /usr/local/bin- se recurre a la carpeta
personal del usuario, informando de ello.
"""
from __future__ import annotations

import os
import shutil
import sys

WORKSPACE_NAME = "ASTURCONSOLE"

# Estructura en dos niveles: SISTEMA / PROCESO.
#
# Antes todo colgaba de la raíz y los resultados de sistemas distintos se
# mezclaban en la misma carpeta (los "byte swap" de Mega Drive junto a los
# de SNES, por ejemplo). Con esta estructura cada proceso de cada sistema
# tiene su sitio, que es lo que se espera al buscar un resultado.

SISTEMAS = {
    "snes": "SNES",
    "genesis": "MEGA DRIVE",
    "msx": "MSX",
}

# clave de proceso -> nombre de carpeta, para cada sistema
ARBOL: dict[str, dict[str, str]] = {
    "snes": {
        "no_header":   "sin cabecera",
        "with_header": "roms con cabecera SWC",
        "checksum":    "checksum corregido",
        "interleave":  "bancos HiROM",
        "swc_disks":   "disquetes SWC",
        "split":       "divididos",
        "rename83":    "nombres 8.3",
        "hfe":         "HFE (HxC-FlashFloppy)",
    },
    "genesis": {
        "byteswap":    "byte swap",
        "smd":         "roms con formato SMD",
        "no_header":   "sin cabecera SMD",
        "split":       "divididos",
        "rename83":    "nombres 8.3",
        "smd_disks":   "discos Super Magic Drive",
        "hfe":         "HFE (HxC-FlashFloppy)",
    },
    "msx": {
        "blank_disks":  "DSK MSX",
        "extracted":    "extraido de disco",
        "tapes":        "cintas",
        "msxdos":       "msxdos",
        "msxdos_utils": "msxdos utils",
        "rename83":     "nombres 8.3",
        "hfe":          "HFE (HxC-FlashFloppy)",
        "split":        "divididos",
    },
}

# Carpeta de ROMs de origen, COMÚN a los tres sistemas: la aplicación
# reconoce por el contenido de qué consola es cada archivo, así que no hace
# falta clasificarlos a mano al copiarlos aquí.
CARPETA_ORIGEN = "roms originales"

# Carpeta donde acaba lo que no se puede clasificar
SIN_CLASIFICAR = "_sin clasificar"

# Compatibilidad con el código que aún pide carpetas por clave suelta:
# se resuelve al sistema que corresponda por defecto.
SISTEMA_POR_DEFECTO = {
    "byteswap": "genesis", "smd": "genesis",
    "swc_disks": "snes", "with_header": "snes", "checksum": "snes",
    "interleave": "snes", "no_header": "snes", "split": "snes",
    "blank_disks": "msx", "extracted": "msx", "tapes": "msx",
    "msxdos": "msx", "msxdos_utils": "msx",
}

_base_dir: str | None = None
_fallback_used = False


def _executable_dir() -> str:
    """Carpeta donde vive el programa (ejecutable compilado o script)."""
    if getattr(sys, "frozen", False):
        # PyInstaller: sys.executable es el binario real; sys._MEIPASS es una
        # carpeta temporal que se borra al salir, así que NO sirve para datos.
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(sys.argv[0] or __file__))


def _writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        prueba = os.path.join(path, ".escritura_test")
        with open(prueba, "w") as fh:
            fh.write("x")
        os.remove(prueba)
        return True
    except OSError:
        return False


def ubicacion_antigua_con_contenido() -> str | None:
    """Si existe una carpeta ASTURCONSOLE junto al ejecutable (la ubicación
    que se usaba ANTES de fijar siempre el HOME) y tiene algo dentro,
    devuelve su ruta — para poder avisar al usuario, nunca para tocarla.

    Deliberadamente NO se mueve nada de forma automática: una versión
    anterior de este código sí lo hacía, y si el traslado fallaba a mitad
    (permisos, una carpeta ya existente, lo que sea) el resultado era
    contenido repartido entre dos sitios sin que la aplicación volviera a
    intentarlo — justo el problema que se quiere evitar aquí. Es mucho más
    seguro simplemente decir dónde está, y que el usuario decida qué mover
    y cuándo, con el control total que da su propio gestor de archivos.
    """
    antigua = os.path.join(_executable_dir(), WORKSPACE_NAME)
    if os.path.abspath(antigua) == os.path.abspath(base_dir()):
        return None
    if not os.path.isdir(antigua):
        return None
    try:
        if os.listdir(antigua):
            return antigua
    except OSError:
        pass
    return None


def base_dir() -> str:
    """Carpeta raíz del espacio de trabajo, creándola si hace falta.

    Siempre en el HOME del usuario (~/ASTURCONSOLE), NUNCA relativa a dónde
    viva el ejecutable o el script: antes se creaba junto a él, lo que
    significaba que compilar en una carpeta distinta —o simplemente borrar
    y regenerar dist/ al recompilar, como hace build_linux.sh— dejaba a la
    aplicación "sin ver" su propio trabajo anterior, creando una carpeta
    nueva y vacía en el sitio nuevo en vez de encontrar la de siempre.

    Si había contenido en la ubicación antigua, NO se mueve solo (ver
    ubicacion_antigua_con_contenido): eso es cosa del usuario.
    """
    global _base_dir
    if _base_dir:
        return _base_dir
    _base_dir = os.path.join(os.path.expanduser("~"), WORKSPACE_NAME)
    os.makedirs(_base_dir, exist_ok=True)
    return _base_dir


def using_fallback() -> bool:
    # Se mantiene por compatibilidad con quien ya llamara a esta función;
    # ahora la ubicación es siempre la misma, así que nunca hay "fallback".
    base_dir()
    return False


def system_dir(sistema: str) -> str:
    """Carpeta raíz de un sistema, p. ej. ASTURCONSOLE/SNES."""
    nombre = SISTEMAS.get(sistema, SISTEMAS["msx"])
    ruta = os.path.join(base_dir(), nombre)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def folder(clave: str, sistema: str | None = None) -> str:
    """Carpeta de un proceso concreto dentro de un sistema.

    Si no se indica sistema, se usa aquel al que pertenece el proceso de
    forma natural (el byte swap es de Mega Drive, los disquetes SWC de
    SNES...), para que el código antiguo siga funcionando.
    """
    if sistema is None:
        sistema = SISTEMA_POR_DEFECTO.get(clave, "msx")
    mapa = ARBOL.get(sistema, {})
    nombre = mapa.get(clave)
    if nombre is None:
        # El proceso no existe en ese sistema: se usa el sistema natural
        natural = SISTEMA_POR_DEFECTO.get(clave)
        if natural and natural != sistema:
            return folder(clave, natural)
        nombre = clave
    ruta = os.path.join(system_dir(sistema), nombre)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def source_folder(sistema: str | None = None) -> str:
    """Carpeta de ROMs de origen, común a todos los sistemas."""
    ruta = os.path.join(base_dir(), CARPETA_ORIGEN)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def unclassified_folder() -> str:
    ruta = os.path.join(base_dir(), SIN_CLASIFICAR)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def all_folders() -> list:
    """Todas las carpetas del árbol, como (sistema, clave, ruta)."""
    salida = [(None, "source", source_folder())]
    for sistema, mapa in ARBOL.items():
        for clave in mapa:
            salida.append((sistema, clave, folder(clave, sistema)))
    return salida


def nombres_de_carpetas() -> set:
    """Nombres de todas las carpetas que crea la aplicación.

    Incluye tanto las de sistema (SNES, MEGA DRIVE, MSX) como las de proceso
    que hay dentro. Sirve para que el explorador distinga las carpetas
    propias de las que haya creado el usuario.
    """
    nombres = {CARPETA_ORIGEN, SIN_CLASIFICAR}
    nombres.update(SISTEMAS.values())
    for mapa in ARBOL.values():
        nombres.update(mapa.values())
    return nombres


def source_has_files(sistema: str | None = None) -> bool:
    """True si hay algún archivo en la carpeta de originales."""
    try:
        for _dirpath, _dirnames, filenames in os.walk(source_folder()):
            for fn in filenames:
                if not fn.startswith(".") and fn != "LEEME.txt":
                    return True
    except OSError:
        pass
    return False


def unique_path(directory: str, filename: str) -> str:
    """Evita sobrescribir: si el nombre existe, añade _2, _3, etc."""
    destino = os.path.join(directory, filename)
    if not os.path.exists(destino):
        return destino
    base, ext = os.path.splitext(filename)
    n = 2
    while True:
        candidato = os.path.join(directory, f"{base}_{n}{ext}")
        if not os.path.exists(candidato):
            return candidato
        n += 1


MSXDOS_README = """Archivos de sistema MSX-DOS
============================

Coloca aquí los archivos de sistema de tu copia de MSX-DOS para poder crear
disquetes arrancables. La aplicación NO los incluye: son software propietario
de ASCII/Microsoft y debes aportarlos tú desde tu propia copia.

Para MSX-DOS 1 (version 1.03):
    MSXDOS.SYS
    COMMAND.COM

Para MSX-DOS 2 (version 2.31):
    MSXDOS2.SYS
    COMMAND2.COM

IMPORTANTE — el sector de arranque
-----------------------------------
Un disco no arranca solo por tener esos archivos. La Disk ROM del MSX lee el
sector 0 del disquete y le cede el control; es el codigo de ese sector el que
busca y carga MSXDOS.SYS. Ademas, MSX-DOS 2 usa un sector de arranque
distinto al de MSX-DOS 1.

Por eso, deja tambien en esta carpeta UNA de estas dos cosas, de donde copiar
el codigo de arranque:

  a) Una imagen .dsk que ya arranque en tu MSX (lo mas comodo). La aplicacion
     copiara su sector 0.
  b) Un archivo llamado BOOTSECTOR.BIN de exactamente 512 bytes con el sector
     de arranque.

Si no encuentra ninguno, la aplicacion creara el disco igualmente con los
archivos copiados, pero avisando de que probablemente arranque en Disk BASIC
en vez de en MSX-DOS.
"""

MSXDOS_UTILS_README = """Utilidades para los discos de sistema
=====================================

Los archivos que dejes en esta carpeta se copiaran al disquete de sistema
junto con los archivos de MSX-DOS: utilidades, herramientas, un AUTOEXEC.BAT,
lo que quieras.

Ten en cuenta:

  - Los nombres se convierten al formato 8.3 de MSX-DOS (ocho caracteres de
    nombre y tres de extension). Un nombre mas largo se recorta.
  - El espacio es limitado: 713 KB utiles en un disquete de 720 KB, y 354 KB
    en uno de 360 KB. La aplicacion comprueba antes que todo quepa y avisa
    con el detalle si no es asi.
  - Cada archivo ocupa clusters completos de 1 KB, asi que muchos archivos
    pequenos gastan mas espacio del que suman.
"""


def _write_folder_readme(path: str, texto: str) -> None:
    ruta = os.path.join(path, "LEEME.txt")
    if os.path.exists(ruta):
        return
    try:
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(texto)
    except OSError:
        pass


# Carpetas que cambiaron de nombre: se renombran conservando el contenido,
# en vez de dejar dos carpetas y que el usuario no sepa cuál usar.
RENOMBRADAS = {
    "disquetes vacios": "DSK MSX",
}


# ---------------------------------------------------------------------------
# Migración desde la estructura antigua (todo colgando de la raíz)
# ---------------------------------------------------------------------------
# Los archivos NO se modifican: solo se mueven a la carpeta que ahora les
# corresponde. Para las carpetas cuyo contenido podía ser de varios sistemas
# —el byte swap servía tanto a SNES como a Mega Drive— se mira DENTRO de cada
# archivo para saber a cuál pertenece. Lo que no se reconoce va a
# "_sin clasificar", en vez de adivinar.

# Carpetas antiguas -> destino nuevo. Un valor None significa que esa carpeta
# MEZCLA archivos de sistemas distintos y hay que clasificarlos uno a uno
# analizando su contenido.
#
# «roms sin cabecera» es el caso: la usaban tanto «quitar cabecera de
# copiador» (SNES) como «quitar cabecera SMD» (Mega Drive). En cambio «roms
# byte swap» solo la usaba Mega Drive, y «roms entrelazado» solo SNES.
MIGRACION = {
    "roms sin cabecera":       None,     # mezcla SNES y Mega Drive: se analiza
    "roms con cabecera":       ("snes", "with_header"),
    "roms checksum corregido": ("snes", "checksum"),
    "roms entrelazado":        ("snes", "interleave"),
    "roms en disquete swc":    ("snes", "swc_disks"),
    "roms divididos":          ("snes", "split"),
    "roms formato smd":        ("genesis", "smd"),
    "DSK MSX":                 ("msx", "blank_disks"),
    "disquetes vacios":        ("msx", "blank_disks"),
    "extraido de disco":       ("msx", "extracted"),
    "cintas msx":              ("msx", "tapes"),
    "msxdos":                  ("msx", "msxdos"),
    "msxdos_utils":            ("msx", "msxdos_utils"),
    "roms byte swap":          ("genesis", "byteswap"),
}

# Al clasificar los archivos de «roms sin cabecera», cada sistema tiene su
# carpeta equivalente en la estructura nueva.
DESTINO_POR_SISTEMA = {
    "genesis": ("genesis", "no_header"),
    "snes": ("snes", "no_header"),
    "msx": None,      # no tenía sentido ahí: va a la carpeta común de originales
}


def _mover(origen: str, destino_dir: str) -> bool:
    try:
        os.makedirs(destino_dir, exist_ok=True)
        os.rename(origen, unique_path(destino_dir, os.path.basename(origen)))
        return True
    except OSError:
        return False


def _clasificar_archivo(ruta: str):
    """Sistema al que pertenece un archivo, mirando su contenido."""
    try:
        import system_detect
    except ImportError:
        return None
    try:
        deteccion = system_detect.detectar_archivo(ruta)
    except Exception:  # noqa: BLE001
        return None
    # Solo se acepta una identificación firme: al mover archivos del usuario
    # es preferible dejarlos sin clasificar que ponerlos donde no van.
    if deteccion.sistema and deteccion.confianza in ("alta", "media"):
        return deteccion.sistema
    return None


def migrar_estructura_antigua(informe=None) -> int:
    """Mueve lo que hubiera en la estructura antigua a la nueva."""
    base = base_dir()
    movidos = 0

    for antigua, destino in MIGRACION.items():
        origen_dir = os.path.join(base, antigua)
        if not os.path.isdir(origen_dir):
            continue
        try:
            elementos = sorted(os.listdir(origen_dir))
        except OSError:
            continue

        for elemento in elementos:
            ruta = os.path.join(origen_dir, elemento)
            if elemento == "LEEME.txt":
                continue

            if destino is not None:
                sistema, clave = destino
                if _mover(ruta, folder(clave, sistema)):
                    movidos += 1
                    if informe is not None:
                        informe.append(f"{antigua}/{elemento}  ->  "
                                       f"{SISTEMAS[sistema]}/{ARBOL[sistema][clave]}")
                continue

            if os.path.isdir(ruta):
                if _mover(ruta, unclassified_folder()):
                    movidos += 1
                continue

            sistema = _clasificar_archivo(ruta)
            destino_clasificado = DESTINO_POR_SISTEMA.get(sistema) if sistema else None
            if destino_clasificado is not None:
                sis, clave = destino_clasificado
                if _mover(ruta, folder(clave, sis)):
                    movidos += 1
                    if informe is not None:
                        informe.append(
                            f"{antigua}/{elemento}  ->  {SISTEMAS[sis]}/"
                            f"{ARBOL[sis][clave]}   (identificado por su contenido)")
            elif _mover(ruta, unclassified_folder()):
                movidos += 1
                if informe is not None:
                    informe.append(f"{antigua}/{elemento}  ->  {SIN_CLASIFICAR}   "
                                   "(no se pudo identificar el sistema)")

        try:
            restantes = [e for e in os.listdir(origen_dir) if e != "LEEME.txt"]
            if not restantes:
                leeme = os.path.join(origen_dir, "LEEME.txt")
                if os.path.isfile(leeme):
                    os.remove(leeme)
                os.rmdir(origen_dir)
        except OSError:
            pass

    return movidos


def ensure_workspace() -> str:
    """Crea el árbol completo de carpetas y migra lo que hubiera. Devuelve la raíz."""
    base = base_dir()
    # La carpeta de origen es común y va la primera: es la puerta de entrada
    source_folder()
    for sistema in SISTEMAS:
        system_dir(sistema)
        for clave in ARBOL[sistema]:
            folder(clave, sistema)

    migrar_estructura_antigua()

    _write_readme(base)
    _write_folder_readme(folder("msxdos", "msx"), MSXDOS_README)
    _write_folder_readme(folder("msxdos_utils", "msx"), MSXDOS_UTILS_README)
    return base


def _write_readme(base: str) -> None:
    ruta = os.path.join(base, "LEEME.txt")
    texto = (
        "ASTURCONSOLE - carpetas de trabajo\n"
        "==================================\n\n"
        "Las carpetas se organizan por SISTEMA y, dentro, por PROCESO. Cada\n"
        "resultado va a su sitio, sin mezclar sistemas.\n\n"
    )
    for clave_sistema, nombre_sistema in SISTEMAS.items():
        texto += f"{nombre_sistema}/\n"
        for clave, nombre in ARBOL[clave_sistema].items():
            descripcion = DESCRIPCIONES.get((clave_sistema, clave), "")
            texto += f"    {nombre:22} {descripcion}\n"
        texto += "\n"
    texto += (
        f"{SIN_CLASIFICAR}/\n"
        "    Archivos que no se pudieron identificar al reorganizar las\n"
        "    carpetas. Muevelos tu mismo donde correspondan.\n\n"
        "Deja tus archivos en la carpeta 'originales' del sistema que toque.\n"
        "La aplicacion nunca modifica los originales: siempre escribe copias.\n"
    )
    try:
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(texto)
    except OSError:
        pass


DESCRIPCIONES = {
    ("snes", "source"):      "ROMs de partida",
    ("snes", "no_header"):   "sin cabecera de copiador",
    ("snes", "with_header"): "ROMs con la cabecera Super Wild Card añadida (no son discos)",
    ("snes", "checksum"):    "con el checksum corregido",
    ("snes", "interleave"):  "con los bancos HiROM intercambiados",
    ("snes", "swc_disks"):   "imagenes .img de disquete para el copion",
    ("snes", "split"):       "fragmentos de ROMs divididas",
    ("genesis", "source"):     "ROMs de partida",
    ("genesis", "byteswap"):   "con los bytes de cada palabra intercambiados",
    ("genesis", "smd"):        "ROMs con formato SMD, entrelazadas en par/impar (no son discos)",
    ("genesis", "no_header"):  "sin la cabecera SMD de 512 bytes",
    ("genesis", "split"):      "fragmentos de ROMs divididas",
    ("msx", "source"):       "ROMs, discos y cintas de partida",
    ("msx", "blank_disks"):  "imagenes de disco .dsk",
    ("msx", "extracted"):    "archivos extraidos de discos",
    ("msx", "tapes"):        "conversiones de cinta (CAS / WAV / TSX)",
    ("msx", "msxdos"):       "TUS archivos de sistema MSX-DOS (ver LEEME)",
    ("msx", "msxdos_utils"): "utilidades a incluir en los discos de sistema",
}
