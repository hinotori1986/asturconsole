@echo off
rem ===========================================================================
rem  ASTURTRANSFER para Windows  -  menu de texto para enviar ROMs al copion
rem
rem  Equivalente del asturtransfer.sh de Linux. Funciona en cualquier Windows
rem  con cmd.exe: XP, Vista, 7, 8, 10, 11, tanto de 32 como de 64 bits.
rem  Para MS-DOS y Windows 95/98/ME usa ASTURDOS.BAT, que es mas limitado
rem  porque COMMAND.COM no admite las ordenes que se usan aqui.
rem
rem  Uso:   asturtransfer.bat [carpeta_con_roms]
rem ===========================================================================
setlocal enabledelayedexpansion

set "VERSION=1.0"
set "CARPETA=%~1"
if "%CARPETA%"=="" set "CARPETA=%CD%"

rem --- localizar uCON64 -------------------------------------------------------
set "UCON64="
if exist "%~dp0ucon64.exe" set "UCON64=%~dp0ucon64.exe"
if not defined UCON64 for %%I in (ucon64.exe) do if exist "%%~$PATH:I" set "UCON64=%%~$PATH:I"
if not defined UCON64 if exist "C:\ucon64\ucon64.exe" set "UCON64=C:\ucon64\ucon64.exe"

set "COPION=swc"
set "TIPO=rom"
set "OPCIONES="
set "CONFIG=%~dp0asturtransfer.cfg"
if exist "%CONFIG%" call "%CONFIG%"

rem La carpeta indicada al arrancar manda sobre la guardada
if not "%~1"=="" set "CARPETA=%~1"

call :COMPROBAR

:MENU
cls
echo ===============================================================
echo   ASTURTRANSFER %VERSION%  -  transferencia al copion
echo ===============================================================
echo.
echo   Copion:  %COPION%        Enviar: %TIPO%        Opciones: %OPCIONES%
echo   Carpeta: %CARPETA%
echo.
echo   1) Elegir una ROM y transferirla
echo   2) Cambiar de copion        (ahora: %COPION%)
echo   3) ROM o SRAM               (ahora: %TIPO%)
echo   4) Correcciones -k / -f     (ahora: %OPCIONES%)
echo   5) Cambiar la carpeta de ROMs
echo   6) Ver estado y diagnostico
echo   7) Salir
echo.
set "OP="
set /p "OP=Elige una opcion: "
if "%OP%"=="1" goto ENVIAR
if "%OP%"=="2" goto COPION_SEL
if "%OP%"=="3" goto TIPO_SEL
if "%OP%"=="4" goto OPCIONES_SEL
if "%OP%"=="5" goto CARPETA_SEL
if "%OP%"=="6" goto ESTADO
if "%OP%"=="7" goto FIN
goto MENU

rem ===========================================================================
:COMPROBAR
cls
set "HAYPROBLEMA="
if not defined UCON64 (
    echo ERROR: no se encuentra ucon64.exe
    echo.
    echo   Coloca ucon64.exe junto a este archivo .bat, o en C:\ucon64\,
    echo   o anadelo al PATH del sistema.
    set "HAYPROBLEMA=1"
)
ver | find "NT" >nul 2>&1
if not errorlevel 1 goto :COMPROBAR_DRIVER
rem Windows 2000 y posteriores tambien informan version distinta; se avisa igual
:COMPROBAR_DRIVER
set "HAYDRIVER="
if exist "%~dp0io.dll" set "HAYDRIVER=io.dll"
if exist "%~dp0inpout32.dll" set "HAYDRIVER=inpout32.dll"
if exist "%~dp0dlportio.dll" set "HAYDRIVER=dlportio.dll"
if not defined HAYDRIVER (
    echo.
    echo AVISO: no se encuentra ningun driver de puerto de E/S junto a este .bat.
    echo.
    echo   Windows NT, 2000, XP y posteriores NO permiten el acceso directo al
    echo   puerto paralelo. uCON64 necesita uno de estos, en su misma carpeta:
    echo        inpout32.dll     (el mas habitual)
    echo        io.dll
    echo        dlportio.dll
    echo.
    echo   Si falta, uCON64 mostrara:
    echo        ERROR: No (working) I/O port driver
    echo.
    echo   En Windows 95, 98 y ME no hace falta ninguno.
    set "HAYPROBLEMA=1"
)
if defined HAYPROBLEMA (
    echo.
    pause
)
goto :eof

