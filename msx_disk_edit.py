"""Edición en el sitio de imágenes de disco FAT12 (MSX-DOS, 360/720 KB, 1.44 MB).

Añade y quita archivos SIN reconstruir el disco: se modifican solo la FAT (en
todas sus copias), el directorio y los clústeres afectados. Así se conservan el
sector de arranque (discos de sistema), la etiqueta de volumen, las subcarpetas
y todo lo que ya había.

Sin dependencias de Qt, para poder probarlo aparte.

Uso típico:
    disco = DiscoFat(bytes_de_la_imagen)
    plan = disco.planificar([("JUEGO.BIN", 12345)], camino=())
    if plan.cabe:
        disco.anadir("JUEGO.BIN", datos)
        nuevos_bytes = disco.imagen()
Todas las operaciones son atómicas a nivel de método: si fallan, la imagen
queda como estaba.
"""
from __future__ import annotations

import datetime
import struct
from dataclasses import dataclass, field

FIN_CADENA = 0xFFF
INVALIDOS = set('"*+,/:;<=>?[\\]|') | {" "}


class ErrorDisco(ValueError):
    """Problema con la imagen o con la operación pedida (mensaje en español)."""


@dataclass
class Elemento:
    nombre: str          # "NOMBRE.EXT"
    es_dir: bool
    tamano: int          # bytes (0 para carpetas)
    cluster: int
    camino: tuple        # carpetas que lo contienen, desde la raíz
    ocupa: int = 0       # bytes realmente ocupados en el disco (clústeres enteros)


@dataclass
class Plan:
    """Resultado de comprobar si unos archivos caben."""
    nombres: list = field(default_factory=list)      # nombre final 8.3 de cada uno
    necesario: int = 0                               # bytes de clústeres que hacen falta
    libre: int = 0                                   # bytes libres (contando lo que se reemplaza)
    falta: int = 0                                   # bytes que faltan (0 si caben)
    entradas_faltan: int = 0                         # entradas de directorio que faltan
    duplicados: list = field(default_factory=list)   # nombres que ya existen en la carpeta
    renombrados: list = field(default_factory=list)  # (original, final) si hubo que acortar

    @property
    def cabe(self) -> bool:
        return self.falta <= 0 and self.entradas_faltan <= 0


def nombre_83(nombre: str) -> tuple[str, str]:
    """Convierte un nombre cualquiera al formato 8.3 de MSX-DOS: mayúsculas,
    sin caracteres prohibidos, 8 de nombre y 3 de extensión."""
    base = nombre.replace("\\", "/").rsplit("/", 1)[-1]
    if "." in base.strip("."):
        n, e = base.rsplit(".", 1)
    else:
        n, e = base, ""

    def limpiar(t: str, largo: int) -> str:
        t = t.upper()
        t = "".join("_" if (c in INVALIDOS or ord(c) < 32 or ord(c) > 126) else c for c in t)
        return t[:largo]

    n, e = limpiar(n, 8), limpiar(e, 3)
    return (n or "SINNOMBRE"), e


def _texto(n: str, e: str) -> str:
    return f"{n}.{e}" if e else n


