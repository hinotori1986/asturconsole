#!/bin/bash
# ============================================================================
#  asturtransfer — interfaz mínima para enviar ROMs al copión con uCON64
#
#  Pensada para la máquina antigua: no necesita Python, ni Qt, ni entorno
#  gráfico. Funciona en la consola de texto pura.
#
#  Usa whiptail (incluido de serie en Debian/Q4OS) para dibujar los menús.
#  Si no estuviera, recurre a dialog, y si tampoco, a un menú de texto
#  plano que funciona en cualquier terminal.
#
#  Uso:   ./asturtransfer.sh [carpeta_con_roms]
# ============================================================================
set -uo pipefail

VERSION="1.0"
CARPETA="${1:-$PWD}"
UCON64="$(command -v ucon64 || echo /usr/local/bin/ucon64)"
CONFIG="$HOME/.asturtransfer"

# Estado, recordado entre ejecuciones
COPION="swc"
TIPO="rom"
OPCIONES=""
[ -f "$CONFIG" ] && . "$CONFIG"

# --- entrada del usuario ----------------------------------------------------
# Los menús se leen del TERMINAL (descriptor 3) y no de la entrada estándar.
# Es lo correcto para una herramienta interactiva y evita que las lecturas
# hechas dentro de subshells (las sustituciones $(...) de los menús) se
# queden sin datos.
# Se usa el descriptor 9 y NO el 3: la forma habitual de recoger la salida
# de whiptail es "3>&1 1>&2 2>&3", así que el 3 debe quedar libre. Usarlo
# aquí hacía que whiptail fallara en silencio y los menús salieran vacíos.
if [ -r /dev/tty ] && exec 9</dev/tty 2>/dev/null; then
    :
else
    exec 9<&0
fi

# --- elección de la herramienta de menús ------------------------------------
MENU=""
if command -v whiptail >/dev/null 2>&1; then
    MENU="whiptail"
elif command -v dialog >/dev/null 2>&1; then
    MENU="dialog"
fi

# ============================================================================
#  Funciones de interfaz (con alternativa en texto plano)
# ============================================================================

msg() {  # msg "titulo" "texto"
    if [ -n "$MENU" ]; then
        $MENU --title "$1" --msgbox "$2" 18 74
    else
        # -e para que los \n del texto se interpreten como saltos de línea,
        # igual que hace whiptail
        echo; echo "=== $1 ==="; echo -e "$2"; echo
        read -rp "Pulsa Intro para continuar..." _ <&9
    fi
}

confirmar() {  # confirmar "titulo" "texto" -> 0 si sí
    if [ -n "$MENU" ]; then
        $MENU --title "$1" --yesno "$2" 16 74
    else
        echo; echo "=== $1 ==="; echo -e "$2"; echo
        read -rp "¿Continuar? (s/N): " r <&9
        [ "$r" = "s" ] || [ "$r" = "S" ]
    fi
}

