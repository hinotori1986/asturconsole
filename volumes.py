"""Detección de volúmenes del sistema y montaje de dispositivos extraíbles.

Un dispositivo USB conectado pero SIN montar no se puede explorar: sus
archivos no son visibles para el sistema de archivos hasta montarlo. Por
eso este módulo hace dos cosas:

  1. Lista los volúmenes ya montados (para acceso rápido).
  2. Detecta particiones presentes pero sin montar, y permite montarlas
     mediante `udisksctl`, que en un escritorio Linux normal funciona sin
     privilegios de root (udisks2 + polkit conceden el permiso al usuario
     de la sesión activa para dispositivos extraíbles).

Si `udisksctl` no está disponible, se informa de ello y se sugiere el
comando manual, en vez de intentar montar por medios que exigirían root.
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import time
from dataclasses import dataclass

# En Windows, un dispositivo conectado siempre aparece con letra de unidad
# asignada automáticamente por el propio sistema operativo: no existe ahí el
# concepto de "conectado pero sin montar" que sí aplica en Linux (donde un
# USB puede estar enchufado sin que nadie lo haya montado todavía). Por eso
# las funciones de este módulo se bifurcan según la plataforma.
IS_WINDOWS = sys.platform.startswith("win")

# Puntos de montaje internos del sistema que no interesa mostrar
_HIDDEN_PREFIXES = (
    "/proc", "/sys", "/dev", "/run", "/snap", "/var/lib", "/var/snap",
    "/boot/efi", "/tmp",
)


@dataclass
class Volume:
    path: str            # dispositivo (/dev/sdb1) o "" si no aplica
    mountpoint: str | None
    label: str
    size: str
    fstype: str
    removable: bool

    @property
    def mounted(self) -> bool:
        return bool(self.mountpoint)

    def display_name(self) -> str:
        nombre = self.label or (os.path.basename(self.mountpoint) if self.mountpoint else "")
        if not nombre:
            nombre = self.path or "(sin nombre)"
        partes = [nombre]
        if self.size:
            partes.append(self.size)
        if self.fstype:
            partes.append(self.fstype)
        etiqueta = "  ·  ".join(partes)
        if self.removable:
            etiqueta = "🔌  " + etiqueta
        return etiqueta


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"no se encontró el comando: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "tiempo de espera agotado"


def _fmt_bytes_simple(n: float) -> str:
    for unidad in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f}{unidad}" if unidad == "B" else f"{n:.1f}{unidad}"
        n /= 1024
    return f"{n:.1f}PB"


# DRIVE_UNKNOWN=0 DRIVE_NO_ROOT_DIR=1 DRIVE_REMOVABLE=2 DRIVE_FIXED=3
# DRIVE_REMOTE=4 DRIVE_CDROM=5 DRIVE_RAMDISK=6  (constantes de GetDriveTypeW)
_WIN_DRIVE_TYPES = {
    2: ("extraíble", True),
    3: ("disco", False),
    4: ("unidad de red", False),
    5: ("CD/DVD", True),
    6: ("disco RAM", False),
}


def _list_windows_drives() -> list[Volume]:
    """Unidades lógicas de Windows (C:, D:, E:...) vía la API de kernel32.

    No depende de pywin32 ni de ninguna librería externa (para no complicar
    el empaquetado con PyInstaller): usa ctypes directamente contra
    kernel32.dll, que está disponible en cualquier Windows.

    Nota: esta función solo puede probarse de verdad en una máquina Windows
    real; aquí se ha verificado la lógica y el manejo de errores, pero no
    la ejecución contra la API real.
    """
    import ctypes
    import string

    salida: list[Volume] = []
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        bitmask = kernel32.GetLogicalDrives()
    except (AttributeError, OSError):
        return salida

    for i, letra in enumerate(string.ascii_uppercase):
        if not (bitmask & (1 << i)):
            continue
        raiz = f"{letra}:\\"
        try:
            tipo = kernel32.GetDriveTypeW(ctypes.c_wchar_p(raiz))
        except OSError:
            continue

        # DRIVE_UNKNOWN (0) y DRIVE_NO_ROOT_DIR (1, letra reservada pero sin
        # medio, como un lector de tarjetas vacío): no hay nada que explorar.
        if tipo in (0, 1):
            continue
        nombre_tipo, removable = _WIN_DRIVE_TYPES.get(tipo, ("", False))

        etiqueta, fstype = "", ""
        info_leida = False
        try:
            buf_etq = ctypes.create_unicode_buffer(261)
            buf_fs = ctypes.create_unicode_buffer(261)
            ok = kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(raiz), buf_etq, 261,
                None, None, None, buf_fs, 261)
            if ok:
                etiqueta, fstype = buf_etq.value, buf_fs.value
                info_leida = True
        except OSError:
            pass

        size = ""
        try:
            libres = ctypes.c_ulonglong(0)
            total = ctypes.c_ulonglong(0)
            ok = kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(raiz), None,
                ctypes.byref(total), ctypes.byref(libres))
            if ok and total.value:
                size = _fmt_bytes_simple(float(total.value))
                info_leida = True
        except OSError:
            pass

        # Un lector de CD/DVD o una ranura de tarjeta SIN MEDIO insertado
        # sigue reportando su tipo de unidad (eso no depende de si hay disco
        # dentro), pero no se puede leer ni etiqueta ni tamaño: se omite en
        # vez de mostrar una entrada fantasma en la que no hay nada que
        # explorar. Un disco fijo o de red, en cambio, se mantiene aunque
        # por lo que sea no se haya podido leer su información.
        if not info_leida and tipo in (2, 5):
            continue

        salida.append(Volume(
            path=raiz, mountpoint=raiz,
            label=etiqueta or nombre_tipo or letra,
            size=size, fstype=fstype, removable=removable,
        ))
    return salida


def list_volumes() -> tuple[list[Volume], list[Volume]]:
    """Devuelve (montados, sin_montar).

    'montados' incluye la carpeta personal y los volúmenes de datos
    relevantes; 'sin_montar' son particiones con sistema de archivos
    detectado que todavía no están montadas (típicamente un USB recién
    conectado en un equipo sin automontaje).

    En Windows esto es más simple: cualquier unidad con letra asignada ya
    es accesible, así que 'sin_montar' siempre queda vacía ahí.
    """
    if IS_WINDOWS:
        return _list_windows_drives(), []

    montados: list[Volume] = []
    sin_montar: list[Volume] = []

    if not shutil.which("lsblk"):
        return montados, sin_montar

    code, out, _err = _run([
        "lsblk", "-J", "-o", "PATH,SIZE,TYPE,MOUNTPOINT,LABEL,RM,FSTYPE,HOTPLUG",
    ])
    if code != 0 or not out.strip():
        return montados, sin_montar

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return montados, sin_montar

    def walk(nodes):
        for n in nodes:
            tipo = n.get("type")
            fstype = n.get("fstype") or ""
            mp = n.get("mountpoint")
            removable = bool(n.get("rm")) or bool(n.get("hotplug"))

            if tipo in ("part", "disk", "rom", "lvm", "crypt"):
                vol = Volume(
                    path=n.get("path") or "",
                    mountpoint=mp,
                    label=n.get("label") or "",
                    size=n.get("size") or "",
                    fstype=fstype,
                    removable=removable,
                )
                if mp:
                    if not any(mp.startswith(p) for p in _HIDDEN_PREFIXES):
                        montados.append(vol)
                elif fstype and fstype not in ("swap", "LVM2_member", "crypto_LUKS"):
                    sin_montar.append(vol)

            if n.get("children"):
                walk(n["children"])

    walk(data.get("blockdevices", []))
    return montados, sin_montar


def home_volumes() -> list[Volume]:
    """Atajos siempre útiles: carpeta personal y ubicaciones habituales."""
    if IS_WINDOWS:
        salida: list[Volume] = []
        home = os.path.expanduser("~")
        salida.append(Volume(path="", mountpoint=home, label="Carpeta personal",
                              size="", fstype="", removable=False))
        for sub in ("Desktop", "Escritorio", "Downloads", "Descargas",
                    "Documents", "Documentos"):
            p = os.path.join(home, sub)
            if os.path.isdir(p):
                salida.append(Volume(path="", mountpoint=p, label=sub,
                                      size="", fstype="", removable=False))
        vistos, unicos = set(), []
        for v in salida:
            if v.mountpoint not in vistos:
                vistos.add(v.mountpoint)
                unicos.append(v)
        return unicos

    salida = []
    home = os.path.expanduser("~")
    salida.append(Volume(path="", mountpoint=home, label="Carpeta personal",
                          size="", fstype="", removable=False))
    for sub in ("Descargas", "Downloads", "Escritorio", "Desktop", "Documentos", "Documents"):
        p = os.path.join(home, sub)
        if os.path.isdir(p):
            salida.append(Volume(path="", mountpoint=p, label=sub,
                                  size="", fstype="", removable=False))
    # Puntos de montaje habituales de medios extraíbles
    user = os.path.basename(home)
    for base in (f"/media/{user}", "/media", "/mnt", "/run/media/" + user):
        if os.path.isdir(base):
            try:
                for entry in sorted(os.listdir(base)):
                    p = os.path.join(base, entry)
                    if os.path.isdir(p) and os.path.ismount(p):
                        salida.append(Volume(path="", mountpoint=p, label=entry,
                                              size="", fstype="", removable=True))
            except OSError:
                pass
    # eliminar duplicados conservando el orden
    vistos, unicos = set(), []
    for v in salida:
        if v.mountpoint not in vistos:
            vistos.add(v.mountpoint)
            unicos.append(v)
    return unicos


def can_mount() -> bool:
    if IS_WINDOWS:
        # Nunca hace falta: Windows asigna letra de unidad automáticamente a
        # cualquier dispositivo en cuanto se conecta.
        return False
    return shutil.which("udisksctl") is not None


def mount_device(device_path: str) -> tuple[bool, str]:
    """Monta un dispositivo con udisksctl (sin root en un escritorio normal).

    Devuelve (éxito, mensaje). Si tiene éxito, el mensaje es el punto de
    montaje resultante.
    """
    if IS_WINDOWS:
        return False, (
            "En Windows no hace falta montar nada: cualquier dispositivo conectado "
            "ya aparece con su letra de unidad asignada automáticamente."
        )
    if not can_mount():
        return False, (
            "No se encontró 'udisksctl' (paquete udisks2), necesario para montar el "
            "dispositivo sin privilegios de root.\n\n"
            f"Puedes montarlo manualmente y volver a intentarlo:\n"
            f"    sudo mount {device_path} /mnt"
        )

    code, out, err = _run(["udisksctl", "mount", "-b", device_path], timeout=30)
    salida = (out + err).strip()

    if code == 0:
        # Formato típico: "Mounted /dev/sdb1 at /media/user/ETIQUETA"
        marcador = " at "
        if marcador in out:
            punto = out.split(marcador, 1)[1].strip().rstrip(".")
            if os.path.isdir(punto):
                return True, punto
        # Si no se pudo extraer del texto, se vuelve a consultar a lsblk
        montados, _ = list_volumes()
        for v in montados:
            if v.path == device_path and v.mountpoint:
                return True, v.mountpoint
        return True, salida or "montado"

    if "already mounted" in salida.lower():
        montados, _ = list_volumes()
        for v in montados:
            if v.path == device_path and v.mountpoint:
                return True, v.mountpoint

    return False, salida or f"no se pudo montar {device_path}"


# ---------------------------------------------------------------------------
# Escritura de imágenes en unidades físicas
# ---------------------------------------------------------------------------
# Grabar una imagen en un dispositivo de bloque SOBRESCRIBE TODO su contenido.
# Por eso aquí solo se ofrecen dispositivos extraíbles (disqueteras USB,
# lectores de disquete, memorias USB) y nunca discos internos, y la interfaz
# exige una confirmación explícita antes de escribir.

# Tamaños máximos admitidos como destino, en bytes. Sirve de red de seguridad:
# una imagen de disquete no debería escribirse jamás en un disco de gran
# capacidad, así que los dispositivos grandes se marcan como peligrosos.
SAFE_TARGET_MAX_BYTES = 4 * 1024 * 1024 * 1024   # 4 GB


@dataclass
class WriteTarget:
    path: str            # /dev/sdb, /dev/fd0
    size_bytes: int
    size_label: str
    model: str
    removable: bool
    mountpoints: list

    @property
    def is_floppy(self) -> bool:
        return "/dev/fd" in self.path or "Floppy" in self.path or self.path in ("A:\\", "B:\\")

    @property
    def looks_safe(self) -> bool:
        """Extraíble o disquetera, y de tamaño razonable para una imagen."""
        if self.is_floppy:
            return True
        return self.removable and 0 < self.size_bytes <= SAFE_TARGET_MAX_BYTES

    def describe(self) -> str:
        partes = [self.path, self.size_label]
        if self.model:
            partes.append(self.model)
        if self.is_floppy:
            partes.append("disquetera")
        elif self.removable:
            partes.append("extraíble")
        return "  ·  ".join(p for p in partes if p)


def _parse_size(texto: str) -> int:
    """Convierte '1.4M', '720K', '8G' a bytes."""
    if not texto:
        return 0
    texto = texto.strip().upper()
    mult = 1
    if texto and texto[-1] in "KMGTB":
        sufijo = texto[-1]
        mult = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}[sufijo]
        texto = texto[:-1]
    try:
        return int(float(texto) * mult)
    except ValueError:
        return 0


def _windows_run_powershell(script: str, timeout: int = 15) -> str:
    """Ejecuta un script corto de PowerShell y devuelve su salida."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _list_windows_physical_disks() -> list:
    """Discos físicos de Windows (\\\\.\\PhysicalDriveN) para grabar imágenes.

    La enumeración usa WMI a través de PowerShell (Get-CimInstance) en vez
    de reimplementar con ctypes los IOCTL de bajo nivel de Windows
    (IOCTL_STORAGE_GET_DEVICE_NUMBER, IOCTL_STORAGE_QUERY_PROPERTY...): esos
    IOCTL trabajan con estructuras C de tamaño variable que son frágiles de
    portar sin poder probarlas contra Windows real, mientras que WMI ya
    expone modelo, tamaño e interfaz (USB/SATA/...) de forma estructurada y
    estable desde hace muchas versiones de Windows.

    La ESCRITURA en sí (write_image_to_device) sí usa CreateFileW/WriteFile
    vía ctypes directamente, porque ahí hace falta control total del
    proceso (progreso, errores concretos), que un script externo no da con
    la misma fidelidad.
    """
    script = (
        "Get-CimInstance Win32_DiskDrive | "
        "Select-Object Index,Model,Size,InterfaceType,MediaType | "
        "ConvertTo-Json -Compress"
    )
    texto = _windows_run_powershell(script)
    if not texto.strip():
        return []
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        return []
    if isinstance(datos, dict):
        datos = [datos]

    salida = []
    for disco in datos:
        try:
            indice = int(disco.get("Index"))
        except (TypeError, ValueError):
            continue
        tam = int(disco.get("Size") or 0)
        interfaz = (disco.get("InterfaceType") or "").upper()
        media = (disco.get("MediaType") or "").lower()
        # USB es casi siempre extraíble; los discos internos (SATA/NVMe/SCSI)
        # casi nunca lo son. Si WMI ya indica "removable media" explícitamente
        # en MediaType, se respeta directamente.
        removable = interfaz == "USB" or "removable" in media
        salida.append(WriteTarget(
            path=f"\\\\.\\PhysicalDrive{indice}",
            size_bytes=tam,
            size_label=_fmt_bytes_simple(float(tam)) if tam else "",
            model=(disco.get("Model") or "").strip(),
            removable=removable,
            mountpoints=[],
        ))
    return salida


