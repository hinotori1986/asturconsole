@echo off
REM Compila ASTURCONSOLE como un único ejecutable para Windows x86_64.
REM Debe ejecutarse EN Windows (PyInstaller no hace compilacion cruzada).
cd /d "%~dp0"

python -m venv .venv-build
call .venv-build\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

pyinstaller --clean --noconfirm asturconsole.spec

echo.
echo Listo: dist\asturconsole.exe
echo Puedes moverlo/renombrarlo y ejecutarlo directamente, no necesita Python instalado.