# menu_opciones "titulo" "texto" etiqueta1 desc1 etiqueta2 desc2 ...
menu_opciones() {
    local titulo="$1" texto="$2"; shift 2
    if [ -n "$MENU" ]; then
        # La salida se recoge por archivo temporal en vez del típico
        # "3>&1 1>&2 2>&3": es equivalente, pero no depende de qué
        # descriptores estén libres.
        local tmp rc
        tmp=$(mktemp)
        $MENU --title "$titulo" --menu "$texto" 20 74 10 "$@" 2>"$tmp"
        rc=$?
        if [ $rc -eq 0 ]; then
            cat "$tmp"
        fi
        rm -f "$tmp"
    else
        echo >&2; echo "=== $titulo ===" >&2; echo -e "$texto" >&2; echo >&2
        local i=1
        local -a claves=()
        while [ $# -gt 0 ]; do
            claves+=("$1")
            printf "  %2d) %-14s %s\n" "$i" "$1" "$2" >&2
            shift 2; i=$((i+1))
        done
        echo >&2
        read -rp "Elige un número: " n <&9
        if [ "$n" -ge 1 ] 2>/dev/null && [ "$n" -le "${#claves[@]}" ]; then
            echo "${claves[$((n-1))]}"
        fi
    fi
}

# ============================================================================
#  Lógica
# ============================================================================

guardar_estado() {
    cat > "$CONFIG" <<EOF
COPION="$COPION"
TIPO="$TIPO"
OPCIONES="$OPCIONES"
CARPETA="$CARPETA"
EOF
}

comprobar_entorno() {
    local problemas=""

    if [ ! -x "$UCON64" ]; then
        problemas+="ERROR: no se encuentra uCON64.\n"
        problemas+="   Instálalo con el script instalar_ucon64_q4os.sh\n\n"
    fi

    if ! ls /dev/parport* >/dev/null 2>&1; then
        problemas+="AVISO: no hay ningún /dev/parportN.\n"
        problemas+="   - ¿Está activado el puerto en la BIOS?\n"
        problemas+="   - El modo debe ser EPP, ECP+EPP o bidireccional (SPP no sirve).\n"
        problemas+="   - Prueba: sudo modprobe parport_pc ppdev\n\n"
    elif ! id -nG | tr ' ' '\n' | grep -qx lp; then
        problemas+="AVISO: tu usuario NO está en el grupo 'lp', así que no podrá\n"
        problemas+="   abrir el puerto. Ejecuta:  sudo usermod -aG lp $USER\n"
        problemas+="   y vuelve a iniciar sesión.\n\n"
    fi

    if [ -n "$problemas" ]; then
        msg "Comprobación del entorno" "$problemas"
    fi
}

extension_esperada() {
    case "$COPION" in
        swc) echo "swc sfc smc fig" ;;
        smd) echo "smd bin md gen" ;;
    esac
}

elegir_carpeta() {
    local nueva
    if [ -n "$MENU" ]; then
        local tmp
        tmp=$(mktemp)
        if $MENU --title "Carpeta de ROMs" --inputbox \
                 "Ruta de la carpeta que contiene las ROMs:" 10 74 "$CARPETA" 2>"$tmp"; then
            nueva=$(cat "$tmp")
        fi
        rm -f "$tmp"
    else
        read -rp "Carpeta de ROMs [$CARPETA]: " nueva <&9
    fi
    [ -n "$nueva" ] && [ -d "$nueva" ] && CARPETA="$nueva"
    guardar_estado
}

elegir_copion() {
    local sel
    sel=$(menu_opciones "Copión" "¿A qué aparato vas a transferir?" \
        "swc" "Super Wild Card / Super Magicom (SNES)" \
        "smd" "Super Magic Drive (Mega Drive)")
    [ -n "$sel" ] && COPION="$sel" && guardar_estado
}

elegir_tipo() {
    local sel
    sel=$(menu_opciones "Qué transferir" "Contenido a enviar al copión:" \
        "rom"  "ROM del juego" \
        "sram" "SRAM (partidas guardadas)")
    [ -n "$sel" ] && TIPO="$sel" && guardar_estado
}

elegir_opciones() {
    local sel
    sel=$(menu_opciones "Correcciones" \
        "Algunos juegos las necesitan. asturconsole te indica cuáles al analizarlos." \
        "ninguna" "Enviar sin modificar (lo habitual)" \
        "-k"      "Crack de proteccion anticopia" \
        "-f"      "Correccion NTSC/PAL" \
        "-k -f"   "Ambas correcciones")
    case "$sel" in
        ninguna) OPCIONES="" ;;
        "") ;;                       # cancelado: no tocar
        *) OPCIONES="$sel" ;;
    esac
    guardar_estado
}

