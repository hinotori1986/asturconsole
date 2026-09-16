"""Asistente de primera ejecución.

Se muestra una única vez (la primera vez que se abre la aplicación, se
recuerda con QSettings) para detectar los problemas de configuración del
sistema más comunes con la transferencia por puerto paralelo en Linux —
los que de verdad ha reportado gente usando la aplicación, no una lista
especulativa de "cosas que podrían fallar".

Deliberadamente NO se mete con nada de Windows aquí: ese caso ya tiene su
propio aviso, más específico, dentro del propio diálogo de transferencia
(ver transfer_dialog.py), porque depende de qué driver de E/S se use y no
hay una única cosa que "arreglar" de antemano.
"""
from __future__ import annotations

import os
import re
import subprocess

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

import transfer_ucon64 as tu


def _settings() -> QSettings:
    return QSettings("ASTURCONSOLE", "asturconsole")


class Problema:
    def __init__(self, titulo: str, descripcion: str,
                 comando_arreglo: list[str] | None = None,
                 etiqueta_boton: str = "Arreglar automáticamente…"):
        self.titulo = titulo
        self.descripcion = descripcion
        self.comando_arreglo = comando_arreglo
        self.etiqueta_boton = etiqueta_boton


def detectar_problemas() -> list[Problema]:
    """Verifica los problemas conocidos y devuelve solo los que aplican a
    este equipo — si no hay ningún puerto paralelo detectado, por ejemplo,
    no tiene sentido avisar sobre permisos de un dispositivo que no existe.
    """
    problemas: list[Problema] = []
    if os.name != "posix":
        return problemas

    dispositivos = tu.list_parallel_devices()
    if not dispositivos:
        return problemas  # sin puerto paralelo, nada de esto aplica

    sin_permiso = [d for d in dispositivos if not os.access(d, os.R_OK | os.W_OK)]
    if sin_permiso:
        usuario = os.environ.get("USER") or os.environ.get("LOGNAME")
        if not usuario:
            try:
                import getpass
                usuario = getpass.getuser()
            except Exception:  # noqa: BLE001
                usuario = ""
        problemas.append(Problema(
            "Sin permisos sobre el puerto paralelo",
            f"Tu usuario no tiene permiso de lectura/escritura sobre "
            f"{', '.join(sin_permiso)}, necesario para transferir a un copión "
            f"(Super Wild Card / Super Magic Drive) por puerto paralelo.\n\n"
            f"La causa habitual es no pertenecer al grupo 'lp'. Se puede arreglar "
            f"ejecutando:\n\n    sudo usermod -aG lp {usuario or '$USER'}\n\n"
            f"Importante: hace falta cerrar la sesión POR COMPLETO y volver a "
            f"entrar (no basta con cerrar y abrir una terminal nueva) para que "
            f"el cambio de grupo tenga efecto.",
            comando_arreglo=["usermod", "-aG", "lp", usuario] if usuario else None,
            etiqueta_boton="Añadirme al grupo 'lp'…",
        ))

    try:
        with open("/proc/modules") as fh:
            modulos = fh.read()
        if re.search(r"^lp\s", modulos, re.MULTILINE):
            problemas.append(Problema(
                "El módulo 'lp' del kernel puede ocupar el puerto",
                "El driver clásico de impresoras paralelas ('lp') está cargado. "
                "Compite por el mismo puerto que necesita uCON64 para hablar con "
                "el copión, y puede hacer que la transferencia no llegue a "
                "hacer nada, sin mostrar ningún error.\n\n"
                "Se puede descargar (solo hasta el próximo reinicio) con:\n\n"
                "    sudo rmmod lp\n\n"
                "Si vuelve a cargarse solo y esto se repite cada vez, puede "
                "impedirse de forma permanente añadiendo una línea a "
                "/etc/modprobe.d/blacklist-lp.conf — busca \"blacklist kernel "
                "module linux\" si necesitas los pasos exactos para eso.",
                comando_arreglo=["rmmod", "lp"],
                etiqueta_boton="Descargar el módulo ahora…",
            ))
    except OSError:
        pass  # /proc/modules no disponible; no es motivo de error aquí

    return problemas


