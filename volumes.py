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
import subprocess
from dataclasses import dataclass

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


def list_volumes() -> tuple[list[Volume], list[Volume]]:
    """Devuelve (montados, sin_montar).

    'montados' incluye la carpeta personal y los volúmenes de datos
    relevantes; 'sin_montar' son particiones con sistema de archivos
    detectado que todavía no están montadas (típicamente un USB recién
    conectado en un equipo sin automontaje).
    """
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
    return shutil.which("udisksctl") is not None


def mount_device(device_path: str) -> tuple[bool, str]:
    """Monta un dispositivo con udisksctl (sin root en un escritorio normal).

    Devuelve (éxito, mensaje). Si tiene éxito, el mensaje es el punto de
    montaje resultante.
    """
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
        return "/dev/fd" in self.path

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


def list_write_targets() -> list:
    """Dispositivos donde se podría grabar una imagen.

    Solo devuelve discos completos (no particiones) y, por seguridad, marca
    los que no parecen extraíbles para que la interfaz los desaconseje.
    """
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
