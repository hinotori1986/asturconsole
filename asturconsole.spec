# -*- mode: python ; coding: utf-8 -*-
# Spec de PyInstaller para ASTURCONSOLE.
# Uso: pyinstaller asturconsole.spec
#
# Genera un único ejecutable ("onefile") con la carpeta assets/ empaquetada
# dentro. Funciona igual en Linux (genera un binario ELF) y en Windows
# (genera un .exe) siempre que se ejecute EN esa plataforma — PyInstaller
# no hace compilación cruzada real.

import os
import sys

block_cipher = None

# Compilación "legacy": si esta variable de entorno está activa, el binario
# resultante lleva el sufijo "-legacy" en el nombre. No cambia nada más del
# propio empaquetado — lo que de verdad marca la diferencia es CÓMO se creó
# el entorno virtual antes de invocar PyInstaller (con o sin acceso al
# PySide6 del sistema): ver build_linux.sh y el workflow de GitHub Actions.
LEGACY = os.environ.get("ASTURCONSOLE_LEGACY") == "1"

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('swc_compat_data.json', '.'), ('data', 'data')],
    # IMPORTANTE: estos módulos se importan de forma diferida (dentro de
    # funciones, no en la cabecera del archivo) para que la app arranque
    # aunque falte QtMultimedia. El análisis estático de PyInstaller NO los
    # detecta, así que hay que declararlos aquí a mano: sin esto el binario
    # compilado arrancaría bien pero fallaría al abrir el reproductor de
    # cinta o el diálogo de transferencia.
    hiddenimports=[
        'tape_player',
        'tape_player_dialog',
        'tape_deck_widget',
        'transfer_dialog',
        'transfer_ucon64',
        'genesis_tools',
        'workspace',
        'msxdos_disk',
        'swc_compat',
        'volumes',
        'write_image_dialog',
        'read_floppy_dialog',
        'disk_panel',
        'extract_dialog',
        'workspace_browser',
        'file_workbench',
        'floppy_write_dialog',
        'folder_picker',
        'system_detect',
        'PySide6.QtMultimedia',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Módulos pesados de Qt que no usamos; excluirlos reduce bastante el
        # tamaño del binario. Si en el futuro se añade alguna función que los
        # necesite, hay que quitarlos de esta lista.
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.Qt3DCore', 'PySide6.QtCharts', 'PySide6.QtQuick',
        'PySide6.QtQml', 'PySide6.QtDataVisualization',
        'tkinter', 'matplotlib', 'numpy',
    ],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_name = 'asturconsole.exe' if sys.platform.startswith('win') else 'asturconsole'
if LEGACY:
    exe_name = 'asturconsole-legacy.exe' if sys.platform.startswith('win') else 'asturconsole-legacy'

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # app de escritorio, sin consola detrás
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # El icono depende de la plataforma: Windows usa .ico, macOS exige .icns
    # y pasarle un .ico aborta la compilación. En Linux el icono del binario
    # no se usa (lo pone el archivo .desktop), así que se omite.
    # El icono depende de la plataforma: Windows quiere .ico, macOS .icns
    # (pasarle un .ico ahí aborta la compilación), y en Linux PyInstaller no
    # empotra icono en el ELF, pero se deja assets/icons/app_icon.png para
    # que quien quiera integrarlo en su escritorio (.desktop) lo tenga a mano.
    icon=(
        'assets/icons/app_icon.ico' if sys.platform.startswith('win')
        else 'assets/icons/app_icon.icns' if sys.platform == 'darwin'
        else None
    ),
)

# En macOS, un ejecutable UNIX suelto (lo que produce EXE() de arriba en modo
# --onefile) NO se muestra con icono personalizado en el Finder por mucho
# icon=... que se le pase: para eso hace falta empaquetarlo como una
# aplicación ".app" de verdad, que es lo que hace BUNDLE() aquí. Sin este
# bloque, el .icns se generaba bien pero nunca llegaba a verse en pantalla.
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='ASTURCONSOLE.app',
        icon='assets/icons/app_icon.icns',
        bundle_identifier='es.ritcher1986.asturconsole',
    )
