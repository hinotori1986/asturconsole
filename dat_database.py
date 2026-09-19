"""Identificación de ROMs de SNES y Mega Drive contra bases de datos .dat
en formato RomCenter (las mismas que usa uCON64 --db/--scan/--rdat).

Formato de cada línea de datos: empieza por el carácter "¬" (0xAC) y trae
varios campos separados por ese mismo carácter. Replica exactamente el
parseo de line_to_dat() en ucon64_dat.c — mismo separador, mismos índices
de campo, misma tabla de "flags" entre corchetes y de país entre
paréntesis, verificado contra ese código fuente y confirmado con ROMs
reales (el CRC32 se calcula sobre la ROM SIN cabecera de copiadora, tal
como espera el propio catálogo GoodTools/GoodSNES/GoodGen).
"""
from __future__ import annotations

import json
import os
import zlib
from dataclasses import dataclass, field

import workspace as ws

DAT_FIELD_SEPARATOR = 0xAC  # "¬", el mismo byte que usa ucon64_dat.c

# Mismo orden y mismos prefijos que dat_flags[] en ucon64_dat.c::line_to_dat.
# El emparejamiento es por prefijo (ej. "[b" cubre "[b1]", "[b2]"...), salvo
# "[!]" que se compara completo.
FLAGS_CONOCIDOS = [
    ("[a", "Alternativo"),
    ("[p", "Pirata"),
    ("[b", "Mal volcado"),
    ("[t", "Con trainer"),
    ("[f", "Arreglado (fixed)"),
    ("[T", "Traducción"),
    ("[h", "Hack"),
    ("[x", "Checksum incorrecto"),
    ("[o", "Overdump"),
    ("[!]", "Volcado verificado"),
]

# Mismo orden que dat_country[] en ucon64_dat.c — el orden importa: (A),
# (B), (C), (E), (F) van al final porque algunos juegos los llevan en el
# propio nombre sin ser código de país (ver el comentario del propio
# ucon64 sobre "SD Gundam Generations (A)...").
PAISES_CONOCIDOS = [
    ("(FC)", "Francia/Canadá"), ("(FN)", "Finlandia"), ("(G)", "Alemania"),
    ("(GR)", "Grecia"), ("(H)", "Holanda"), ("(HK)", "Hong Kong"),
    ("(I)", "Italia"), ("(J)", "Japón"), ("(JE)", "Japón y Europa"),
    ("(JU)", "Japón y EE.UU."), ("(JUE)", "Japón, EE.UU. y Europa"),
    ("(K)", "Corea"), ("(NL)", "Países Bajos"), ("(PD)", "Dominio público"),
    ("(S)", "España"), ("(SW)", "Suecia"), ("(U)", "EE.UU."),
    ("(UE)", "EE.UU. y Europa"), ("(UK)", "Inglaterra"),
    ("(Unk)", "País desconocido"),
    ("(1)", "Japón y Corea"), ("(4)", "EE.UU. y Brasil NTSC"),
    ("(A)", "Australia"), ("(B)", "fuera de EE.UU. (Genesis)"),
    ("(C)", "China"), ("(E)", "Europa"), ("(F)", "Francia"),
]


@dataclass
class DatEntry:
    name: str
    crc32: int
    fsize: int
    flags: list[str] = field(default_factory=list)
    country: str | None = None
    is_good_dump: bool = False
    origen: str = "oficial"  # "oficial" (.dat original) o "usuario" (UserCatalog)

    @property
    def resumen_flags(self) -> str:
        return ", ".join(self.flags) if self.flags else ""


def _detectar_flags_y_pais(name: str) -> tuple[list[str], str | None, bool]:
    flags = []
    for prefijo, etiqueta in FLAGS_CONOCIDOS:
        if prefijo in name:
            flags.append(etiqueta)
    es_bueno = "Volcado verificado" in flags
    pais = None
    for prefijo, etiqueta in PAISES_CONOCIDOS:
        if prefijo in name:
            pais = etiqueta
            break
    return flags, pais, es_bueno