rem ===========================================================================
:ENVIAR
cls
echo Buscando ROMs en: %CARPETA%
echo.
if /i "%COPION%"=="swc" set "EXTS=*.swc *.sfc *.smc *.fig"
if /i "%COPION%"=="smd" set "EXTS=*.smd *.bin *.md *.gen"

set "LISTA=%TEMP%\astur_lista.txt"
if exist "%LISTA%" del "%LISTA%" >nul 2>&1
for %%E in (%EXTS%) do (
    if exist "%CARPETA%\%%E" dir /b /a-d "%CARPETA%\%%E" >> "%LISTA%" 2>nul
)
if not exist "%LISTA%" (
    echo No se encontro ninguna ROM con estas extensiones: %EXTS%
    echo.
    pause
    goto MENU
)

rem Contar cuantas hay
set /a TOTAL=0
for /f "usebackq delims=" %%L in ("%LISTA%") do set /a TOTAL+=1
if %TOTAL%==0 (
    echo No se encontro ninguna ROM.
    echo.
    pause
    goto MENU
)

rem Con muchas ROMs se pide un filtro, como en la version de Linux
set "FILTRO="
if %TOTAL% GTR 30 (
    echo Hay %TOTAL% ROMs en la carpeta.
    set /p "FILTRO=Escribe parte del nombre para filtrar (Intro = todas): "
)
set "LISTA2=%TEMP%\astur_lista2.txt"
if exist "%LISTA2%" del "%LISTA2%" >nul 2>&1
if "%FILTRO%"=="" (
    copy /y "%LISTA%" "%LISTA2%" >nul
) else (
    findstr /i /c:"%FILTRO%" "%LISTA%" > "%LISTA2%"
)

set /a N=0
for /f "usebackq delims=" %%L in ("%LISTA2%") do set /a N+=1
if %N%==0 (
    echo Ninguna ROM contiene "%FILTRO%".
    echo.
    pause
    goto MENU
)

cls
echo ===============================================================
echo   ROMs disponibles (%N%)   Filtro: %FILTRO%
echo ===============================================================
echo.
set /a I=0
for /f "usebackq delims=" %%L in ("%LISTA2%") do (
    set /a I+=1
    set "ARCHIVO_!I!=%%L"
    echo   !I!^) %%L
)
echo.
set "SEL="
set /p "SEL=Numero de la ROM (Intro = cancelar): "
if "%SEL%"=="" goto MENU
set "ELEGIDA=!ARCHIVO_%SEL%!"
if not defined ELEGIDA goto MENU

set "RUTA=%CARPETA%\%ELEGIDA%"
if not exist "%RUTA%" (
    echo El archivo no existe: %RUTA%
    pause
    goto MENU
)

if /i "%TIPO%"=="sram" (
    if /i "%COPION%"=="swc" set "OPCION=--xswcs"
    if /i "%COPION%"=="smd" set "OPCION=--xsmds"
) else (
    if /i "%COPION%"=="swc" set "OPCION=--xswc"
    if /i "%COPION%"=="smd" set "OPCION=--xsmd"
)

cls
echo ===============================================================
echo   CONFIRMAR TRANSFERENCIA
echo ===============================================================
echo.
echo   Archivo:  %ELEGIDA%
echo   Copion:   %COPION%
echo   Enviar:   %TIPO%
echo   Opciones: %OPCIONES%
echo.
echo   Comando:
echo     "%UCON64%" %OPCION% %OPCIONES% "%RUTA%"
echo.
echo   Enciende el copion ANTES de continuar.
if /i "%COPION%"=="smd" echo   Recuerda: el archivo debe estar YA en formato SMD.
if /i "%COPION%"=="swc" echo   Recuerda: el archivo debe llevar YA la cabecera Super Wild Card.
echo.
set "SN="
set /p "SN=Continuar? (S/N): "
if /i not "%SN%"=="S" goto MENU

