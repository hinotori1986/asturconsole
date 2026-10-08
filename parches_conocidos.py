"""Base de datos de parches conocidos, por juego — para decidir qué
casillas de "parches al vuelo" pre-marcar en la ventana de transferencia
SIN depender de ejecutar los patrones de búsqueda binaria sobre el ROM
para ver si "coinciden" (eso puede dar falsos positivos: por ejemplo, un
patrón de 3 bytes de detección de SlowROM que coincidió por pura
casualidad en un punto cualquiera de un ROM de varios megabytes, sin que
el juego tuviera relación real con esa protección).

En su lugar, este módulo identifica el juego de forma fiable (por su
CRC32, el mismo que ya se calcula en otras partes de la aplicación) y
consulta una lista curada de qué parches le hacen falta de verdad,
verificados uno a uno — no una heurística genérica aplicada a ciegas.

Mientras la lista no contenga el juego en cuestión, TODAS las casillas
de parches empiezan desmarcadas por defecto: es preferible no marcar
nada a marcar algo por una coincidencia casual — el usuario conserva
siempre el control manual completo.

Hay dos niveles, incluso con el mismo formato JSON, para poder fusionar
uno dentro del otro con una simple copia de claves:

- Lista OFICIAL (data/parches_oficiales_{sistema}.json): se empaqueta
  con la aplicación —igual que los catálogos GoodSNES/GoodGen ya
  empaquetados en data/— así que cualquiera que descargue el ejecutable
  ya la lleva incluida, sin mecanismo extra alguno.
- Catálogo de USUARIO (UserPatchCatalog, en la carpeta de ASTURCONSOLE
  del propio usuario, fuera del ejecutable): lo que cada usuario va
  descubriendo y confirmando por su cuenta, para juegos que la lista
  oficial aún no cubre. buscar() consulta primero la oficial y, si no
  encuentra nada, el catálogo de usuario.

Cuando una entrada del catálogo de usuario queda confirmada y se quiere
que la lleve todo el mundo de fábrica, se "promueve" copiándola al JSON
oficial correspondiente (ver herramientas_dev/promover_parches.py) y
subiendo ese archivo al repositorio — se incluirá solo en el próximo
build, no hace falta ningún otro paso.

Además de "qué parches aplicar", cada entrada lleva un estado de
compatibilidad general con el Super Wild Card / Super Magic Drive:
ESTADO_COMPATIBLE (funciona tal cual, sin nada), ESTADO_NECESITA_PARCHE
(funciona solo con los parches indicados en los campos de más abajo) o
ESTADO_INCOMPATIBLE (no funciona en el copión, no hay parche conocido
todavía). ESTADO_DESCONOCIDO es el valor por defecto para cualquier
juego que no esté en ninguna de las dos listas — no significa
"compatible", significa que sencillamente no se ha probado.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field

import catalogo_sync as cs
import workspace as ws

ESTADO_DESCONOCIDO = "desconocido"
ESTADO_COMPATIBLE = "compatible"
ESTADO_NECESITA_PARCHE = "necesita_parche"
ESTADO_INCOMPATIBLE = "incompatible"


def _app_base_dir() -> str:
    """Carpeta base de la app: la del ejecutable si PyInstaller la ha
    empaquetado (sys._MEIPASS), o la del propio script en ejecución
    normal. Duplicado de main.py/transfer_ucon64.py/file_workbench.py —
    mismo motivo: no crear una dependencia circular entre módulos por
    una sola función."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


@dataclass
class ParchesConocidos:
    estado: str = ESTADO_DESCONOCIDO
    crack: bool = False       # SNES: -k, quitar protección anti-copia
    pal: bool = False         # SNES: -f, corregir NTSC/PAL
    slowrom: bool = False     # SNES: -l, quitar comprobación SlowROM
    checksum: bool = False    # SNES y Genesis: --chk, corregir checksum
    region: bool = False      # Genesis: -f, quitar protección regional (NTSC/PAL)
    notas: str = ""
    # SNES, solo catálogo de usuario: lo que el usuario ha marcado PARA
    # CADA consola de destino por separado, {"NTSC": {...}, "PAL": {...}}
    # (cada valor: estado + crack/pal/slowrom/checksum). Un juego PAL en
    # consola NTSC suele necesitar -k y -f, y en consola PAL solo -k: son
    # dos fichas distintas y cada una se guarda y se recupera por separado.
    # Los campos planos de arriba pasan a ser la UNIÓN de las dos fichas
    # (los lectores antiguos, que no saben de destinos, siguen viendo algo
    # coherente); si "destinos" está vacío, la entrada es del formato
    # antiguo (una sola ficha plana para cualquier destino).
    destinos: dict = field(default_factory=dict)
    # True = esta entrada (o, en el formato por destinos, esta ficha) la
    # ha marcado/desmarcado el USUARIO a mano en la aplicación. Solo esas
    # marcas ganan al catálogo que la aplicación instala por su cuenta
    # (ver catalogo_sync): el resto de lo que haya en el archivo del
    # usuario (copias antiguas, entradas importadas) cede ante él.
    usuario: bool = False

    def vacio(self) -> bool:
        return not (self.crack or self.pal or self.slowrom
                     or self.checksum or self.region)

    def para_destino(self, destino: str) -> "ParchesConocidos | None":
        """La ficha propia de este destino ("NTSC"/"PAL"), o None si el
        usuario nunca ha guardado nada para él. Una ficha con estado
        'desconocido' y sin casillas SÍ es un valor válido: significa que
        el usuario la ha vaciado a propósito (ver UserPatchCatalog.
        guardar_destino) y no debe volver a aparecer la sugerencia
        oficial en su lugar."""
        d = self.destinos.get(destino)
        if d is None:
            return None
        return ParchesConocidos(
            estado=d["estado"], crack=d["crack"], pal=d["pal"],
            slowrom=d["slowrom"], checksum=d["checksum"], notas=self.notas,
            usuario=bool(d.get("usuario", False)))


DESTINOS_SNES = ("NTSC", "PAL")


def _ficha_destino(parches: "ParchesConocidos", usuario: bool = False) -> dict:
    ficha = dict(estado=parches.estado, crack=bool(parches.crack),
                 pal=bool(parches.pal), slowrom=bool(parches.slowrom),
                 checksum=bool(parches.checksum))
    if usuario:
        ficha["usuario"] = True     # solo se escribe cuando es cierto
    return ficha


def _destinos_desde_dict(crudo) -> dict:
    """Lee el campo "destinos" de un JSON, tolerando cualquier basura
    (claves desconocidas, tipos raros) sin lanzar: lo que no se entienda
    se descarta."""
    destinos: dict = {}
    if not isinstance(crudo, dict):
        return destinos
    for destino, d in crudo.items():
        if destino not in DESTINOS_SNES or not isinstance(d, dict):
            continue
        flags = {k: bool(d.get(k, False)) for k in ("crack", "pal", "slowrom", "checksum")}
        estado = d.get("estado")
        if estado not in (ESTADO_DESCONOCIDO, ESTADO_COMPATIBLE,
                          ESTADO_NECESITA_PARCHE, ESTADO_INCOMPATIBLE):
            estado = ESTADO_NECESITA_PARCHE if any(flags.values()) else ESTADO_DESCONOCIDO
        destinos[destino] = dict(estado=estado, **flags)
        if d.get("usuario") is True:
            destinos[destino]["usuario"] = True
    return destinos


