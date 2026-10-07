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
from dataclasses import asdict, dataclass

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

    def vacio(self) -> bool:
        return not (self.crack or self.pal or self.slowrom
                     or self.checksum or self.region)


def _parches_desde_dict(campos: dict) -> ParchesConocidos:
    flags = dict(
        crack=campos.get("crack", False),
        pal=campos.get("pal", False),
        slowrom=campos.get("slowrom", False),
        checksum=campos.get("checksum", False),
        region=campos.get("region", False),
        notas=campos.get("notas", ""))
    # Migración de entradas guardadas antes de que existiera "estado": si
    # el JSON no lo trae pero alguna casilla está a True, es una entrada
    # de "necesita_parche" de toda la vida — no se pierde información al
    # cargarla con el nuevo esquema.
    estado = campos.get("estado")
    if estado is None:
        algun_flag = flags["crack"] or flags["pal"] or flags["slowrom"] \
            or flags["checksum"] or flags["region"]
        estado = ESTADO_NECESITA_PARCHE if algun_flag else ESTADO_DESCONOCIDO
    return ParchesConocidos(estado=estado, **flags)


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
        self._indice[crc32_hex.lower()] = parches
        os.makedirs(os.path.dirname(self._ruta), exist_ok=True)
        datos = {crc: asdict(p) for crc, p in self._indice.items()}
        with open(self._ruta, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)


def _ruta_catalogo_usuario(sistema: str) -> str:
    return os.path.join(ws.base_dir(), "Parches", f"mis-parches-{sistema}.json")


SNES_USER_DB = UserPatchCatalog(_ruta_catalogo_usuario("snes"))
GENESIS_USER_DB = UserPatchCatalog(_ruta_catalogo_usuario("genesis"))


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
              "que uCON64 -f. Se neutraliza solo con destino NTSC.",
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
              "(U)' coincide por casualidad en esta ROM y es incorrecto: se excluye.",
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


def buscar(sistema: str, crc32_hex: str) -> ParchesConocidos:
    """Devuelve los parches conocidos para este CRC32 exacto — primero en
    la lista oficial, luego en el catálogo de usuario — o una entrada
    vacía (todo desmarcado) si el juego no está en ninguna de las dos."""
    tabla = SNES if sistema == "snes" else GENESIS if sistema == "genesis" else {}
    encontrado = tabla.get(crc32_hex.lower())
    if encontrado is not None:
        return encontrado
    user_db = SNES_USER_DB if sistema == "snes" else GENESIS_USER_DB if sistema == "genesis" else None
    if user_db is not None:
        encontrado = user_db.buscar(crc32_hex)
        if encontrado is not None:
            return encontrado
    return ParchesConocidos()


def guardar_en_catalogo_usuario(sistema: str, crc32_hex: str, parches: ParchesConocidos):
    """Añade o actualiza una entrada en el catálogo de usuario de este
    sistema — para cuando el propio usuario confirma (normalmente
    probando en hardware real) que una combinación de parches funciona
    para un juego que la lista oficial aún no cubre."""
    user_db = SNES_USER_DB if sistema == "snes" else GENESIS_USER_DB if sistema == "genesis" else None
    if user_db is not None:
        user_db.guardar(crc32_hex, parches)

