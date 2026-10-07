# Transferencia por puerto paralelo en Linux — cómo se diagnosticó y qué hacer si vuelve a pasar

Esta página documenta una investigación larga (v1.0.1 → v1.1) sobre por qué
la transferencia por puerto paralelo a copiones (Super Wild Card, Super
Magic Drive) no funcionaba en una instalación de Linux Mint, mientras que
en Fedora sí funcionaba con el mismo hardware. Se deja por escrito para no
tener que repetir el mismo proceso de diagnóstico si vuelve a aparecer en
otro equipo, otra distribución, u otra persona.

**El síntoma** era siempre el mismo, y es la pista más importante a
reconocer: uCON64 muestra toda la información del ROM (cabecera, checksum,
volcado hexadecimal) con total normalidad, y justo después **no pasa
nada más** — ni progreso, ni error, ni el proceso termina. Como si se
hubiera quedado colgado, pero sin ningún mensaje.

## La causa: no era una sola cosa, eran cuatro

Lo que hizo esto largo de diagnosticar es que había **varios problemas
independientes, cada uno capaz de producir exactamente el mismo síntoma
por sí solo**. Arreglar tres de los cuatro y dejar uno sin resolver
seguía dando "no pasa nada" — así que cada corrección parecía no haber
servido de nada hasta que se corrigió la última pieza.

### 1. El usuario no pertenece al grupo `lp`

El acceso a `/dev/parportN` en Linux requiere pertenecer a este grupo.
Sin él, el sistema deniega el acceso en silencio.

```bash
sudo usermod -aG lp $USER
```

**Importante:** hace falta cerrar sesión y volver a entrar — no basta
con reiniciar el programa ni con abrir una terminal nueva dentro de la
misma sesión. El cambio de grupo solo se aplica a sesiones que empiezan
después del cambio.

Cómo comprobarlo: `groups` en una terminal — si no aparece `lp` en la
lista, el cambio no se ha aplicado todavía.

### 2. El módulo del kernel `lp` tiene el dispositivo reservado

Aunque el usuario esté en el grupo correcto, el módulo genérico de
impresora paralela del kernel (`lp`, no confundir con el grupo del mismo
nombre) puede haber reservado el dispositivo para sí mismo antes de que
uCON64 intente usarlo. Esto también bloquea en silencio, sin ningún
mensaje de error.

```bash
sudo rmmod lp
```

Se puede comprobar si está cargado con `lsmod | grep lp`, o mirando
`/proc/modules` directamente. Si se quiere que no vuelva a cargarse
nunca automáticamente:

```bash
echo "blacklist lp" | sudo tee /etc/modprobe.d/blacklist-lp.conf
```