def _recalcular_planos(p: "ParchesConocidos"):
    """Deja los campos planos de la entrada como unión de sus fichas por
    destino (ver el comentario de ParchesConocidos.destinos)."""
    fichas = list(p.destinos.values())
    p.crack = any(f["crack"] for f in fichas)
    p.pal = any(f["pal"] for f in fichas)
    p.slowrom = any(f["slowrom"] for f in fichas)
    p.checksum = any(f["checksum"] for f in fichas)
    estados = [f["estado"] for f in fichas]
    for candidato in (ESTADO_NECESITA_PARCHE, ESTADO_INCOMPATIBLE, ESTADO_COMPATIBLE):
        if candidato in estados:
            p.estado = candidato
            break
    else:
        p.estado = ESTADO_DESCONOCIDO


def _parches_desde_dict(campos: dict) -> ParchesConocidos:
    flags = dict(
        crack=campos.get("crack", False),
        pal=campos.get("pal", False),
        slowrom=campos.get("slowrom", False),
        checksum=campos.get("checksum", False),
        region=campos.get("region", False),
        notas=campos.get("notas", ""))
    destinos = _destinos_desde_dict(campos.get("destinos"))
    # Migración de entradas guardadas antes de que existiera "estado": si
    # el JSON no lo trae pero alguna casilla está a True, es una entrada
    # de "necesita_parche" de toda la vida — no se pierde información al
    # cargarla con el nuevo esquema.
    estado = campos.get("estado")
    if estado is None:
        algun_flag = flags["crack"] or flags["pal"] or flags["slowrom"] \
            or flags["checksum"] or flags["region"]
        estado = ESTADO_NECESITA_PARCHE if algun_flag else ESTADO_DESCONOCIDO
    return ParchesConocidos(estado=estado, destinos=destinos,
                            usuario=campos.get("usuario") is True, **flags)


def _cargar_json_parches(ruta: str) -> dict[str, ParchesConocidos]:
    """Lee un archivo con el esquema {crc32_hex: {crack, pal, ...}} —
    usado tanto para las listas oficiales empaquetadas como para el
    catálogo de usuario, exactamente el mismo formato en los dos casos."""
    indice: dict[str, ParchesConocidos] = {}
    if os.path.isfile(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as fh:
                datos = json.load(fh)
            for crc, campos in datos.items():
                indice[crc.lower()] = _parches_desde_dict(campos)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
            pass  # archivo corrupto o ilegible: se trata como si estuviera vacío
    return indice


# Clave: CRC32 del ROM en hexadecimal, minúsculas, sin "0x" — se calcula
# sobre el cuerpo del ROM sin cabecera de copiador (el mismo criterio que
# usa el resto de la aplicación al analizar ROMs). Se indexa por CRC32 y
# no por nombre de archivo porque el nombre no es fiable (puede venir
# renombrado, con o sin región/idioma indicados, etc.) — el CRC32 del
# contenido sí identifica el volcado exacto de forma inequívoca.
#
# Cargadas una sola vez, al importar el módulo, desde data/ — no
# hardcodeadas como diccionario Python: así "publicar" un descubrimiento
# nuevo es solo editar/fusionar un JSON, sin tocar código ni arriesgarse
# a un error de sintaxis Python en un diccionario cada vez más largo.
SNES: dict[str, ParchesConocidos] = _cargar_json_parches(
    os.path.join(_app_base_dir(), "data", "parches_oficiales_snes.json"))

GENESIS: dict[str, ParchesConocidos] = _cargar_json_parches(
    os.path.join(_app_base_dir(), "data", "parches_oficiales_genesis.json"))


class UserPatchCatalog:
    """Catálogo propio del usuario, en JSON, separado por completo de las
    listas oficiales de arriba (esas quedan siempre intactas en el
    código fuente, y se sobrescriben con cada actualización de la app —
    guardar aquí una entrada nunca se pierde por eso). Mismo patrón que
    dat_database.UserCatalog."""

    def __init__(self, ruta: str):
        self._ruta = ruta
        self._indice: dict[str, ParchesConocidos] | None = None

    def _asegurar_cargado(self):
        if self._indice is None:
            self._indice = _cargar_json_parches(self._ruta)

    def buscar(self, crc32_hex: str) -> ParchesConocidos | None:
        self._asegurar_cargado()
        return self._indice.get(crc32_hex.lower())

    def guardar(self, crc32_hex: str, parches: ParchesConocidos):
        self._asegurar_cargado()
        parches.usuario = True      # lo marca el usuario: gana al catálogo de la app
        self._indice[crc32_hex.lower()] = parches
        self._escribir()

    def borrar(self, crc32_hex: str):
        self._asegurar_cargado()
        if self._indice.pop(crc32_hex.lower(), None) is not None:
            self._escribir()

    def _escribir(self):
        os.makedirs(os.path.dirname(self._ruta), exist_ok=True)
        datos = {}
        for crc, p in self._indice.items():
            campos = asdict(p)
            if not p.destinos:
                campos.pop("destinos")  # formato antiguo: sin ruido en el JSON
            if not p.usuario:
                campos.pop("usuario")   # la marca solo se escribe cuando es cierta
            datos[crc] = campos
        # Escritura atómica: un corte a mitad no deja el catálogo a medias,
        # y ahora se escribe a CADA casilla que se marca/desmarca.
        tmp = self._ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self._ruta)

    def buscar_destino(self, crc32_hex: str, destino: str) -> ParchesConocidos | None:
        entrada = self.buscar(crc32_hex)
        return entrada.para_destino(destino) if entrada is not None else None

    def guardar_destino(self, crc32_hex: str, destino: str, parches: ParchesConocidos,
                        notas: str = "", sembrar: dict | None = None):
        """Guarda la ficha de UN destino sin tocar la del otro. Si la
        entrada existente es del formato antiguo (una ficha plana válida
        para cualquier destino, sin "destinos"), `sembrar` ({"NTSC"|"PAL":
        ParchesConocidos}) da lo que esa ficha antigua significaba para
        los otros destinos, para que al pasar al formato nuevo no se
        pierda lo que ya estaba guardado."""
        self._asegurar_cargado()
        crc = crc32_hex.lower()
        entrada = self._indice.get(crc)
        if entrada is None:
            entrada = ParchesConocidos()
            self._indice[crc] = entrada
        elif not entrada.destinos and sembrar and \
                (entrada.estado != ESTADO_DESCONOCIDO or not entrada.vacio()):
            for otro, ficha in sembrar.items():
                if otro != destino and otro in DESTINOS_SNES:
                    entrada.destinos[otro] = _ficha_destino(ficha)
        entrada.destinos[destino] = _ficha_destino(parches, usuario=True)
        if notas:
            entrada.notas = notas
        _recalcular_planos(entrada)
        self._escribir()

    def borrar_destino(self, crc32_hex: str, destino: str):
        """Olvida la ficha de un destino (vuelve a su estado inicial). Si
        ya no queda ninguna, la entrada entera desaparece del catálogo."""
        self._asegurar_cargado()
        crc = crc32_hex.lower()
        entrada = self._indice.get(crc)
        if entrada is None or destino not in entrada.destinos:
            return
        del entrada.destinos[destino]
        if entrada.destinos:
            _recalcular_planos(entrada)
        else:
            del self._indice[crc]
        self._escribir()


