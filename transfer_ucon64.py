"""Frontend de uCON64 para transferir ROMs por el puerto paralelo a copiones
de época: Super Wild Card (SNES) y Super Magic Drive (Mega Drive).

Por qué envolver uCON64 en vez de reimplementar el protocolo
-------------------------------------------------------------
El handshake de los copiones FFE (Super Wild Card, Super Magic Drive y
familia) es un bucle byte a byte con temporización estricta sobre las
líneas de datos/estado del puerto paralelo. uCON64 lo implementa en C con
acceso directo a los registros del puerto. Reimplementarlo en Python sobre
ppdev supondría varias llamadas al kernel por cada byte -decenas de
millones para una ROM de 4 MB-, con el riesgo añadido de romper la
temporización que espera el hardware. Envolver la herramienta de
referencia es más rápido y mucho más seguro para el copión.

Este módulo NO ejecuta nada por sí mismo: solo localiza el binario,
construye la línea de comandos y valida las condiciones previas. La
ejecución la hace la interfaz con QProcess, para poder mostrar la salida
en tiempo real.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass


# Opciones de transferencia de uCON64 por copión.
# Verificadas contra la documentación oficial de uCON64 (readme/FAQ):
#   --xswc  envía/recibe ROM a/de Super Wild Card y compatibles
#   --xsmd  envía/recibe ROM a/de Super Magic Drive
# En ambos casos, uCON64 recibe automáticamente (vuelca el cartucho) cuando
# el archivo indicado no existe, y envía cuando sí existe.
@dataclass(frozen=True)
class CopierProfile:
    key: str
    label: str
    system: str
    rom_option: str          # opción para ROM
    sram_option: str | None  # opción para SRAM, si existe
    extensions: tuple[str, ...]
    notes: str


COPIERS: tuple[CopierProfile, ...] = (
    CopierProfile(
        key="swc",
        label="Super Wild Card / Super Magicom (SNES)",
        system="snes",
        rom_option="--xswc",
        sram_option="--xswcs",
        extensions=(".swc", ".sfc", ".smc", ".fig"),
        notes=(
            "uCON64 usa la información de la cabecera del volcado al enviarlo, así que "
            "conviene que la cabecera sea correcta. Si el archivo está entrelazado, "
            "conviértelo antes a formato Super Wild Card (desentrelazado)."
        ),
    ),
    CopierProfile(
        key="smd",
        label="Super Magic Drive (Mega Drive / Genesis)",
        system="genesis",
        rom_option="--xsmd",
        sram_option="--xsmds",
        extensions=(".smd", ".bin", ".md", ".gen"),
        notes=(
            "El Super Magic Drive espera el formato entrelazado propio de SMD. "
            "Si tu volcado está en formato plano (.bin), conviértelo antes."
        ),
    ),
)


def copier_by_key(key: str) -> CopierProfile:
    for c in COPIERS:
        if c.key == key:
            return c
    raise KeyError(f"copión desconocido: {key}")


def _app_base_dir() -> str:
    """Carpeta base de la app: la del ejecutable si PyInstaller la ha
    empaquetado (sys._MEIPASS), o la del propio script en ejecución
    normal. Mismo criterio que main.py — duplicado aquí en vez de
    importado para no crear una dependencia circular entre módulos."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


def find_ucon64(explicit_path: str | None = None) -> str | None:
    """Localiza el ejecutable de uCON64. Devuelve la ruta o None."""
    if explicit_path:
        if os.path.isfile(explicit_path) and os.access(explicit_path, os.X_OK):
            return explicit_path
        return None
    # Prioridad máxima: la copia que trae la propia carpeta de ASTURCONSOLE
    # (carpeta "ucon64" junto al ejecutable/script). Es la que se sabe que
    # lleva aplicados los parches de esta app — el retardo real entre
    # bloques que hace falta en hardware PCIe moderno, N_TRY_MAX ajustado,
    # y el reset del puerto al cerrar — así que se prefiere sobre
    # cualquier otra copia que el sistema pudiera tener instalada por su
    # cuenta, sin esos parches.
    base = _app_base_dir()
    for nombre in ("ucon64.exe", "ucon64"):
        candidato = os.path.join(base, "ucon64", nombre)
        if not os.path.isfile(candidato):
            continue
        if os.name != "nt" and not os.access(candidato, os.X_OK):
            # PyInstaller extrae los "datas" empaquetados a una carpeta
            # temporal en cada arranque (sys._MEIPASS) y no siempre
            # conserva el bit ejecutable original del archivo — se
            # restaura aquí mismo en vez de dejar que find_ucon64
            # simplemente no lo encuentre.
            try:
                os.chmod(candidato, 0o755)
            except OSError:
                pass
        if os.access(candidato, os.X_OK):
            return candidato
    for name in ("ucon64", "ucon64.exe"):
        found = shutil.which(name)
        if found:
            return found
    # Rutas habituales de instalación manual
    for candidate in ("/usr/local/bin/ucon64", "/usr/bin/ucon64",
                      os.path.expanduser("~/bin/ucon64")):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def list_parallel_devices() -> list[str]:
    """Dispositivos ppdev presentes en el sistema (Linux)."""
    found = []
    for i in range(4):
        dev = f"/dev/parport{i}"
        if os.path.exists(dev):
            found.append(dev)
    return found


