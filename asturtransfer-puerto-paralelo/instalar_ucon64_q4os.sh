#!/bin/bash
# ============================================================================
#  instalar_ucon64_q4os.sh
#
#  Compila e instala uCON64 en Q4OS (o cualquier Debian/Devuan, incluido
#  32 bits) preparado para transferir ROMs a copiones por PUERTO PARALELO.
#
#  Se compila con --enable-ppdev a propósito: así uCON64 usa el dispositivo
#  /dev/parportN del kernel y NO necesita ser setuid root. Basta con que tu
#  usuario pertenezca al grupo "lp". La alternativa (acceso directo al
#  puerto con ioperm) obliga a dar permisos de root al binario, cosa que
#  conviene evitar.
#
#  Uso:
#     chmod +x instalar_ucon64_q4os.sh
#     ./instalar_ucon64_q4os.sh /ruta/a/ucon64-2.2.2-src.tar.gz
# ============================================================================
set -euo pipefail

FUENTE="${1:-}"
TRABAJO="$HOME/ucon64-build"

echo "=============================================="
echo "  Instalación de uCON64 para puerto paralelo"
echo "=============================================="
echo

# --- comprobaciones previas -------------------------------------------------
if [ -z "$FUENTE" ] || [ ! -f "$FUENTE" ]; then
    echo "ERROR: indica el archivo de fuentes." >&2
    echo "   Ejemplo: ./instalar_ucon64_q4os.sh ~/Descargas/ucon64-2.2.2-src.tar.gz" >&2
    exit 1
fi

echo "Arquitectura del sistema: $(uname -m)"
echo "Fuentes: $FUENTE"
echo

# --- 1. herramientas de compilación ----------------------------------------
echo ">>> Paso 1/6: instalando herramientas de compilación"
echo "    (pedirá tu contraseña para usar apt)"
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    zlib1g-dev \
    libncurses-dev \
    file

# build-essential  -> gcc, make y cabeceras de C
# zlib1g-dev       -> soporte de archivos .zip y .gz dentro de uCON64
# libncurses-dev   -> salida en color y control de terminal
echo

# --- 2. desempaquetar -------------------------------------------------------
echo ">>> Paso 2/6: desempaquetando"
rm -rf "$TRABAJO"
mkdir -p "$TRABAJO"
tar xzf "$FUENTE" -C "$TRABAJO"
DIR=$(find "$TRABAJO" -maxdepth 1 -mindepth 1 -type d | head -n1)
if [ ! -d "$DIR/src" ]; then
    echo "ERROR: no se encontró la carpeta src/ dentro de las fuentes." >&2
    exit 1
fi
echo "    Carpeta: $DIR"
echo

# --- 3. configurar ----------------------------------------------------------
echo ">>> Paso 3/6: configurando (con ppdev, sin necesidad de setuid root)"
cd "$DIR/src"
./configure --enable-ppdev
echo

# --- 4. compilar ------------------------------------------------------------
echo ">>> Paso 4/6: compilando (puede tardar bastante en equipos antiguos)"
make
echo

# --- 5. instalar ------------------------------------------------------------
echo ">>> Paso 5/6: instalando en /usr/local/bin"
sudo make install || {
    echo "    'make install' falló; copiando el binario a mano."
    sudo cp -f ucon64 /usr/local/bin/
}
echo

# --- 6. permisos del puerto paralelo ---------------------------------------
echo ">>> Paso 6/6: preparando el acceso al puerto paralelo"

# Cargar los módulos del kernel del puerto paralelo
sudo modprobe parport    2>/dev/null || true
sudo modprobe parport_pc 2>/dev/null || true
sudo modprobe ppdev      2>/dev/null || true

# Que se carguen también en cada arranque
for m in parport_pc ppdev; do
    if ! grep -qx "$m" /etc/modules 2>/dev/null; then
        echo "$m" | sudo tee -a /etc/modules >/dev/null
    fi
done

# El grupo lp es el propietario de /dev/parportN
sudo usermod -aG lp "$USER"

echo
echo "=============================================="
echo "  Instalación terminada"
echo "=============================================="
echo
echo "Versión instalada:"
ucon64 --version 2>/dev/null | head -3 || echo "  (ejecuta 'ucon64' para comprobarlo)"
echo
echo "Dispositivos de puerto paralelo detectados:"
ls -l /dev/parport* 2>/dev/null || echo "  NINGUNO — ver diagnóstico más abajo"
echo
echo "IMPORTANTE: cierra la sesión y vuelve a entrar para que el grupo 'lp'"
echo "tenga efecto. Comprueba después con:   groups"
echo
echo "CONFIGURACIÓN DEL PUERTO"
echo "  Compilado con ppdev, el dispositivo NO se indica con --port, sino en"
echo "  el archivo de configuración ~/.ucon64rc, con la línea:"
echo "        parport_dev=/dev/parport0"
echo "  Ese archivo se crea solo la primera vez que ejecutas uCON64, y ya trae"
echo "  ese valor por defecto. Solo hay que cambiarlo si tu puerto es parport1"
echo "  o parport2."
echo
echo "TRANSFERIR UNA ROM"
echo "  Super Wild Card (SNES):     ucon64 --xswc juego.swc"
echo "  Super Magic Drive (Mega):   ucon64 --xsmd juego.smd"
echo
echo "  Añade --port=378 solo si compilaste SIN ppdev (acceso directo al puerto)."
echo
echo "OPCIONES ÚTILES SEGÚN LA LISTA DE COMPATIBILIDAD"
echo "  -k   aplicar crack de protección anticopia"
echo "  -f   corregir NTSC/PAL"
echo "  (asturconsole te dice cuáles necesita cada juego al analizarlo)"
echo
echo "SI NO APARECE NINGÚN /dev/parportN:"
echo "  - Comprueba que el puerto está activado en la BIOS."
echo "  - En la BIOS, el modo del puerto debe ser EPP, ECP+EPP o bidireccional;"
echo "    el modo 'SPP'/'solo salida' NO sirve para los copiones."
echo "  - Revisa qué detecta el kernel:   dmesg | grep -i parport"
echo "  - Direcciones de E/S en uso:      cat /proc/ioports | grep -i parport"
echo