ASTURCONSOLE a partir de v1.1 incluye un botón ("Comprobar requisitos
del sistema", dentro del diálogo de transferencia) que detecta esto
automáticamente y ofrece un botón para descargarlo con un solo clic
(pide la contraseña con el diálogo gráfico del sistema, sin necesitar
terminal).

### 3. uCON64 compilado sin soporte `ppdev`

Hay dos formas de compilar uCON64 para acceder al puerto paralelo en
Linux, y son mutuamente excluyentes:

- **Con `ppdev`** (usa `/dev/parportN` + `ioctl`): no necesita privilegios
  especiales más allá del grupo `lp`. Es el método moderno y seguro.
- **Sin `ppdev`** (usa `iopl()`/`ioperm()`, acceso directo a los puertos
  de E/S del procesador): requiere ser root o tener la capability
  `CAP_SYS_RAWIO`, sin excepción. El grupo `lp` no tiene ningún efecto
  aquí — son dos mecanismos de permisos completamente independientes.

El script `configure` de uCON64 tiene `--enable-ppdev`, **con "no" como
valor por defecto**. Cualquier compilación manual desde el código fuente
que no especifique esta opción explícitamente acaba usando el camino que
necesita root — sin ningún aviso de que existiera la alternativa.

Los paquetes oficiales de las distribuciones (`sudo apt install ucon64`,
`sudo dnf install ucon64`, etc.) normalmente sí vienen compilados con
`ppdev` activado. El problema aparece cuando uCON64 se compila a mano.

Cómo comprobarlo:
```bash
ucon64 --version
```
y buscar la línea `parallel port backup unit support: yes (ppdev)`
— si dice simplemente `yes` sin `(ppdev)`, es la compilación sin ppdev.

Cómo recompilar correctamente:
```bash
wget https://downloads.sourceforge.net/project/ucon64/ucon64/2.2.2/ucon64-2.2.2-src.tar.bz2
tar xjf ucon64-2.2.2-src.tar.bz2
cd ucon64-2.2.2-src/src
./configure --enable-ppdev
make -j4
sudo make install
```

Alternativa sin recompilar: dar la capability específica al binario ya
compilado, sin necesitar ejecutar todo el programa como root:
```bash
sudo setcap cap_sys_rawio+ep /ruta/al/ucon64
```
(en nuestro caso esto no fue suficiente por sí solo, porque el problema
real de fondo era otro — ver el punto 4 — pero puede bastar si tu único
problema es este).

### 4. `parport_dev` apunta al dispositivo equivocado

Este fue el más difícil de encontrar, porque no da ningún error: uCON64
simplemente asume `/dev/parport0` por defecto. Si el sistema tiene más
de un dispositivo parport (por ejemplo, un puerto paralelo "fantasma"
reconocido por la placa base además de la tarjeta PCI/PCIe real), y la
tarjeta real no es la que se numera como `parport0`, uCON64 intenta
comunicarse con un dispositivo que no es el correcto — o que no
corresponde a ningún hardware real — y se queda esperando una respuesta
que nunca llega.

Cómo comprobar cuántos dispositivos hay:
```bash
ls /dev/parport*
```

Si aparece más de uno (`/dev/parport0`, `/dev/parport1`...), hay que
averiguar cuál es el correcto — normalmente por prueba y error, o
comparando con una instalación de otra distribución donde sí funcione.

Cómo indicarle a uCON64 cuál usar — editando `~/.ucon64rc`:
```
parport_dev=/dev/parport1
```

No hay ninguna opción de línea de comandos para esto: `--port` solo
sirve para direcciones de E/S numéricas (`--port=0x378`) o para USB
(`--port=usb0`), nunca para nombres de dispositivo `/dev/parportN`. El
archivo de configuración es la única vía.

**Desde la v1.9.1 la aplicación lo hace por ti**: al elegir `/dev/parportN` con
los botones del diálogo (o escribirlo en «Otro (manual)») escribe `parport_dev=`
en `~/.ucon64rc` —cambiando solo esa línea, con una copia de seguridad en
`~/.ucon64rc.asturconsole.bak`— y no pasa `--port`. Antes los botones pasaban
`--port=/dev/parportN`, que uCON64 ignora (comprobado con el binario incluido:
sigue abriendo el dispositivo de `~/.ucon64rc`), así que en un equipo con dos
puertos (uno de la placa y la tarjeta real, lo habitual) la transferencia se
quedaba en el equivocado sin ningún error. Una instalación nueva de Linux no
tiene ese ajuste: `~/.ucon64rc` arranca con `parport_dev=/dev/parport0`.

## Por qué Fedora funcionaba y Mint no, con el mismo hardware

No era una diferencia de distribución en sí — era que, en una
investigación anterior sobre disqueteras (Greaseweazle), ya se había
determinado y configurado manualmente `parport_dev=/dev/parport1` en el
`.ucon64rc` de esa instalación de Fedora. La instalación de Mint era
nueva y nunca había recibido ese mismo ajuste. Al reproducirlo ahí,
empezó a funcionar igual.

**Moraleja:** si el mismo programa funciona en una distribución y no en
otra con el mismo hardware, sospecha primero de la configuración
persistente específica de esa instalación (archivos de config con ajustes
manuales de sesiones anteriores) antes que de diferencias entre
distribuciones o del propio hardware.

## Herramienta de diagnóstico usada

Cuando la información visible en la interfaz no basta (como en este
caso: "no pasa nada, sin ningún error"), `strace` da la respuesta
definitiva sobre qué está haciendo un proceso en el instante exacto en
que parece colgado:

```bash
timeout 15 strace -f -tt -o /tmp/trace.txt ucon64 --xsmd --frontend "archivo.smd"
tail -20 /tmp/trace.txt
```

La última llamada al sistema sin completar (sin un `= <número>` al
final de la línea) es el punto exacto del bloqueo. En este caso, fue
justo ahí donde apareció el mensaje real (`EACCES` al intentar abrir
`/dev/parport0`) que la propia interfaz de ASTURCONSOLE no estaba
mostrando por un problema aparte (ver siguiente sección).

## Efecto secundario encontrado y corregido: mensajes de error que se perdían

Durante esta investigación se encontró un bug real en ASTURCONSOLE,
independiente de todo lo anterior: si el proceso de uCON64 terminaba
**muy rápido** (por ejemplo, un fallo inmediato de permisos, en menos de
un milisegundo), el mensaje de error podía perderse sin llegar nunca a
mostrarse en la consola de la aplicación. La señal de "hay datos
nuevos que leer" no llegaba a procesarse antes de que la aplicación
limpiara la referencia al proceso ya terminado.

Corregido en v1.1: `_on_finished()`, en `transfer_dialog.py`, ahora lee
explícitamente cualquier dato pendiente antes de soltar la referencia al
proceso. Esto es genérico y no depende de qué error concreto se
produzca — cualquier fallo futuro que termine muy rápido debería verse
correctamente a partir de ahora.

## Qué uCON64 usa la aplicación (y por qué no vale cualquiera)

La app usa **la copia de la carpeta `ucon64/`**, con prioridad sobre cualquier otra
del sistema (`transfer_ucon64.find_ucon64`), o la ruta que indiques en el campo del
diálogo. No es el uCON64 oficial sin tocar: es la 2.2.2 con dos cambios, hechos
porque el código original está pensado para CPUs de 1999:

- **`N_TRY_MAX` 65 536 → 16 777 216** en el sondeo del estado del puerto. El
  original agota las 65 536 lecturas en microsegundos en un PC actual y, como su
  aviso de error está desactivado en el fuente (`#if 0`), sigue enviando datos sin
  que el copión esté listo.
- **Los retardos fijos entre bloques son un `nanosleep` de 40 ms** (tiempo de
  reloj) en vez de un bucle que cuenta vueltas de CPU. Un primer intento multiplicó
  también esos retardos por 256 y distorsionó la temporización del Super Wild Card;
  40 ms es lo que equivalía a las vueltas de la versión que funcionó.

Comprobado en el código máquina del binario incluido (4 esperas de puerto con
límite 16 777 216 y 9 llamadas al retardo de 40 ms). Un `ucon64` de otro origen
(paquete de la distribución, compilado a mano) tendrá `ppdev` pero **no estos
cambios**, y puede transferir mal sin avisar en un PC moderno.

El botón «Comprobar requisitos del sistema» juzga desde la v1.9.1 el binario que
vas a usar de verdad (el del campo del diálogo) y detecta `ppdev` leyendo el propio
binario. Antes miraba siempre la primera copia del `PATH` y daba un falso error con
cualquier binario que tuviera `ppdev`.

## Resumen para revisar rápido si esto vuelve a pasar

Orden recomendado de comprobación, de más a menos común:

1. `groups` → ¿aparece `lp`?
2. `lsmod | grep lp` → ¿el módulo `lp` está cargado? Si sí: `sudo rmmod lp`
3. `ucon64 --version` → ¿dice `(ppdev)`? Si no, recompilar o `setcap`
4. `ls /dev/parport*` → ¿hay más de uno? Si sí, probar cada uno en
   `~/.ucon64rc` con `parport_dev=/dev/parportN`
5. Si nada de esto lo resuelve: `strace` para ver la llamada exacta
   donde se bloquea, y buscar esa llamada específica en el código
   fuente de uCON64 (`src/misc/parallel.c` es donde vive casi toda la
   lógica de acceso al puerto)

A partir de v1.1, los puntos 1 a 4 se comprueban automáticamente desde
el botón "Comprobar requisitos del sistema" en el diálogo de
transferencia (solo visible en Linux).