# Construye la lista de ROMs de la carpeta y deja elegir una
elegir_y_enviar() {
    local -a items=()
    local n=0 f
    local exts; exts=$(extension_esperada)

    while IFS= read -r f; do
        [ -f "$f" ] || continue
        local base tam
        base=$(basename "$f")
        tam=$(du -h "$f" 2>/dev/null | cut -f1)
        items+=("$base" "$tam")
        n=$((n+1))
    done < <(
        for e in $exts; do
            find "$CARPETA" -maxdepth 1 -type f \
                 \( -iname "*.$e" \) 2>/dev/null
        done | sort
    )

    if [ "$n" -eq 0 ]; then
        msg "Sin archivos" \
            "No se encontró ninguna ROM en:\n$CARPETA\n\nExtensiones buscadas para este copión:\n  $exts\n\nUsa la opción 'Carpeta' del menú para cambiar de ubicación."
        return
    fi

    local elegido
    elegido=$(menu_opciones "Elegir ROM ($n encontradas)" \
        "Carpeta: $CARPETA" "${items[@]}")
    [ -z "$elegido" ] && return

    local ruta="$CARPETA/$elegido"
    local opcion
    if [ "$TIPO" = "sram" ]; then
        case "$COPION" in swc) opcion="--xswcs" ;; smd) opcion="--xsmds" ;; esac
    else
        case "$COPION" in swc) opcion="--xswc" ;; smd) opcion="--xsmd" ;; esac
    fi

    local cmd="$UCON64 $opcion"
    [ -n "$OPCIONES" ] && cmd="$cmd $OPCIONES"
    cmd="$cmd \"$ruta\""

    local aviso=""
    if [ "$COPION" = "smd" ]; then
        aviso="\n\nRecuerda: el archivo debe estar YA en formato SMD (cabecera de\n512 bytes + datos entrelazados). Un .bin plano no funcionará."
    else
        aviso="\n\nRecuerda: el archivo debe llevar YA la cabecera Super Wild Card."
    fi

    confirmar "Confirmar transferencia" \
"Archivo:  $elegido
Copión:   $COPION
Enviar:   $TIPO
Opciones: ${OPCIONES:-(ninguna)}

Comando:
  $cmd

Enciende el copión ANTES de continuar.$aviso" || return

    clear
    echo "=============================================="
    echo " Transfiriendo: $elegido"
    echo " Comando: $cmd"
    echo "=============================================="
    echo
    eval "$cmd"
    local codigo=$?
    echo
    if [ $codigo -eq 0 ]; then
        echo ">>> Transferencia terminada correctamente."
    else
        echo ">>> uCON64 terminó con código $codigo."
        echo "    Si el copión no responde: comprueba que está encendido, que el"
        echo "    cable es bidireccional y que el puerto está en modo EPP."
    fi
    echo
    read -rp "Pulsa Intro para volver al menú..." _ <&9
}

ver_info() {
    local info=""
    info+="uCON64:   $UCON64\n"
    if [ -x "$UCON64" ]; then
        info+="Versión:  $("$UCON64" --version 2>/dev/null | grep -m1 -i '^uCON64' || echo '?')\n"
    fi
    info+="\nPuertos paralelo detectados:\n"
    if ls /dev/parport* >/dev/null 2>&1; then
        info+="$(ls -l /dev/parport* | sed 's/^/  /')\n"
    else
        info+="  ninguno\n"
    fi
    info+="\nTus grupos: $(id -nG)\n"
    info+="\nDispositivo configurado en ~/.ucon64rc:\n"
    info+="  $(grep -m1 '^parport_dev' "$HOME/.ucon64rc" 2>/dev/null || echo '(sin configurar; se crea al ejecutar uCON64)')\n"
    msg "Estado del sistema" "$info"
}

# ============================================================================
#  Bucle principal
# ============================================================================
comprobar_entorno

while true; do
    accion=$(menu_opciones "asturtransfer $VERSION" \
"Copión: $COPION    Enviar: $TIPO    Opciones: ${OPCIONES:-ninguna}
Carpeta: $CARPETA" \
        "enviar"   "Elegir una ROM y transferirla" \
        "copion"   "Cambiar de copión (ahora: $COPION)" \
        "tipo"     "ROM o SRAM (ahora: $TIPO)" \
        "opciones" "Correcciones -k / -f (ahora: ${OPCIONES:-ninguna})" \
        "carpeta"  "Cambiar la carpeta de ROMs" \
        "estado"   "Ver estado del puerto y permisos" \
        "salir"    "Salir")

    case "$accion" in
        enviar)   elegir_y_enviar ;;
        copion)   elegir_copion ;;
        tipo)     elegir_tipo ;;
        opciones) elegir_opciones ;;
        carpeta)  elegir_carpeta ;;
        estado)   ver_info ;;
        salir|"") clear; echo "Hasta luego."; exit 0 ;;
    esac
done
