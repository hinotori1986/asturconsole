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

VERSION="1.1"

# A partir de este número de ROMs se pide un filtro antes de listar
MAX_SIN_FILTRO=40
CARPETA_ARG="${1:-}"
UCON64="$(command -v ucon64 || echo /usr/local/bin/ucon64)"
CONFIG="$HOME/.asturtransfer"

# Estado, recordado entre ejecuciones
COPION="swc"
TIPO="rom"
OPCIONES=""
CARPETA="$PWD"
[ -f "$CONFIG" ] && . "$CONFIG"

# La carpeta indicada al arrancar manda sobre la guardada en la configuración
if [ -n "$CARPETA_ARG" ]; then
    if [ -d "$CARPETA_ARG" ]; then
        CARPETA="$CARPETA_ARG"
    else
        echo "AVISO: la carpeta indicada no existe: $CARPETA_ARG" >&2
        echo "       Se usará: $CARPETA" >&2
        sleep 2
    fi
fi

# --- entrada del usuario ----------------------------------------------------
# Los menús se leen del TERMINAL (descriptor 3) y no de la entrada estándar.
# Es lo correcto para una herramienta interactiva y evita que las lecturas
# hechas dentro de subshells (las sustituciones $(...) de los menús) se
# queden sin datos.
# Se usa el descriptor 9 y NO el 3: la forma habitual de recoger la salida
# de whiptail es "3>&1 1>&2 2>&3", así que el 3 debe quedar libre. Usarlo
# aquí hacía que whiptail fallara en silencio y los menús salieran vacíos.
if { exec 9</dev/tty; } 2>/dev/null; then
    :
else
    exec 9<&0
fi

# Las ventanas de whiptail se dibujan en la SALIDA ESTÁNDAR. Como los menús
# se invocan dentro de $(...) para recoger la elección, esa salida quedaba
# capturada y la ventana no llegaba a la pantalla: whiptail se quedaba
# esperando una tecla que nadie podía ver dónde pulsar (el programa parecía
# colgado). Por eso el dibujo se manda explícitamente al terminal.
# Se comprueba escribiendo de verdad: en algunos entornos /dev/tty existe
# pero no se puede abrir, y entonces cualquier redirección hacia él aborta.
if { : > /dev/tty; } 2>/dev/null; then
    PANTALLA="/dev/tty"
else
    PANTALLA="/dev/stderr"
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
        $MENU --title "$1" --msgbox "$2" 18 74 >"$PANTALLA"
    else
        # -e para que los \n del texto se interpreten como saltos de línea,
        # igual que hace whiptail
        echo; echo "=== $1 ==="; echo -e "$2"; echo
        read -rp "Pulsa Intro para continuar..." _ <&9
    fi
}