class FirstRunWizard(QDialog):
    """Muestra los problemas detectados, uno a uno, con un botón para
    intentar arreglar automáticamente los que tienen una solución de un
    solo comando (pide confirmación gráfica de administrador con pkexec
    antes de ejecutar nada)."""

    def __init__(self, problemas: list[Problema], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Comprobación inicial — ASTURCONSOLE")
        self.setMinimumWidth(560)
        self.setStyleSheet(
            "QDialog { background: #12141c; }"
            "QLabel { color: #dde3ef; }"
            "QLabel#Titulo { color: #3ef29a; font-weight: 700; font-size: 15px; }"
            "QPushButton { background: #1f2330; color: #dde3ef; border: 1px solid "
            "#2c3342; border-radius: 6px; padding: 8px 14px; }"
            "QPushButton:hover { border-color: #3ef29a; }"
            "QPushButton#Arreglar { background: rgba(62,242,154,0.12); "
            "border-color: #3ef29a; color: #3ef29a; font-weight: 700; }"
        )
        self._problemas = problemas

        lay = QVBoxLayout(self)
        lay.setSpacing(14)

        intro = QLabel(
            f"Se ha detectado un puerto paralelo en este equipo, y "
            f"{'un problema' if len(problemas) == 1 else f'{len(problemas)} problemas'} "
            f"que suelen impedir que la transferencia a un copión (Super Wild "
            f"Card / Super Magic Drive) funcione. Esto solo afecta a esa "
            f"función concreta — el resto de la aplicación funciona con "
            f"normalidad de todas formas."
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        for problema in problemas:
            titulo = QLabel(f"⚠ {problema.titulo}")
            titulo.setObjectName("Titulo")
            lay.addWidget(titulo)
            desc = QLabel(problema.descripcion)
            desc.setWordWrap(True)
            desc.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(desc)
            if problema.comando_arreglo:
                fila = QHBoxLayout()
                fila.addStretch(1)
                btn = QPushButton(problema.etiqueta_boton)
                btn.setObjectName("Arreglar")
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _c=False, p=problema: self._arreglar(p))
                fila.addWidget(btn)
                lay.addLayout(fila)

        lay.addStretch(1)
        cerrar_btn = QPushButton("Cerrar")
        cerrar_btn.clicked.connect(self.accept)
        fila_cerrar = QHBoxLayout()
        fila_cerrar.addStretch(1)
        fila_cerrar.addWidget(cerrar_btn)
        lay.addLayout(fila_cerrar)

    def _arreglar(self, problema: Problema):
        comando = problema.comando_arreglo
        resumen = " ".join(comando)
        respuesta = QMessageBox.question(
            self, "Confirmar",
            f"Se va a ejecutar, pidiendo la contraseña de administrador:\n\n"
            f"    sudo {resumen}\n\n¿Adelante?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if respuesta != QMessageBox.Yes:
            return
        try:
            resultado = subprocess.run(
                ["pkexec"] + comando, capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            QMessageBox.warning(
                self, "Comprobación inicial",
                "No se encontró 'pkexec' en este sistema. Ejecuta el comando "
                f"manualmente desde una terminal:\n\n    sudo {resumen}")
            return
        except OSError as e:
            QMessageBox.warning(self, "Comprobación inicial", f"No se pudo ejecutar: {e}")
            return
        if resultado.returncode == 0:
            QMessageBox.information(
                self, "Comprobación inicial",
                "Hecho. " + (
                    "Recuerda cerrar sesión por completo y volver a entrar para que "
                    "el cambio de grupo tenga efecto."
                    if "usermod" in comando else
                    "El módulo se ha descargado; puede volver a cargarse solo en "
                    "algún momento (por ejemplo, al reiniciar)."
                ))
        else:
            detalle = resultado.stderr.strip() or "sin más detalles"
            QMessageBox.warning(self, "Comprobación inicial", f"No se pudo completar: {detalle}")


def mostrar_si_primera_vez(parent=None):
    """Punto de entrada: comprueba si ya se mostró antes (QSettings) y, si
    no, detecta problemas y muestra el asistente solo si encuentra alguno
    — si todo está bien, no interrumpe con un diálogo de "todo correcto"
    que nadie necesita ver."""
    settings = _settings()
    if settings.value("first_run/wizard_shown", False, type=bool):
        return
    settings.setValue("first_run/wizard_shown", True)

    problemas = detectar_problemas()
    if problemas:
        FirstRunWizard(problemas, parent).exec()