cls
echo Transfiriendo: %ELEGIDA%
echo.
"%UCON64%" %OPCION% %OPCIONES% "%RUTA%"
set "CODIGO=%ERRORLEVEL%"
echo.
if "%CODIGO%"=="0" (
    echo ^>^>^> Transferencia terminada correctamente.
) else (
    echo ^>^>^> uCON64 termino con codigo %CODIGO%.
    echo.
    echo     Si aparecio "No (working) I/O port driver":
    echo        falta inpout32.dll junto a ucon64.exe.
    echo     Si el copion no responde:
    echo        - Esta encendido y con un disquete dentro?
    echo        - El cable debe ser paralelo BIDIRECCIONAL.
    echo        - En la BIOS, el puerto en EPP, ECP+EPP o bidireccional.
    echo          En modo SPP el copion no puede contestar.
)
echo.
pause
goto MENU

rem ===========================================================================
:COPION_SEL
cls
echo   1) Super Wild Card / Super Magicom (SNES)
echo   2) Super Magic Drive (Mega Drive)
echo.
set "C="
set /p "C=Elige: "
if "%C%"=="1" set "COPION=swc"
if "%C%"=="2" set "COPION=smd"
call :GUARDAR
goto MENU

:TIPO_SEL
cls
echo   1) ROM del juego
echo   2) SRAM (partidas guardadas)
echo.
set "C="
set /p "C=Elige: "
if "%C%"=="1" set "TIPO=rom"
if "%C%"=="2" set "TIPO=sram"
call :GUARDAR
goto MENU

:OPCIONES_SEL
cls
echo   Algunos juegos necesitan correcciones. asturconsole te indica
echo   cuales al analizar la ROM.
echo.
echo   1) Ninguna (lo habitual)
echo   2) -k    crack de proteccion anticopia
echo   3) -f    correccion NTSC/PAL
echo   4) -k -f ambas
echo.
set "C="
set /p "C=Elige: "
if "%C%"=="1" set "OPCIONES="
if "%C%"=="2" set "OPCIONES=-k"
if "%C%"=="3" set "OPCIONES=-f"
if "%C%"=="4" set "OPCIONES=-k -f"
call :GUARDAR
goto MENU

:CARPETA_SEL
cls
echo   Carpeta actual: %CARPETA%
echo.
set "NUEVA="
set /p "NUEVA=Nueva carpeta (Intro = dejarla igual): "
if not "%NUEVA%"=="" (
    if exist "%NUEVA%\" (
        set "CARPETA=%NUEVA%"
        call :GUARDAR
    ) else (
        echo Esa carpeta no existe.
        pause
    )
)
goto MENU

:ESTADO
cls
echo ===============================================================
echo   ESTADO
echo ===============================================================
echo.
echo   uCON64:  %UCON64%
if defined UCON64 "%UCON64%" --version 2>nul | find "uCON64"
echo.
echo   Driver de puerto de E/S encontrado: %HAYDRIVER%
echo.
echo   Archivos DLL junto a este .bat:
dir /b "%~dp0*.dll" 2>nul
echo.
echo   Recordatorio: en Windows XP y posteriores hace falta inpout32.dll
echo   (o io.dll / dlportio.dll) en la misma carpeta que ucon64.exe.
echo   En Windows 95/98/ME no hace falta ninguno.
echo.
pause
goto MENU

:GUARDAR
> "%CONFIG%" echo set "COPION=%COPION%"
>> "%CONFIG%" echo set "TIPO=%TIPO%"
>> "%CONFIG%" echo set "OPCIONES=%OPCIONES%"
>> "%CONFIG%" echo set "CARPETA=%CARPETA%"
goto :eof

:FIN
cls
echo Hasta luego.
endlocal
