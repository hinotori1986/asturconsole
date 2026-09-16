@echo off
rem ===========================================================================
rem  ASTURDOS.BAT  -  menu para enviar ROMs al copion desde MS-DOS
rem
rem  Para MS-DOS 5/6 y Windows 95/98/ME (COMMAND.COM). En Windows XP y
rem  posteriores usa ASTURTRANSFER.BAT, que es mas completo.
rem
rem  Por que es mas simple que la version de Windows: COMMAND.COM no tiene
rem  SET /P (leer texto del teclado), ni FOR /F, ni variables retardadas. Solo
rem  se puede leer una tecla con CHOICE.COM, que viene con MS-DOS 6 y con
rem  Windows 9x. Por eso aqui se trabaja con una lista corta de ROMs elegidas
rem  con una sola tecla, en vez de un buscador.
rem
rem  VENTAJA IMPORTANTE de usar DOS: bajo DOS y Windows 9x NO hace falta
rem  ningun driver de puerto de E/S. El acceso al puerto paralelo esta
rem  permitido, asi que uCON64 funciona directamente.
rem
rem  Uso:   ASTURDOS
rem         (ejecutalo desde la carpeta donde tengas las ROMs)
rem ===========================================================================

rem CHOICE.COM debe estar accesible: viene con MS-DOS 6 y con Windows 9x.
rem Si no lo tienes, copialo desde C:\DOS o C:\WINDOWS\COMMAND.
if not exist UCON64.EXE goto NOUCON64

:MENU
cls
echo ==========================================================
echo   ASTURDOS - transferencia al copion (MS-DOS)
echo ==========================================================
echo.
echo   1) Enviar ROM a Super Wild Card    (SNES)
echo   2) Enviar ROM a Super Magic Drive  (Mega Drive)
echo   3) Enviar SRAM a Super Wild Card
echo   4) Enviar SRAM a Super Magic Drive
echo   5) Ver las ROMs de esta carpeta
echo   6) Ayuda y diagnostico
echo   7) Salir
echo.
choice /c:1234567 /n Elige una opcion:
if errorlevel 7 goto FIN
if errorlevel 6 goto AYUDA
if errorlevel 5 goto LISTAR
if errorlevel 4 goto SRAMSMD
if errorlevel 3 goto SRAMSWC
if errorlevel 2 goto ROMSMD
if errorlevel 1 goto ROMSWC
goto MENU

:ROMSWC
set OPCION=--xswc
set QUE=ROM (Super Wild Card)
set PATRON=*.SWC
goto PEDIRNOMBRE

:ROMSMD
set OPCION=--xsmd
set QUE=ROM (Super Magic Drive)
set PATRON=*.SMD
goto PEDIRNOMBRE

:SRAMSWC
set OPCION=--xswcs
set QUE=SRAM (Super Wild Card)
set PATRON=*.SRM
goto PEDIRNOMBRE

:SRAMSMD
set OPCION=--xsmds
set QUE=SRAM (Super Magic Drive)
set PATRON=*.SRM
goto PEDIRNOMBRE

:PEDIRNOMBRE
cls
echo ==========================================================
echo   Enviar %QUE%
echo ==========================================================
echo.
echo   Archivos disponibles:
echo.
dir /b /w %PATRON%
echo.
echo   COMMAND.COM no permite escribir texto desde un .BAT, asi que
echo   el archivo se indica al ejecutar. Vuelve al indicador de DOS y
echo   escribe directamente:
echo.
echo       UCON64 %OPCION% NOMBRE
echo.
echo   Por ejemplo:   UCON64 %OPCION% JUEGO.SWC
echo.
echo   Opciones utiles, si el juego las necesita:
echo       -k    crack de proteccion anticopia
echo       -f    correccion NTSC/PAL
echo   Ejemplo:  UCON64 %OPCION% -k JUEGO.SWC
echo.
echo   Enciende el copion ANTES de lanzar el comando.
echo.
pause
goto MENU

:LISTAR
cls
echo ==========================================================
echo   ROMs en esta carpeta
echo ==========================================================
echo.
echo -- Super Wild Card (SNES) --
dir /b /w *.SWC *.SFC *.SMC *.FIG
echo.
echo -- Super Magic Drive (Mega Drive) --
dir /b /w *.SMD *.BIN *.MD *.GEN
echo.
echo -- Partidas guardadas --
dir /b /w *.SRM
echo.
pause
goto MENU

:AYUDA
cls
echo ==========================================================
echo   AYUDA Y DIAGNOSTICO
echo ==========================================================
echo.
echo   VENTAJA DE DOS
echo   Bajo MS-DOS y Windows 95/98/ME NO hace falta ningun driver de
echo   puerto de E/S: el acceso directo al puerto esta permitido. En
echo   Windows XP y posteriores si haria falta inpout32.dll.
echo.
echo   EL PUERTO EN LA BIOS
echo   Debe estar en modo EPP, ECP+EPP o bidireccional. En modo SPP o
echo   "solo salida" el copion no puede contestar y no funcionara.
echo.
echo   EL PUERTO EN UCON64
echo   Por defecto usa la direccion 378. Si tu puerto esta en otra:
echo       UCON64 --xswc --port=278 JUEGO.SWC
echo.
echo   FORMATO DE LOS ARCHIVOS
echo   uCON64 envia el archivo TAL CUAL, sin convertirlo:
echo     - SNES: debe llevar ya la cabecera Super Wild Card.
echo     - Mega Drive: debe estar ya en formato SMD (cabecera de 512
echo       bytes mas datos entrelazados). Un .BIN plano NO sirve.
echo   Preparalos antes en el PC moderno con asturconsole.
echo.
echo   NOMBRES DE ARCHIVO
echo   DOS solo admite nombres 8.3. Al copiar las ROMs desde el PC
echo   moderno, acorta los nombres o se truncaran.
echo.
pause
goto MENU

:NOUCON64
cls
echo.
echo   ERROR: no se encuentra UCON64.EXE en esta carpeta.
echo.
echo   Copia UCON64.EXE (la version para DOS, compilada con DJGPP)
echo   junto a este archivo .BAT, o ejecuta este .BAT desde la carpeta
echo   donde tengas uCON64.
echo.
pause
goto FIN

:FIN
cls
echo Hasta luego.