@dataclass
class PreflightResult:
    ok: bool
    errors: list[str]
    warnings: list[str]


def preflight(ucon64_path: str | None, rom_path: str | None,
              copier: CopierProfile, port: str | None,
              sending: bool = True) -> PreflightResult:
    """Comprobaciones previas a lanzar la transferencia."""
    errors: list[str] = []
    warnings: list[str] = []

    if not ucon64_path:
        errors.append(
            "No se encontró el ejecutable de uCON64. Instálalo o indica su ruta "
            "manualmente."
        )

    if sending:
        if not rom_path:
            errors.append("No has elegido ningún archivo de ROM para enviar.")
        elif not os.path.isfile(rom_path):
            errors.append(f"El archivo no existe: {rom_path}")
        else:
            ext = os.path.splitext(rom_path)[1].lower()
            if ext not in copier.extensions:
                warnings.append(
                    f"La extensión '{ext}' no es una de las habituales para este copión "
                    f"({', '.join(copier.extensions)}). Comprueba que el formato sea el correcto."
                )
            size = os.path.getsize(rom_path)
            if size == 0:
                errors.append("El archivo está vacío.")
    else:
        if rom_path and os.path.exists(rom_path):
            errors.append(
                "Para volcar (recibir) el cartucho, el archivo de destino NO debe existir: "
                "uCON64 decide entre enviar y recibir según exista o no. Elige otro nombre."
            )

    # Puerto: la comprobación de permisos se hace sobre TODOS los
    # /dev/parportN disponibles, no solo si el usuario eligió uno a mano
    # explícitamente — el valor por defecto del selector es "(automático)"
    # (port=None), el caso más habitual, y antes esa comprobación se
    # saltaba por completo en ese caso: el aviso de "añade tu usuario al
    # grupo lp" solo aparecía si ya habías seleccionado el dispositivo
    # exacto a mano, precisamente cuando menos falta hacía.
    if port and port.startswith("/dev/"):
        if not os.path.exists(port):
            errors.append(f"El dispositivo {port} no existe.")
        elif not os.access(port, os.R_OK | os.W_OK):
            warnings.append(
                f"Sin permisos de lectura/escritura sobre {port}. Añade tu usuario al grupo "
                "'lp' (sudo usermod -aG lp $USER, y vuelve a iniciar sesión) o ejecuta como root."
            )
    elif os.name == "posix" and not (port or "").startswith("0x"):
        dispositivos = list_parallel_devices()
        sin_permiso = [d for d in dispositivos if not os.access(d, os.R_OK | os.W_OK)]
        if sin_permiso:
            warnings.append(
                f"Sin permisos de lectura/escritura sobre {', '.join(sin_permiso)}. Añade tu "
                "usuario al grupo 'lp' (sudo usermod -aG lp $USER, y vuelve a iniciar sesión "
                "por completo — cerrar y volver a abrir sesión, no solo la terminal) o "
                "ejecuta como root."
            )
        elif not dispositivos:
            warnings.append(
                "No se detecta ningún /dev/parportN. Puede que falte cargar los módulos del "
                "kernel (sudo modprobe ppdev parport_pc) o que el equipo no tenga puerto "
                "paralelo real."
            )

    # El módulo "lp" del kernel (el driver clásico para impresoras
    # paralelas) puede tomar el puerto en modo exclusivo y dejarlo
    # ocupado para "ppdev", que es el que necesita uCON64 para el acceso
    # genérico al hardware que exige el protocolo del copión — ambos
    # compiten por el mismo dispositivo físico. Si está cargado, es una
    # causa muy probable de que la transferencia no haga nada en
    # absoluto sin ningún error visible.
    if os.name == "posix" and list_parallel_devices():
        try:
            with open("/proc/modules") as fh:
                modulos_cargados = fh.read()
            if re.search(r"^lp\s", modulos_cargados, re.MULTILINE):
                warnings.append(
                    "El módulo 'lp' del kernel está cargado y puede estar ocupando el "
                    "puerto paralelo en exclusiva (el driver clásico de impresoras "
                    "compite por el mismo hardware que necesita uCON64). Prueba a "
                    "descargarlo con: sudo rmmod lp"
                )
        except OSError:
            pass  # /proc/modules no disponible (poco común, no es motivo de error aquí)

    return PreflightResult(ok=not errors, errors=errors, warnings=warnings)


