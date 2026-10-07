#!/usr/bin/env python3
"""Herramienta de DESARROLLO, no parte de la aplicación empaquetada — no
se referencia desde main.py ni se incluye en asturconsole.spec.

Fusiona el catálogo personal de parches de un usuario (creado desde la
propia app, en ~/ASTURCONSOLE/Parches/mis-parches-{sistema}.json) dentro
del JSON oficial del proyecto (data/parches_oficiales_{sistema}.json).
Una vez fusionado, basta con hacer commit + push de ese archivo: el
siguiente build de GitHub Actions ya lo incluye para todo el mundo, sin
ningún otro paso ni mecanismo adicional.

Uso:
    python3 promover_parches.py snes
    python3 promover_parches.py genesis
    python3 promover_parches.py snes --origen /ruta/a/otro/mis-parches-snes.json

Sin --origen, se usa la ubicación estándar (~/ASTURCONSOLE/Parches/) del
propio usuario que ejecuta este script — útil también para fusionar el
catálogo que otra persona te haya pasado (pídele su
mis-parches-{sistema}.json y pásalo con --origen).

Una entrada que ya existiera en el oficial con datos distintos se
sobrescribe con la del catálogo personal (se asume que la personal es la
más reciente/confirmada) — se muestra un aviso para cada caso así, por
si conviene revisarlo a mano antes de confirmar.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parches_conocidos as pc  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sistema", choices=["snes", "genesis"])
    ap.add_argument("--origen", default=None,
                    help="Ruta del mis-parches-{sistema}.json a fusionar "
                         "(por defecto, el propio de este usuario)")
    args = ap.parse_args()

    ruta_origen = args.origen or pc._ruta_catalogo_usuario(args.sistema)
    ruta_oficial = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data", f"parches_oficiales_{args.sistema}.json")

    if not os.path.isfile(ruta_origen):
        print(f"No se encontró el catálogo de origen: {ruta_origen}")
        return 1

    with open(ruta_origen, "r", encoding="utf-8") as fh:
        entradas_origen = json.load(fh)
    entradas_oficial = {}
    if os.path.isfile(ruta_oficial):
        with open(ruta_oficial, "r", encoding="utf-8") as fh:
            entradas_oficial = json.load(fh)

    nuevas, actualizadas = [], []
    for crc, campos in entradas_origen.items():
        crc = crc.lower()
        if crc not in entradas_oficial:
            nuevas.append(crc)
        elif entradas_oficial[crc] != campos:
            actualizadas.append(crc)
        entradas_oficial[crc] = campos

    with open(ruta_oficial, "w", encoding="utf-8") as fh:
        json.dump(entradas_oficial, fh, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"Fusionado en {ruta_oficial}")
    print(f"  {len(nuevas)} entrada(s) nueva(s): {', '.join(nuevas) or '(ninguna)'}")
    print(f"  {len(actualizadas)} entrada(s) actualizada(s) (revisa si tiene sentido): "
          f"{', '.join(actualizadas) or '(ninguna)'}")
    print(f"  {len(entradas_oficial)} entrada(s) en total en el archivo oficial")
    print("\nAhora: git add, commit y push de este archivo para que se incluya "
          "en el próximo build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
