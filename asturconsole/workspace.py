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
import sys

WORKSPACE_NAME = "ASTURCONSOLE"

# Clave interna -> nombre de carpeta visible
CATEGORIES: dict[str, str] = {
    "source":       "roms originales",
    "byteswap":     "roms byte swap",
    "swc_disks":    "roms en disquete swc",
    "no_header":    "roms sin cabecera",
    "with_header":  "roms con cabecera",
    "checksum":     "roms checksum corregido",
    "interleave":   "roms entrelazado",
    "smd":          "roms formato smd",
    "split":        "roms divididos",
    "tapes":        "cintas msx",
    "extracted":    "extraido de disco",
    "blank_disks":  "DSK MSX",
    "msxdos":       "msxdos",
    "msxdos_utils": "msxdos_utils",
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


def base_dir() -> str:
    """Carpeta raíz del espacio de trabajo, creándola si hace falta."""
    global _base_dir, _fallback_used
    if _base_dir:
        return _base_dir

    candidata = os.path.join(_executable_dir(), WORKSPACE_NAME)
    if _writable(candidata):
        _base_dir = candidata
        return _base_dir

    # Sin permiso junto al ejecutable: usar la carpeta personal
    _fallback_used = True
    alternativa = os.path.join(os.path.expanduser("~"), WORKSPACE_NAME)
    os.makedirs(alternativa, exist_ok=True)
    _base_dir = alternativa
    return _base_dir


def using_fallback() -> bool:
    """True si hubo que usar la carpeta personal por falta de permisos."""
    base_dir()
    return _fallback_used


def ensure_workspace() -> str:
    """Crea la carpeta base y todas las subcarpetas. Devuelve la base."""
    base = base_dir()
    _migrar_carpetas_antiguas(base)
    for nombre in CATEGORIES.values():
        os.makedirs(os.path.join(base, nombre), exist_ok=True)
    _write_readme(base)
    _write_folder_readme(folder("msxdos"), MSXDOS_README)
    _write_folder_readme(folder("msxdos_utils"), MSXDOS_UTILS_README)
    return base


def folder(category: str) -> str:
    """Ruta de la subcarpeta de una categoría, creándola si hace falta."""
    nombre = CATEGORIES.get(category, CATEGORIES["source"])
    ruta = os.path.join(base_dir(), nombre)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def source_folder() -> str:
    return folder("source")


def source_has_files() -> bool:
    """True si la carpeta de originales contiene algún archivo."""
    ruta = source_folder()
    try:
        for _dirpath, _dirnames, filenames in os.walk(ruta):
            for fn in filenames:
                if not fn.startswith("."):
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


def _migrar_carpetas_antiguas(base: str) -> None:
    for antiguo, nuevo in RENOMBRADAS.items():
        origen = os.path.join(base, antiguo)
        destino = os.path.join(base, nuevo)
        if not os.path.isdir(origen):
            continue
        try:
            if not os.path.exists(destino):
                os.rename(origen, destino)
            else:
                # Ya existe la nueva: se mueve el contenido y se borra la vieja
                for elemento in os.listdir(origen):
                    try:
                        os.rename(os.path.join(origen, elemento),
                                  unique_path(destino, elemento))
                    except OSError:
                        pass
                try:
                    os.rmdir(origen)
                except OSError:
                    pass
        except OSError:
            pass


def _write_readme(base: str) -> None:
    ruta = os.path.join(base, "LEEME.txt")
    if os.path.exists(ruta):
        return
    texto = (
        "ASTURCONSOLE — carpetas de trabajo\n"
        "================================\n\n"
        "Deja aquí tus archivos y la aplicación los encontrará sola:\n\n"
        f"  {CATEGORIES['source']}/\n"
        "      Carpeta de entrada. Pon aquí las ROMs, discos o cintas que\n"
        "      quieras analizar. Es la que se abre al arrancar.\n\n"
        "El resto de carpetas las rellena la aplicación con los resultados:\n\n"
        f"  {CATEGORIES['byteswap']}/       ROMs tras aplicar byte swap\n"
        f"  {CATEGORIES['swc_disks']}/  imágenes .img de disquete Super Wild Card\n"
        f"  {CATEGORIES['no_header']}/     ROMs sin cabecera de copiador\n"
        f"  {CATEGORIES['with_header']}/     ROMs con cabecera añadida\n"
        f"  {CATEGORIES['checksum']}/  ROMs con el checksum corregido\n"
        f"  {CATEGORIES['interleave']}/      resultados de entrelazar/desentrelazar\n"
        f"  {CATEGORIES['smd']}/     conversiones a/desde formato SMD\n"
        f"  {CATEGORIES['split']}/       fragmentos de ROMs divididas\n"
        f"  {CATEGORIES['tapes']}/            conversiones de cinta (CAS/WAV/TSX)\n"
        f"  {CATEGORIES['extracted']}/    archivos extraídos de discos DSK\n"
        f"  {CATEGORIES['blank_disks']}/                imágenes de disco MSX (.dsk)\n\n"
        "Carpetas que rellenas TÚ (ver el LEEME.txt de cada una):\n\n"
        f"  {CATEGORIES['msxdos']}/                archivos de sistema MSX-DOS\n"
        f"  {CATEGORIES['msxdos_utils']}/          utilidades a incluir en el disco\n\n"
        "Puedes mover o borrar libremente lo que haya en estas carpetas: la\n"
        "aplicación nunca modifica los archivos originales, siempre escribe\n"
        "copias nuevas.\n"
    )
    try:
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(texto)
    except OSError:
        pass
