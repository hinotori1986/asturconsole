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

# Elegir entre compilar "normal" (usa la wheel de PySide6/Shiboken6 de PyPI,
# más simple, pero esas ruedas están compiladas asumiendo un procesador con
# AVX2/SSE4.2) o "legacy" (usa el PySide6 que empaqueta la propia
# distribución, compilado con un baseline de instrucciones mucho más
# conservador — imprescindible en equipos con CPUs anteriores a ~2011,
# como un Pentium/Core 2 Duo, que solo llegan a SSSE3). Confirmado con un
# Pentium E5300 (Wolfdale): la wheel de PyPI provoca SIGILL en
# libshiboken6, y el paquete nativo de Fedora (python3-pyside6) no.
#
# Se sugiere automáticamente según las flags de /proc/cpuinfo, pero se
# puede forzar con --legacy / --modern, o con la variable de entorno
# ASTURCONSOLE_BUILD_MODE=legacy|modern (útil para scripts/CI sin preguntar).
MODO="${ASTURCONSOLE_BUILD_MODE:-}"
for arg in "$@"; do
    case "$arg" in
        --legacy) MODO="legacy" ;;
        --modern) MODO="modern" ;;
    esac
done

if [ -z "$MODO" ]; then
    SUGERENCIA="modern"
    if [ -f /proc/cpuinfo ] && ! grep -qm1 -E '\bavx2\b' /proc/cpuinfo; then
        SUGERENCIA="legacy"
    fi
    echo "No se ha indicado el modo de compilación (--legacy / --modern)."
    if [ "$SUGERENCIA" = "legacy" ]; then
        echo "Este procesador no anuncia AVX2 en /proc/cpuinfo: se sugiere 'legacy'."
    else
        echo "Este procesador anuncia AVX2 en /proc/cpuinfo: se sugiere 'modern'."
    fi
    read -r -p "¿Compilar en modo [legacy/modern] ($SUGERENCIA)? " RESPUESTA
    MODO="${RESPUESTA:-$SUGERENCIA}"
fi

if [ "$MODO" != "legacy" ] && [ "$MODO" != "modern" ]; then
    echo "ERROR: modo '$MODO' no reconocido (usa 'legacy' o 'modern')." >&2
    exit 1
fi
echo "Modo de compilación: $MODO"
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

if [ "$MODO" = "legacy" ]; then
    # No se debe instalar PySide6 por pip en modo legacy: hace falta el
    # paquete nativo de la distro, compilado con un baseline de
    # instrucciones amplio. Se comprueba ANTES de crear el venv, para
    # avisar con claridad si falta en vez de fallar más adelante con un
    # error de import menos descriptivo.
    if ! python3 -c 'import PySide6' >/dev/null 2>&1; then
        echo "ERROR: en modo 'legacy' hace falta PySide6 instalado como paquete del" >&2
        echo "       sistema (NO por pip), para evitar la wheel de PyPI, compilada" >&2
        echo "       asumiendo AVX2/SSE4.2. En Fedora:  sudo dnf install python3-pyside6" >&2
        echo "       En Debian/Ubuntu 24.10+:  sudo apt install python3-pyside6.qtwidgets" >&2
        exit 1
    fi
    VENV=.venv-build-legacy
    if [ ! -d "$VENV" ]; then
        echo "Creando entorno virtual en $VENV (con acceso al PySide6 del sistema)..."
        python3 -m venv --system-site-packages "$VENV"
    fi
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"

    echo "Instalando dependencias (sin tocar PySide6, que ya viene del sistema)..."
    pip install --upgrade pip -q
    pip install -r requirements.txt -q --no-deps
    pip install pyinstaller -q
    export ASTURCONSOLE_LEGACY=1
else
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
fi

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

BIN_NAME="asturconsole"
[ "$MODO" = "legacy" ] && BIN_NAME="asturconsole-legacy"

echo
if [ -f "dist/$BIN_NAME" ]; then
    SIZE=$(du -h "dist/$BIN_NAME" | cut -f1)
    echo "== Listo =="
    echo "Binario: $(pwd)/dist/$BIN_NAME  ($SIZE)"
    echo
    if [ "$MODO" = "legacy" ]; then
        echo "Modo legacy: lleva empotradas las librerias de Qt/PySide6 de esta"
        echo "distribucion (compiladas con un baseline de instrucciones amplio),"
        echo "en vez de las de PyPI. Sigue sin necesitar Python ni PySide6"
        echo "instalados en la maquina donde se ejecute."
    else
        echo "Puedes moverlo o renombrarlo libremente: no necesita Python ni PySide6"
        echo "instalados en la maquina donde se ejecute."
    fi
    echo
    echo "Para probarlo:  ./dist/$BIN_NAME"
else
    echo "ERROR: la compilacion termino pero no se encontro dist/$BIN_NAME" >&2
    exit 1
fi
