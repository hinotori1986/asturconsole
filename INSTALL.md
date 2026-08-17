# ASTURCONSOLE — Instalación, ejecución y compilación

Guía práctica. Para el detalle técnico de cada función, ver `README.md`.

---

## 1. Ejecutar directamente (lo más rápido para probar)

No hace falta compilar nada:

```bash
unzip asturconsole.zip
cd asturconsole

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python3 main.py
```

### Avisos habituales durante la compilación (no son errores)

```
WARNING: ldd warnings for '.../PySide6/Qt/lib/libavcodec.so.61':
ldd: no tiene permiso de ejecución para '.../libavcodec.so.61'
```

PySide6 instala las librerías de Qt sin permiso de ejecución y PyInstaller
se queja al inspeccionarlas. **No es fatal**, pero como esas librerías son
el motor multimedia (el que usa el reproductor de cinta), conviene
corregirlo. El script `build_linux.sh` ya lo hace automáticamente; si
compilas a mano:

```bash
chmod +x .venv-build/lib/python3.*/site-packages/PySide6/Qt/lib/*.so*
```

### ¿Hace falta sudo?

**No.** La compilación solo escribe dentro de la carpeta del proyecto
(`.venv-build/`, `build/`, `dist/`). Usar `sudo` es contraproducente: deja
esas carpetas con propietario `root` y los siguientes intentos sin `sudo`
fallarán por permisos. Si te ha pasado:

```bash
sudo rm -rf .venv-build build dist
./build_linux.sh
```

`sudo` solo hace falta para instalar paquetes del sistema
(`sudo apt install python3-venv libxcb-cursor0`).

### Si falla al arrancar

| Error | Solución |
|---|---|
| `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"` | `sudo apt install libxcb-cursor0` (Debian/Ubuntu) |
| `ModuleNotFoundError: No module named 'PySide6'` | No activaste el entorno virtual, o falló `pip install` |
| El reproductor de cinta avisa de que falta QtMultimedia | Reinstala PySide6 completo: `pip install --force-reinstall PySide6` |

Para diagnosticar problemas de Qt con más detalle:

```bash
QT_DEBUG_PLUGINS=1 python3 main.py
```

---

## 2. Compilar un binario para Linux

Genera un ejecutable único que **no necesita Python ni PySide6** instalados
en la máquina donde se ejecute.

```bash
./build_linux.sh
```

El script se encarga de todo: comprueba la versión de Python, crea un
entorno virtual aislado (`.venv-build`), instala las dependencias y
PyInstaller, y compila usando `asturconsole.spec`.

Resultado: **`dist/asturconsole`**

```bash
./dist/asturconsole
```

### Notas sobre el binario

- Es "onefile": Python, Qt y los iconos van dentro de un único archivo. A
  cambio, el primer arranque es algo más lento (se descomprime a una
  carpeta temporal).
- Tamaño esperado: en torno a 60–90 MB, según la versión de PySide6. El
  `.spec` ya excluye módulos pesados de Qt que no se usan (WebEngine, Quick,
  QML, Charts…) para reducirlo.
- **El binario NO es portable entre distribuciones muy distintas.**
  PyInstaller enlaza contra la `glibc` del sistema donde se compila, así que
  un binario hecho en Ubuntu 24.04 puede no arrancar en una distribución
  bastante más antigua. Si necesitas máxima compatibilidad, compílalo en la
  distribución más antigua que quieras soportar.

### Compilación manual (si prefieres controlar los pasos)

```bash
python3 -m venv .venv-build
source .venv-build/bin/activate
pip install -r requirements.txt pyinstaller
pyinstaller --clean --noconfirm asturconsole.spec
```

---

## 3. Compilar para Windows

PyInstaller **no hace compilación cruzada**: el `.exe` hay que generarlo en
Windows. Dos opciones:

**a) En una máquina Windows**, con Python instalado:

```
build_windows.bat
```

Resultado: `dist\asturconsole.exe`

**b) Con GitHub Actions** (si no tienes Windows a mano): sube la carpeta a
un repositorio de GitHub. El workflow incluido en
`.github/workflows/build.yml` compila **Linux y Windows a la vez**, cada uno
en su propia máquina virtual. Ve a la pestaña *Actions* → *Run workflow*, y
al terminar descarga los binarios desde *Artifacts*.

---

## 4. Dependencias externas opcionales

La app funciona sin ellas, pero algunas funciones concretas las necesitan:

| Función | Requisito |
|---|---|
| Reproductor de cinta (audio) | `PySide6.QtMultimedia` (viene con PySide6) |
| Transferencia al copión por puerto paralelo | `ucon64` instalado, y un puerto paralelo **real** (ver `README.md`) |
| Montar dispositivos USB desde el selector de carpeta | `udisks2` (`sudo apt install udisks2`); suele venir instalado en cualquier escritorio |

Para instalar uCON64 en Debian/Ubuntu:

```bash
sudo apt install ucon64
```

Si no está en los repositorios de tu distribución, se puede compilar desde
`https://ucon64.sourceforge.io`. La app permite indicar manualmente la ruta
al ejecutable si no lo encuentra sola.

---

## 5. Estructura del proyecto

```
asturconsole/
├── main.py                    Interfaz principal (pestañas por sistema)
├── rom_formats.py             Parsers: MSX (ROM/BIN/DSK), Mega Drive, SNES
├── snes_tools.py              Cabeceras de copiador, checksum, división SWC
├── genesis_tools.py           Mega Drive: formato SMD entrelazado
├── cas_tape.py                Cintas MSX: CAS ⇄ WAV
├── tsx_tape.py                Cintas MSX: CAS ⇄ TSX (bloque KCS #4B)
├── tape_player.py             Motor de audio del reproductor
├── tape_player_dialog.py      Interfaz del reproductor
├── transfer_ucon64.py         Lógica del frontend de uCON64
├── transfer_dialog.py         Interfaz de transferencia por puerto paralelo
├── volumes.py                 Detección de volúmenes y montaje de USB
├── folder_picker.py           Selector de carpeta con volúmenes y USB
├── assets/icons/              Iconos SVG y textura de fondo
├── asturconsole.spec         Configuración de PyInstaller
├── build_linux.sh             Compilación para Linux
├── build_windows.bat          Compilación para Windows
└── .github/workflows/build.yml   Compilación automática de ambos
```

Los módulos de lógica (`rom_formats`, `snes_tools`, `cas_tape`, `tsx_tape`,
`transfer_ucon64`) son Python puro sin dependencia de Qt: se pueden importar
y probar por separado desde un intérprete, sin abrir la interfaz.