def _ruta_catalogo_usuario(sistema: str) -> str:
    return os.path.join(ws.base_dir(), "Parches", f"mis-parches-{sistema}.json")


def _ruta_catalogo_app(sistema: str) -> str:
    return os.path.join(ws.base_dir(), cs.CARPETA_PARCHES, cs.ARCHIVOS_APP[sistema])


# DOS archivos en ~/ASTURCONSOLE/Parches/ para que nadie se pise:
#   * mis-parches-{sistema}.json  -> el del USUARIO. La aplicación solo lo
#     escribe cuando el usuario marca/desmarca algo; nunca lo sobrescribe
#     una actualización.
#   * parches-{sistema}-asturconsole.json -> el de la APLICACIÓN. Lo genera
#     catalogo_sync en cada arranque (catálogo de fábrica + las entradas
#     del archivo del usuario que la aplicación no tenga). Es de solo
#     lectura para el resto del código: se puede regenerar sin perder nada.
SNES_USER_DB = UserPatchCatalog(_ruta_catalogo_usuario("snes"))
GENESIS_USER_DB = UserPatchCatalog(_ruta_catalogo_usuario("genesis"))
SNES_APP_DB = UserPatchCatalog(_ruta_catalogo_app("snes"))
GENESIS_APP_DB = UserPatchCatalog(_ruta_catalogo_app("genesis"))


def _bases(sistema: str):
    """(oficial, catalogo_usuario, catalogo_app) de un sistema."""
    if sistema == "snes":
        return SNES, SNES_USER_DB, SNES_APP_DB
    if sistema == "genesis":
        return GENESIS, GENESIS_USER_DB, GENESIS_APP_DB
    return {}, None, None


def _tiene_marca(e: ParchesConocidos | None) -> bool:
    """¿Hay en esta entrada algo marcado a mano por el usuario?"""
    return e is not None and (
        e.usuario or any(d.get("usuario") for d in e.destinos.values()))


@dataclass
class VarianteDual:
    """Para el puñado de juegos donde adaptar la ROM a la región contraria
    a la nativa del dump exige INVERTIR su propia comprobación de región
    (ver snes_crack.aplicar_inversion_region), no neutralizarla sin más
    como el resto de "pal" en ParchesConocidos — normalmente porque el
    juego tiene código genuinamente distinto según la región (velocidad,
    timing de animación/música) y forzar siempre el mismo camino sería
    incorrecto para quien vaya a usarlo en la región nativa.

    Por eso estos juegos no llevan pal=True en su ParchesConocidos base
    (el motor genérico de -f no tiene ningún patrón para su comprobación
    de región, que vive aparte en PATRONES_INVERSION_REGION) y en su lugar
    tienen una entrada aquí: el usuario elige a qué consola de destino
    quiere la copia (DualRegionCopyDialog en main.py), y solo si elige la
    región CONTRARIA a la nativa se aplica también la inversión."""
    region_nativa: str        # "PAL" o "NTSC" -- la que ya funciona solo con `base`
    base: ParchesConocidos    # parches que hacen falta SIEMPRE, sea cual sea el destino
    patron_descripcion: str   # descripción exacta de su entrada en snes_crack.PATRONES_INVERSION_REGION -- ver aplicar_inversion_region
    notas: str = ""


