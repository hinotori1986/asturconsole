# -*- mode: python ; coding: utf-8 -*-
# Spec de PyInstaller para ASTURCONSOLE.
# Uso: pyinstaller asturconsole.spec
#
# Genera un único ejecutable ("onefile") con la carpeta assets/ empaquetada
# dentro. Funciona igual en Linux (genera un binario ELF) y en Windows
# (genera un .exe) siempre que se ejecute EN esa plataforma — PyInstaller
# no hace compilación cruzada real.

import sys

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('swc_compat_data.json', '.')],
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
    icon=('assets/icons/app_icon.ico' if sys.platform.startswith('win') else None),
)