def _windows_write_image(image_path: str, device_path: str) -> tuple[bool, str]:
    """Escribe una imagen sobre un disco físico de Windows a bajo nivel.

    Usa CreateFileW/WriteFile de kernel32 vía ctypes: es el único camino
    para escribir bytes en crudo sobre un dispositivo en Windows, no hay
    equivalente a abrir /dev/sdX como archivo normal.

    Limitación conocida y no resuelta aquí: no se bloquea/desmonta el
    volumen antes de escribir (FSCTL_LOCK_VOLUME / FSCTL_DISMOUNT_VOLUME).
    Si Windows tiene el disco en uso, la escritura puede fallar; en ese caso
    el mensaje de error lo indica y sugiere cerrar el Explorador de
    archivos o desconectar y reconectar la unidad antes de reintentar.

    Casi siempre requiere ejecutar la aplicación como Administrador: a
    diferencia de udisks2/polkit en Linux, Windows no tiene un mecanismo
    estándar para conceder este permiso a un usuario normal.
    """
    import ctypes
    from ctypes import wintypes

    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]

    handle = kernel32.CreateFileW(
        device_path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, 0, None,
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        codigo = ctypes.get_last_error()
        return False, (
            f"No se pudo abrir {device_path} (código de error de Windows: {codigo}).\n\n"
            "Casi siempre es un problema de permisos: ejecuta asturconsole como "
            "Administrador (clic derecho → 'Ejecutar como administrador') e "
            "inténtalo de nuevo."
        )

    try:
        with open(image_path, "rb") as fh:
            total = 0
            while True:
                bloque = fh.read(1024 * 1024)
                if not bloque:
                    break
                escritos = wintypes.DWORD(0)
                ok = kernel32.WriteFile(
                    handle, bloque, len(bloque), ctypes.byref(escritos), None)
                if not ok or escritos.value != len(bloque):
                    codigo = ctypes.get_last_error()
                    return False, (
                        f"Error al escribir en {device_path} tras {total} bytes "
                        f"(código de Windows: {codigo}). El disco puede estar en uso: "
                        "cierra cualquier ventana del Explorador que lo tenga abierto "
                        "y vuelve a intentarlo."
                    )
                total += escritos.value
        return True, "escritura completada"
    except OSError as e:
        return False, f"error leyendo la imagen: {e}"
    finally:
        kernel32.CloseHandle(handle)


def list_write_targets() -> list:
    """Dispositivos donde se podría grabar una imagen.

    Solo devuelve discos completos (no particiones) y, por seguridad, marca
    los que no parecen extraíbles para que la interfaz los desaconseje.
    """
    if IS_WINDOWS:
        salida = _list_windows_physical_disks()
        # Las disqueteras físicas (si las hay) también son destinos válidos
        for dev in list_floppy_drives():
            if not any(t.path == dev for t in salida):
                salida.append(WriteTarget(dev, 1474560, "1.4M", "disquetera",
                                          True, []))
        return salida

    salida = []
    if not shutil.which("lsblk"):
        return salida

    code, out, _err = _run([
        "lsblk", "-J", "-d", "-o", "PATH,SIZE,TYPE,RM,HOTPLUG,MODEL,MOUNTPOINT",
    ])
    if code != 0 or not out.strip():
        return salida
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return salida

    for n in data.get("blockdevices", []):
        if n.get("type") != "disk":
            continue
        path = n.get("path") or ""
        if not path:
            continue
        removable = bool(n.get("rm")) or bool(n.get("hotplug"))
        size_label = n.get("size") or ""
        salida.append(WriteTarget(
            path=path,
            size_bytes=_parse_size(size_label),
            size_label=size_label,
            model=(n.get("model") or "").strip(),
            removable=removable,
            mountpoints=mountpoints_of(path),
        ))

    # Disqueteras clásicas, que lsblk no siempre lista. Se añaden también los
    # nodos con geometría explícita (u720, u360): son los que hay que usar para
    # escribir un disquete de 720 o 360 KB en una unidad de 1.44 MB, ya que el
    # nodo genérico asume 1.44 y produciría un disco ilegible.
    for i in range(2):
        dev = f"/dev/fd{i}"
        if os.path.exists(dev) and not any(t.path == dev for t in salida):
            salida.append(WriteTarget(dev, 1474560, "1.4M", "disquetera", True, []))
        for sufijo, tam, etiqueta in (("u720", 737280, "720K"), ("u360", 368640, "360K")):
            nodo = f"{dev}{sufijo}"
            if os.path.exists(nodo) and not any(t.path == nodo for t in salida):
                salida.append(WriteTarget(
                    nodo, tam, etiqueta, f"disquetera {etiqueta}", True, []))

    return salida


def mountpoints_of(device_path: str) -> list:
    """Puntos de montaje del dispositivo y de sus particiones."""
    if not shutil.which("lsblk"):
        return []
    code, out, _err = _run(["lsblk", "-J", "-o", "PATH,MOUNTPOINT", device_path])
    if code != 0:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    puntos = []

    def walk(nodes):
        for n in nodes:
            mp = n.get("mountpoint")
            if mp:
                puntos.append(mp)
            if n.get("children"):
                walk(n["children"])

    walk(data.get("blockdevices", []))
    return puntos


def unmount_device(device_path: str) -> tuple[bool, str]:
    """Desmonta el dispositivo y sus particiones antes de escribir en crudo."""
    if not can_mount():
        return False, "no se encontró 'udisksctl' para desmontar"
    errores = []
    code, out, err = _run(["lsblk", "-J", "-o", "PATH,MOUNTPOINT", device_path])
    objetivos = [device_path]
    try:
        data = json.loads(out)

        def walk(nodes):
            for n in nodes:
                if n.get("mountpoint"):
                    objetivos.append(n.get("path"))
                if n.get("children"):
                    walk(n["children"])
        walk(data.get("blockdevices", []))
    except (json.JSONDecodeError, TypeError):
        pass

    for destino in dict.fromkeys(objetivos):
        c, o, e = _run(["udisksctl", "unmount", "-b", destino], timeout=20)
        salida = (o + e).lower()
        if c != 0 and "not mounted" not in salida:
            errores.append(f"{destino}: {(o + e).strip()}")
    if errores:
        return False, "; ".join(errores)
    return True, "desmontado"


def write_image_to_device(image_path: str, device_path: str) -> tuple[bool, str]:
    """Graba una imagen en un dispositivo de bloque.

    Escribe directamente si hay permiso; si no, recurre a `pkexec dd`, que
    pide la contraseña mediante el diálogo gráfico del sistema. NUNCA se
    invoca sin que la interfaz haya confirmado antes con el usuario.
    """
    if not os.path.isfile(image_path):
        return False, f"no existe la imagen: {image_path}"

    if IS_WINDOWS:
        # En Windows un \\.\PhysicalDriveN no pasa la comprobación de
        # os.path.exists ni os.access de la misma forma que un archivo
        # normal: la apertura y el permiso se comprueban directamente al
        # intentar abrirlo con CreateFileW dentro de _windows_write_image.
        return _windows_write_image(image_path, device_path)

    if not os.path.exists(device_path):
        return False, f"no existe el dispositivo: {device_path}"

    if os.access(device_path, os.W_OK):
        try:
            with open(image_path, "rb") as origen, open(device_path, "wb") as destino:
                while True:
                    trozo = origen.read(1024 * 1024)
                    if not trozo:
                        break
                    destino.write(trozo)
                destino.flush()
                os.fsync(destino.fileno())
            return True, "escritura completada"
        except OSError as e:
            return False, f"error de escritura: {e}"

    if not shutil.which("pkexec"):
        return False, (
            "sin permisos de escritura sobre el dispositivo y no se encontró 'pkexec' "
            "para pedirlos.\n\nPuedes hacerlo manualmente desde una terminal:\n"
            f"    sudo dd if='{image_path}' of='{device_path}' bs=1M conv=fsync status=progress"
        )

    code, out, err = _run([
        "pkexec", "dd", f"if={image_path}", f"of={device_path}",
        "bs=1M", "conv=fsync",
    ], timeout=900)
    if code == 0:
        return True, "escritura completada"
    return False, (out + err).strip() or f"dd terminó con código {code}"


# ---------------------------------------------------------------------------
# Lectura de disquetes físicos (equivalente a COPIA720 bajo Linux)
# ---------------------------------------------------------------------------
# COPIA720 lee el disquete pista a pista con la BIOS, reintentando los
# sectores que fallan y tolerando errores si se le pide. Aquí se hace lo
# equivalente sobre Linux: se lee por pistas desde el nodo de dispositivo con
# la geometría adecuada, reintentando las que dan error y rellenando con un
# patrón conocido las que no hay forma de leer, en vez de abortar el volcado
# entero (que es lo que hace `dd` por defecto).

FLOPPY_GEOMETRIES = {
    "720":  {"etiqueta": '720 KB (MSX doble cara, 3.5" DS/DD)',
             "bytes": 737280, "pistas": 160, "sufijo": "u720",
             "sect": 9, "head": 2, "track": 80, "rate": 0x02, "gap": 0x2A,
             "spec1": 0xDF, "fmt_gap": 0x50},
    "360":  {"etiqueta": '360 KB (MSX cara simple)',
             "bytes": 368640, "pistas": 80, "sufijo": "u360",
             "sect": 9, "head": 1, "track": 80, "rate": 0x02, "gap": 0x2A,
             "spec1": 0xDF, "fmt_gap": 0x50},
    "1440": {"etiqueta": '1.44 MB (3.5" HD)',
             "bytes": 1474560, "pistas": 160, "sufijo": "u1440",
             "sect": 18, "head": 2, "track": 80, "rate": 0x00, "gap": 0x1B,
             "spec1": 0xCF, "fmt_gap": 0x6C},

    # Los dos formatos "superformateados" del Super Magic Drive / Super Wild
    # Card (ver SMD_DISK_FORMATS en rom_formats.py): no existe un nodo de
    # dispositivo estándar de Linux para ellos (no forman parte de la lista
    # fija del driver de floppy), así que se aplican con FDSETPRM en tiempo
    # de ejecución en vez de un nodo con sufijo fijo (ver _set_floppy_geometry).
    #
    # rate=0x00 (500 kbit/s) es la misma velocidad que el HD estándar de
    # 1.44 MB: la densidad magnética no cambia, lo que cambia es cuántos
    # sectores se aprietan en cada pista reduciendo el espacio entre ellos.
    #
    # ADVERTENCIA IMPORTANTE sobre gap/fmt_gap: estos valores controlan el
    # espacio entre sectores, y para que quepan más sectores de lo estándar
    # hace falta un hueco más pequeño que en un disco normal. El ajuste
    # ÓPTIMO depende de la velocidad real de la disquetera concreta, que
    # herramientas especializadas como `superformat` (paquete fdutils)
    # miden en vivo antes de formatear. Los valores de aquí son una
    # estimación razonable (menores que el estándar HD, en la proporción
    # típica de un superformateo de 20 sectores/pista), pero NO se han
    # podido verificar contra hardware real. Son de fiar para ESCRIBIR
    # datos en un disco ya formateado (donde gap/fmt_gap no importan,
    # porque las pistas ya existen); para FORMATEAR desde cero, es más
    # seguro formatear antes con `superformat` y usar aquí solo la
    # escritura.
    "1600": {"etiqueta": "1600 KB (formato especial del Super Magic Drive / SWC)",
             "bytes": 1638400, "pistas": 160, "sufijo": None,
             "sect": 20, "head": 2, "track": 80, "rate": 0x00, "gap": 0x0C,
             "spec1": 0xCF, "fmt_gap": 0x0C},
    "800":  {"etiqueta": "800 KB (doble densidad superformateada)",
             "bytes": 819200, "pistas": 160, "sufijo": None,
             "sect": 10, "head": 2, "track": 80, "rate": 0x02, "gap": 0x1B,
             "spec1": 0xDF, "fmt_gap": 0x30},
}


def _linux_iow(tipo: int, nr: int, size: int) -> int:
    """Reproduce la macro _IOW(type, nr, size) de <asm-generic/ioctl.h>,
    para no dejar el número de ioctl como una constante mágica sin poder
    verificarse ni volver a calcularse si hiciera falta.
    """
    IOC_NRBITS, IOC_TYPEBITS, IOC_SIZEBITS = 8, 8, 14
    IOC_NRSHIFT = 0
    IOC_TYPESHIFT = IOC_NRSHIFT + IOC_NRBITS
    IOC_SIZESHIFT = IOC_TYPESHIFT + IOC_TYPEBITS
    IOC_DIRSHIFT = IOC_SIZESHIFT + IOC_SIZEBITS
    IOC_WRITE = 1
    return ((IOC_WRITE << IOC_DIRSHIFT) | (tipo << IOC_TYPESHIFT)
            | (nr << IOC_NRSHIFT) | (size << IOC_SIZESHIFT))


def _set_floppy_geometry(fd: int, geometria: str) -> None:
    """Define la geometría del disquete en tiempo de ejecución con FDSETPRM,
    para los formatos que no tienen un nodo de dispositivo estándar en
    Linux (/dev/fd0u720 sí existe en el kernel; /dev/fd0u1600 no, porque
    1600 KB no es uno de los formatos que el driver de floppy trae
    predefinidos).

    struct floppy_struct (linux/fd.h), 32 bytes en un sistema de 64 bits:
        unsigned int size, sect, head, track, stretch;
        unsigned char gap, rate, spec1, fmt_gap;
        const char *name;   // NULL: solo se usa en los formatos predefinidos
    """
    info = FLOPPY_GEOMETRIES[geometria]
    import fcntl
    FDSETPRM = _linux_iow(2, 0x42, struct.calcsize("5I4BP"))
    total_sectores = info["bytes"] // 512
    estructura = struct.pack(
        "5I4BP",
        total_sectores, info["sect"], info["head"], info["track"], 0,
        info["gap"], info["rate"], info["spec1"], info["fmt_gap"],
        0,  # name = NULL
    )
    fcntl.ioctl(fd, FDSETPRM, estructura)


class _WindowsRawDevice:
    """Envoltorio mínimo sobre CreateFileW/ReadFile/WriteFile/SetFilePointer
    de kernel32, para tratar un dispositivo de Windows (\\\\.\\A:,
    \\\\.\\PhysicalDriveN) como un archivo posicionable.

    Hace falta porque, a diferencia de Linux (donde /dev/fd0 es un archivo
    especial que open() abre con normalidad), en Windows estos dispositivos
    NO se pueden abrir con la función open() estándar de Python: exigen
    CreateFileW y las funciones de E/S de la propia API de Windows.
    """
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    FILE_BEGIN = 0

    def __init__(self, path: str, escritura: bool = False):
        import ctypes
        from ctypes import wintypes
        self._ct = ctypes
        self._wt = wintypes
        self._k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self._k32.CreateFileW.restype = wintypes.HANDLE
        acceso = self.GENERIC_READ | (self.GENERIC_WRITE if escritura else 0)
        self.handle = self._k32.CreateFileW(
            path, acceso, self.FILE_SHARE_READ | self.FILE_SHARE_WRITE,
            None, self.OPEN_EXISTING, 0, None)
        invalido = ctypes.c_void_p(-1).value
        if not self.handle or self.handle == invalido:
            codigo = ctypes.get_last_error()
            raise OSError(f"no se pudo abrir {path} (código de Windows: {codigo})")

    def seek(self, offset: int):
        ct = self._ct
        low = offset & 0xFFFFFFFF
        high = ct.c_long(offset >> 32)
        self._k32.SetFilePointer(self.handle, low, ct.byref(high), self.FILE_BEGIN)

    def read(self, n: int) -> bytes:
        ct = self._ct
        buf = ct.create_string_buffer(n)
        leidos = self._wt.DWORD(0)
        ok = self._k32.ReadFile(self.handle, buf, n, ct.byref(leidos), None)
        if not ok:
            raise OSError(f"error de lectura (código de Windows: {ct.get_last_error()})")
        return buf.raw[:leidos.value]

    def write(self, datos: bytes) -> int:
        ct = self._ct
        escritos = self._wt.DWORD(0)
        ok = self._k32.WriteFile(self.handle, datos, len(datos), ct.byref(escritos), None)
        if not ok:
            raise OSError(f"error de escritura (código de Windows: {ct.get_last_error()})")
        return escritos.value

    def close(self):
        self._k32.CloseHandle(self.handle)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _list_windows_floppy_drives() -> list:
    """Disqueteras de Windows: comprueba si existen A: o B: como unidad
    lógica reconocida por el sistema (bit correspondiente en
    GetLogicalDrives). Windows suele reservar estas letras para el driver
    de disquete si está instalado, exista o no un disquete insertado.
    """
    import ctypes
    encontradas = []
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return encontradas
    for i, letra in enumerate(("A", "B")):
        if bitmask & (1 << i):
            encontradas.append(f"\\\\.\\{letra}:")
    return encontradas


def list_floppy_drives() -> list:
    """Disqueteras reales del sistema (no unidades USB)."""
    if IS_WINDOWS:
        return _list_windows_floppy_drives()
    encontradas = []
    for i in range(4):
        dev = f"/dev/fd{i}"
        if os.path.exists(dev):
            encontradas.append(dev)
    return encontradas


def floppy_device_for(base_device: str, geometria: str) -> str:
    """Nodo con la geometría explícita, p. ej. /dev/fd0u720.

    Es el equivalente en Linux a lo que hace COPIA720 reprogramando la tabla
    de parámetros del disco: sin esto, el sistema asume 1.44 MB y un disquete
    de 720 KB se lee mal o no se lee.

    En Windows no existe un nodo equivalente: se abre siempre la misma letra
    de unidad (\\\\.\\A:) y la geometría se aplica al leer/escribir el número
    exacto de bytes de cada formato, no seleccionando un dispositivo distinto.
    """
    if IS_WINDOWS:
        return base_device
    info = FLOPPY_GEOMETRIES.get(geometria)
    if not info:
        return base_device
    nodo = base_device + info["sufijo"]
    return nodo if os.path.exists(nodo) else base_device


def _windows_read_floppy(device: str, geometria: str, reintentos: int,
                         tolerar_errores: bool, progreso=None):
    info = FLOPPY_GEOMETRIES.get(geometria)
    if not info:
        raise ValueError(f"geometría desconocida: {geometria}")
    total_pistas = info["pistas"]
    bytes_pista = info["bytes"] // total_pistas
    salida = bytearray()
    fallos = []

    try:
        dispositivo = _WindowsRawDevice(device, escritura=False)
    except OSError as e:
        raise ValueError(
            f"no se pudo abrir {device}: {e}\n\n"
            "Comprueba que hay un disquete dentro y que la unidad es una "
            "disquetera real. En Windows puede hacer falta ejecutar "
            "asturconsole como Administrador."
        ) from e

    try:
        for pista in range(total_pistas):
            datos = None
            for _intento in range(reintentos):
                try:
                    dispositivo.seek(pista * bytes_pista)
                    trozo = dispositivo.read(bytes_pista)
                    if len(trozo) == bytes_pista:
                        datos = trozo
                        break
                except OSError:
                    pass
                time.sleep(0.12)

            if datos is None:
                fallos.append(pista)
                if not tolerar_errores:
                    raise ValueError(
                        f"error irrecuperable en la pista {pista} "
                        f"(cilindro {pista // 2}, cara {pista % 2})"
                    )
                datos = bytes([0xF6]) * bytes_pista

            salida += datos
            if progreso:
                progreso(pista + 1, total_pistas, len(fallos))
    finally:
        dispositivo.close()

    return bytes(salida), fallos


def read_floppy(device: str, geometria: str = "720", reintentos: int = 5,
                tolerar_errores: bool = True, progreso=None):
    """Vuelca un disquete completo, pista a pista y con reintentos.

    Devuelve (datos, lista_de_pistas_con_error). Si `tolerar_errores` es
    False, se detiene en el primer fallo irrecuperable.

    `progreso` es una función opcional que recibe (pista, total, fallos).
    """
    if IS_WINDOWS:
        return _windows_read_floppy(device, geometria, reintentos,
                                    tolerar_errores, progreso)

    info = FLOPPY_GEOMETRIES.get(geometria)
    if not info:
        raise ValueError(f"geometría desconocida: {geometria}")

    total_pistas = info["pistas"]
    bytes_pista = info["bytes"] // total_pistas
    salida = bytearray()
    fallos = []

    try:
        fd = os.open(device, os.O_RDONLY)
    except OSError as e:
        raise ValueError(
            f"no se pudo abrir {device}: {e}\n\n"
            "Comprueba que hay un disquete dentro, que la unidad es una "
            "disquetera real (no un adaptador USB) y que tienes permisos "
            "(grupo 'floppy' o 'disk')."
        ) from e

    try:
        _set_floppy_geometry(fd, geometria)
    except OSError as e:
        os.close(fd)
        if info["sufijo"] is None:
            # Sin nodo de dispositivo estándar para este formato (1600/800
            # KB): sin poder fijar la geometría explícitamente, el kernel
            # asumiría la de un disco estándar y leería mal. Es un error que
            # impide continuar, no algo que se pueda ignorar.
            raise ValueError(
                f"no se pudo establecer la geometría de {geometria} KB en "
                f"{device} ({e}). Comprueba que el módulo 'floppy' del "
                "kernel está cargado (sudo modprobe floppy) y que el "
                "dispositivo es una disquetera real, no un adaptador USB "
                "(los adaptadores USB no aceptan geometría personalizada)."
            ) from e
        # Para los formatos con nodo de sufijo (720/360/1440) el nodo ya
        # lleva la geometría implícita; si además falla FDSETPRM no es
        # grave, se continúa con la que ya tiene el nodo.

    try:
        for pista in range(total_pistas):
            datos = None
            for intento in range(reintentos):
                try:
                    os.lseek(fd, pista * bytes_pista, os.SEEK_SET)
                    trozo = os.read(fd, bytes_pista)
                    if len(trozo) == bytes_pista:
                        datos = trozo
                        break
                except OSError:
                    pass
                # Entre intentos se deja reposar la mecánica, como hacen los
                # volcadores clásicos al reiniciar la controladora.
                time.sleep(0.12)

            if datos is None:
                fallos.append(pista)
                if not tolerar_errores:
                    raise ValueError(
                        f"error irrecuperable en la pista {pista} "
                        f"(cilindro {pista // 2}, cara {pista % 2})"
                    )
                # Relleno con el mismo byte que usa un disco formateado
                datos = bytes([0xF6]) * bytes_pista

            salida += datos
            if progreso:
                progreso(pista + 1, total_pistas, len(fallos))
    finally:
        os.close(fd)

    return bytes(salida), fallos


def format_floppy_command(device: str, geometria: str) -> list:
    """Comando para formatear un disquete, si hay herramienta disponible.

    Se prefiere ufiformat (paquete ufiformat) y si no fdformat (fdutils).
    Devuelve [] si no hay ninguna instalada.
    """
    info = FLOPPY_GEOMETRIES.get(geometria, {})
    nodo = floppy_device_for(device, geometria)
    if shutil.which("ufiformat"):
        tam = {"720": "720", "360": "360", "1440": "1440"}.get(geometria, "720")
        return ["ufiformat", "-f", tam, device]
    if shutil.which("fdformat"):
        return ["fdformat", nodo]
    return []


# ---------------------------------------------------------------------------
# Formateo y escritura de disquetes a bajo nivel
# ---------------------------------------------------------------------------
# El controlador de disquete de Linux permite formatear PISTA A PISTA con las
# llamadas FDFMTBEG / FDFMTTRK / FDFMTEND. Es el equivalente directo de lo que
# hace COPIA720 bajo DOS con la interrupción 13h función 05h, y permite la
# opción más útil de aquel programa: formatear cada pista justo antes de
# grabarla, que es lo que recupera disquetes viejos que de otro modo dan error.

FDFMTBEG = 0x0247          # comienzo de una sesión de formateo
FDFMTTRK = 0x400C0248      # formatear una pista (struct format_descr)
FDFMTEND = 0x0249          # fin de la sesión
FDFLUSH  = 0x024B          # vaciar la caché del controlador


def _floppy_ioctl(fd: int, peticion: int, argumento=0):
    import fcntl
    return fcntl.ioctl(fd, peticion, argumento)


def format_track(fd: int, cabezal: int, pista: int) -> bool:
    """Formatea una sola pista. Devuelve True si lo consigue."""
    import fcntl
    import struct
    try:
        # struct format_descr { unsigned int device, head, track; }
        descr = struct.pack("III", 0, cabezal, pista)
        fcntl.ioctl(fd, FDFMTTRK, descr)
        return True
    except OSError:
        return False


def _windows_write_floppy(device: str, datos: bytes, geometria: str,
                          formatear: bool, verificar: bool, reintentos: int,
                          progreso=None):
    """Escribe los DATOS de un disquete en Windows, pista a pista.

    A diferencia de Linux, aquí NO se implementa el formateo a bajo nivel
    pista a pista (equivalente a la opción /F de COPIA720): el IOCTL de
    Windows para ello (IOCTL_DISK_FORMAT_TRACKS) está pobremente
    documentado y su soporte varía mucho según el controlador de disquete
    instalado, sin forma de probarlo aquí contra Windows real. El disquete
    debe estar ya formateado (con el propio Explorador de Windows, por
    ejemplo) antes de grabar sobre él.
    """
    info = FLOPPY_GEOMETRIES.get(geometria)
    if not info:
        raise ValueError(f"geometría desconocida: {geometria}")
    if len(datos) != info["bytes"]:
        raise ValueError(
            f"la imagen mide {len(datos)} bytes y un disquete de {geometria} KB "
            f"necesita exactamente {info['bytes']}"
        )

    total = info["pistas"]
    bytes_pista = info["bytes"] // total
    fallos: list = []

    try:
        dispositivo = _WindowsRawDevice(device, escritura=True)
    except OSError as e:
        raise ValueError(
            f"no se pudo abrir {device} para escritura: {e}\n\n"
            "Comprueba que hay un disquete dentro, que NO tiene la pestaña de "
            "protección abierta, y que ejecutas asturconsole como Administrador "
            "(en Windows casi siempre hace falta para escribir en un dispositivo)."
        ) from e

    try:
        for pista in range(total):
            trozo = datos[pista * bytes_pista:(pista + 1) * bytes_pista]
            hecho = False
            for _intento in range(reintentos):
                try:
                    dispositivo.seek(pista * bytes_pista)
                    escrito = dispositivo.write(trozo)
                    if escrito == len(trozo):
                        hecho = True
                        break
                except OSError:
                    pass
                time.sleep(0.1)

            if hecho and verificar:
                try:
                    dispositivo.seek(pista * bytes_pista)
                    leido = dispositivo.read(bytes_pista)
                    if leido != trozo:
                        hecho = False
                except OSError:
                    hecho = False

            if not hecho:
                fallos.append(pista)
            if progreso:
                progreso(pista + 1, total, len(fallos))
    finally:
        dispositivo.close()

    return fallos, []   # sin pistas "reformateadas": no se formatea en Windows


def write_floppy(device: str, datos: bytes, geometria: str = "720",
                 formatear: bool = False, verificar: bool = False,
                 reintentos: int = 3, progreso=None):
    """Graba una imagen en un disquete, pista a pista.

    Reproduce el comportamiento de COPIA720:
      - `formatear`: formatea cada pista justo antes de grabarla (opción /F).
        Recupera disquetes que dan error de escritura de otro modo.
        SOLO DISPONIBLE EN LINUX (ver _windows_write_floppy).
      - `verificar`: relee cada pista y la compara (opción /V).
      - Si una pista falla sin haber formateado, se formatea y se reintenta,
        igual que hace COPIA720 al recuperarse de un error.

    Devuelve (pistas_con_error, pistas_reformateadas).
    """
    if IS_WINDOWS:
        return _windows_write_floppy(device, datos, geometria, formatear,
                                     verificar, reintentos, progreso)

    import fcntl

    info = FLOPPY_GEOMETRIES.get(geometria)
    if not info:
        raise ValueError(f"geometría desconocida: {geometria}")
    if len(datos) != info["bytes"]:
        raise ValueError(
            f"la imagen mide {len(datos)} bytes y un disquete de {geometria} KB "
            f"necesita exactamente {info['bytes']}"
        )

    total = info["pistas"]
    bytes_pista = info["bytes"] // total
    fallos, reformateadas = [], []

    try:
        fd = os.open(device, os.O_RDWR)
    except OSError as e:
        raise ValueError(
            f"no se pudo abrir {device} para escritura: {e}\n\n"
            "Comprueba que hay un disquete dentro, que NO tiene la pestaña de "
            "protección abierta y que tienes permisos (grupo 'floppy' o 'disk')."
        ) from e

    try:
        _set_floppy_geometry(fd, geometria)
    except OSError as e:
        os.close(fd)
        if info["sufijo"] is None:
            raise ValueError(
                f"no se pudo establecer la geometría de {geometria} KB en "
                f"{device} ({e}). Comprueba que el módulo 'floppy' del "
                "kernel está cargado (sudo modprobe floppy) y que el "
                "dispositivo es una disquetera real, no un adaptador USB."
            ) from e

    sesion_formateo = False
    try:
        if formatear:
            try:
                _floppy_ioctl(fd, FDFMTBEG)
                sesion_formateo = True
            except OSError:
                # Sin permiso o unidad que no lo admite: se sigue sin formatear
                formatear = False

        for pista in range(total):
            cilindro, cabezal = pista // 2, pista % 2
            if info["pistas"] == 80:          # cara simple: todo en la cara 0
                cilindro, cabezal = pista, 0

            trozo = datos[pista * bytes_pista:(pista + 1) * bytes_pista]
            hecho = False
            formateada_aqui = False

            for intento in range(reintentos):
                if formatear and not formateada_aqui:
                    format_track(fd, cabezal, cilindro)
                    formateada_aqui = True
                try:
                    os.lseek(fd, pista * bytes_pista, os.SEEK_SET)
                    escrito = os.write(fd, trozo)
                    if escrito == len(trozo):
                        hecho = True
                        break
                except OSError:
                    pass
                # Como COPIA720: si falla y no se estaba formateando, se
                # formatea la pista y se vuelve a intentar.
                if not formateada_aqui and sesion_formateo:
                    if format_track(fd, cabezal, cilindro):
                        formateada_aqui = True
                        reformateadas.append(pista)
                time.sleep(0.1)

            if hecho and verificar:
                try:
                    os.fsync(fd)
                    os.lseek(fd, pista * bytes_pista, os.SEEK_SET)
                    leido = os.read(fd, bytes_pista)
                    if leido != trozo:
                        hecho = False
                except OSError:
                    hecho = False

            if not hecho:
                fallos.append(pista)

            if progreso:
                progreso(pista + 1, total, len(fallos))

        try:
            os.fsync(fd)
        except OSError:
            pass
    finally:
        if sesion_formateo:
            try:
                _floppy_ioctl(fd, FDFMTEND)
            except OSError:
                pass
        os.close(fd)

    return fallos, reformateadas


def format_floppy(device: str, geometria: str = "720", progreso=None):
    """Formatea un disquete completo, pista a pista.

    Devuelve la lista de pistas que no se pudieron formatear.

    Para los formatos "superformateados" del Super Magic Drive / Super Wild
    Card (1600 y 800 KB): el hueco entre sectores (gap) que usa esta función
    es una estimación razonable, no un valor medido contra hardware real —
    herramientas especializadas como `superformat` (paquete fdutils) miden
    en vivo la velocidad exacta de la disquetera antes de formatear, porque
    el margen óptimo varía ligeramente de una unidad a otra. Si el formateo
    con esta función da muchos errores en estos dos formatos concretos, es
    preferible formatear antes con `superformat` y usar aquí solo la
    escritura (que si es fiable: una vez el disco ya está formateado, el
    valor del gap deja de importar).

    NO DISPONIBLE EN WINDOWS por esta aplicación: el IOCTL equivalente
    (IOCTL_DISK_FORMAT_TRACKS) tiene soporte muy variable según el driver de
    la controladora y no se puede garantizar ni probar aquí. Se lanza un
    error explicando la alternativa: formatear el disquete con el propio
    Explorador de Windows antes de usarlo con asturconsole.
    """
    if IS_WINDOWS:
        raise ValueError(
            "El formateo de disquetes a bajo nivel no está disponible en Windows "
            "desde esta aplicación (el mecanismo que usa Windows para ello tiene "
            "soporte muy irregular según el equipo).\n\n"
            "Formatea el disquete primero con el propio Windows: clic derecho "
            "sobre la unidad A: en 'Este equipo' → Formatear. Después ya se puede "
            "grabar la imagen con normalidad."
        )

    info = FLOPPY_GEOMETRIES.get(geometria)
    if not info:
        raise ValueError(f"geometría desconocida: {geometria}")

    total = info["pistas"]
    fallos = []
    try:
        fd = os.open(device, os.O_RDWR)
    except OSError as e:
        raise ValueError(
            f"no se pudo abrir {device}: {e}\n\n"
            "Comprueba que hay un disquete dentro, sin protección contra "
            "escritura, y que tienes permisos sobre la unidad."
        ) from e

    try:
        _set_floppy_geometry(fd, geometria)
    except OSError as e:
        os.close(fd)
        if info["sufijo"] is None:
            raise ValueError(
                f"no se pudo establecer la geometría de {geometria} KB en "
                f"{device} ({e}). Comprueba que el módulo 'floppy' del "
                "kernel está cargado (sudo modprobe floppy)."
            ) from e

    try:
        try:
            _floppy_ioctl(fd, FDFMTBEG)
        except OSError as e:
            raise ValueError(
                "el sistema no permite formatear esta unidad a bajo nivel. "
                "Los adaptadores USB de disquete no lo admiten: solo las "
                "disqueteras conectadas a la controladora."
            ) from e

        for pista in range(total):
            cilindro, cabezal = pista // 2, pista % 2
            if total == 80:
                cilindro, cabezal = pista, 0
            if not format_track(fd, cabezal, cilindro):
                fallos.append(pista)
            if progreso:
                progreso(pista + 1, total, len(fallos))

        try:
            _floppy_ioctl(fd, FDFMTEND)
        except OSError:
            pass
    finally:
        os.close(fd)

    return fallos


def detect_floppy_geometry(device: str):
    """Deduce el formato del disquete leyendo su sector de arranque.

    Devuelve la clave de geometría ("360", "720", "1440") o None. Se apoya en
    el BPB, que indica sectores totales y número de caras: es más fiable que
    suponer, y evita leer un disco de 360 KB como si fuera de 720.
    """
    import struct
    if IS_WINDOWS:
        try:
            with _WindowsRawDevice(device, escritura=False) as dispositivo:
                sector = dispositivo.read(512)
        except OSError:
            return None
    else:
        try:
            fd = os.open(device, os.O_RDONLY)
        except OSError:
            return None
        try:
            sector = os.read(fd, 512)
        except OSError:
            return None
        finally:
            os.close(fd)

    if len(sector) < 32:
        return None
    try:
        bps = struct.unpack_from("<H", sector, 0x0B)[0]
        total_sectores = struct.unpack_from("<H", sector, 0x13)[0]
        caras = struct.unpack_from("<H", sector, 0x1A)[0]
    except struct.error:
        return None

    if bps != 512 or not total_sectores:
        return None
    tamano = total_sectores * bps
    for clave, info in FLOPPY_GEOMETRIES.items():
        if info["bytes"] == tamano:
            # coherencia con el número de caras declarado
            if clave == "360" and caras not in (0, 1):
                continue
            return clave
    return None