def parse_dat_line(raw_line: bytes) -> DatEntry | None:
    """Parsea una línea de datos del .dat (la que empieza por 0xAC).
    Devuelve None si la línea no tiene ese formato o le faltan campos."""
    if not raw_line or raw_line[0] != DAT_FIELD_SEPARATOR:
        return None
    campos = raw_line.split(bytes([DAT_FIELD_SEPARATOR]))
    # campos[0] es "" (lo que hay antes del primer separador). Igual que en
    # ucon64_dat.c: dat_field[3]=name, dat_field[5]=crc32, dat_field[6]=fsize
    # — aquí, sin ese primer elemento vacío ya separado, son los índices
    # 3, 5 y 6 tal cual (ver la comprobación empírica contra ROMs reales).
    try:
        name = campos[4].decode("latin-1").strip()
        crc32 = int(campos[6].decode("ascii"), 16)
        if campos[7][:1] == b"N" and len(campos) > 9 and campos[8][:1] == b"O":
            # caso especial de ucon64_dat.c: "NO" en vez de un tamaño
            # (bad CRC conocido en algunos .dat de GoodXXXX) — el tamaño
            # real está un campo más allá.
            fsize = int(campos[9].decode("ascii"))
        else:
            fsize = int(campos[7].decode("ascii"))
    except (IndexError, ValueError, UnicodeDecodeError):
        return None
    if not name:
        return None
    flags, pais, es_bueno = _detectar_flags_y_pais(name)
    return DatEntry(name=name, crc32=crc32, fsize=fsize, flags=flags,
                     country=pais, is_good_dump=es_bueno)


class DatDatabase:
    """Índice CRC32 -> DatEntry para un archivo .dat. Carga perezosa: el
    archivo no se lee hasta la primera búsqueda, para no ralentizar el
    arranque de la aplicación con algo que muchas sesiones no llegan a
    usar."""

    def __init__(self, ruta: str):
        self._ruta = ruta
        self._indice: dict[int, DatEntry] | None = None

    def _asegurar_cargado(self):
        if self._indice is not None:
            return
        indice: dict[int, DatEntry] = {}
        try:
            with open(self._ruta, "rb") as fh:
                datos = fh.read()
        except OSError:
            self._indice = {}
            return
        for linea in datos.replace(b"\r\n", b"\n").split(b"\n"):
            entrada = parse_dat_line(linea)
            if entrada is not None:
                indice[entrada.crc32] = entrada
        self._indice = indice

    def __len__(self) -> int:
        self._asegurar_cargado()
        return len(self._indice)

    def buscar_por_crc32(self, crc32: int) -> DatEntry | None:
        self._asegurar_cargado()
        return self._indice.get(crc32)


def calcular_crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _ruta_datos(nombre_archivo: str) -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "data", nombre_archivo)


# Las dos bases de datos que trae la aplicación. Los nombres de archivo
# concretos (con su fecha/nombre propio de cada catálogo) se mantienen tal
# cual los distribuyó su autor original, en vez de renombrarlos a algo
# genérico — así queda claro de qué compilación exacta viene cada una si
# hay que buscar/actualizar en el futuro.
SNES_DB = DatDatabase(_ruta_datos("snes-even-better.dat"))
GENESIS_DB = DatDatabase(_ruta_datos("gen-20031115.dat"))


def identificar_snes(datos_rom: bytes, tiene_cabecera_copiadora: bool) -> DatEntry | None:
    """Busca una ROM de SNES en la base de datos. `tiene_cabecera_copiadora`
    lo decide quien llama (ya se detecta en _analyze_snes con
    st.detect_copier_header) — el CRC32 del catálogo se calcula siempre
    sobre la ROM SIN esa cabecera de 512 bytes."""
    payload = datos_rom[512:] if tiene_cabecera_copiadora else datos_rom
    return SNES_DB.buscar_por_crc32(calcular_crc32(payload))


def identificar_genesis(datos_rom: bytes, tiene_cabecera_smd: bool) -> DatEntry | None:
    """Igual que identificar_snes, pero para Genesis/Mega Drive. Los
    volcados en formato SMD entrelazado tampoco coinciden con el catálogo
    tal cual — hace falta la versión BIN ya desentrelazada, que es quien
    llama debe proporcionar en `datos_rom` (no se desentrelaza aquí)."""
    return GENESIS_DB.buscar_por_crc32(calcular_crc32(datos_rom))


