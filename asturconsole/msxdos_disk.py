"""Creación de disquetes MSX-DOS arrancables a partir de los archivos de
sistema que aporte el usuario.

Por qué el usuario debe aportar los archivos
---------------------------------------------
`MSXDOS.SYS`, `COMMAND.COM` y sus equivalentes de MSX-DOS 2 son software
propietario de ASCII/Microsoft. La aplicación no los incluye ni los
distribuye: el usuario los coloca en la carpeta `msxdos/` de su espacio de
trabajo, desde su propia copia.

Por qué hace falta además el sector de arranque
------------------------------------------------
Un disco no arranca por el mero hecho de contener esos archivos. Según el
MSX2 Technical Handbook, la Disk ROM lee el sector 0 del disquete, lo copia
a C000h y le cede el control; si el primer byte no es EBh o E9h, arranca
DISK-BASIC directamente. Es el código de ese sector el que localiza y carga
MSXDOS.SYS en 0100h. Además, MSX-DOS 2 emplea un sector de arranque
distinto, que carga MSXDOS2.SYS.

Por eso el usuario debe dejar también en `msxdos/` una imagen .dsk que ya
arranque (de la que se copia el sector 0) o un `BOOTSECTOR.BIN` de 512
bytes. Si no hay ninguno, el disco se crea igualmente pero se avisa de que
probablemente arrancará en DISK-BASIC.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import rom_formats as rf

# Nombres de archivo de sistema por versión de MSX-DOS
DOS1_SYSTEM_FILES = ("MSXDOS.SYS", "COMMAND.COM")
DOS2_SYSTEM_FILES = ("MSXDOS2.SYS", "COMMAND2.COM")

DOS_VERSIONS = {
    "dos1": ("MSX-DOS 1 (1.03)", DOS1_SYSTEM_FILES),
    "dos2": ("MSX-DOS 2 (2.31)", DOS2_SYSTEM_FILES),
}

BOOTSECTOR_FILENAME = "BOOTSECTOR.BIN"


@dataclass
class SystemDiskPlan:
    version: str
    files: list = field(default_factory=list)      # [(nombre, datos)]
    boot_sector: bytes | None = None
    boot_source: str = ""
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    used_bytes: int = 0
    free_bytes: int = 0
    entries: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def find_system_files(msxdos_dir: str, version: str) -> tuple[list, list]:
    """Localiza los archivos de sistema de la versión pedida.

    Devuelve (encontrados, faltantes). La comparación es sin distinguir
    mayúsculas, ya que en Linux los nombres pueden estar en minúsculas.
    """
    _label, requeridos = DOS_VERSIONS[version]
    presentes = {}
    try:
        for fn in os.listdir(msxdos_dir):
            ruta = os.path.join(msxdos_dir, fn)
            if os.path.isfile(ruta):
                presentes[fn.upper()] = ruta
    except OSError:
        return [], list(requeridos)

    encontrados, faltantes = [], []
    for nombre in requeridos:
        ruta = presentes.get(nombre.upper())
        if ruta:
            encontrados.append((nombre, ruta))
        else:
            faltantes.append(nombre)
    return encontrados, faltantes


def find_boot_sector(msxdos_dir: str, bps: int = 512) -> tuple[bytes | None, str]:
    """Busca el código de arranque: primero BOOTSECTOR.BIN, y si no, el
    sector 0 de cualquier .dsk presente en la carpeta.

    Devuelve (sector, descripción del origen).
    """
    try:
        entradas = sorted(os.listdir(msxdos_dir))
    except OSError:
        return None, ""

    # 1) Archivo explícito de sector de arranque
    for fn in entradas:
        if fn.upper() == BOOTSECTOR_FILENAME:
            datos = _read(os.path.join(msxdos_dir, fn))
            if len(datos) >= bps:
                return datos[:bps], fn
            return None, ""

    # 2) Sector 0 de una imagen .dsk que parezca arrancable
    for fn in entradas:
        if not fn.lower().endswith((".dsk", ".img")):
            continue
        try:
            datos = _read(os.path.join(msxdos_dir, fn))
        except OSError:
            continue
        if len(datos) < bps:
            continue
        # La Disk ROM exige EBh o E9h como primer byte del sector de arranque
        if datos[0] in (0xEB, 0xE9):
            return datos[:bps], fn
    return None, ""


def collect_utils(utils_dir: str) -> list:
    """Archivos de la carpeta de utilidades, ordenados por nombre."""
    salida = []
    try:
        for fn in sorted(os.listdir(utils_dir)):
            ruta = os.path.join(utils_dir, fn)
            if not os.path.isfile(ruta):
                continue
            if fn.startswith(".") or fn.upper() == "LEEME.TXT":
                continue
            salida.append((fn, ruta))
    except OSError:
        pass
    return salida


def plan_system_disk(msxdos_dir: str, utils_dir: str, version: str,
                     fmt: str = "720", include_utils: bool = True,
                     volume_label: str = "") -> SystemDiskPlan:
    """Prepara (sin escribir nada) el contenido de un disquete de sistema y
    comprueba que quepa en el formato elegido."""
    plan = SystemDiskPlan(version=version)
    label, requeridos = DOS_VERSIONS[version]

    encontrados, faltantes = find_system_files(msxdos_dir, version)
    if faltantes:
        plan.errors.append(
            f"Faltan archivos de {label} en la carpeta «msxdos»: "
            + ", ".join(faltantes)
            + ". Cópialos ahí desde tu propia copia de MSX-DOS."
        )

    archivos = []
    for nombre, ruta in encontrados:
        try:
            archivos.append((nombre, _read(ruta)))
        except OSError as e:
            plan.errors.append(f"No se pudo leer {nombre}: {e}")

    if include_utils:
        for nombre, ruta in collect_utils(utils_dir):
            try:
                archivos.append((nombre, _read(ruta)))
            except OSError as e:
                plan.warnings.append(f"Se omite {nombre}: {e}")

    plan.files = archivos

    f = rf.MSX_DISK_FORMATS[str(fmt)]
    plan.boot_sector, plan.boot_source = find_boot_sector(msxdos_dir, f.bps)
    if not plan.boot_sector:
        plan.warnings.append(
            "No se encontró código de arranque (ni BOOTSECTOR.BIN ni una imagen .dsk "
            "arrancable en la carpeta «msxdos»). El disco se creará con los archivos "
            "copiados, pero es muy probable que el MSX arranque en DISK-BASIC en vez de "
            "en MSX-DOS: la Disk ROM necesita el código del sector 0 para cargar el "
            "sistema."
        )

    usados, libres, entradas = rf.plan_msx_disk(archivos, f, volume_label)
    plan.used_bytes, plan.free_bytes, plan.entries = usados, libres, entradas
    if usados > libres:
        sobra = usados - libres
        plan.errors.append(
            f"No cabe en un disquete de {f.label}: hacen falta {rf.fmt_bytes(usados)} "
            f"y solo hay {rf.fmt_bytes(libres)} ({rf.fmt_bytes(sobra)} de más). "
            "Quita algún archivo de «msxdos_utils» o usa el formato de 720 KB."
        )
    if entradas > f.root_entries:
        plan.errors.append(
            f"Demasiados archivos: {entradas} entradas de directorio para un máximo "
            f"de {f.root_entries}."
        )
    return plan


def build_system_disk(plan: SystemDiskPlan, fmt: str = "720",
                      volume_label: str = "") -> bytes:
    """Genera la imagen del disquete de sistema a partir de un plan válido."""
    if not plan.ok:
        raise ValueError("; ".join(plan.errors))
    _label, sistema = DOS_VERSIONS[plan.version]
    return rf.write_files_to_msx_dsk(
        plan.files, fmt=fmt, volume_label=volume_label,
        boot_sector=plan.boot_sector,
        system_attr_for=tuple(n.upper() for n in sistema),
    )