# Igual que SNES/GENESIS más arriba: por ahora un diccionario Python
# pequeño y curado a mano (no un JSON en data/) porque cada entrada implica
# también un patrón concreto en snes_crack.PATRONES_INVERSION_REGION —
# publicar una de estas no es solo copiar una línea de JSON, así que de
# momento no tiene sentido separar los datos del código como sí ocurre con
# el catálogo de parches simples.
VARIANTES_DUALES_SNES: dict[str, VarianteDual] = {
    "3a571132": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Claymates (Europe)"),
        patron_descripcion="Claymates (Europe)",
        notas="Región nativa PAL (HiROM FastROM de 1 MB, solo ROM). Comprobación "
              "directa de $213F (BIT #$0010 + BNE) en $CC:834C, confirmada con "
              "trazas reales y probada por el usuario. Se neutraliza solo si el "
              "destino elegido es NTSC.",
    ),
    "b581e100": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Clay Fighter (Europe)"),
        patron_descripcion="Clay Fighter (Europe)",
        notas="Región nativa PAL (HiROM FastROM de 2 MB, solo ROM). Mismo "
              "mecanismo que Clay Fighter (U) con la polaridad invertida: "
              "INFERIDO por análisis estático, pendiente de confirmar con "
              "una traza o en hardware. Se aplica solo con destino NTSC.",
    ),
    "2832c824": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Pinocchio (Europe)"),
        patron_descripcion="Pinocchio (Europe)",
        notas="Región nativa PAL (HiROM FastROM de 3 MB, solo ROM). Aviso real "
              "confirmado (texto «THIS VERSION OF PINOCCHIO IS DESIGNED TO RUN "
              "ON A PAL MACHINE ONLY» en el ROM) -- se neutraliza el BEQ de la "
              "única lectura de $213F solo si el destino elegido es NTSC. "
              "CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "e4925f15": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="The Adventures of Dr. Franken (Europe)"),
        patron_descripcion="The Adventures of Dr. Franken (Europe)",
        notas="Región nativa PAL, sin protección anti-copia detectada. "
              "Aviso de región confirmado por captura real del usuario "
              "(texto no localizable por búsqueda directa, posible fuente "
              "de tiles propia) -- se neutraliza solo para destino NTSC.",
    ),
    "1ad61bd0": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="90 Minutes - European Prime Goal (Europe)"),
        patron_descripcion="90 Minutes - European Prime Goal (Europe)",
        notas="Región nativa PAL, sin protección anti-copia detectada. "
              "Comprobación de región confirmada real (texto de aviso "
              "encontrado y verificado en la ROM) -- se neutraliza solo "
              "si el destino elegido es NTSC. CONFIRMADO por el usuario en "
              "hardware real con destino NTSC.",
    ),
    "17657db6": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE, crack=True,
                               notas="Donkey Kong Country (E) Rev1"),
        patron_descripcion="Donkey Kong Country (E) Rev1",
        notas="Protección de escritura/lectura de SRAM (parche 1) necesaria "
              "siempre, en cualquier consola. La comprobación de región "
              "(parche 2) se invierte solo si el destino elegido es NTSC "
              "-- para PAL (la región nativa de este dump) no hace falta "
              "tocarla. CONFIRMADO por el usuario en hardware real (NTSC y PAL).",
    ),
    "ad2cbf9c": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE, crack=True,
                               notas="Super Metroid (Europe)"),
        patron_descripcion="Super Metroid (Europe)",
        notas="Región nativa PAL (LoROM de 3 MB, 8 KB de SRAM). Necesita -k "
              "(protección de SRAM) en CUALQUIER consola; con destino NTSC "
              "además se neutralizan sus 2 comprobaciones de $213F (-f). "
              "CONFIRMADO por el usuario en hardware real.",
    ),
    "d7e4732f": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="X-Kaliber 2097 (Europe)"),
        patron_descripcion="X-Kaliber 2097 (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB, sin SRAM). Única lectura de "
              "$213F en $00:CA95 (BIT #$10 + BEQ sobre un RTS); en NTSC cae en "
              "la pantalla de aviso. Hallado con trazas reales; mismo resultado "
              "que uCON64 -f. Se neutraliza solo con destino NTSC. CONFIRMADO por "
              "el usuario en hardware real con destino NTSC.",
    ),
    "6a455ee2": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Wolfenstein 3D (Europe)"),
        patron_descripcion="Wolfenstein 3D (Europe)",
        notas="Región nativa PAL (HiROM de 1 MB, FastROM, sin SRAM). Única lectura "
              "de $213F en $C0:743A (código compilado en C: AND #$10, CMP #$10, "
              "BNE +1, INX); en NTSC cae en la pantalla de aviso. Se neutraliza "
              "el BNE (D0 01 -> EA EA) para que se comporte como PAL. uCON64 -f "
              "no lo detecta. CONFIRMADO por el usuario en hardware real "
              "(Super Wild Card) con destino NTSC.",
    ),
    "019c4b02": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="WeaponLord (Europe)"),
        patron_descripcion="WeaponLord (Europe)",
        notas="Región nativa PAL (HiROM de 3 MB, FastROM, sin SRAM). Única "
              "comprobación real de $213F en $EA:487D (BIT #$10 + BNE sobre un "
              "RTL); en NTSC cae en la pantalla de aviso. Se cambia BNE por BRA "
              "(D0 -> 80). uCON64 -f no lo detecta. CONFIRMADO por el usuario "
              "en hardware real con destino NTSC.",
    ),
    "531463e1": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Top Gear 2 (Europe)"),
        patron_descripcion="Top Gear 2 (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB, sin SRAM). Rutina de detección "
              "en $81:F900: lee STAT78 y mide la duración del vblank, y deja "
              "$FC/$FD a $FF (NTSC) o $00 (PAL); $81:F845 las lee juntas "
              "(LDA de 16 bits) y salta al aviso si no son 0. Hay que anular "
              "las DOS condiciones (BEQ y BCC -> NOP NOP). uCON64 -f no lo "
              "detecta. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "974523ff": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Terranigma (Europe)"),
        patron_descripcion="Terranigma (Europe)",
        notas="Región nativa PAL (HiROM de 4 MB). Única comprobación real de "
              "$213F en $87:97C9, dentro de un script del intérprete de bytecode "
              "del juego (BIT #$10 + BNE sobre un JMP al aviso). Se cambia BNE "
              "por BRA (D0 -> 80), igual que uCON64 -f. La lista de "
              "compatibilidad de uCON64 la da como 'funciona sin parche', pero "
              "en consola NTSC necesita este fix. El patrón genérico 'Mighty Max "
              "(U)' coincide por casualidad en esta ROM y es incorrecto: se excluye. "
              "CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "94fd16a5": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Super Putty (Europe)"),
        patron_descripcion="Super Putty (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB, sin SRAM). Única lectura de "
              "$213F en $01:E9FC (AND #$10 + BNE sobre un RTL); en NTSC cae en "
              "la pantalla de aviso. Se cambia BNE por BRA (D0 -> 80). uCON64 -f "
              "no lo detecta. CONFIRMADO por el usuario en hardware real con "
              "destino NTSC.",
    ),
    "6d86bfb0": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Super Street Fighter II (Europe)"),
        patron_descripcion="Super Street Fighter II (Europe)",
        notas="Región nativa PAL (HiROM de 4 MB, sin SRAM). Única lectura de "
              "$213F en $C0:120D, tras leer el país de su propia cabecera "
              "($C0:FFD9); en NTSC cae en la pantalla de aviso. Se cambia BNE "
              "por BRA (D0 -> 80). uCON64 -f no lo detecta. CONFIRMADO por el "
              "usuario en hardware real con destino NTSC.",
    ),
    "3bcb5d70": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Super Pinball - Behind the Mask (Europe)"),
        patron_descripcion="Super Pinball - Behind the Mask (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 1 MB, sin SRAM). Única "
              "lectura de $213F en $00:F4BB (AND #$10 + BEQ al aviso), tras "
              "leer el país de su cabecera. Se cambia BEQ por NOP NOP (F0 0B "
              "-> EA EA). uCON64 -f no lo detecta. CONFIRMADO por el usuario "
              "en hardware real con destino NTSC.",
    ),
    "b0e4e48a": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Prehistorik Man (Europe)"),
        patron_descripcion="Prehistorik Man (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB). $82:86F2 lee STAT78 y, solo en "
              "PAL, pone a 1 el word $27; en NTSC queda con basura y el juego "
              "sigue la rama del aviso. Se cambia BEQ por NOP NOP (F0 09 -> EA EA). "
              "uCON64 -f no lo detecta. CONFIRMADO por el usuario en hardware real "
              "con destino NTSC.",
    ),
    "e0adf929": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE, crack=True,
                               notas="Samurai Shodown (Europe)"),
        patron_descripcion="Samurai Shodown (Europe)",
        notas="Región nativa PAL (HiROM FastROM de 4 MB, sin SRAM). Dos cosas: "
              "1) región, $DF:46EE (LDA.L $00213F; AND #$10; BNE), BNE por BRA, "
              "igual que uCON64 -f; 2) detector de copiadores en $DF:483A (y su "
              "copia en $C2:0000) que escribe en ROM/SRAM y se repite sin fin si "
              "el valor se guarda (SWC): se corta con RTL en las dos copias "
              "(casilla -k, siempre marcada). CONFIRMADO por el usuario en "
              "hardware real con destino NTSC.",
    ),
    "de112322": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Secret of Mana (Europe) Rev 1"),
        patron_descripcion="Secret of Mana (Europe) Rev 1",
        notas="Región nativa PAL (HiROM de 2 MB, con SRAM). El código va comprimido (LZ) y se descomprime en RAM al arrancar; la comprobación ($7E:D45A) cae en bytes sin comprimir de la ROM: LDA.L $00213F; AND #$10; CMP #$10; BEQ. Se cambia BEQ por BRA (F0 -> 80), igual que uCON64 -f. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "f6b0eaa9": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Revolution X (Europe)"),
        patron_descripcion="Revolution X (Europe)",
        notas="Región nativa PAL (LoROM de 2 MB). $81:F08D guarda el bit 4 de STAT78 en $1A20 y la rutina de arranque decide por el flag Z si muestra el aviso. Se cambia BNE por BRA (D0 -> 80) en $86:8E06. uCON64 -f no lo detecta. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "5a183e62": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="R-Type III (Europe)"),
        patron_descripcion="R-Type III (Europe)",
        notas="Región nativa PAL (LoROM de 2 MB). La comprobación se copia a RAM ($7E:D988): LDA.L $00213F; AND #$10; BNE. Se cambia BNE por BRA (D0 -> 80), igual que uCON64 -f. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "e901a947": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="BioMetal (Europe)"),
        patron_descripcion="BioMetal (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB). Rutina $00:94B1: LDA $213F; BIT #$10; BNE $9517. Con NTSC cae en tres bloques de texto de aviso y se queda en un bucle infinito (JMP $9514). Se cambia BNE por BRA (D0 -> 80) para destino NTSC. OJO: el genérico «Mighty Max» lo dejaría siempre en el aviso. uCON64 -f no lo detecta. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "f9ae28db": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Illusion of Time (Europe)"),
        patron_descripcion="Illusion of Time (Europe)",
        notas="Región nativa PAL (HiROM de 2 MB). $8B:C932: LDA $213F; BIT #$10; BNE $C93E. Con NTSC cae en JMP $C8EA (motor de scripts con el aviso). Se cambia BNE por BRA (D0 -> 80) para destino NTSC. OJO: el genérico «Mighty Max» escribiría 80 00 (mal). uCON64 -f no lo detecta. Hallado con trazas reales y CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "d56c21a1": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Donald in Maui Mallard (Europe)"),
        patron_descripcion="Donald in Maui Mallard (Europe)",
        notas="Región nativa PAL (LoROM de 3 MB). $00:E416: LDA $213F; AND #$10; CMP #$10; BEQ +3; BRL $E463. Con NTSC va por otra rama ($0832=2). Se cambia BEQ por BRA (F0 -> 80) para destino NTSC. La lectura de $00:906D solo guarda el bit y no se toca. uCON64 -f no lo detecta. Hallado con trazas reales y CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "038212ea": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Dragon - The Bruce Lee Story (Europe)"),
        patron_descripcion="Dragon - The Bruce Lee Story (Europe)",
        notas="Región nativa PAL (HiROM de 2 MB). La comprobación está duplicada ($C0:008C y $C0:268F): LDA.L $00213F; BIT #$10; BNE +4; PEA $4F5B; RTS. Con NTSC cae en el aviso ($C0:4F5C). Se cambia BNE por BRA (D0 -> 80) en las dos copias para destino NTSC. uCON64 -f no lo detecta. Hallado con trazas reales y CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "9b1ea779": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Fever Pitch Soccer (Europe)"),
        patron_descripcion="Fever Pitch Soccer (Europe)",
        notas="Región nativa PAL (LoROM de 2 MB). $00:98A0: LDA $213F; BIT #$10; BNE $98BA. Con NTSC crea el objeto del aviso y usa constantes NTSC. Se cambia BNE por BRA (D0 -> 80): siempre la inicialización PAL (el juego puede ir a velocidad de 50 Hz). OJO: el genérico «Head-On Soccer» escribiría 80 00 (mal). uCON64 -f no lo detecta. Hallado con trazas reales y CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "b9d6269d": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Joe & Mac 3 - Lost in the Tropics (Europe)"),
        patron_descripcion="Joe & Mac 3 - Lost in the Tropics (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 1 MB). $84:FF92: LDA $213F; AND #$10; BNE $FFCA. Con NTSC muestra el aviso y se queda en un bucle (BRA a sí mismo). Se cambia BNE por BRA (D0 -> 80) para destino NTSC. OJO: el genérico «Monday Night Football» corrompería el desplazamiento. uCON64 -f no lo detecta. Hallado con trazas reales y CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "a7f8d832": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Fatal Fury Special (Europe)"),
        patron_descripcion="Fatal Fury Special (Europe)",
        notas="Región nativa PAL (HiROM de 3 MB). Rutina $C2:0110: LDA.L $00213F; AND #$0010; BEQ +3 -> con NTSC el BEQ se toma y devuelve Carry=1 (aviso). Se neutraliza el BEQ (EA EA) para destino NTSC. OJO: no sirve BEQ->BRA (iría siempre al aviso; el genérico «Pac-In-Time» lo haría). uCON64 -f no lo detecta. Hallado con trazas reales y CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "d013316b": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="GP-1 (Europe)"),
        patron_descripcion="GP-1 (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB). Única lectura de $213F en $01:DF9E: BIT #$10; BEQ $DFA7 -> con NTSC salta a $E059 y escribe el texto de aviso (5 líneas). Se neutraliza el BEQ (EA EA) para destino NTSC (mismo parche que uCON64 -f usa en Super Metroid (E)). Hallado con trazas reales y CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "0ce626ba": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Hebereke's Popoitto (Europe)"),
        patron_descripcion="Hebereke's Popoitto (Europe)",
        notas="Región nativa PAL (LoROM de 512 KB). $80:815C: LDA $213F; AND #$10; BNE $8166; INC $0EF4. Con NTSC se incrementa $0EF4 y la pantalla de arranque ($80:F74B/F78D) usa otro texto y se salta la rutina de la pantalla normal. Se cambia BNE por BRA (D0 -> 80) para destino NTSC. OJO: el genérico «Monday Night Football» dejaría siempre el modo NTSC. uCON64 -f no lo detecta. Hallado con trazas reales y CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "7a313722": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Hebereke's Popoon (Europe)"),
        patron_descripcion="Hebereke's Popoon (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB). $03:8FE2: LDA.L $00213F; AND #$10; BNE $9001. Con NTSC carga el script de aviso ($9200) y se queda en un bucle (BRA a sí mismo en $03:8FFF). Se cambia BNE por BRA (D0 -> 80) para destino NTSC. uCON64 -f no lo detecta. Hallado con trazas reales y CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "6cd568a9": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="International Superstar Soccer (Europe)"),
        patron_descripcion="International Superstar Soccer (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 1 MB). Única lectura de $213F en $80:833F: AND #$10; CMP $00FFBD (byte $10 de la cabecera = PAL); BEQ $80838E. Si no coincide con la consola, pinta el aviso y se queda en BRA a sí mismo ($80:838C). Se cambia BEQ por BRA (F0 -> 80) para destino NTSC. uCON64 -f no lo detecta. Hallado con trazas reales y CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "cba724ba": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="International Superstar Soccer Deluxe (Europe)"),
        patron_descripcion="International Superstar Soccer Deluxe (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 2 MB). Única lectura de $213F en $80:83DF: AND #$10; CMP $80FFAD (byte $10 = PAL); BEQ $808449. Si no coincide con la consola, pinta el aviso y se cuelga. Se cambia BEQ por BRA (F0 -> 80) para destino NTSC. uCON64 -f no lo detecta. Hallado con trazas reales y CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "995cc0a3": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Kirby's Dream Course (Europe)"),
        patron_descripcion="Kirby's Dream Course (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 1 MB). $80:8135: LDA.L $00213F; AND #$10; BNE $814A. Con NTSC cae en JML $868000 (pantalla de aviso). Se cambia BNE por BRA (D0 -> 80) para destino NTSC. uCON64 -f no lo detecta (el genérico «Art of Fighting» escribe el mismo byte). Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "dd0d08be": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Kirby's Ghost Trap (Europe)"),
        patron_descripcion="Kirby's Ghost Trap (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 1 MB). Rutina de script $80:A32C: con NTSC pone $0302=1 y el script salta a la pantalla de aviso. Se neutraliza el BEQ (EA EA) para que $0302 quede siempre a 0, igual que el parche de uCON64 -f para Super Metroid (E). Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "588a9707": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Pop'n TwinBee (Europe)"),
        patron_descripcion="Pop'n TwinBee (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 1 MB). Rutina de Konami $80:95C3: AND #$10; CMP $80FFBD ($10 = PAL); BEQ $9634. Si no coincide pinta el aviso y se queda en un bucle. Se cambia BEQ por BRA (F0 -> 80) para destino NTSC (mismo parche que uCON64 -f usa en Lethal Enforcers (U)). Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "91a03035": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Pop'n TwinBee - Rainbow Bell Adventures (Europe)"),
        patron_descripcion="Pop'n TwinBee - Rainbow Bell Adventures (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 1 MB). Rutina de Konami $80:8DB8: AND #$10; CMP $00FFBD ($10 = PAL); BEQ $8E38. Si no coincide pinta el aviso y se queda en un bucle. Se cambia BEQ por BRA (F0 -> 80) para destino NTSC. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "1ac7f523": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Kick Off 3 - European Challenge (Europe)"),
        patron_descripcion="Kick Off 3 - European Challenge (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB). $0F:8016: LDA $213F; AND #$10; CMP #$10; BEQ $8022; JMP $9059 (aviso). Se cambia BEQ por BRA (F0 -> 80) para destino NTSC. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "7e2c7143": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Lucky Luke (Europe)"),
        patron_descripcion="Lucky Luke (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 1,5 MB). $82:D5CE: LDA $213F; AND #$00FF; BIT #$0010; BNE $D626 (RTL). Con NTSC sigue y muestra el aviso. Se cambia BNE por BRA (D0 -> 80) para destino NTSC. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "1979cf23": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Metal Marines (Europe)"),
        patron_descripcion="Metal Marines (Europe)",
        notas="Región nativa PAL (LoROM de 1,5 MB). Máquina de estados con el contador $84: el estado 0 ($00:A43C) hace LDA $213F; AND #$10; BEQ -> con PAL salta directamente al estado 3 (juego); con NTSC pasa por el estado 1 (pantalla de aviso) y se queda en el 2. Se neutraliza el BEQ (EA EA) para destino NTSC. OJO: el genérico «Bonkers» lo haría al revés (siempre aviso). uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "c65e0e5b": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Nigel Mansell's World Championship Racing (Europe) (Rev 1)"),
        patron_descripcion="Nigel Mansell's World Championship Racing (Europe) (Rev 1)",
        notas="Región nativa PAL (LoROM FastROM de 1 MB). La rutina $1F:FFCC (llamada desde $1F:A331) deja $F8/$F9 a 0 solo si la consola es PAL (STAT78 bit 4) y el contador de líneas llega a $0400; si no, salta a la pantalla de aviso. Se neutralizan los dos saltos (EA EA) para que siempre quede $F8 = $F9 = 0 (estado de una PAL real); el resto de lecturas de STAT78 (temporización) no se toca. OJO: los genéricos de la versión USA y «Super Metroid (E)» caen aquí en sentido contrario y quedan excluidos. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "79941300": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Pac-Attack (Europe)"),
        patron_descripcion="Pac-Attack (Europe)",
        notas="Región nativa PAL (LoROM de 512 KB). $00:80E9: LDA.L $00213F; AND #$0010; EOR #$0010; BEQ $8104 -> con NTSC cae en la pantalla de aviso. Se cambia BEQ por BRA (F0 -> 80) para destino NTSC. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "026f2c19": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Plok (Europe)"),
        patron_descripcion="Plok (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB). $80:DC14: LDA $213F; AND #$10; CMP #$10; BNE $DC44 -> con NTSC se toma el salto y entra en la rutina de aviso. Se neutraliza el BNE (EA EA) para destino NTSC. OJO: no sirve BNE->BRA (iría siempre al aviso). uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "fce7bade": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Kevin Keegan's Player Manager (Europe)"),
        patron_descripcion="Kevin Keegan's Player Manager (Europe)",
        notas="Región nativa PAL (LoROM de 512 KB). $07:867F: LDA $213F; AND #$10; CMP #$10; BEQ $86C8 -> con NTSC cae en un bloque que dibuja la pantalla de aviso y se queda en un bucle infinito. Se cambia BEQ por BRA (F0 -> 80) para destino NTSC. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "348be5ca": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Pac-In-Time (Europe)"),
        patron_descripcion="Pac-In-Time (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB). $80:83EE: LDA.L $00213F; AND #$0010; BNE $8418 -> con NTSC cae en un bloque que dibuja el aviso y termina en BRA $8416 (bucle infinito). Se cambia BNE por BRA (D0 -> 80) para destino NTSC. OJO: el genérico «Fatal Fury Special (U)» coincide aquí y deja el desplazamiento a 0 (siempre aviso, también en PAL); queda excluido por CRC. uCON64 -f no lo detecta. Hallado con trazas reales; CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "7bbfe8c0": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="NBA Hang Time (Europe)"),
        patron_descripcion="NBA Hang Time (Europe)",
        notas="Región nativa PAL (HiROM FastROM de 3 MB, sin chip). $C3:0DFF: LDA.L $00213F; AND #$0010; BEQ +1; RTL -> con NTSC el BEQ se toma y salta al bloque de aviso (reinicia la PPU y se queda esperando). Se neutraliza el BEQ (EA EA) para destino NTSC. OJO: el genérico «Pac-In-Time (U)» coincide aquí y lo convertiría en BRA (siempre aviso, también en PAL); queda excluido por CRC. Las otras lecturas de STAT78 son lecturas de latch. uCON64 -f no lo detecta. Hallado con trazas reales; CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "f43c155c": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Sparkster (Europe)"),
        patron_descripcion="Sparkster (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 1 MB). Comprobación de la familia Konami en $80:839D: LDA $213F; AND #$10; CMP.L $00FFAD (byte de cabecera, $10 = PAL); BEQ $83EC -> con NTSC pinta un aviso y se queda en BRA a sí mismo. Se cambia BEQ por BRA (F0 -> 80) para destino NTSC. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "6f7d1745": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Smash Tennis (Europe)"),
        patron_descripcion="Smash Tennis (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB). $00:8133: LDA $213F; AND #$10; STA $0104; LDA #$0A; LDX $0104; BNE +3; LDA #$28; STA $00 -> con NTSC el estado de la máquina de estados es $28 (pantalla de aviso en $82:A383) en vez de $0A. Se cambia BNE por BRA (D0 -> 80) para destino NTSC; el flag $0104 se deja tal cual. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "64edfc5d": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Sunset Riders (Europe)"),
        patron_descripcion="Sunset Riders (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 1 MB). $80:924E: LDA $00FFBD; AND #$10; STA $00; LDA $213F; AND #$10; CMP $00; BEQ $9261 -> con NTSC pone el estado de aviso ($0D). Se cambia BEQ por BRA (F0 -> 80) para destino NTSC. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "2a9966c0": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Soccer Kid (Europe)"),
        patron_descripcion="Soccer Kid (Europe)",
        notas="Región nativa PAL (LoROM de 1,25 MB). $8A:8D3C: REP #$30; LDA $213F; BIT #$0010; BNE $8D47; JMP $8DC5 -> con NTSC cae en el JMP a la pantalla de aviso (termina en BRA a sí mismo). Se cambia BNE por BRA (D0 -> 80) para destino NTSC. OJO: el genérico «Eric Cantona Football?» machaca el LDA en esta ROM; queda excluido por CRC. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "797e2e82": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Spirou (Europe)"),
        patron_descripcion="Spirou (Europe)",
        notas="Región nativa PAL (LoROM de 1,25 MB). Rutina $84:B0F6: LDA $213F; AND #$10; BEQ $B102 -> con NTSC salta al estado de aviso ($0686 = $15). Se neutraliza el BEQ (EA EA) para destino NTSC. Las otras lecturas de STAT78 ($82E0, $830B) son lecturas de latch. OJO: el genérico «Bonkers (U) / Captain Commando (U)» lo convertiría en BRA (siempre aviso); queda excluido por CRC. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "d1a1f7e5": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Star Trek - The Next Generation - Future's Past (Europe)"),
        patron_descripcion="Star Trek - The Next Generation - Future's Past (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 2 MB). $00:804C: LDA $213F; AND #$10; BNE $8057; JML $80D6F1 -> con NTSC cae en el JML a la pantalla de aviso. Se cambia BNE por BRA (D0 -> 80) para destino NTSC. OJO: el genérico «ABC Monday Night Football (U)» pone el desplazamiento a 0 (siempre aviso); queda excluido por CRC. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "523e4153": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Tetris & Dr. Mario (Europe)"),
        patron_descripcion="Tetris & Dr. Mario (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB). $80:BD39: LDA $213F; BIT #$10; BEQ $BD8D -> con NTSC pone el estado $19 (pantalla de aviso, que solo se alcanza desde aquí); con PAL sigue con la comprobación de cabecera y vuelve. Se neutraliza el BEQ (EA EA) para destino NTSC; el genérico «Super Metroid (E)» escribe los mismos bytes. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "6d16f5e7": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="World Cup Striker (Europe) (En Fr De)"),
        patron_descripcion="World Cup Striker (Europe)",
        notas="Región nativa PAL (HiROM de 1 MB). $82:B6FC: LDA $213F; BIT #$0010; BNE $B718 (RTS); JSR $8490 -> con NTSC no se toma el BNE y cae en el JSR a la pantalla de aviso (espera en $4212). Se cambia BNE por BRA (D0 -> 80) para destino NTSC. OJO: el genérico «Eric Cantona Football?» machaca el LDA en esta ROM; queda excluido por CRC. uCON64 -f no lo detecta. Hallado con trazas reales. Con el parche pasa el aviso en consola NTSC, pero el juego muestra fallos gráficos (glitches) por su temporización de 50 Hz: en el catálogo figura como «funciona» en consola PAL y «no funciona» en consola NTSC.",
    ),
    "0a699604": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Super Conflict (Europe)"),
        patron_descripcion="Super Conflict (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB). $00:FF02: LDA $213F; AND #$0010; BEQ $FF0B; RTL -> con NTSC salta el RTL y entra en la pantalla de aviso. Se neutraliza el BEQ (EA EA) para destino NTSC. OJO: el genérico «The Adventures of Dr. Franken (U)» lo convertiría en BRA (siempre aviso); queda excluido por CRC. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "89cd72b0": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Super International Cricket (Europe)"),
        patron_descripcion="Super International Cricket (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB). $00:80F3 guarda STAT78 en $047A y $94:FA18 hace LDA $047A; AND #$10; BNE $FA92 -> con NTSC cae en la pantalla de aviso (termina en JMP a sí mismo). Se cambia BNE por BRA (D0 -> 80) para destino NTSC. OJO: el genérico «The Adventures of Dr. Franken (U)» toca otras dos rutinas ($E2CBE y $E2CD5, no ejecutadas en las trazas) y queda excluido por CRC. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "19b69a57": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Tetris 2 (Europe)"),
        patron_descripcion="Tetris 2 (Europe)",
        notas="Región nativa PAL (LoROM de 1 MB). $80:8050: LDA $213F; BIT #$10; BNE $805B; LDA #$83 -> con NTSC elige el estado 3 de la máquina de estados (pantalla de aviso). Se cambia BNE por BRA (D0 -> 80) para destino NTSC; además se neutralizan (EA EA) 7 copias del bucle LDA $213F; BIT #$10; BEQ atrás (no ejecutadas en las trazas; en PAL nunca se toma, sin efecto). OJO: los genéricos «Mighty Max (U)» y «Terranigma» pondrían el salto a +0 (siempre aviso, también en PAL); quedan excluidos por CRC. uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "a94a47be": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Tintin - Prisoners of the Sun (Europe) (En Fr De Es)"),
        patron_descripcion="Tintin (Europe)",
        notas="Región nativa PAL. Rutina $82:D314 / $83:D04A: LDA $213F; AND #$00FF; BIT #$0010; BNE (RTL); PHA; JSL (detiene la música y muestra el aviso; queda en un bucle de espera). Con NTSC no se toma el BNE. Se cambia por BRA (D0 -> 80) para destino NTSC. Las demás lecturas de STAT78 son lecturas de latch (semilla aleatoria). uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "caed3fe4": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Tintin in Tibet (Europe) (En Es Sv)"),
        patron_descripcion="Tintin (Europe)",
        notas="Región nativa PAL. Rutina $82:D314 / $83:D04A: LDA $213F; AND #$00FF; BIT #$0010; BNE (RTL); PHA; JSL (detiene la música y muestra el aviso; queda en un bucle de espera). Con NTSC no se toma el BNE. Se cambia por BRA (D0 -> 80) para destino NTSC. Las demás lecturas de STAT78 son lecturas de latch (semilla aleatoria). uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "f1dce2b7": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Tintin in Tibet (Europe) (En Fr De Nl)"),
        patron_descripcion="Tintin (Europe)",
        notas="Región nativa PAL. Rutina $82:D314 / $83:D04A: LDA $213F; AND #$00FF; BIT #$0010; BNE (RTL); PHA; JSL (detiene la música y muestra el aviso; queda en un bucle de espera). Con NTSC no se toma el BNE. Se cambia por BRA (D0 -> 80) para destino NTSC. Las demás lecturas de STAT78 son lecturas de latch (semilla aleatoria). uCON64 -f no lo detecta. Hallado con trazas reales. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "143051a5": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Art of Fighting (Europe)"),
        patron_descripcion="Art of Fighting (Europe)",
        notas="Región nativa PAL (HiROM de 2 MB). Rutina $C0:1591: LDA.L $00213F; AND #$10; BEQ +4 -> con NTSC el BEQ se toma y devuelve Carry=1 (aviso). Se neutraliza el BEQ (EA EA) para destino NTSC. OJO: no sirve BEQ->BRA (iría siempre al aviso). uCON64 -f no lo detecta. CONFIRMADO por el usuario en hardware real con destino NTSC.",
    ),
    "fabff8bd": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Zombies Ate My Neighbors (Europe)"),
        patron_descripcion="Zombies Ate My Neighbors (Europe)",
        notas="Región nativa PAL (LoROM SlowROM de 1 MB, solo ROM). Única "
              "lectura de $213F en $80:919C (AND #$0010 + BNE); en NTSC cae "
              "en el aviso. Hallado con trazas reales y CONFIRMADO por el "
              "usuario en consola NTSC. Se neutraliza solo con destino NTSC.",
    ),
    "9a8178bf": VarianteDual(
        region_nativa="PAL",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="Yoshi's Safari (Europe)"),
        patron_descripcion="Yoshi's Safari (Europe)",
        notas="Región nativa PAL (LoROM FastROM de 1 MB, solo ROM). "
              "Comprobación de $213F en el arranque ($80:8055, AND #$10 + "
              "BNE); en NTSC entra en la pantalla de aviso. Hallado con "
              "trazas reales y CONFIRMADO por el usuario en consola NTSC. "
              "Se neutraliza solo con destino NTSC.",
    ),
    "f5ab5d91": VarianteDual(
        region_nativa="NTSC",
        base=ParchesConocidos(estado=ESTADO_NECESITA_PARCHE,
                               notas="RoboCop versus The Terminator (U)"),
        patron_descripcion="RoboCop versus The Terminator (U)",
        notas="Región nativa NTSC (dump USA normal, sin protección "
              "anti-copia detectada). La comprobación de región vive "
              "dentro del propio motor de script del juego, no en "
              "código fijo -- se invierte solo si el destino elegido es "
              "PAL; para NTSC (la región nativa) no hace falta tocar "
              "nada. Importante: el primer intento de arreglo (v1.6.x, "
              "como parche universal en PATRONES_PAL) resultó ser una "
              "INVERSIÓN, no una neutralización -- funcionaba en PAL "
              "pero rompía NTSC (mostraba el aviso donde antes no "
              "salía). Por eso este juego necesita el mecanismo de "
              "doble variante en vez de un parche simple.",
    ),
}