class UserCatalog:
    """Catálogo propio del usuario, separado por completo de los .dat
    oficiales (esos se dejan siempre intactos, tal como se distribuyeron,
    por si algún día hay una versión más nueva que los sustituya). Aquí
    se guardan las ROMs que el usuario tiene y que un catálogo de 2003 no
    puede cubrir: hacks, traducciones de fans, homebrews, revisiones
    posteriores a esa fecha, etc.

    Formato propio (JSON) en vez de RomCenter: no hace falta la
    compatibilidad con uCON64/RomCenter para un archivo que solo lee y
    escribe la propia ASturconsole — JSON es mucho más simple de generar
    y editar a mano si hiciera falta."""

    def __init__(self, ruta: str):
        self._ruta = ruta
        self._indice: dict[int, DatEntry] | None = None

    def _asegurar_cargado(self):
        if self._indice is not None:
            return
        indice: dict[int, DatEntry] = {}
        if os.path.isfile(self._ruta):
            try:
                with open(self._ruta, "r", encoding="utf-8") as fh:
                    datos = json.load(fh)
                for item in datos:
                    entrada = DatEntry(
                        name=item["name"], crc32=item["crc32"], fsize=item["fsize"],
                        flags=item.get("flags", []), country=item.get("country"),
                        is_good_dump=item.get("is_good_dump", False), origen="usuario")
                    indice[entrada.crc32] = entrada
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                pass  # catálogo de usuario corrupto o inexistente: se empieza de cero
        self._indice = indice

    def __len__(self) -> int:
        self._asegurar_cargado()
        return len(self._indice)

    def buscar_por_crc32(self, crc32: int) -> DatEntry | None:
        self._asegurar_cargado()
        return self._indice.get(crc32)

    def todas(self) -> list[DatEntry]:
        self._asegurar_cargado()
        return list(self._indice.values())

    def añadir(self, entrada: DatEntry):
        self._asegurar_cargado()
        entrada.origen = "usuario"
        self._indice[entrada.crc32] = entrada
        self._guardar()

    def renombrar(self, crc32: int, nuevo_nombre: str):
        self._asegurar_cargado()
        entrada = self._indice.get(crc32)
        if entrada is None:
            raise KeyError(f"no hay ninguna entrada con CRC32 {crc32:08x}")
        entrada.name = nuevo_nombre
        self._guardar()

    def eliminar(self, crc32: int):
        self._asegurar_cargado()
        if crc32 in self._indice:
            del self._indice[crc32]
            self._guardar()

    def _guardar(self):
        os.makedirs(os.path.dirname(self._ruta), exist_ok=True)
        datos = [
            {"name": e.name, "crc32": e.crc32, "fsize": e.fsize, "flags": e.flags,
             "country": e.country, "is_good_dump": e.is_good_dump}
            for e in self._indice.values()
        ]
        with open(self._ruta, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)


def _ruta_catalogo_usuario(sistema: str) -> str:
    return os.path.join(ws.base_dir(), "Catalogo", f"mi-catalogo-{sistema}.json")


SNES_USER_DB = UserCatalog(_ruta_catalogo_usuario("snes"))
GENESIS_USER_DB = UserCatalog(_ruta_catalogo_usuario("genesis"))


def identificar_snes_con_usuario(datos_rom: bytes, tiene_cabecera_copiadora: bool) -> DatEntry | None:
    """Como identificar_snes, pero mirando también el catálogo propio del
    usuario si el oficial no encuentra nada."""
    encontrado = identificar_snes(datos_rom, tiene_cabecera_copiadora)
    if encontrado is not None:
        return encontrado
    payload = datos_rom[512:] if tiene_cabecera_copiadora else datos_rom
    return SNES_USER_DB.buscar_por_crc32(calcular_crc32(payload))


def identificar_genesis_con_usuario(datos_rom: bytes, tiene_cabecera_smd: bool) -> DatEntry | None:
    encontrado = identificar_genesis(datos_rom, tiene_cabecera_smd)
    if encontrado is not None:
        return encontrado
    return GENESIS_USER_DB.buscar_por_crc32(calcular_crc32(datos_rom))