confirmar() {  # confirmar "titulo" "texto" -> 0 si sí
    if [ -n "$MENU" ]; then
        $MENU --title "$1" --yesno "$2" 16 74 >"$PANTALLA"
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
        $MENU --title "$titulo" --menu "$texto" 20 74 10 "$@" >"$PANTALLA" 2>"$tmp"
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

    # El controlador de impresora se apropia del puerto e impide el acceso
    # exclusivo que uCON64 necesita (PPCLAIM). Es la causa más habitual de
    # que la transferencia falle aun teniendo permisos correctos.
    if lsmod 2>/dev/null | grep -q "^lp "; then
        problemas+="IMPORTANTE: el módulo 'lp' (impresora) está cargado y se apropia\n"
        problemas+="   del puerto. uCON64 no podrá obtener acceso exclusivo y fallará\n"
        problemas+="   con 'Could not get exclusive access'. Descárgalo con:\n"
        problemas+="        sudo rmmod lp\n"
        problemas+="   Y para que no vuelva a cargarse en cada arranque:\n"
        problemas+="        echo 'blacklist lp' | sudo tee /etc/modprobe.d/no-lp.conf\n\n"
    fi

    # Con ppdev, el dispositivo se toma del archivo de configuración
    if [ -f "$HOME/.ucon64rc" ]; then
        local dev
        dev=$(grep -m1 '^parport_dev' "$HOME/.ucon64rc" | cut -d= -f2)
        if [ -n "$dev" ] && [ ! -e "$dev" ]; then
            problemas+="AVISO: ~/.ucon64rc apunta a '$dev', que no existe.\n"
            problemas+="   Corrige esa línea con el dispositivo real (ver 'estado').\n\n"
        fi
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
                 "Ruta de la carpeta que contiene las ROMs:" 10 74 "$CARPETA" \
                 >"$PANTALLA" 2>"$tmp"; then
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

# Construye la lista de ROMs de la carpeta y deja elegir una.
#
# Las etiquetas del menú son NÚMEROS y no los nombres de archivo. Con
# colecciones grandes, los nombres reales (largos, con espacios, apóstrofos
# y comas) hacían que whiptail recibiera cientos de argumentos enormes y
# fallara en silencio, con lo que el programa parecía no hacer nada.
elegir_y_enviar() {
    local exts; exts=$(extension_esperada)
    local lista; lista=$(mktemp)

    for e in $exts; do
        find "$CARPETA" -maxdepth 1 -type f -iname "*.$e" -print 2>/dev/null
    done | sort > "$lista"

    local total; total=$(wc -l < "$lista")
    if [ "$total" -eq 0 ]; then
        rm -f "$lista"
        msg "Sin archivos" \
"No se encontró ninguna ROM en:\n$CARPETA\n\nExtensiones buscadas para este copión ($COPION):\n  $exts\n\nUsa la opción 'Carpeta' del menú para cambiar de ubicación."
        return
    fi

    # Con muchos archivos, primero se filtra por texto para no navegar una
    # lista interminable.
    local filtro=""
    if [ "$total" -gt "$MAX_SIN_FILTRO" ]; then
        if [ -n "$MENU" ]; then
            local tmpf; tmpf=$(mktemp)
            if $MENU --title "Buscar" --inputbox \
                 "Hay $total ROMs en la carpeta.\n\nEscribe parte del nombre para filtrar,\no deja el campo vacío para verlas todas:" \
                 12 70 "" >"$PANTALLA" 2>"$tmpf"; then
                filtro=$(cat "$tmpf")
            else
                rm -f "$tmpf" "$lista"; return
            fi
            rm -f "$tmpf"
        else
            echo >&2
            read -rp "Hay $total ROMs. Filtrar por nombre (Intro = todas): " filtro <&9
        fi
    fi

    local filtrada; filtrada=$(mktemp)
    if [ -n "$filtro" ]; then
        grep -i -- "$filtro" "$lista" > "$filtrada" || true
    else
        cp "$lista" "$filtrada"
    fi
    rm -f "$lista"

    local n; n=$(wc -l < "$filtrada")
    if [ "$n" -eq 0 ]; then
        rm -f "$filtrada"
        msg "Sin resultados" "Ninguna ROM contiene «$filtro»."
        return
    fi

    # Construir el menú con etiquetas numéricas
    local -a items=()
    local i=1 ruta base tam
    while IFS= read -r ruta; do
        base=$(basename "$ruta")
        tam=$(du -h "$ruta" 2>/dev/null | cut -f1)
        # Recortar los nombres muy largos para que quepan en el cuadro
        if [ ${#base} -gt 58 ]; then
            base="${base:0:55}..."
        fi
        items+=("$i" "$base  [$tam]")
        i=$((i+1))
    done < "$filtrada"

    local elegido
    elegido=$(menu_opciones "Elegir ROM ($n de $(basename "$CARPETA"))" \
        "Filtro: ${filtro:-(ninguno)}" "${items[@]}")
    if [ -z "$elegido" ]; then
        rm -f "$filtrada"; return
    fi

    local ruta_elegida
    ruta_elegida=$(sed -n "${elegido}p" "$filtrada")
    rm -f "$filtrada"
    [ -z "$ruta_elegida" ] && return
    [ -f "$ruta_elegida" ] || { msg "Error" "El archivo ya no existe."; return; }

    local nombre; nombre=$(basename "$ruta_elegida")
    local opcion
    if [ "$TIPO" = "sram" ]; then
        case "$COPION" in swc) opcion="--xswcs" ;; smd) opcion="--xsmds" ;; esac
    else
        case "$COPION" in swc) opcion="--xswc" ;; smd) opcion="--xsmd" ;; esac
    fi

    local cmd="$UCON64 $opcion"
    [ -n "$OPCIONES" ] && cmd="$cmd $OPCIONES"
    cmd="$cmd \"$ruta_elegida\""

    local aviso=""
    if [ "$COPION" = "smd" ]; then
        aviso="\n\nRecuerda: el archivo debe estar YA en formato SMD (cabecera de\n512 bytes + datos entrelazados). Un .bin plano no funcionará."
    else
        aviso="\n\nRecuerda: el archivo debe llevar YA la cabecera Super Wild Card."
    fi

    confirmar "Confirmar transferencia" \