def buscar_variante_dual(sistema: str, crc32_hex: str) -> VarianteDual | None:
    """Devuelve la VarianteDual para este CRC32 exacto, o None si el juego
    no es de este tipo especial (el caso normal, cubierto por buscar())."""
    tabla = VARIANTES_DUALES_SNES if sistema == "snes" else {}
    return tabla.get(crc32_hex.lower())


def _candidatas(sistema: str, crc32_hex: str) -> list[ParchesConocidos]:
    """Entradas que hablan de este CRC32, de más a menos prioritaria:
      1. lo oficial incluido en la aplicación (JSON de data/);
      2. lo que el usuario ha marcado a mano;
      3. el catálogo que instala la aplicación (parches-*-asturconsole.json);
      4. lo demás del archivo del usuario (sin marcar: copias antiguas,
         entradas importadas, juegos probados sin conexión que la
         aplicación aún no haya incorporado)."""
    oficial, user_db, app_db = _bases(sistema)
    crc = crc32_hex.lower()
    cand: list[ParchesConocidos] = []
    if crc in oficial:
        cand.append(oficial[crc])
    u = user_db.buscar(crc) if user_db is not None else None
    if _tiene_marca(u):
        cand.append(u)
    a = app_db.buscar(crc) if app_db is not None else None
    if a is not None:
        cand.append(a)
    if u is not None and not _tiene_marca(u):
        cand.append(u)
    return cand


