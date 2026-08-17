#!/usr/bin/env bash
# Compila ASTURCONSOLE como un único ejecutable para Linux x86_64.
#
# Debe ejecutarse EN Linux: PyInstaller no hace compilación cruzada real,
# así que el binario de Windows hay que generarlo en Windows (o con el
# workflow de GitHub Actions incluido en .github/workflows/build.yml).
set -euo pipefail
cd "$(dirname "$0")"

echo "== ASTURCONSOLE — compilación para Linux =="
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: no se encuentra python3." >&2
    exit 1
fi

echo "Python detectado: $(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' \
    || { echo "ERROR: se necesita Python 3.9 o superior." >&2; exit 1; }

# PyInstaller suele tardar en dar soporte a las versiones recien publicadas de
# Python. Si la compilacion falla con errores extranos en versiones muy nuevas,
# la solucion habitual es compilar con una version algo mas asentada.
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info < (3,13) else 1)'; then
    echo
    echo "AVISO: estas usando una version de Python muy reciente."
    echo "       Si PyInstaller falla, prueba a compilar con Python 3.11 o 3.12:"
    echo "         sudo apt install python3.12 python3.12-venv"
    echo "         rm -rf .venv-build"
    echo "         python3.12 -m venv .venv-build && ./build_linux.sh"
    echo "       (la aplicacion en si funciona bien con cualquier version >= 3.9;"
    echo "        esto afecta solo al empaquetado del binario)"
    echo
fi

if ! python3 -c 'import venv' >/dev/null 2>&1; then
    echo "ERROR: falta el modulo venv. En Debian/Ubuntu: sudo apt install python3-venv" >&2
    exit 1
fi

VENV=.venv-build
if [ ! -d "$VENV" ]; then
    echo "Creando entorno virtual en $VENV..."
    python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "Instalando dependencias..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install pyinstaller -q

if ! python3 -c 'from PySide6 import QtMultimedia' >/dev/null 2>&1; then
    echo
    echo "AVISO: PySide6.QtMultimedia no esta disponible en este entorno."
    echo "       El binario se compilara igualmente, pero el reproductor de cinta"
    echo "       no funcionara. Revisa la instalacion de PySide6."
    echo
fi

# PySide6 instala las librerias de Qt (incluidas las de FFmpeg que usa
# QtMultimedia) sin el bit de ejecucion. PyInstaller lanza 'ldd' sobre ellas
# para resolver sus dependencias y falla con avisos del tipo:
#   ldd: no tiene permiso de ejecucion para .../libavcodec.so.61
# No es fatal, pero puede hacer que el binario se empaquete incompleto y que
# el reproductor de cinta no funcione. Se corrige dandoles permiso:
QT_LIB_DIR=$(python3 -c 'import PySide6, os; print(os.path.join(os.path.dirname(PySide6.__file__), "Qt", "lib"))' 2>/dev/null || true)
if [ -n "$QT_LIB_DIR" ] && [ -d "$QT_LIB_DIR" ]; then
    echo "Ajustando permisos de las librerias de Qt en $QT_LIB_DIR ..."
    chmod +x "$QT_LIB_DIR"/*.so* 2>/dev/null || true
fi

echo "Compilando..."
pyinstaller --clean --noconfirm asturconsole.spec

echo
if [ -f dist/asturconsole ]; then
    SIZE=$(du -h dist/asturconsole | cut -f1)
    echo "== Listo =="
    echo "Binario: $(pwd)/dist/asturconsole  ($SIZE)"
    echo
    echo "Puedes moverlo o renombrarlo libremente: no necesita Python ni PySide6"
    echo "instalados en la maquina donde se ejecute."
    echo
    echo "Para probarlo:  ./dist/asturconsole"
else
    echo "ERROR: la compilacion termino pero no se encontro dist/asturconsole" >&2
    exit 1
fi
