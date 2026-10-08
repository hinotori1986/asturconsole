"""Persistencia de la selección y de la posición de scroll en las listas de
archivos que se reconstruyen desde cero (ventana de trabajo y explorador).

Sin esto, cada vez que la lista se volvía a rellenar (al terminar una
herramienta, al pulsar «Actualizar», al filtrar o al volver a una carpeta)
saltaba al principio y se perdía la selección, algo muy pesado con carpetas
de decenas o cientos de ROMs que se van probando una a una.

Uso típico, dentro de un `_poblar()`:

    estado = capturar_estado(self.lista, ruta_de_item)   # antes de clear()
    self.lista.clear(); ...añadir items...
    restaurar_estado(self.lista, estado, ruta_de_item)    # al final

`ruta_de_item(item)` devuelve la clave estable del elemento (normalmente su
ruta de archivo) o None si el elemento no debe recordarse.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer


def capturar_estado(lista, ruta_de_item) -> dict:
    """Foto de la selección, el elemento actual y el scroll de `lista`."""
    seleccion = set()
    for it in lista.selectedItems():
        r = ruta_de_item(it)
        if r is not None:
            seleccion.add(r)
    actual = lista.currentItem()
    return {
        "seleccion": seleccion,
        "actual": ruta_de_item(actual) if actual is not None else None,
        "scroll": lista.verticalScrollBar().value(),
    }


def restaurar_estado(lista, estado: dict | None, ruta_de_item) -> None:
    """Devuelve a `lista` la selección y el scroll guardados en `estado`.

    Lo que ya no exista (archivo borrado o filtrado) simplemente se ignora.
    El scroll se reaplica también un instante después, porque en vista de
    iconos el rango de la barra no se conoce hasta que Qt termina de
    colocar los elementos.
    """
    if not estado:
        return
    seleccion = estado.get("seleccion") or set()
    actual = estado.get("actual")
    primero = None
    if seleccion or actual is not None:
        lista.blockSignals(True)
        try:
            for i in range(lista.count()):
                it = lista.item(i)
                r = ruta_de_item(it)
                if r is None:
                    continue
                if r in seleccion:
                    it.setSelected(True)
                    if primero is None:
                        primero = it
                if r == actual:
                    lista.setCurrentItem(it)
        finally:
            lista.blockSignals(False)
        # las señales estaban bloqueadas: avisar una sola vez del cambio
        lista.itemSelectionChanged.emit()

    scroll = int(estado.get("scroll") or 0)

    def _aplicar():
        try:
            lista.doItemsLayout()
            barra = lista.verticalScrollBar()
            barra.setValue(min(scroll, barra.maximum()))
        except RuntimeError:   # la lista ya se destruyó (ventana cerrada)
            pass

    _aplicar()
    QTimer.singleShot(0, _aplicar)