def buscar(sistema: str, crc32_hex: str) -> ParchesConocidos:
    """Devuelve los parches conocidos para este CRC32 exacto (ver el orden
    en _candidatas) o una entrada vacía (todo desmarcado) si el juego no
    está en ningún sitio."""
    cand = _candidatas(sistema, crc32_hex)
    return cand[0] if cand else ParchesConocidos()


def buscar_sugerencia(sistema: str, crc32_hex: str) -> ParchesConocidos:
    """Como buscar(), pero SIN contar las fichas por destino: en esas
    entradas los campos planos son solo la unión derivada de las fichas
    (ver ParchesConocidos.destinos), no una sugerencia del catálogo. Sirve
    de punto de partida cuando no hay ficha para el destino concreto."""
    for e in _candidatas(sistema, crc32_hex):
        if not e.destinos:
            return e
    return ParchesConocidos()


def guardar_en_catalogo_usuario(sistema: str, crc32_hex: str, parches: ParchesConocidos):
    """Añade o actualiza una entrada en el catálogo de usuario de este
    sistema — para cuando el propio usuario confirma (normalmente
    probando en hardware real) que una combinación de parches funciona
    para un juego que la lista oficial aún no cubre."""
    user_db = SNES_USER_DB if sistema == "snes" else GENESIS_USER_DB if sistema == "genesis" else None
    if user_db is not None:
        user_db.guardar(crc32_hex, parches)