class DiscoFat:
    def __init__(self, datos: bytes):
        if len(datos) < 1024:
            raise ErrorDisco("La imagen es demasiado pequeña para ser un disco.")
        self._d = bytearray(datos)
        d = self._d
        self.bps = struct.unpack_from("<H", d, 0x0B)[0]
        self.spc = d[0x0D]
        self.reservados = struct.unpack_from("<H", d, 0x0E)[0]
        self.nfat = d[0x10]
        self.raiz_entradas = struct.unpack_from("<H", d, 0x11)[0]
        self.total_sectores = struct.unpack_from("<H", d, 0x13)[0]
        self.spf = struct.unpack_from("<H", d, 0x16)[0]
        if (self.bps not in (512, 1024, 2048) or self.spc == 0 or self.nfat == 0
                or self.raiz_entradas == 0 or self.spf == 0 or self.total_sectores == 0):
            raise ErrorDisco("Los datos del sector de arranque no son válidos: no parece un disco FAT12.")
        if self.total_sectores * self.bps > len(d):
            raise ErrorDisco("La imagen está truncada: es más pequeña de lo que dice su cabecera.")
        self.inicio_fat = self.reservados * self.bps
        self.inicio_raiz = (self.reservados + self.nfat * self.spf) * self.bps
        raiz_sectores = -(-(self.raiz_entradas * 32) // self.bps)
        self.inicio_datos = self.inicio_raiz + raiz_sectores * self.bps
        self.bytes_cluster = self.spc * self.bps
        self.clusters = (self.total_sectores * self.bps - self.inicio_datos) // self.bytes_cluster
        if self.clusters < 1 or self.clusters >= 0xFF0:
            raise ErrorDisco("Tamaño de disco no compatible (no es FAT12).")

    # -- acceso a la imagen ------------------------------------------------
    def imagen(self) -> bytes:
        return bytes(self._d)

    def _fat(self) -> bytearray:
        n = self.spf * self.bps
        return bytearray(self._d[self.inicio_fat:self.inicio_fat + n])

    def _guardar_fat(self, fat: bytearray):
        n = self.spf * self.bps
        for i in range(self.nfat):
            ini = self.inicio_fat + i * n
            self._d[ini:ini + n] = fat

    @staticmethod
    def _leer(fat: bytes, n: int) -> int:
        off = (n * 3) // 2
        if n % 2 == 0:
            return fat[off] | ((fat[off + 1] & 0x0F) << 8)
        return (fat[off] >> 4) | (fat[off + 1] << 4)

    @staticmethod
    def _escribir(fat: bytearray, n: int, valor: int):
        off = (n * 3) // 2
        if n % 2 == 0:
            fat[off] = valor & 0xFF
            fat[off + 1] = (fat[off + 1] & 0xF0) | ((valor >> 8) & 0x0F)
        else:
            fat[off] = (fat[off] & 0x0F) | ((valor & 0x0F) << 4)
            fat[off + 1] = (valor >> 4) & 0xFF

    def _cadena(self, fat: bytes, inicio: int) -> list[int]:
        cadena, cur, guardia = [], inicio, 0
        while 2 <= cur <= self.clusters + 1 and guardia <= self.clusters:
            cadena.append(cur)
            cur = self._leer(fat, cur)
            guardia += 1
        return cadena

    def _ini_cluster(self, c: int) -> int:
        return self.inicio_datos + (c - 2) * self.bytes_cluster

    def _libres(self, fat: bytes) -> list[int]:
        return [c for c in range(2, self.clusters + 2) if self._leer(fat, c) == 0]

    # -- directorios -------------------------------------------------------
    def _huecos(self, cluster_dir: int | None, fat: bytes) -> list[int]:
        """Posiciones absolutas de las entradas (32 bytes) de un directorio."""
        if cluster_dir is None:
            return [self.inicio_raiz + i * 32 for i in range(self.raiz_entradas)]
        pos = []
        for c in self._cadena(fat, cluster_dir):
            base = self._ini_cluster(c)
            pos.extend(base + i * 32 for i in range(self.bytes_cluster // 32))
        return pos

    def _entradas(self, huecos: list[int]):
        """(posición, nombre, ext, atributo, cluster, tamaño) de las entradas vivas."""
        for p in huecos:
            b0 = self._d[p]
            if b0 == 0x00:
                break
            if b0 == 0xE5:
                continue
            attr = self._d[p + 11]
            if attr & 0x08 or attr == 0x0F:
                continue
            n = bytes(self._d[p:p + 8]).decode("ascii", "replace").rstrip()
            e = bytes(self._d[p + 8:p + 11]).decode("ascii", "replace").rstrip()
            if n in (".", ".."):
                continue
            cl = struct.unpack_from("<H", self._d, p + 26)[0]
            tam = struct.unpack_from("<I", self._d, p + 28)[0]
            yield p, n, e, attr, cl, tam

    def _cluster_de_camino(self, camino: tuple, fat: bytes) -> int | None:
        cur: int | None = None
        for nombre in camino:
            n, e = nombre_83(nombre)
            for _p, nn, ee, attr, cl, _t in self._entradas(self._huecos(cur, fat)):
                if nn == n and ee == e and attr & 0x10:
                    cur = cl
                    break
            else:
                raise ErrorDisco(f"No existe la carpeta «{nombre}» en el disco.")
        return cur

    # -- consulta ----------------------------------------------------------
    def espacio(self) -> tuple[int, int]:
        """(bytes libres, bytes totales de datos)."""
        fat = self._fat()
        return len(self._libres(fat)) * self.bytes_cluster, self.clusters * self.bytes_cluster

    def listar(self, camino: tuple = (), recursivo: bool = True) -> list[Elemento]:
        fat = self._fat()
        return self._listar(camino, fat, recursivo, 0)

    def _listar(self, camino, fat, recursivo, prof) -> list[Elemento]:
        if prof > 16:
            return []
        cl_dir = self._cluster_de_camino(camino, fat)
        out = []
        for _p, n, e, attr, cl, tam in self._entradas(self._huecos(cl_dir, fat)):
            es_dir = bool(attr & 0x10)
            nombre = _texto(n, e)
            ocupa = len(self._cadena(fat, cl)) * self.bytes_cluster if cl >= 2 else 0
            out.append(Elemento(nombre, es_dir, 0 if es_dir else tam, cl, camino, ocupa))
            if es_dir and recursivo:
                out.extend(self._listar(camino + (nombre,), fat, True, prof + 1))
        return out

    def leer_archivo(self, camino: tuple, nombre: str) -> bytes:
        fat = self._fat()
        cl_dir = self._cluster_de_camino(camino, fat)
        n, e = nombre_83(nombre)
        for _p, nn, ee, attr, cl, tam in self._entradas(self._huecos(cl_dir, fat)):
            if nn == n and ee == e and not attr & 0x10:
                out = bytearray()
                for c in self._cadena(fat, cl):
                    ini = self._ini_cluster(c)
                    out += self._d[ini:ini + self.bytes_cluster]
                return bytes(out[:tam])
        raise ErrorDisco(f"No existe el archivo «{nombre}» en el disco.")

    # -- planificación -----------------------------------------------------
    def planificar(self, archivos: list, camino: tuple = (),
                   reemplazar: bool = True) -> Plan:
        """Comprueba si `archivos` [(nombre, tamaño)] caben en `camino`.

        Con `reemplazar` True, los que ya existen se cuentan como sustituidos
        (su espacio actual se libera). No modifica nada."""
        fat = self._fat()
        cl_dir = self._cluster_de_camino(camino, fat)
        huecos = self._huecos(cl_dir, fat)
        existentes = {(n, e): (p, cl) for p, n, e, _a, cl, _t in self._entradas(huecos)}

        plan = Plan()
        usados = set(existentes)
        a_liberar = 0
        clusters_necesarios = 0
        nuevas_entradas = 0
        for nombre, tam in archivos:
            n, e = nombre_83(nombre)
            final = (n, e)
            if final in usados and final not in existentes:
                # dos de la lista chocan al acortar: se numera
                for i in range(1, 100):
                    suf = f"~{i}"
                    cand = (n[:8 - len(suf)] + suf, e)
                    if cand not in usados:
                        final = cand
                        break
            if _texto(*final).upper() != nombre.upper():
                plan.renombrados.append((nombre, _texto(*final)))
            if final in existentes:
                plan.duplicados.append(_texto(*final))
                if reemplazar:
                    a_liberar += len(self._cadena(fat, existentes[final][1]))
                else:
                    continue
            else:
                nuevas_entradas += 1
            usados.add(final)
            plan.nombres.append(_texto(*final))
            clusters_necesarios += -(-tam // self.bytes_cluster) if tam else 0

        # entradas de directorio
        libres_dir = sum(1 for p in huecos if self._d[p] in (0x00, 0xE5))
        extra_dir_clusters = 0
        if nuevas_entradas > libres_dir:
            if cl_dir is None:
                plan.entradas_faltan = nuevas_entradas - libres_dir
            else:
                por_cluster = self.bytes_cluster // 32
                extra_dir_clusters = -(-(nuevas_entradas - libres_dir) // por_cluster)
        clusters_necesarios += extra_dir_clusters

        libres = len(self._libres(fat)) + a_liberar
        plan.necesario = clusters_necesarios * self.bytes_cluster
        plan.libre = libres * self.bytes_cluster
        plan.falta = max(0, plan.necesario - plan.libre)
        return plan

    # -- operaciones -------------------------------------------------------
    def anadir(self, nombre: str, datos: bytes, camino: tuple = (),
               reemplazar: bool = True) -> str:
        """Añade un archivo. Devuelve el nombre 8.3 final. Si no cabe, lanza
        ErrorDisco y la imagen queda intacta."""
        copia = bytearray(self._d)
        try:
            return self._anadir(nombre, datos, camino, reemplazar)
        except Exception:
            self._d = copia
            raise

    def _anadir(self, nombre, datos, camino, reemplazar) -> str:
        fat = self._fat()
        cl_dir = self._cluster_de_camino(camino, fat)
        n, e = nombre_83(nombre)
        huecos = self._huecos(cl_dir, fat)
        existentes = {(nn, ee): (p, cl) for p, nn, ee, _a, cl, _t in self._entradas(huecos)}
        if (n, e) in existentes:
            if not reemplazar:
                raise ErrorDisco(f"Ya existe «{_texto(n, e)}» en el disco.")
            p_old, cl_old = existentes[(n, e)]
            if self._d[p_old + 11] & 0x10:
                raise ErrorDisco(f"«{_texto(n, e)}» es una carpeta: no se puede reemplazar por un archivo.")
            self._borrar_entrada(p_old, cl_old, fat)
            huecos = self._huecos(cl_dir, fat)

        necesarios = -(-len(datos) // self.bytes_cluster) if datos else 0
        libres = self._libres(fat)
        if necesarios > len(libres):
            falta = (necesarios - len(libres)) * self.bytes_cluster
            raise ErrorDisco(f"No hay espacio: faltan {falta} bytes.")

        hueco = next((p for p in huecos if self._d[p] in (0x00, 0xE5)), None)
        if hueco is None:
            if cl_dir is None:
                raise ErrorDisco("El directorio raíz está lleno (no caben más entradas).")
            # ampliar la carpeta con un clúster nuevo
            if necesarios + 1 > len(libres):
                raise ErrorDisco("No hay espacio ni para ampliar la carpeta.")
            nuevo = libres.pop(0)
            ultimo = self._cadena(fat, cl_dir)[-1]
            self._escribir(fat, ultimo, nuevo)
            self._escribir(fat, nuevo, FIN_CADENA)
            ini = self._ini_cluster(nuevo)
            self._d[ini:ini + self.bytes_cluster] = bytes(self.bytes_cluster)
            hueco = ini

        asignados = libres[:necesarios]
        for i, c in enumerate(asignados):
            ini = self._ini_cluster(c)
            trozo = datos[i * self.bytes_cluster:(i + 1) * self.bytes_cluster]
            self._d[ini:ini + self.bytes_cluster] = trozo.ljust(self.bytes_cluster, b"\x00")
            self._escribir(fat, c, asignados[i + 1] if i + 1 < len(asignados) else FIN_CADENA)

        self._poner_entrada(hueco, n, e, 0x20, asignados[0] if asignados else 0, len(datos))
        self._guardar_fat(fat)
        return _texto(n, e)

    def crear_carpeta(self, nombre: str, camino: tuple = ()) -> str:
        """Crea una carpeta vacía (ocupa un clúster). Si la carpeta que la
        contiene está llena se amplía con otro clúster."""
        copia = bytearray(self._d)
        try:
            fat = self._fat()
            cl_dir = self._cluster_de_camino(camino, fat)
            n, e = nombre_83(nombre)
            if e:
                raise ErrorDisco("Las carpetas no llevan extensión: quita el punto y lo que le sigue.")
            huecos = self._huecos(cl_dir, fat)
            if any((nn, ee) == (n, e) for _p, nn, ee, *_ in self._entradas(huecos)):
                raise ErrorDisco(f"Ya existe «{_texto(n, e)}» en esa carpeta.")
            libres = self._libres(fat)
            hueco = next((p for p in huecos if self._d[p] in (0x00, 0xE5)), None)
            if hueco is None:
                if cl_dir is None:
                    raise ErrorDisco("El directorio raíz está lleno: quita algún archivo antes de crear la carpeta.")
                if len(libres) < 2:
                    raise ErrorDisco("No queda espacio en el disco: quita algún archivo antes de crear la carpeta.")
                nuevo = libres.pop(0)
                ultimo = self._cadena(fat, cl_dir)[-1]
                self._escribir(fat, ultimo, nuevo)
                self._escribir(fat, nuevo, FIN_CADENA)
                ini = self._ini_cluster(nuevo)
                self._d[ini:ini + self.bytes_cluster] = bytes(self.bytes_cluster)
                hueco = ini
            if not libres:
                raise ErrorDisco("No queda espacio en el disco: quita algún archivo antes de crear la carpeta.")
            c = libres[0]
            self._escribir(fat, c, FIN_CADENA)
            ini = self._ini_cluster(c)
            self._d[ini:ini + self.bytes_cluster] = bytes(self.bytes_cluster)
            self._poner_entrada(ini, ".", "", 0x10, c, 0)
            self._poner_entrada(ini + 32, "..", "", 0x10, cl_dir or 0, 0)
            self._poner_entrada(hueco, n, e, 0x10, c, 0)
            self._guardar_fat(fat)
            return _texto(n, e)
        except Exception:
            self._d = copia
            raise

    def borrar(self, nombre: str, camino: tuple = ()) -> int:
        """Quita un archivo o una carpeta (con todo lo que contenga). Devuelve
        los bytes liberados."""
        copia = bytearray(self._d)
        try:
            fat = self._fat()
            cl_dir = self._cluster_de_camino(camino, fat)
            n, e = nombre_83(nombre)
            for p, nn, ee, attr, cl, _t in self._entradas(self._huecos(cl_dir, fat)):
                if (nn, ee) == (n, e):
                    liberado = self._borrar_entrada(p, cl, fat, recursivo=True)
                    self._guardar_fat(fat)
                    return liberado
            raise ErrorDisco(f"No existe «{nombre}» en el disco.")
        except Exception:
            self._d = copia
            raise

    def _borrar_entrada(self, pos: int, cluster: int, fat: bytearray,
                        recursivo: bool = False, _prof: int = 0) -> int:
        if _prof > 16:
            return 0
        liberado = 0
        es_dir = bool(self._d[pos + 11] & 0x10)
        if es_dir and recursivo and cluster >= 2:
            for p, _n, _e, _a, cl, _t in list(self._entradas(self._huecos(cluster, fat))):
                liberado += self._borrar_entrada(p, cl, fat, True, _prof + 1)
        if cluster >= 2:
            for c in self._cadena(fat, cluster):
                self._escribir(fat, c, 0)
                liberado += self.bytes_cluster
        self._d[pos] = 0xE5
        return liberado

    def _poner_entrada(self, pos: int, n: str, e: str, attr: int, cluster: int, tam: int):
        ahora = datetime.datetime.now()
        fecha = ((max(ahora.year, 1980) - 1980) << 9) | (ahora.month << 5) | ahora.day
        hora = (ahora.hour << 11) | (ahora.minute << 5) | (ahora.second // 2)
        ent = bytearray(32)
        ent[0:8] = n.encode("ascii", "replace").ljust(8)
        ent[8:11] = e.encode("ascii", "replace").ljust(3)
        ent[11] = attr
        struct.pack_into("<H", ent, 22, hora)
        struct.pack_into("<H", ent, 24, fecha)
        struct.pack_into("<H", ent, 26, cluster)
        struct.pack_into("<I", ent, 28, tam)
        self._d[pos:pos + 32] = ent


def sugerir_borrados(elementos: list, falta: int, maximo: int = 5) -> list:
    """Archivos que convendría quitar para liberar al menos `falta` bytes.

    Primero se busca UN solo archivo, el más pequeño que baste (se pierde lo
    mínimo); si ninguno basta, se van sumando los más grandes. Devuelve []
    si ni así se llega."""
    archivos = [e for e in elementos if not e.es_dir and e.ocupa > 0]
    suficientes = [e for e in archivos if e.ocupa >= falta]
    if suficientes:
        return [min(suficientes, key=lambda e: e.ocupa)]
    elegidos, acumulado = [], 0
    for e in sorted(archivos, key=lambda e: e.ocupa, reverse=True):
        if acumulado >= falta or len(elegidos) >= maximo:
            break
        elegidos.append(e)
        acumulado += e.ocupa
    return elegidos if acumulado >= falta else []