"Archivo:  $nombre
Copión:   $COPION
Enviar:   $TIPO
Opciones: ${OPCIONES:-(ninguna)}

Enciende el copión ANTES de continuar.$aviso" || return

    clear
    echo "=============================================="
    echo " Transfiriendo: $nombre"
    echo " Comando: $cmd"
    echo "=============================================="
    echo

    local registro; registro=$(mktemp)
    eval "$cmd" 2>&1 | tee "$registro"
    local codigo=${PIPESTATUS[0]}
    echo
    if [ $codigo -eq 0 ]; then
        echo ">>> Transferencia terminada correctamente."
    else
        echo ">>> uCON64 terminó con código $codigo."
        echo
        if grep -qi "exclusive access" "$registro"; then
            echo "    CAUSA: otro módulo se ha apropiado del puerto (casi siempre 'lp',"
            echo "    el controlador de impresora)."
            echo "    SOLUCIÓN:   sudo rmmod lp"
            echo "    Permanente: echo 'blacklist lp' | sudo tee /etc/modprobe.d/no-lp.conf"
        elif grep -qi "Could not open parallel port device" "$registro"; then
            echo "    CAUSA: no se pudo abrir el dispositivo, casi siempre por permisos."
            echo "    SOLUCIÓN:   sudo usermod -aG lp $USER    (y volver a iniciar sesión)"
            echo "    Comprueba también la ruta configurada:"
            echo "        grep parport_dev ~/.ucon64rc ; ls -l /dev/parport*"
        elif grep -qi "no.*I/O port driver\|not compiled" "$registro"; then
            echo "    CAUSA: uCON64 no tiene soporte de puerto paralelo compilado."
            echo "    SOLUCIÓN: recompílalo con  ./configure --enable-ppdev"
        elif grep -qiE "time.?out|not respond|no response" "$registro"; then
            echo "    CAUSA: el copión no responde."
            echo "      - ¿Está ENCENDIDO y con un disquete dentro?"
            echo "      - El cable debe ser paralelo BIDIRECCIONAL."
            echo "      - En la BIOS, el puerto en EPP, ECP+EPP o bidireccional."
        else
            echo "    Comprueba que el copión está encendido, que el cable es"
            echo "    bidireccional y que el puerto está en modo EPP en la BIOS."
        fi
    fi
    rm -f "$registro"
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
    if lsmod 2>/dev/null | grep -q "^lp "; then
        info+="\nMódulo 'lp' (impresora): CARGADO  <-- impedirá la transferencia\n"
        info+="   Solución:  sudo rmmod lp\n"
    else
        info+="\nMódulo 'lp' (impresora): no cargado (correcto)\n"
    fi
    if lsmod 2>/dev/null | grep -q "^ppdev"; then
        info+="Módulo 'ppdev': cargado (correcto)\n"
    else
        info+="Módulo 'ppdev': NO cargado  ->  sudo modprobe ppdev\n"
    fi
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