def buscar_destino(sistema: str, crc32_hex: str, destino: str) -> ParchesConocidos | None:
    """Ficha guardada para este juego y esta consola de destino
    ("NTSC"/"PAL"), o None si no hay ninguna. Orden: 1) la que el USUARIO
    ha marcado a mano (lo comprobado en hardware real manda sobre todo);
    2) la del catálogo de la aplicación; 3) una ficha sin marcar del
    archivo del usuario. El resultado lleva `.usuario` = True solo en el
    primer caso, para que la interfaz sepa si es una marca del usuario."""
    if sistema != "snes":
        return None
    crc = crc32_hex.lower()
    u = SNES_USER_DB.buscar(crc)
    a = SNES_APP_DB.buscar(crc)
    for entrada, exigir_marca in ((u, True), (a, False), (u, False)):
        if entrada is None:
            continue
        ficha = entrada.para_destino(destino)
        if ficha is None:
            continue
        if exigir_marca and not ficha.usuario:
            continue
        return ficha
    return None


def buscar_destino_app(sistema: str, crc32_hex: str, destino: str) -> ParchesConocidos | None:
    """Solo la ficha del catálogo de la aplicación (sin mirar lo del
    usuario). La interfaz la usa para saber si, al vaciar un destino a
    mano, hay algo de la aplicación que volvería a aparecer."""
    if sistema != "snes":
        return None
    a = SNES_APP_DB.buscar(crc32_hex.lower())
    return a.para_destino(destino) if a is not None else None


def guardar_destino_usuario(sistema: str, crc32_hex: str, destino: str,
                            parches: ParchesConocidos, notas: str = "",
                            sembrar: dict | None = None):
    if sistema == "snes":
        SNES_USER_DB.guardar_destino(crc32_hex, destino, parches, notas, sembrar)


def borrar_destino_usuario(sistema: str, crc32_hex: str, destino: str):
    if sistema == "snes":
        SNES_USER_DB.borrar_destino(crc32_hex, destino)