def build_command(ucon64_path: str, copier: CopierProfile, target_path: str,
                  port: str | None = None, sram: bool = False,
                  extra_args: list[str] | None = None) -> list[str]:
    """Construye la línea de comandos de uCON64 para la transferencia."""
    option = copier.sram_option if sram else copier.rom_option
    if option is None:
        raise ValueError("este copión no tiene opción de SRAM configurada")

    # El orden importa en la build de Windows (MinGW): con --frontend
    # DESPUÉS del nombre de archivo, uCON64 falla con "Cannot open ""
    # for writing" — un bug de parseo de argumentos específico de esa
    # build, confirmado con hardware real. Poniendo todas las opciones
    # ANTES del archivo (el propio archivo siempre al final) funciona
    # igual de bien en Linux y evita el problema en Windows.
    # --frontend solo tiene sentido cuando algo interpreta esa salida
    # programáticamente (el "%\n" puro que imprime en vez de la barra
    # ASCII decorativa) — es justo lo que hace _procesar_texto() en
    # Linux. En Windows la salida de uCON64 no se captura en absoluto
    # (ver _start(): consola propia, sin redirección) y la ve el usuario
    # directamente, así que --frontend solo produciría números sueltos y
    # feos en pantalla en vez de la barra "\r[====----] NN% NN KB/s" que
    # uCON64 ya dibuja por su cuenta cuando no se le pide --frontend.
    cmd = [ucon64_path, option]
    if os.name != "nt":
        cmd.append("--frontend")
    if port:
        cmd.append(f"--port={port}")
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(target_path)

    if os.name != "nt":
        # En Linux, cuando la salida estándar de un programa en C no está
        # conectada a una terminal real sino a un pipe (que es justo lo
        # que hace QProcess para poder leerla), la librería de E/S estándar
        # cambia de buffering "por línea" a buffering "completo": los
        # mensajes se acumulan en un buffer interno en vez de enviarse al
        # momento. Si uCON64 llega a bloquearse esperando el puerto
        # paralelo (el puerto ocupado, sin los permisos correctos...) SIN
        # terminar el proceso, cualquier mensaje de error que hubiera
        # escrito justo antes de bloquearse se queda atrapado en ese
        # buffer para siempre — nunca llega a la consola de la interfaz,
        # aunque uCON64 sí lo haya "impreso" por su parte. "stdbuf" (de
        # GNU coreutils, ya presente en cualquier Linux de escritorio
        # habitual) fuerza el buffering por línea aunque la salida vaya a
        # un pipe, para que estos mensajes no se pierdan nunca.
        stdbuf = shutil.which("stdbuf")
        if stdbuf:
            cmd = [stdbuf, "-oL", "-eL"] + cmd

    return cmd


HARDWARE_NOTICE = (
    "Requisitos de hardware para la transferencia por puerto paralelo:\n"
    "\n"
    "• Hace falta un puerto paralelo REAL (integrado en la placa o tarjeta PCI/PCIe). "
    "Los adaptadores USB→paralelo NO funcionan: son dispositivos de clase impresora y "
    "no permiten el control a nivel de bit que exige el protocolo del copión.\n"
    "• Se necesita un cable paralelo bidireccional estándar.\n"
    "• En Linux, el acceso a /dev/parportN requiere pertenecer al grupo 'lp' "
    "(o ejecutar como root) y tener cargados los módulos 'ppdev' y 'parport_pc'.\n"
    "• Enciende el copión ANTES de iniciar la transferencia."
)
