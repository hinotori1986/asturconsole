#!/bin/bash
# ============================================================================
#  instalar_icono_linux.sh
#
#  En Linux, PyInstaller NO empotra ningún icono dentro del binario ELF
#  (a diferencia de Windows con .ico o macOS con .icns): es una limitación
#  del propio formato ejecutable de Linux, no un descuido de este proyecto.
#  Por eso, si compilas con build_linux.sh, el binario "asturconsole" en sí
#  nunca tendrá icono propio, lo abras como lo abras.
#
#  Lo que SÍ funciona en Linux es registrar la aplicación en el sistema de
#  escritorio estándar (freedesktop.org): un archivo .desktop que apunta al
#  icono. Este script hace exactamente eso, para que ASTURCONSOLE aparezca
#  con su icono en el menú de aplicaciones, en el dock/barra de tareas al
#  ejecutarlo, y al anclarlo como favorito.
#
#  Uso, después de compilar con build_linux.sh:
#     ./instalar_icono_linux.sh
# ============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARIO="$DIR/dist/asturconsole"
ICONO_ORIGEN="$DIR/assets/icons/app_icon.png"

echo "=============================================="
echo "  Instalar el icono de ASTURCONSOLE en el escritorio"
echo "=============================================="
echo

if [ ! -f "$BINARIO" ]; then
    echo "ERROR: no se encuentra $BINARIO" >&2
    echo "       Compila antes con: ./build_linux.sh" >&2
    exit 1
fi
if [ ! -f "$ICONO_ORIGEN" ]; then
    echo "ERROR: no se encuentra $ICONO_ORIGEN" >&2
    exit 1
fi

ICONOS_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$ICONOS_DIR" "$DESKTOP_DIR"

# 1. Copiar el icono a la ubicación estándar del sistema de iconos
cp -f "$ICONO_ORIGEN" "$ICONOS_DIR/asturconsole.png"
echo "Icono copiado a: $ICONOS_DIR/asturconsole.png"

# 2. Generar el lanzador .desktop con la ruta REAL del binario en este equipo
#    (no la ruta genérica de ejemplo que trae el proyecto)
cat > "$DESKTOP_DIR/asturconsole.desktop" << EOF
[Desktop Entry]
Type=Application
Name=ASTURCONSOLE
Comment=Analisis y manipulacion de ROMs, discos y cintas MSX/SNES/Mega Drive
Exec=$BINARIO
Icon=asturconsole
Terminal=false
Categories=Utility;Emulator;
EOF
echo "Lanzador creado en: $DESKTOP_DIR/asturconsole.desktop"

# 3. Avisar al entorno de escritorio de que hay iconos/aplicaciones nuevas,
#    si las herramientas para ello están instaladas (no es grave si no lo están)
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo
echo "Listo. ASTURCONSOLE debería aparecer con su icono en el menú de"
echo "aplicaciones. Si tu escritorio no lo detecta enseguida, prueba a"
echo "cerrar sesión y volver a entrar, o a buscar 'asturconsole' en el menú."
echo
echo "Si vuelves a compilar (build_linux.sh) NO hace falta repetir este"
echo "paso, salvo que hayas movido la carpeta del proyecto de sitio."
