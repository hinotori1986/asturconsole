"""Diagnóstico de requisitos del sistema para la transferencia por puerto
paralelo en Linux (Windows tiene sus propios problemas, ya documentados
aparte en transfer_dialog.py — este módulo es específico de Linux).

Nace de un patrón que se repite en cada usuario nuevo: "le doy al botón
de enviar y no pasa nada, sin ningún error visible". Casi siempre es uno
de un puñado de problemas conocidos (falta pertenecer al grupo "lp",
CUPS tiene acaparada la impresora del puerto paralelo, o directamente no
existe ningún dispositivo parport en el sistema) — este módulo los
comprueba todos de una vez y da instrucciones concretas para cada uno,
en vez de que cada usuario tenga que redescubrirlos por su cuenta.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass
class Comprobacion:
    titulo: str
    ok: bool
    detalle: str
    solucion: str = ""  # vacío si ok=True, o si no hay nada que el usuario pueda hacer
    accion_id: str = ""  # identificador opcional; si no está vacío, la interfaz puede
    # ofrecer un botón que resuelva el problema directamente (ver ejecutar_accion())


@dataclass
class DiagnosticoPuertoParalelo:
    comprobaciones: list = field(default_factory=list)

    @property
    def todo_ok(self) -> bool:
        return all(c.ok for c in self.comprobaciones)

    @property
    def hay_problemas_accionables(self) -> bool:
        return any(not c.ok and c.solucion for c in self.comprobaciones)


def _modulo_ppdev_cargado() -> Comprobacion:
    """ppdev es el módulo distinto de parport_pc: parport_pc detecta el
    hardware y crea la infraestructura base, pero ppdev es el que expone
    /dev/parportN de forma que un programa en espacio de usuario (como
    uCON64) pueda controlar el puerto directamente, bit a bit. Sin él
    cargado, el dispositivo puede EXISTIR (si parport_pc sí está) pero no
    aceptar las operaciones de bajo nivel que hacen falta — el proceso se
    queda esperando indefinidamente, sin ningún error.
    """
    try:
        with open("/proc/modules", "r") as fh:
            contenido = fh.read()
    except OSError:
        return Comprobacion(
            "Módulo del kernel \"ppdev\"", True,
            "No se pudo leer /proc/modules (algunos entornos restringidos, como "
            "contenedores, no lo exponen) — no se puede comprobar desde aquí.")

    cargado = any(linea.split()[0] == "ppdev" for linea in contenido.splitlines() if linea.strip())
    if cargado:
        return Comprobacion(
            "Módulo del kernel \"ppdev\"", True,
            "Cargado — es el que permite el control directo del puerto desde uCON64.")
    return Comprobacion(
        "Módulo del kernel \"ppdev\"", False,
        "El módulo \"ppdev\" no está cargado. Es DISTINTO de \"parport_pc\" (que solo "
        "detecta el hardware): sin ppdev, uCON64 no puede tomar control directo, bit "
        "a bit, del puerto — aunque /dev/parportN exista, el proceso se queda "
        "esperando indefinidamente sin ningún mensaje de error.",
        "Cárgalo con:\n\n"
        "    sudo modprobe ppdev\n\n"
        "Para que se cargue solo en cada arranque en el futuro:\n\n"
        "    echo \"ppdev\" | sudo tee -a /etc/modules"
    )


def _modulo_lp_cargado() -> Comprobacion:
    """El módulo "lp" del kernel (el driver genérico de impresora paralela)
    puede tener el dispositivo /dev/parportN reservado para sí mismo,
    bloqueando el acceso de bajo nivel que necesita uCON64 (a través de
    ppdev) — sin dar NINGÚN error visible: el proceso simplemente se
    queda esperando el dispositivo para siempre, exactamente el síntoma
    de "aparece la información del ROM y ahí se queda, sin nada más".
    """
    try:
        with open("/proc/modules", "r") as fh:
            contenido = fh.read()
    except OSError:
        return Comprobacion(
            "Módulo del kernel \"lp\"", True,
            "No se pudo leer /proc/modules (algunos entornos restringidos, como "
            "contenedores, no lo exponen) — no se puede comprobar desde aquí.")

    cargado = any(linea.split()[0] == "lp" for linea in contenido.splitlines() if linea.strip())
    if not cargado:
        return Comprobacion(
            "Módulo del kernel \"lp\"", True,
            "El módulo \"lp\" no está cargado — no puede haber conflicto con ppdev.")
    return Comprobacion(
        "Módulo del kernel \"lp\"", False,
        "El módulo \"lp\" del kernel está cargado. Es el driver genérico de "
        "impresora paralela, y puede tener el dispositivo /dev/parportN "
        "reservado para sí mismo — esto bloquea silenciosamente el acceso "
        "directo que necesita uCON64 (vía ppdev): el proceso se queda "
        "esperando el dispositivo indefinidamente, sin ningún mensaje de "
        "error, justo el síntoma de \"aparece la información del ROM y ahí "
        "se queda\".",
        "Descárgalo (basta con hacerlo una vez por sesión, antes de "
        "transferir — se puede volver a cargar solo, o al reiniciar):\n\n"
        "    sudo rmmod lp\n\n"
        "Si quieres que no se cargue nunca automáticamente en el futuro:\n\n"
        "    echo \"blacklist lp\" | sudo tee /etc/modprobe.d/blacklist-lp.conf",
        accion_id="descargar_modulo_lp",
    )


def _probar_apertura_real() -> Comprobacion:
    """Reproduce EXACTAMENTE los mismos pasos que uCON64 al inicializar el
    puerto en Linux (open -> PPEXCL -> PPCLAIM -> PPSETMODE en modo SPP
    básico, el más simple de todos — el que usa --xsmd), cada uno con un
    timeout corto, para saber en qué paso CONCRETO se bloquea si es que
    se bloquea. Todas las comprobaciones anteriores (grupo, módulo lp,
    CUPS) pueden estar en orden y aun así el puerto no responder — por
    ejemplo, si el chipset de una tarjeta PCI/PCIe concreta no negocia
    bien el modo IEEE1284 con el driver del kernel. Sin esta prueba, la
    única señal visible sería "la transferencia no hace nada", sin decir
    en qué punto exacto se atasca.
    """
    candidatos = ["/dev/parport0", "/dev/parport1"]
    dispositivo = next((p for p in candidatos if os.path.exists(p)), None)
    if not dispositivo:
        return Comprobacion(
            "Prueba real de apertura del puerto", True,
            "No se comprueba: no hay ningún dispositivo parport presente "
            "(ver la comprobación de arriba).")

    import fcntl
    import signal
    import struct

    PPCLAIM = 0x708B
    PPRELEASE = 0x708C
    PPEXCL = 0x708F
    PPSETMODE = 0x40047080
    IEEE1284_MODE_COMPAT = 0x100

    class _ExpiroTiempo(Exception):
        pass

    def _handler(signum, frame):
        raise _ExpiroTiempo()

    fd = None
    paso_actual = "abrir el dispositivo (open)"
    try:
        signal.signal(signal.SIGALRM, _handler)
        signal.alarm(4)
        fd = os.open(dispositivo, os.O_RDWR)

        paso_actual = "reservarlo en exclusiva (ioctl PPEXCL)"
        signal.alarm(4)
        fcntl.ioctl(fd, PPEXCL, 0)

        paso_actual = "reclamarlo (ioctl PPCLAIM)"
        signal.alarm(4)
        fcntl.ioctl(fd, PPCLAIM, 0)

        paso_actual = "configurar el modo SPP básico (ioctl PPSETMODE)"
        signal.alarm(4)
        fcntl.ioctl(fd, PPSETMODE, struct.pack("i", IEEE1284_MODE_COMPAT))

        signal.alarm(0)
        return Comprobacion(
            "Prueba real de apertura del puerto", True,
            f"Se abrió, reservó y configuró {dispositivo} correctamente, "
            "sin bloquearse en ningún paso.")
    except _ExpiroTiempo:
        return Comprobacion(
            "Prueba real de apertura del puerto", False,
            f"Se ha quedado bloqueado más de 4 segundos al intentar {paso_actual} "
            f"sobre {dispositivo}, sin ningún error — el driver del kernel no "
            "está respondiendo a esa operación concreta. Con los permisos y el "
            "resto de requisitos ya en orden, esto suele apuntar al propio "
            "chipset de la tarjeta (algunos controladores PCI/PCIe de puerto "
            "paralelo no negocian bien ciertos modos IEEE1284 con el driver "
            "estándar de Linux).",
            "Prueba con otra tarjeta de puerto paralelo si tienes alguna "
            "disponible (los chipsets más simples/tradicionales suelen ir "
            "mejor que los controladores PCIe modernos con lógica interna "
            "compleja). Si el equipo tiene un puerto paralelo integrado en "
            "la placa base, prueba con ese en vez de la tarjeta de expansión."
        )
    except OSError as e:
        return Comprobacion(
            "Prueba real de apertura del puerto", False,
            f"Error inmediato (no bloqueo) al intentar {paso_actual} sobre "
            f"{dispositivo}: {e}",
            "Revisa el mensaje de error de arriba — indica la causa exacta "
            "que dio el sistema."
        )
    finally:
        signal.alarm(0)
        if fd is not None:
            try:
                # Liberar el claim explícitamente antes de cerrar: cerrar el
                # fd debería bastar (el driver libera el claim al cerrarlo),
                # pero ser explícitos evita cualquier duda de que el puerto
                # quede "ocupado" por nuestra propia prueba de diagnóstico y
                # bloquee una transferencia real justo después.
                fcntl.ioctl(fd, PPRELEASE, 0)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass


def _ucon64_necesita_root() -> Comprobacion:
    """Hay dos formas completamente distintas de compilar uCON64 para
    acceder al puerto paralelo en Linux: con soporte "ppdev" (usa
    /dev/parportN + ioctl, no necesita privilegios especiales más allá
    del grupo "lp"), o sin él (usa iopl()/ioperm(), acceso directo a los
    puertos de E/S del procesador, que SIEMPRE requiere ser root o tener
    la capability CAP_SYS_RAWIO — el grupo "lp" no tiene ningún efecto
    aquí, son dos mecanismos independientes). Los binarios compilados a
    mano desde el código fuente (typicamente en /usr/local/bin) suelen
    tener ppdev desactivado por defecto; los paquetes de la distribución
    (en /usr/bin) normalmente lo llevan activado. Sin esta comprobación,
    el síntoma es idéntico al de un problema de permisos de "lp" —
    "aparece la información del ROM y ahí se queda" —, pero el error real
    ("Could not set the I/O privilege level") solo se ve corriendo
    uCON64 en una terminal, no dentro de esta interfaz.
    """
    ruta = shutil.which("ucon64")
    if not ruta:
        return Comprobacion(
            "Privilegios de uCON64 para el puerto paralelo", True,
            "No se comprueba: uCON64 no está instalado (ver la comprobación de arriba).")

    getcap = shutil.which("getcap")
    if not getcap:
        return Comprobacion(
            "Privilegios de uCON64 para el puerto paralelo", True,
            "No se pudo comprobar (falta la herramienta \"getcap\" del paquete "
            "libcap2-bin) — si la transferencia no funciona pese a que el resto "
            "de comprobaciones estén en orden, prueba el comando de la solución "
            "de todos modos.")

    try:
        resultado = subprocess.run([getcap, ruta], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return Comprobacion(
            "Privilegios de uCON64 para el puerto paralelo", True,
            "No se pudo comprobar (no es necesariamente un problema).")

    tiene_capability = "cap_sys_rawio" in resultado.stdout.lower()
    es_setuid = os.path.exists(ruta) and (os.stat(ruta).st_mode & 0o4000)
    if tiene_capability or es_setuid:
        return Comprobacion(
            "Privilegios de uCON64 para el puerto paralelo", True,
            f"{ruta} ya tiene el permiso necesario para acceder al puerto "
            "directamente (capability CAP_SYS_RAWIO o bit setuid).")

    return Comprobacion(
        "Privilegios de uCON64 para el puerto paralelo", False,
        f"{ruta} no está compilado con soporte \"ppdev\" — usa acceso directo a "
        "los puertos de E/S (iopl()), que siempre requiere privilegios de root "
        "o la capability CAP_SYS_RAWIO. El grupo \"lp\" NO tiene ningún efecto "
        "en este caso: son dos mecanismos de permisos completamente "
        "independientes. El síntoma es idéntico al de un problema de grupo — "
        "\"aparece la información del ROM y ahí se queda\" — así que es fácil "
        "confundirlos; el error real (\"Could not set the I/O privilege "
        "level\") solo se ve ejecutando uCON64 en una terminal directamente.",
        f"Dale a uCON64 el permiso específico que necesita, sin tener que "
        f"ejecutarlo entero como root cada vez:\n\n"
        f"    sudo setcap cap_sys_rawio+ep {ruta}\n\n"
        "O, más robusto a largo plazo: recompílalo con soporte ppdev "
        "(./configure --enable-ppdev), que no necesita privilegios especiales "
        "en absoluto — es probable que el paquete de tu distribución "
        "(\"sudo apt install ucon64\") ya venga así, a diferencia de una "
        "compilación manual."
    )


def _en_grupo_lp() -> Comprobacion:
    try:
        import grp
        gid_lp = grp.getgrnam("lp").gr_gid
    except (ImportError, KeyError):
        # ni siquiera existe el grupo "lp" en este sistema (algunas
        # distribuciones minimalistas no lo crean) — no hay nada que
        # comprobar ni corregir en ese caso.
        return Comprobacion("Permiso de grupo (lp)", True,
                            "Este sistema no usa el grupo \"lp\" para el acceso a puertos.")
    try:
        grupos_actuales = os.getgroups()
    except (AttributeError, OSError):
        return Comprobacion("Permiso de grupo (lp)", True, "No se pudo comprobar (no es Linux).")

    if gid_lp in grupos_actuales:
        return Comprobacion("Permiso de grupo (lp)", True,
                            "Tu usuario ya pertenece al grupo \"lp\", necesario para acceder al puerto paralelo.")
    return Comprobacion(
        "Permiso de grupo (lp)", False,
        "Tu usuario NO pertenece al grupo \"lp\". Sin esto, el sistema deniega el "
        "acceso al puerto paralelo en silencio: el programa de transferencia "
        "simplemente no hace nada visible, sin ningún mensaje de error.",
        "Ejecuta esto en una terminal, y CIERRA SESIÓN Y VUELVE A ENTRAR después "
        "(no basta con reiniciar el programa, hace falta una sesión nueva):\n\n"
        f"    sudo usermod -aG lp {os.environ.get('USER', '$USER')}"
    )


def _existe_dispositivo_parport() -> Comprobacion:
    candidatos = ["/dev/parport0", "/dev/parport1"]
    encontrados = [p for p in candidatos if os.path.exists(p)]
    if not encontrados:
        return Comprobacion(
            "Dispositivo de puerto paralelo", False,
            "No aparece ningún /dev/parport* en el sistema. Puede que el módulo del "
            "kernel no esté cargado, o que el equipo no tenga puerto paralelo real "
            "ni una tarjeta PCI/PCIe que lo añada.",
            "Si tienes una tarjeta PCI/PCIe de puerto paralelo, prueba a cargar el "
            "módulo del kernel manualmente:\n\n"
            "    sudo modprobe parport_pc\n\n"
            "Si sigue sin aparecer, comprueba que la tarjeta se detecta con \"lspci\"."
        )
    sin_permiso = [p for p in encontrados if not os.access(p, os.R_OK | os.W_OK)]
    if sin_permiso:
        return Comprobacion(
            "Dispositivo de puerto paralelo", False,
            f"Encontrado ({', '.join(encontrados)}), pero tu usuario no tiene permiso "
            f"de lectura/escritura sobre {', '.join(sin_permiso)} — esto suele ser "
            "justo lo que arregla pertenecer al grupo \"lp\" (ver la comprobación de "
            "arriba), pero puede seguir fallando si acabas de añadirte al grupo y "
            "todavía no has cerrado sesión.",
            "Comprueba primero la comprobación de \"Permiso de grupo (lp)\" de más "
            "arriba. Si ya perteneces al grupo y sigue sin funcionar, revisa los "
            f"permisos del propio archivo con:\n\n    ls -l {sin_permiso[0]}"
        )
    return Comprobacion(
        "Dispositivo de puerto paralelo", True,
        f"Encontrado y accesible: {', '.join(encontrados)}.")


def _cups_ocupa_el_puerto() -> Comprobacion:
    lpstat = shutil.which("lpstat")
    if not lpstat:
        return Comprobacion(
            "Impresoras CUPS en el puerto paralelo", True,
            "CUPS (el sistema de impresión) no está instalado — no puede haber conflicto.")
    try:
        resultado = subprocess.run([lpstat, "-v"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return Comprobacion(
            "Impresoras CUPS en el puerto paralelo", True,
            "No se pudo consultar CUPS (no es necesariamente un problema).")

    salida = resultado.stdout.lower()
    lineas_conflicto = [
        linea for linea in salida.splitlines()
        if "parallel" in linea or "/dev/lp" in linea or "/dev/parport" in linea
    ]
    if not lineas_conflicto:
        return Comprobacion(
            "Impresoras CUPS en el puerto paralelo", True,
            "Ninguna impresora de CUPS está configurada sobre el puerto paralelo.")
    return Comprobacion(
        "Impresoras CUPS en el puerto paralelo", False,
        "Hay al menos una impresora configurada en CUPS usando el puerto paralelo "
        "o /dev/lp*. Si es así, CUPS puede tener el dispositivo reservado para sí "
        "mismo, impidiendo que uCON64 acceda a él aunque tengas los permisos "
        "correctos:\n" + "\n".join(f"    {l.strip()}" for l in lineas_conflicto),
        "Si no usas esa impresora (es habitual dejarla configurada de fábrica sin "
        "haberla usado nunca), puedes eliminarla desde la configuración de "
        "impresoras del sistema, o por terminal averiguando su nombre con "
        "\"lpstat -v\" y luego:\n\n"
        "    sudo lpadmin -x NOMBRE_DE_LA_IMPRESORA"
    )


def _ucon64_disponible() -> Comprobacion:
    ruta = shutil.which("ucon64")
    if ruta:
        return Comprobacion("uCON64 instalado", True, f"Encontrado en: {ruta}")
    return Comprobacion(
        "uCON64 instalado", False,
        "No se encuentra \"ucon64\" en el PATH del sistema.",
        "Instálalo desde el gestor de paquetes de tu distribución (por ejemplo, "
        "\"sudo apt install ucon64\" en Debian/Ubuntu/Mint), o indica su ruta "
        "manualmente en el campo correspondiente del diálogo de transferencia."
    )


def ejecutar_accion(accion_id: str) -> tuple[bool, str]:
    """Ejecuta la acción rápida asociada a una comprobación fallida,
    pidiendo la contraseña gráficamente vía pkexec (polkit) en vez de
    obligar al usuario a abrir una terminal para un comando de una sola
    línea. Devuelve (éxito, mensaje) para que la interfaz lo muestre.
    """
    if accion_id == "descargar_modulo_lp":
        pkexec = shutil.which("pkexec")
        if not pkexec:
            return False, (
                "No se encontró \"pkexec\" en este sistema (forma parte de "
                "polkit, normalmente ya instalado en cualquier escritorio Linux "
                "moderno) — descárgalo manualmente desde una terminal:\n\n"
                "    sudo rmmod lp"
            )
        try:
            resultado = subprocess.run(
                [pkexec, "rmmod", "lp"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False, "La operación no respondió a tiempo — pruébalo desde una terminal."
        if resultado.returncode == 0:
            return True, "Módulo \"lp\" descargado correctamente."
        # Aquí caen tanto "el usuario canceló el diálogo de contraseña" como
        # "el módulo está en uso por otro proceso" — pkexec no distingue
        # ambos casos con un código de salida propio, así que se muestra
        # el mensaje tal cual lo dé rmmod/pkexec.
        detalle = resultado.stderr.strip() or "operación cancelada o el módulo está en uso"
        return False, f"No se pudo descargar el módulo: {detalle}"

    return False, f"Acción desconocida: {accion_id!r}"


def diagnosticar() -> DiagnosticoPuertoParalelo:
    """Ejecuta todas las comprobaciones y devuelve el resultado conjunto.

    Solo tiene sentido en Linux: en Windows los problemas de transferencia
    por puerto paralelo son de otra naturaleza por completo (drivers de
    terceros, chipsets concretos — ver los avisos ya existentes en
    transfer_dialog.py), no de permisos de grupo ni de CUPS.
    """
    return DiagnosticoPuertoParalelo(comprobaciones=[
        _en_grupo_lp(),
        _modulo_lp_cargado(),
        _existe_dispositivo_parport(),
        _cups_ocupa_el_puerto(),
        _ucon64_disponible(),
        _ucon64_necesita_root(),
        _probar_apertura_real(),
    ])
