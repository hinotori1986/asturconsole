# ASTURCONSOLE

Aplicación de escritorio (PySide6 / Qt6) que explora un directorio e interpreta
cabeceras de ROM/disco para **MSX**, **Sega Mega Drive** y **Super Nintendo**.

Es la versión nativa de la interfaz web original: mismo motor de análisis,
mismos colores por sistema y el mismo volcado hexadecimal enlazado a los
campos interpretados (al pasar el ratón sobre un campo se iluminan sus bytes).

## Instalación

La forma más simple es descargar el binario ya compilado de la
[última Release](../../releases/latest): hay uno para Linux, Windows y
macOS, listo para ejecutar sin instalar Python ni ninguna dependencia.

Para ejecutarlo desde el código fuente en su lugar:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> En distribuciones basadas en Debian/Ubuntu, si Qt6 se queja de no encontrar
> el plugin de plataforma `xcb`, instala la librería del sistema que falta:
> `sudo apt install libxcb-cursor0`

## Ejecutar

```bash
python3 main.py
```

## Estructura

- `rom_formats.py` — parsing puro Python (sin Qt) de cabeceras MSX (ROM/BIN/DSK),
  Sega Mega Drive y Super Nintendo, más la detección de mapper MSX.
  Reutilizable o testeable de forma independiente de la interfaz.
- `snes_tools.py` — conversión SNES: cabeceras de copiadora (añadir/quitar),
  cálculo del checksum interno y división en fragmentos de disquete. También
  puro Python, testeable de forma independiente.
- `cas_tape.py` — conversor de cintas MSX CAS ⇄ WAV (codificación FSK
  "Kansas City"). Puro Python, testeable de forma independiente.
- `tsx_tape.py` — conversor de cintas MSX CAS ⇄ TSX (bloque KCS #4B sobre
  TZX 1.21). Puro Python, testeable de forma independiente.
- `audio_tools.py` — conversión de audio (MP3/WAV/FLAC/OGG) a WAV mono de
  16 bits para las cintas MSX, por trozos y con elección automática de canal.
  Sin dependencias de Qt, testeable de forma independiente.
- `tape_player.py` — motor de reproducción de audio (Qt Multimedia):
  generación del PCM, inversión de fase y control de transporte.
- `tape_player_dialog.py` — interfaz del reproductor de cinta.
- `transfer_ucon64.py` — lógica del frontend de uCON64: localización del
  ejecutable, construcción de comandos y validaciones previas. Sin Qt.
- `transfer_dialog.py` — interfaz de transferencia por puerto paralelo.
- `main.py` — interfaz gráfica PySide6: pestañas por sistema, selector de
  carpeta, lista de archivos, panel de detalle con campos clicables y volcado
  hexadecimal con resaltado.

## Qué interpreta cada pestaña

- **MSX**: ROM de cartucho (firma `AB` → INIT/STATEMENT/DEVICE/TEXT, más
  **detección de mapper**, ver más abajo), binarios con cabecera de carga
  BLOAD (byte `0xFE` → dirección de inicio/fin/ejecución) y discos **.DSK**
  (FAT12), con **subdirectorios anidados**: el árbol se recorre
  recursivamente (con protección ante discos corruptos/cíclicos), las
  entradas administrativas `.` y `..` se omiten automáticamente. Al pasar el
  ratón sobre cualquier archivo (en la lista principal o dentro del árbol del
  disco) aparece una vista previa: tipo detectado, cabecera interpretada si la
  tiene, mapper si es una ROM, y un volcado hex/ASCII de los primeros bytes.
  Con clic derecho sobre un archivo o carpeta del disco puedes **extraerlo**
  a una carpeta de tu elección; un botón "Extraer todo el disco…" vuelca el
  disco completo preservando la jerarquía de carpetas.

### Detección de mapper MSX (MegaROM)

Un botón "🛈 Mappers MSX" en la pestaña MSX abre la lista de referencia
completa. Resumen:

- **Se detectan activamente** (aparecen como campo "Mapper detectado" al
  analizar una ROM, con un nivel de confianza):
  - Konami (sin SCC / Konami4), Konami SCC (Konami5), ASCII8, ASCII16 —
    mediante heurística por patrón de direcciones de escritura
    (`LD (nn),A` a las direcciones de conmutación de banco propias de cada
    uno). Es una heurística, igual que hacen blueMSX u openMSX cuando la ROM
    no está en su base de datos — no una certeza absoluta.
  - Variantes con **SRAM** (ESE-RAM: ASCII8/ASCII16/Konami SCC + SRAM),
    detectadas como aviso adicional por escritura en el registro de control
    7FFEh/7FFFh.
  - **NEO-8 / NEO-16** — mapper moderno con registro de 16 bits; se detecta
    de forma **determinista** (no heurística) por su firma de texto oficial
    `"ROM_NEO8"` / `"ROM_NE16"` en el offset 0x10 del ROM, tal como especifica
    la documentación oficial de MSXgl.
- **Documentados pero no detectados** (no hay direcciones de conmutación
  publicadas de forma fiable para distinguirlos): Zemina 8K/16K, Yamanooto,
  ASCII16-X. Aparecen en la lista de referencia para que sepas que existen,
  con una nota de por qué no se autodetectan.

Fuentes usadas: MSX Wiki ["MegaROM Mappers"](https://www.msx.org/wiki/MegaROM_Mappers),
[bifi.msxnet.org/msxnet/tech/megaroms](http://bifi.msxnet.org/msxnet/tech/megaroms)
(documentación técnica clásica de la escena MSX) y, para NEO-8/NEO-16, la
especificación oficial de [MSXgl](https://aoineko.org/msxgl/index.php?title=NEO_mapper).

## Selector de carpeta con volúmenes y dispositivos USB

El botón "Elegir carpeta" (y todos los diálogos de carpeta de destino) abren
un selector propio que muestra:

- **Acceso rápido**: carpeta personal, Descargas/Escritorio/Documentos, y
  los medios extraíbles ya montados en `/media/<usuario>`, `/run/media/…`
  o `/mnt`.
- **Volúmenes montados**: detectados con `lsblk`, con etiqueta, tamaño y
  sistema de archivos. Se filtran los puntos de montaje internos del
  sistema (`/proc`, `/sys`, `/snap`…) para no ensuciar la lista.
- **Conectados pero sin montar**: particiones presentes en el sistema que
  todavía no están montadas — el caso típico de un USB recién conectado en
  un equipo sin automontaje. **Un dispositivo sin montar no se puede
  explorar**, así que la app ofrece un botón "Montar dispositivo" que usa
  `udisksctl` (paquete `udisks2`), lo que en un escritorio Linux normal
  funciona **sin privilegios de root**: udisks2 + polkit conceden el permiso
  al usuario de la sesión activa para dispositivos extraíbles. Tras montarlo,
  la lista se actualiza y el nuevo punto de montaje queda seleccionado.

Si `udisksctl` no está instalado, la app lo indica y sugiere montarlo a mano
en vez de intentar métodos que exigirían root. El botón "Examinar…" sigue
disponible para navegar libremente por el sistema de archivos.

## Selección múltiple y panel de archivos generados

**Selección múltiple.** La lista de archivos admite selección múltiple
(Ctrl+clic, Mayús+clic para rangos, Ctrl+A para todo). Las operaciones de
conversión detectan cuántos archivos hay seleccionados:

- **Un archivo**: comportamiento clásico, con diálogo de "guardar como".
- **Varios archivos**: pide **una sola carpeta de destino**, aplica
  automáticamente la coletilla correspondiente a cada archivo
  (`_sin_cabecera`, `_swc`, `_checksum`, `_deint`, `_int`…) y termina con un
  informe detallado de qué se procesó y qué se omitió, con el motivo de cada
  omisión. Un archivo que no se pueda procesar (p. ej. porque ya tiene
  cabecera) no aborta el resto del lote.

Aplica a: quitar cabecera, añadir cabecera (genérica y SWC), corregir
checksum, y entrelazar/desentrelazar. Las operaciones de división quedan
fuera del modo lote, porque cada archivo de entrada genera varios de salida.

**Panel de archivos generados.** Bajo la lista de originales hay un segundo
panel, con divisor arrastrable, donde aparecen los archivos que la
aplicación va creando. Se puebla **al instante** tras cada operación (la app
registra lo que escribe, no depende de un refresco), e incluye:

- Botón **⟳**: re-escanea las carpetas de destino conocidas, para recoger
  también archivos creados fuera de la aplicación.
- Botón **✕**: vacía la lista (no borra nada del disco).
- Clic sobre un archivo: lo analiza en el panel de detalle igual que
  cualquier original, para comprobar de inmediato que la conversión salió
  bien.
- Clic derecho: abrir la carpeta contenedora, o quitarlo de la lista.

Los archivos generados también se pueden seleccionar para aplicarles nuevas
operaciones, de modo que se pueden encadenar conversiones sin tener que
volver a abrir la carpeta.

## Conversión de formato Mega Drive

En la pestaña **Mega Drive** hay un panel con las conversiones habituales.
Ojo, porque son **dos transformaciones distintas** que a veces se confunden:

### Byte swap (16 bits)

Intercambia los dos bytes de cada palabra de 16 bits a lo largo de todo el
archivo. Es la diferencia entre un volcado normal y uno "swapped": se
reconoce a simple vista en el offset 0x100, donde un ROM correcto muestra
`SEGA GENESIS` y uno intercambiado muestra `ESAGG NESESI`.

**Por qué ocurre: es una cuestión de endianness.** El 68000 de la Mega Drive
es *big-endian*, es decir, guarda el byte más significativo de cada palabra
de 16 bits en primer lugar. Un ROM "swapped" es exactamente el mismo
contenido almacenado en *little-endian*. Por eso la firma se corrompe de una
forma tan característica: `SEGA` son dos palabras de 16 bits (`SE` y `GA`) y
al invertir cada una queda `ES` + `AG` → `ESAG`. Y por eso el archivo sigue
teniendo el mismo tamaño y sigue siendo válido: no se pierde ni se añade
nada, solo cambia el orden dentro de cada palabra.

El origen suele estar en el volcador o en la máquina que hizo el dump: un
copiador o un PC x86 (little-endian) que lee la ROM en palabras de 16 bits y
las escribe tal cual a disco produce justo este efecto.

**Importante: el entrelazado SMD no es un problema de endianness**, aunque a
veces se le llame "byte swap" coloquialmente. Ahí los bytes se reagrupan por
bloques de 16 KB por cómo accede a memoria la BIOS del Super Magic Drive
(ver más abajo). Son dos transformaciones con causas distintas, y aplicar la
equivocada deja el archivo peor que antes — de ahí que estén separadas y que
la app verifique el resultado en ambos casos.

La operación es **su propia inversa** (aplicarla dos veces devuelve el
original), y la app **detecta automáticamente** en qué estado está el
archivo, indicándolo en el mensaje de resultado y en el nombre de salida
(`_normal` o `_swapped`). Además, al analizar un ROM cuya cabecera no se
reconoce, la app comprueba si es un caso de bytes intercambiados y lo avisa,
en vez de limitarse a decir "cabecera no encontrada".

**Verificado byte a byte** contra un par de archivos reales del mismo juego
(*Aero the Acro-Bat 2*, versión normal y versión "Swapped Bytes") aportados
por el usuario: la conversión reproduce exactamente el otro archivo en ambos
sentidos.

### Formato SMD (Super Magic Drive)

Esto es **otra cosa distinta del byte swap**: convierte entre el formato
plano (`.bin`/`.gen`/`.md`) y el formato entrelazado `.smd` del Super Magic
Drive:

- **SMD → BIN (desentrelazar)**
- **BIN → SMD (entrelazar)**
- **Quitar cabecera SMD** (los 512 bytes iniciales)

Un `.smd` consta de una cabecera de 512 bytes y los datos organizados en
bloques de 16 KB; dentro de cada bloque, la primera mitad contiene los bytes
de una paridad y la segunda los de la otra. El entrelazado viene de que la
BIOS del Super Magic Drive funciona en modo de compatibilidad con Master
System, lo que limita el tamaño de los accesos a memoria.

**Sobre la ambigüedad de las fuentes y cómo se resuelve.** Las
descripciones publicadas se contradicen sobre qué paridad va primero (unas
dicen "primero los pares", otras "primero los impares"; la discrepancia
viene de contar desde 0 o desde 1). En vez de elegir una a ciegas, la app
implementa **ambas variantes y verifica el resultado**: un ROM de Mega Drive
válido tiene la firma `SEGA` en el offset 0x100, así que se prueba la
conversión y se comprueba ese marcador. La variante que produce una cabecera
válida es, por definición, la correcta para ese archivo. Si ninguna la
produce, la app lo dice claramente en vez de dar por bueno un resultado sin
verificar.

Admite selección múltiple, igual que las herramientas de SNES.

## Grabar imágenes en disquete físico

Las imágenes `.dsk` y `.img` se pueden grabar en una unidad real (disquetera
USB, lector de disquete interno…) desde el menú contextual de la lista de
archivos generados, o directamente tras crear disquetes vacíos.

Grabar en crudo sobre un dispositivo **borra todo su contenido**, así que el
diálogo está construido para evitar accidentes:

- Por defecto solo se listan **discos extraíbles y disqueteras**. Los discos
  internos —y las memorias USB de gran capacidad— quedan ocultos tras una
  casilla explícita y, si se activa, aparecen en rojo con la advertencia.
- Se avisa si el dispositivo es mucho mayor que la imagen (señal de que
  quizá sea una memoria USB de datos y no una disquetera), y el botón se
  bloquea si la imagen no cabe.
- Hay que escribir la palabra **GRABAR** para habilitar el botón, y después
  confirmar en un diálogo que muestra el dispositivo concreto.
- El dispositivo se **desmonta automáticamente** antes de escribir.
- La escritura ocurre en un hilo aparte y la ventana no se puede cerrar a
  mitad de la operación.

Si el usuario no tiene permisos directos sobre el dispositivo, la escritura
se hace con `pkexec dd`, que pide la contraseña por el diálogo gráfico del
sistema. Si no hubiera `pkexec`, se muestra el comando `dd` equivalente para
ejecutarlo a mano.

## Transferencia al copión por puerto paralelo (SNES / Mega Drive)

En las pestañas **SNES** y **Mega Drive**, el botón "⇄ Enviar a Super Wild
Card…" / "⇄ Enviar a Super Magic Drive…" abre el diálogo de transferencia.

**Usa uCON64 como motor**, no una reimplementación propia. El motivo es
deliberado: el handshake de los copiones FFE es un bucle byte a byte con
temporización estricta sobre las líneas del puerto paralelo. uCON64 lo
implementa en C con acceso directo a los registros; hacerlo en Python sobre
`ppdev` supondría varias llamadas al kernel por byte (decenas de millones
para una ROM de 4 MB), con riesgo de romper la temporización que espera el
hardware. Envolver la herramienta de referencia es más rápido y mucho más
seguro para el copión.

El diálogo se encarga de: localizar el ejecutable de uCON64 (o dejar que
indiques su ruta), elegir copión y puerto (`/dev/parportN` detectados
automáticamente, o direcciones `0x378`/`0x278`/`0x3bc`), validar las
condiciones previas antes de lanzar nada, y mostrar la salida de uCON64 en
tiempo real en una consola integrada, con posibilidad de cancelar.

Comandos que construye (verificados contra la documentación oficial de
uCON64): `--xswc` para Super Wild Card y compatibles, `--xsmd` para Super
Magic Drive, y `--xswcs`/`--xsmds` para SRAM.

### Requisitos de hardware (importante)

- Hace falta un **puerto paralelo real** (integrado o tarjeta PCI/PCIe).
  Los **adaptadores USB→paralelo NO funcionan**: son dispositivos de clase
  impresora y no permiten el control a nivel de bit que exige el protocolo.
- Cable paralelo **bidireccional** estándar.
- En Linux: módulos `ppdev` y `parport_pc` cargados, y pertenecer al grupo
  `lp` (o ejecutar como root) para acceder a `/dev/parportN`.
- Encender el copión **antes** de iniciar la transferencia.

La app comprueba varias de estas condiciones y avisa antes de lanzar la
transferencia (permisos, existencia del dispositivo, extensión del archivo
coherente con el copión elegido, etc.).

### ⚠️ Fiabilidad por plataforma: Linux es la vía recomendada

En **Linux**, la transferencia por puerto paralelo accede al hardware a
través de `ppdev` (soporte del propio kernel) y funciona de forma fiable.

En **Windows**, uCON64 necesita un driver de terceros para acceder al
puerto (`InpOut32.dll` o `giveio64`, ninguno mantenido activamente ni
firmado por Microsoft más allá de una firma de terceros). En pruebas
extensas con una tarjeta PCIe de puerto paralelo con chipset ASIX AX99100
(un controlador que emula IEEE1284 en vez de exponer un puerto paralelo
de acceso directo tipo Super I/O clásico), la transferencia arrancaba sin
errores pero **los datos nunca llegaban íntegros al copión**: el
protocolo FFE que usan estos copiones necesita temporización muy
ajustada, y la capa de traducción interna de ese chipset introduce
latencia suficiente para romperla. Con otro hardware de puerto paralelo
(sobre todo uno tradicional integrado en placa base) podría funcionar sin
problema — la causa raíz está más en la combinación de driver+chipset
concreta que en el propio uCON64 o en ASTURCONSOLE.

**Recomendación**: si vas a transferir por puerto paralelo con
regularidad, usa la versión Linux si te es posible. La versión Windows
es igual de fiable para todo lo demás (conversión de formatos, disquetes,
cintas, HFE…) — la limitación conocida es específica de esta función.

## Crear disquetes MSX vacíos

Botón **"Crear disquetes vacíos…"** en el panel de cintas de MSX. Genera
imágenes `.dsk` de 720 KB recién formateadas y vacías, con el formato
estándar de disco MSX de doble cara y doble densidad (80 pistas, 9 sectores
por pista, 2 caras; 512 bytes/sector, 2 sectores por clúster, 112 entradas
de raíz, descriptor de medio 0xF9). Quedan 713 KB libres, igual que tras un
FORMAT en MSX-DOS.

Se puede indicar el nombre base (por defecto `MSXDD001`), la cantidad
(hasta 100) y, opcionalmente, una etiqueta de volumen. La numeración
continúa desde los dígitos finales del nombre: `MSXDD001` genera
`MSXDD001.dsk`, `MSXDD002.dsk`… hasta `MSXDD100.dsk`. Los archivos van a la
carpeta `disquetes vacios` del espacio de trabajo.

## Reproductor de cinta (carga en MSX real)

Botón **"▶ Reproducir cinta…"** en el panel de cintas. Abre un `.cas` o
`.tsx` (los TSX se convierten a CAS al vuelo) y lo emite por la tarjeta de
sonido, para cargarlo en un MSX real conectando la salida de audio del PC a
la entrada de casete del ordenador.

Incluye una **pletina animada** inspirada en los data recorders de la época
(NEC PC-6081 / DR-310 y similares): las dos bobinas giran mientras carga, el
rollo de la bobina emisora se va vaciando y el de la receptora llenándose (y
la velocidad de giro aumenta conforme adelgaza, como en un casete real), un
cuentavueltas mecánico de tres dígitos avanza con el progreso, y la tecla
correspondiente de la botonera queda hundida e iluminada según el estado
(PLAY, PAUSE, REW o STOP), con piloto de actividad e indicador de nivel.

**Las teclas de la pletina son los controles reales**: se pulsan directamente
sobre el dibujo, sin botones duplicados debajo que taparan el aparato. PLAY,
PAUSE y STOP hacen lo esperado, y **REW rebobina al principio de la cinta**
con su animación (bobinas girando al revés y cuentavueltas cayendo a cero).
REC y FF se dibujan atenuados: existían en el aparato original pero aquí no
tienen función.

Para cargar la cinta hay dos botones: **«Abrir cinta…»**, que empieza en las
carpetas de trabajo, y **«Dispositivos…»**, que abre el mismo selector de
volúmenes y USB que usa la pestaña SNES, con opción de montar la unidad
antes de buscar el archivo dentro.

Deliberadamente simple en cuanto a controles: reproducir/pausa/detener, barra de progreso,
volumen, y solo tres ajustes, todos ellos con una razón concreta:

- **Velocidad**: 1200 / 2400 (estándar de la ROM) y 3000 / 3600 (no
  estándar — el MSX debe haberse configurado antes para leer a esa
  velocidad; la app avisa de ello). Estas dos últimas son las mismas
  velocidades extra que ofrecen otras herramientas del ecosistema.
- **Frecuencia de muestreo**: por defecto **96000 Hz**, no 44100. Es un
  detalle que importa más de lo que parece: a 2400 baudios y 44.1 kHz solo
  hay ~4.6 muestras por semiciclo del tono agudo, lo que deforma la onda
  cuadrada y es causa habitual de cargas fallidas; a 96 kHz hay ~10. La app
  calcula esta cifra y avisa cuando el margen es justo.
- **Invertir fase**: algunos equipos solo reconocen la señal con una
  polaridad concreta.

Además permite elegir el dispositivo de salida (útil si tienes una tarjeta
de sonido concreta conectada al MSX). El audio se genera y reproduce
siempre en mono, como corresponde al puerto de casete.

Recomendación al usar: desactivar ecualizadores, "mejoras de audio" y
cualquier efecto del sistema, y evitar el remuestreo automático del
servidor de sonido — deforman la señal y suelen impedir la carga.

### Grabar cintas (digitalizar una cinta real)

La tecla **REC** de la pletina graba la entrada de audio a un archivo WAV,
para digitalizar cintas físicas: se conecta la salida del casete a la entrada
de línea del PC y se pulsa REC. Vuelve a pulsarse REC (o STOP) para terminar.

- Siempre **mono y sin ningún procesado**: cualquier filtro o normalización
  deformaría los flancos de la onda y dificultaría la decodificación.
- Frecuencias ofrecidas: 22050, **43200**, 44100, 48000 y 96000 Hz. La de
  43200 aparece porque es la que usan varias grabaciones de referencia de la
  escena MSX: al ser múltiplo exacto de 1200 (36 × 1200), cada ciclo del tono
  cae en un número entero de muestras y la onda no acumula deriva.
- Durante la grabación, el indicador LOAD LEVEL muestra el **nivel real de la
  señal de entrada** y la interfaz avisa si está saturando o si es demasiado
  bajo, que son las dos causas habituales de que luego no se pueda decodificar.
- Al terminar, la aplicación **analiza automáticamente** lo grabado: si
  reconoce bloques MSX, indica cuántos y a qué velocidad; si no, avisa de que
  probablemente haya un problema de nivel.

## Conversor de cintas MSX (CAS ⇄ WAV ⇄ TSX)

En la pestaña MSX, un panel aparte permite convertir entre los tres
formatos de cinta:

- **CAS → WAV** / **WAV → CAS**: codificación FSK "Kansas City" de la BIOS
  del MSX. Ver detalle más abajo.
- **CAS → TSX** / **TSX → CAS**: TSX es una extensión de TZX (versión
  1.21) con un bloque específico **#4B** para datos Kansas City Standard.
  Cada segmento del CAS (delimitado por su marca de sincronismo de 8
  bytes) se envuelve en un bloque #4B con los parámetros de temporización
  KCS (duración de pulso piloto/cero/uno en T-states, nº de pulsos del
  piloto, configuración de bits/bytes). La marca de sincronismo en sí
  **no** se guarda en los datos del bloque — es implícita en la existencia
  del propio bloque #4B — y se reconstruye automáticamente al volver a
  CAS, con el relleno de alineación a 8 bytes que exige el formato.

  **Especificación verificada de dos formas independientes:** contra los
  comentarios de cabecera del código fuente de referencia (`tsx.php`,
  proyecto TSXphpclass de NataliaPC, creadora del formato:
  [github.com/nataliapc/MSX_devs](https://github.com/nataliapc/MSX_devs/blob/master/TSXphpclass/tsx.php))
  y disecando byte a byte tres archivos `.tsx` reales (ripeos de cintas
  comerciales MSX). Probado con ida y vuelta CAS→TSX→CAS con datos propios
  (idéntico byte a byte) y con los tres archivos reales aportados por el
  usuario (ciclo TSX→CAS→TSX→CAS estable). El lector reconoce además los
  bloques TZX estándar más comunes (texto, información de archivo,
  pausas, bloques Spectrum, CSW...) lo justo para poder saltarlos sin
  interpretarlos, ya que el contenido relevante para MSX siempre está en
  los bloques #4B.

  Nota real encontrada durante la verificación: en juegos con cargador de
  cinta personalizado/con protección (habitual en títulos más complejos,
  p. ej. arcades como *After Burner*), solo el primer bloque sigue el
  formato de cabecera CAS estándar reconocible (10 bytes de tipo + 6 de
  nombre); el resto son datos en bruto específicos de ese cargador. No es
  un fallo de conversión — el conversor extrae fielmente lo que hay,
  igual que haría cualquier herramienta de la escena de preservación.

### MP3 → WAV mono (dispositivos modernos de cinta)

Los dispositivos modernos que sustituyen al casete suelen guardar la cinta
como **MP3 estéreo**, pero el MSX trabaja con una única línea de señal: un
**WAV mono**. El botón **MP3 → WAV mono…** (también disponible como acción
en la ventana de trabajo) decodifica el audio y lo reduce a un canal,
guardando un WAV PCM de 16 bits en la carpeta de cintas MSX. Acepta también
WAV (estéreo), FLAC y OGG, y admite lo que haya dentro del archivo aunque la
extensión diga otra cosa (un archivo real probado se llamaba `.MP3` pero
contenía MPEG Layer II). No modifica la forma de onda más allá de decodificar
y reducir a un canal: los datos del MSX viajan en la frecuencia de la señal,
no en su volumen.

- **Canal.** *Automático* (por defecto) examina el primer minuto y elige:
  mezcla los dos canales si llevan la misma señal; usa solo uno si el otro
  está casi vacío o solo lleva ruido; y también usa solo uno si los canales
  están en **contrafase** (uno es el inverso del otro), porque entonces una
  mezcla simple se cancela y sale un WAV **mudo**. También se puede forzar
  mezcla, izquierdo o derecho. Importa más de lo que parece: el *WAV → CAS*
  de la aplicación, ante un WAV estéreo, lee solo el canal **izquierdo**; el
  dispositivo real probado grababa la señal únicamente en el **derecho** (el
  izquierdo era ruido al 6 %), de modo que sin este paso se habría leído el
  canal equivocado.
- **Frecuencia de muestreo.** Por defecto se conserva la del archivo (algunos
  dispositivos y codificadores graban a 32000 o 24000 Hz); se puede
  remuestrear a 44100, 48000 o 22050 Hz.
- **Aviso de nivel.** Se juzga por el nivel *típico* (percentil 90 de los
  picos por trozo), no por el máximo: con el máximo bastaban 21 muestras
  sueltas al final de un MP3 en contrafase para que un WAV mudo marcara 93 %
  y no saltara el aviso. Si el nivel típico queda por debajo del 10 % se avisa,
  sugiriendo probar otro canal.
- **Cintas largas.** Se procesa por trozos, sin cargar el audio entero:
  medido con una cinta de 30 minutos, unos 5 segundos y 63 MB de memoria
  máxima (el WAV resultante, de 159 MB, nunca está entero en memoria). El
  archivo real de 6 min 44 s tarda 1,5 s.

Decodificador: el módulo `miniaudio` (`pip install miniaudio cffi`, ya en
`requirements.txt`; hay que instalar también `cffi`, ver `INSTALL.md`). Si no
está, se usa `ffmpeg` si está en el PATH. Si no hay ninguno, la aplicación lo
indica antes de pedir ningún archivo. Ambos dan el mismo resultado salvo por
el recorte del retardo del codificador (hasta unos 3100 muestras de diferencia
al principio/final, irrelevante para una cinta).

**Límites, medidos y no supuestos:**

- La conversión en sí es exacta: con audio sin pérdidas el resultado es
  idéntico muestra a muestra a la señal original. Pero el **MP3/MP2 comprime
  con pérdidas** y eso no se puede deshacer.
- **Con el archivo real probado (un juego, «POKER», 160 kbps) la cinta NO se
  recupera completa** con el *WAV → CAS* de la aplicación: se leen las 14
  secciones, con cabeceras y direcciones coherentes (cargador BASIC y 5
  bloques binarios), pero los datos recuperados son solo el 93–96 % de lo que
  declaran las cabeceras BLOAD, con cualquiera de los dos detectores de cruces
  probados. No se ha determinado si la pérdida viene de la señal (audio
  grabado a fondo de escala y comprimido) o del decodificador.
- En pruebas con una cinta sintética a 1200 baudios, el *WAV → CAS* se mostró
  sensible al ruido que añade la compresión: con bordes suavizados (más
  parecido a una cinta real) falló a todas las tasas de bits probadas
  (64–320 kbps), y con una onda cuadrada perfecta solo acertó a 160, 192 y
  320 kbps. Con un detector de cruces con histéresis (como el comparador de un
  MSX real) se recuperó la mayoría de los casos (17 de 24 combinaciones).
- **No se ha probado** cómo se comportan un MSX real ni un emulador con estos
  WAV; las pruebas se hicieron contra el propio decodificador de la aplicación.

### CAS ⇄ WAV
- **CAS → WAV**: codifica el archivo `.cas` como audio FSK "Kansas City",
  el esquema que usa la BIOS del MSX — a 1200 baudios (el habitual) el bit 0
  es un ciclo a 1200 Hz y el bit 1 son dos ciclos a 2400 Hz; a 2400 baudios
  (turbo) se dobla a 2400/4800 Hz. Cada byte se transmite como 1 bit de
  arranque + 8 bits de datos (LSB primero) + 2 bits de parada. El WAV se
  genera **siempre en mono** (el casete del MSX es una única línea de
  señal; un WAV estéreo solo duplicaría datos sin aportar nada — la propia
  herramienta de referencia del ecosistema, MCP, genera igualmente mono).
- **WAV → CAS**: hace el proceso inverso, con **velocidad detectada
  automáticamente**. Tres detalles aprendidos al probar contra grabaciones
  reales aportadas por el usuario, que hacían fallar la conversión:

  1. **Cruces descendentes, no ascendentes.** En una senoide bien generada
     cada ciclo empieza justo en el cruce descendente, así que medir entre
     cruces descendentes da la duración exacta del ciclo. Con los
     ascendentes, la fase difiere entre las dos frecuencias y cada cambio de
     tono producía un periodo intermedio espurio. Medido en un archivo real:
     con ascendentes salían periodos de 9, 18, 13 y 14 muestras; con
     descendentes, solo 9 y 18 — las dos frecuencias reales.
  2. **La marca de sincronismo no está en el audio.** Los 8 bytes de la marca
     de un `.CAS` son una convención del formato que representa el TONO
     PILOTO; no van grabados en la cinta. El decodificador detecta las
     rachas largas de tono agudo y coloca la marca en su lugar, con el
     relleno de alineación a 8 bytes.
  3. **Las cintas reales no van a velocidades redondas.** Los ripeos
     aportados resultaron estar a ~1225 y ~1696 baudios (dependen del
     cargador del juego y de la mecánica del casete). Imponer 1200/2400 hacía
     fallar la lectura; ahora la velocidad se mide de la propia señal.

  4. **Las pausas entre bloques.** Las cintas reales llevan silencios (medidos:
     0,625 s tras una cabecera, para que el MSX la procese, y 2,5 s antes del
     archivo siguiente). El decodificador los reconocía como un bit 0 espurio;
     ahora los trata como separadores de bloque. Y el generador los emite,
     junto con una cola corta de tono tras cada bloque: sin ella, el último
     ciclo quedaba absorbido por el silencio —que no produce cruces por cero—
     y se perdía el último bit del bloque.

  Verificado contra 12 grabaciones reales de cintas comerciales: las 12 se
  decodifican con bloques y nombres válidos. **Validación cruzada**: para
  *Zanac*, que el usuario aportó en ambos formatos, el CAS obtenido desde el
  WAV y el obtenido desde el TSX resultan **idénticos byte a byte** — dos
  rutas de decodificación independientes que llegan al mismo resultado. Pensado para audio limpio
  generado digitalmente (por esta misma herramienta, un emulador, etc.), no
  para grabaciones reales de casete con ruido o deriva de velocidad — para
  eso existen herramientas especializadas como *castools* (`wav2cas`), que
  aplican control de umbral, envolvente y fase para tolerar señal
  degradada.

Simplificación deliberada: se antepone un tono piloto de la misma duración
a cada marca de sincronismo del CAS, en vez de alternar entre piloto largo
(cabecera) y corto (datos) como hacen algunas grabaciones de referencia.
Es más simple y nunca causa fallos de carga (un piloto más largo de lo
necesario no es un problema); el archivo WAV resultante es algo más largo
de lo estrictamente necesario a cambio de esa robustez.

Probado con ida y vuelta CAS→WAV→CAS a 1200/2400 baudios, 8/16 bit y varias
frecuencias de muestreo, incluidos los 256 valores de byte posibles y un
archivo de 64 KB (tamaño típico de un juego): reconstruye el original byte
a byte.

Fuentes usadas para el formato CAS y la codificación FSK: hilos técnicos de
[msx.org](https://www.msx.org/forum/msx-talk/general-discussion/cas-format)
sobre el formato ".CAS", [MSX Wiki "Emulation related file formats"](https://www.msx.org/wiki/Emulation_related_file_formats),
y la página de Wikipedia sobre el [Kansas City standard](https://en.wikipedia.org/wiki/Kansas_City_standard).
- **Mega Drive**: cabecera SEGA en `0x100` (títulos JP/exportación, serie,
  checksum, rangos de ROM/RAM, región).
- **Super NES**: localiza LoROM (`0x7FC0`) o HiROM (`0xFFC0`), detecta cabecera
  de copiadora (+512 bytes), valida el checksum contra su complemento y
  muestra tipo de mapeo, tamaño de ROM/RAM y región. Además incluye una barra
  de herramientas de conversión (ver más abajo).

## Herramientas de conversión SNES (copiadoras de época)

En la pestaña SNES, además de leer la cabecera, puedes actuar sobre el
archivo seleccionado. Todas las operaciones guardan el resultado como un
**archivo nuevo**, nunca sobrescriben el original:

- **Quitar cabecera**: elimina el bloque de 512 bytes que anteponen la
  mayoría de copiadoras (Super Wild Card, Super UFO, Pro Fighter...).
- **Añadir cabecera genérica**: antepone 512 bytes a cero, el formato que
  reconoce prácticamente cualquier emulador o copiadora.
- **Añadir cabecera Super Wild Card**: antepone una cabecera con la firma
  `AA BB 04` y el nº de bloques de 8 KB calculado a partir del tamaño del
  archivo. El archivo resultante se nombra con extensión **`.swc`**
  (confirmado: es la extensión real que usa/espera el hardware — "dumped
  games end up in .SWC format... Only \*.RTS, \*.BBD and \*.SWC have a
  header", según [robohara.com](https://www.robohara.com/?p=1042) y el
  [FAQ de la SWC DX2](http://dbwbp.com/index.php/9-misc/31-swc-dx2-faq)).
- **Verificar / corregir checksum**: recalcula el checksum interno de la
  ROM (suma de 16 bits con espejado para tamaños que no son potencia de
  dos) y lo escribe en la cabecera SNES, respetando si el archivo tiene o
  no cabecera de copiador delante.
- **Dividir en disquetes (bruto)…**: trocea el archivo en fragmentos del
  tamaño de disquete que elijas (360 KB / 720 KB / 1.2 MB / 1.44 MB /
  personalizado), numerados como `NOMBRE.001`, `NOMBRE.002`, etc. Son
  fragmentos de bytes en bruto, **no** discos con sistema de archivos — hay
  que copiarlos a disquetes ya formateados con otra herramienta. Útil para
  usos genéricos; para Super Wild Card usa la opción específica de abajo.
- **Dividir en discos SWC…**: la opción correcta para repartir un ROM
  grande entre varios disquetes de una Super Wild Card. Genera imágenes
  `.img` de 1.44 MB **con sistema de archivos FAT12 real** (arrancables,
  formato WinImage), cada una con un único archivo dentro y **su propia
  cabecera SWC de 512 bytes** — no solo la primera parte. Cada cabecera
  hereda todos los bytes de la cabecera original (SRAM, modo de arranque,
  etc., que son específicos del juego y no se pueden reconstruir desde
  cero con fiabilidad) y solo se ajustan dos campos por parte: el recuento
  de páginas de 8 KB (bytes 0-1) y el bit "quedan más partes" en el byte 2
  (activado en todas menos la última). Requiere que el archivo ya tenga
  cabecera Super Wild Card (usa antes "Añadir cabecera Super Wild Card").

  **Verificado contra hardware físico real, dos veces:** el propio usuario
  aportó archivos `.img` reales de una Super Wild Card DX2 en
  funcionamiento — primero *Adventures of Batman & Robin* (LoROM, partido
  en 2 discos de ~1 MB exactos) y después *ClayFighter: Tournament Edition*
  (HiROM, partido en 3 discos de tamaño máximo). En ambos casos, reconstruir
  el ROM completo a partir de los archivos reales y volver a dividirlo con
  esta función reproduce los `.img` originales **byte a byte** en la parte
  que importa (sector de arranque, FAT, directorio, cabecera y datos del
  archivo); las únicas diferencias son bytes sin relevancia funcional
  (número de serie de volumen y marcas de tiempo del directorio, que son
  aleatorios/arbitrarios incluso entre distintas grabaciones con WinImage) y,
  en discos con la última parte más pequeña, el contenido del espacio sin
  usar del disquete (que esta herramienta rellena con ceros limpios en vez
  de dejar restos de un uso anterior de un disquete físico).
- **Desentrelazar (HiROM) / Entrelazar (HiROM)**: convierte entre el formato
  normal de HiROM y el formato "entrelazado" que producían Game Doctor y
  Super UFO al volcar cartuchos HiROM (y, por error, alguna Super Wild Card
  mal configurada). El formato Super Wild Card en sí **no** va entrelazado:
  para pasar un volcado entrelazado a formato SWC hay que desentrelazarlo
  primero y luego añadir la cabecera SWC. Algoritmo verificado con la
  documentación del proyecto uCON64 y con pruebas de ida y vuelta
  (entrelazar→desentrelazar reconstruye el archivo original byte a byte).
- **Byte swap por lotes…**: aplica el entrelazado/desentrelazado anterior a
  todos los archivos SNES (`.sfc .smc .fig .swc .ufo .bin`) de una carpeta,
  incluidas subcarpetas. Eliges la operación y la coletilla (por defecto
  `_deint` o `_int`); cada resultado se guarda como archivo nuevo junto al
  original, que nunca se modifica. Los archivos que ya tienen la coletilla
  se omiten automáticamente para no reprocesar resultados de una pasada
  anterior. Al terminar muestra un informe con lo procesado y lo omitido
  (y por qué).

### Sobre la fiabilidad del entrelazado

Solo se implementa el formato de entrelazado "simple" (mitades de 32 KB
alternadas por banco de 64 KB), que es el que documenta el propio proyecto
uCON64 como el más habitual. Esa misma documentación menciona que existe
**al menos una variante distinta** (usada por algunos juegos con chip
Super FX), que esta herramienta no reconoce — si tu ROM usa esa variante,
el resultado del desentrelazado no será correcto. Verifica siempre el
resultado (por ejemplo comprobando que el checksum cuadra tras recalcularlo,
o que el título de la cabecera aparece legible) antes de darlo por bueno.

### Sobre la fiabilidad de la detección de marca de copiadora

Las cabeceras de copiadoras SNES de los 90 no siguieron un estándar único
documentado de forma consistente entre fuentes. Solo se identifica con
confianza:

- el bloque **genérico** de 512 bytes (detectado por
  `tamaño_archivo % 32768 == 512`, que es lo que comprueban también los
  emuladores), y
- la cabecera **Super Wild Card**, por su firma fija `AA BB 04` en los
  offsets **8-10** (verificado byte a byte contra la especificación oficial
  de JSI/Front Far East —
  [wiki.superfamicom.org/super-wild-card](https://wiki.superfamicom.org/super-wild-card)—
  y contra varios archivos `.SWC`/`.img` reales de una Super Wild Card DX2
  física en funcionamiento).

El resto de copiadoras de la época (Super UFO, Pro Fighter, Game Doctor...)
compartían ese mismo bloque de 512 bytes sin ninguna firma distintiva, así
que no se puede saber con certeza cuál lo generó — en esos casos se muestra
como "genérica" en vez de adivinar una marca.

## Limitaciones conocidas (versión inicial)

- La detección de mapper MSX clásico es heurística (por patrón de
  direcciones de escritura), no una certeza garantizada; ROMs con código muy
  atípico podrían no distinguirse con claridad ("No determinado").
- SNES/Mega Drive no recalculan el checksum real del ROM salvo con la
  herramienta explícita de "Verificar / corregir checksum" en SNES.
- La vista previa al pasar el ratón sobre archivos grandes (> 1.5 MB, poco
  habitual en MSX) se omite por rendimiento; solo se muestra tamaño.

## Tipografía de la firma

La firma «asturconsole by ritcher1986» se muestra en azul con una tipografía
de aire gótico. La aplicación busca primero una blackletter real instalada en
el sistema (UnifrakturMaguntia, Old English Text MT, Cloister Black, Fette
Fraktur…) y, si no encuentra ninguna, usa **Gloock**, incluida en
`assets/fonts/` — un serif de alto contraste con aire gótico, distribuido
bajo licencia SIL Open Font License (la licencia se incluye junto al
archivo). Si quieres un aspecto blackletter auténtico, basta con instalar una
de esas familias en el sistema: la aplicación la usará automáticamente.

## Iconos y fondo personalizados

`assets/icons/` contiene arte propio (no fotos ni logos reales, por
derechos de autor si la app se redistribuye) en el mismo lenguaje visual
retro/CRT del resto de la interfaz — silueta de cartucho, tipografía
monoespaciada, colores de acento por sistema:

- `msx.svg` — cartucho MSX (verde fósforo)
- `genesis.svg` — cartucho Mega Drive (rojo)
- `snes.svg` — cartucho SNES (lila)
- `superwildcard.svg` — cartucho Super Wild Card (dorado, con el rayo de
  "copiadora/flash"); se usa en el botón de añadir cabecera SWC de la
  pestaña SNES
- `app_icon.svg` — icono principal de la app (monitor CRT con el prompt
  "ROM://" y cursor parpadeante)
- `scanlines_bg.png` — textura tileable de 4×4 px con líneas de escaneo
  muy sutiles, usada como fondo de la ventana principal

Los tres iconos de pestaña (MSX/Mega Drive/SNES) y el icono de ventana se
cargan automáticamente al arrancar `main.py`; no hace falta ninguna
dependencia extra (PySide6 soporta SVG de forma nativa a través de
`QIcon`).

## Compilar un binario standalone (Linux / Windows)

La app puede empaquetarse como un único ejecutable que no necesita Python
instalado, usando [PyInstaller](https://pyinstaller.org/). **Importante:**
PyInstaller no hace compilación cruzada real — hay que compilar el binario
de Linux *en* Linux, y el de Windows *en* Windows. Hay dos formas de
hacerlo:

### Opción A: en tu propia máquina

```bash
# Linux
./build_linux.sh
# -> dist/asturconsole

# Windows (símbolo del sistema, no PowerShell)
build_windows.bat
REM -> dist\asturconsole.exe
```

Cada script crea su propio entorno virtual, instala `PySide6` y
`pyinstaller`, y compila usando `asturconsole.spec` (que ya incluye la
carpeta `assets/` empaquetada dentro del ejecutable, así que los iconos y
la textura de fondo funcionan igual que en modo desarrollo).

### Opción B: GitHub Actions (recomendada si no tienes ambos sistemas)

El repositorio incluye `.github/workflows/build.yml`, que compila **Linux
y Windows a la vez**, cada uno en su propia máquina virtual de GitHub —así
no hace falta tener un Windows a mano para generar el `.exe`. Para usarlo:

1. Sube esta carpeta a un repositorio de GitHub.
2. Ve a la pestaña **Actions** del repositorio y ejecuta el workflow
   manualmente ("Run workflow"), o simplemente haz push a `main`.
3. Cuando termine, descarga los dos binarios desde la sección
   **Artifacts** de la ejecución: `asturconsole-linux64` y
   `asturconsole-windows64`.

### Notas

- El icono de la app en Windows usa `assets/icons/app_icon.ico` (formato
  específico de Windows, generado a partir del mismo diseño que
  `app_icon.svg`, en varias resoluciones de 16 a 256 px).
- En Linux, si al ejecutar el binario compilado Qt se queja de no
  encontrar el plugin de plataforma `xcb`, instala `libxcb-cursor0`
  (`sudo apt install libxcb-cursor0`), igual que en modo desarrollo.
- El ejecutable resultante es "onefile": todo (Python, Qt, los assets) va
  dentro de un único archivo, a costa de un arranque un pelín más lento
  la primera vez que se descomprime a una carpeta temporal.

## Catálogo de parches conocidos (dos archivos, sin pisarse)

En `~/ASTURCONSOLE/Parches/` conviven dos archivos distintos:

| Archivo | Quién lo escribe | Qué contiene |
|---|---|---|
| `mis-parches-snes.json` | **Tú** (la app, solo cuando marcas o desmarcas casillas) | Tus pruebas. **Ninguna actualización lo toca nunca.** |
| `parches-snes-asturconsole.json` | **La aplicación**, en cada arranque | El catálogo de fábrica + los juegos de tu archivo que la fábrica no tenga. |

Reglas al generar `parches-snes-asturconsole.json` (si no cambia, ni se
reescribe; si lo borras, se regenera):

- Los juegos que solo estén en tu archivo se **añaden** al de la aplicación.
- Si un juego está en los dos con datos distintos, **mandan los parámetros de
  la aplicación** (están revisados con trazas reales).
- Excepción: lo que **marques o desmarques a mano** en la app queda anotado en
  tu archivo con `"usuario": true` y **siempre gana**, en tiempo real y al
  volver a abrir el juego. Si luego vacías esa consola, vuelve lo de la app.

Orden de consulta (de más a menos prioridad): lo que has marcado tú a mano,
la ficha del catálogo de la aplicación, el resto de tu archivo.

Para publicar tus hallazgos en la siguiente versión, copia tu
`mis-parches-snes.json` sobre `data/semillas/mis-parches-snes.json` antes de
compilar (las marcas `"usuario"` no deben ir en la semilla).

## Novedades de la versión 2.0

- **Región PAL/NTSC en ROMs europeas de SNES:** nuevas variantes dobles
  (juego PAL nativo adaptable a consola NTSC, confirmadas en hardware real con
  Super Wild Card): Wolfenstein 3D, WeaponLord, Top Gear 2, Terranigma,
  Super Putty, Super Street Fighter II, Super Metroid, X-Kaliber 2097,
  Zombies Ate My Neighbors, Yoshi's Safari y Clay Fighter, entre otras. Cada
  una se detectó con trazas reales de MesenCE (ROM que muestra el aviso frente
  a ROM que funciona) y no con un patrón genérico.
- **Parches -k (anticopia SRAM) corregidos:** los patrones portados desde
  uCON64 escribían un byte desplazado; ahora el resultado coincide byte a byte
  con `uCON64 -k` y `-l` en las 60 ROMs de comprobación.
- **Terranigma (Europe):** ya no recibe por error el patrón genérico de
  "Mighty Max (U)", que dejaba el aviso activo.
- **Catálogo de parches conocidos:** se vuelca desde la propia aplicación a
  `~/ASTURCONSOLE/Parches/` al instalar y en cada versión nueva, dejando copia
  del anterior.
- **Parches guardados por consola de destino (SNES):** un mismo juego puede
  necesitar cosas distintas según la consola (un juego PAL en consola NTSC:
  `-k` y `-f`; en consola PAL: solo `-k`). Ahora NTSC y PAL tienen cada una su
  ficha con sus propias casillas. Lo que marcas o desmarcas se guarda al
  instante para la consola de destino elegida, el estado pasa solo a
  «Necesita parche», y si desmarcas todas esa consola vuelve al estado inicial
  (ningún botón de estado marcado). Lo que guardas manda sobre la sugerencia
  del catálogo. Las fichas antiguas (una sola para todo) se siguen leyendo y se
  convierten solas al primer cambio, sin perder lo guardado.
- Botón de subir carpeta con icono propio.
- **Sin solución por ahora:** Winter Gold (chip Super FX, pantalla negra en el
  Super Wild Card) y World Cup Striker (el juego parpadea en NTSC por su
  temporización de 50 Hz).


## Novedades de la versión 2.1

- **Más juegos PAL en consola NTSC (SNES), confirmados en hardware real con
  Super Wild Card:** Super Pinball: Behind the Mask, Secret of Mana (Rev 1),
  Revolution X, R-Type III, Samurai Shodown y Prehistorik Man, todos con
  variante dual (el parche solo se aplica con destino NTSC). Cada uno se
  localizó con trazas reales de MesenCE; uCON64 `-f` solo cubre Samurai
  Shodown, Secret of Mana y R-Type III.
- **Samurai Shodown y el detector de copiadores:** además de la región, la ROM
  escribe en ROM y SRAM y relee el valor; en un copión (SRAM y ROM escribibles)
  se queda en bucle y deja la pantalla en negro. Se quita con el parche `-k`
  (rutina cortada con RTL en sus dos copias, porque el juego las compara).
- **Secret of Mana:** el código de la comprobación va comprimido (LZ) y se
  descomprime en RAM al arrancar; el parche genérico escribía en el byte
  equivocado. Corregido.
- **Parche genérico «Art of Fighting»:** ahora depende de la región nativa de la
  ROM (en una ROM PAL fuerza el salto en vez de dejar las dos ramas iguales),
  igual que uCON64 `-f`.
- **2.2.8 - Cracks de región que «desaparecían»:** dos fallos en la ventana de
  transferencia hacían que un parche de región confirmado (p. ej. Super Street
  Fighter II Europe) no apareciera marcado. (1) La consola de destino se guardaba
  también al preseleccionarla por programa: sin preferencia previa, abrir una
  ROM PAL dejaba guardado «PAL» sin que nadie lo eligiera, y desde entonces los
  juegos PAL se abrían en PAL, donde no hace falta ningún parche. Ahora solo se
  guarda cuando el usuario pulsa el interruptor. (2) Desmarcar a mano la última
  casilla guardaba una ficha vacía que tapaba para siempre el parche confirmado
  de los juegos de doble variante; ahora una ficha vacía no lo tapa (marcar
  «Compatible» a propósito sí se respeta).
- **2.2.7 - Corrección de arranque:** la aplicación se cerraba al iniciar, con
  `AttributeError: 'Resultado' object has no attribute 'copia'`, la primera vez
  que se instalaba o se actualizaba el catálogo de parches (quedaba un resto de
  un diseño anterior que guardaba copia del catálogo). Eliminado: el catálogo de
  la aplicación es un archivo derivado y el del usuario nunca se toca. Además,
  `ucon64/ucon64` y los `.sh` van marcados como ejecutables en el zip y
  `build_linux.sh` da permiso al binario antes de compilar (evita el aviso de
  `ldd`).
- **2.2.6 - Región PAL Europa completa:** 14 variantes duales PAL nuevas (solo
  se parchean con destino NTSC), halladas con trazas reales de MesenCE y
  confirmadas en hardware real (consola NTSC), salvo World Cup Striker:
  Sparkster, Smash Tennis, Sunset Riders, Terranigma, Soccer Kid, Spirou, Star
  Trek TNG - Future's Past, Tetris & Dr. Mario, Super Conflict, Super
  International Cricket, Tetris 2, los tres Tintin (Prisoners of the Sun, y
  Tintin in Tibet en sus dos versiones) y X-Kaliber 2097. Según el juego se
  cambia `BNE/BEQ` por `BRA` o se neutraliza el salto (`EA EA`). Varios
  genéricos de uCON64 coincidían en estas ROMs y las dejaban siempre en el
  aviso (también en PAL); quedan excluidos por CRC.
  **World Cup Striker (Europe):** pasa el aviso en NTSC pero muestra fallos
  gráficos por su temporización de 50 Hz; queda catalogado como «funciona» en
  consola PAL y «no funciona» en consola NTSC (criterio general para los juegos
  con fallos gráficos: funcionan si la región de la consola coincide con la del
  juego, y no funcionan si no coincide). Winter Gold (Europe) queda registrado
  como «No funciona» (chip Super FX).
- **2.2.4 - Pac-In-Time y NBA Hang Time (Europe) en consola NTSC, confirmados
  en hardware real:** variantes duales PAL (solo se parchean con destino NTSC).
  En Pac-In-Time (E) el chequeo de STAT78 lleva a un bucle infinito y se cambia
  `BNE` por `BRA`; en NBA Hang Time (E) se neutraliza el `BEQ` de la rutina de
  región (`$C3:0E08`). Los genéricos de «Fatal Fury Special (U)» y «Pac-In-Time
  (U)», que coincidían en estas ROMs y las dejaban siempre en el aviso (también
  en PAL), quedan excluidos por CRC. Incluye la persistencia de selección y
  scroll de la ventana de trabajo introducida en 2.2.3.
- **2.2.3 - La ventana de trabajo recuerda dónde estabas:** la lista de
  archivos (y el explorador de la carpeta Asturconsole) ya no salta al principio
  ni pierde la selección al terminar una herramienta, al pulsar «Actualizar»,
  al filtrar por nombre o tipo, o al volver a una carpeta ya visitada. La
  selección sobrevive aunque un filtro oculte temporalmente parte de los
  archivos. Nuevo parche confirmado en hardware: Kevin Keegan's Player Manager
  (Europe), variante dual PAL (el único chequeo de STAT78 cae en una pantalla de
  aviso con bucle infinito; se fuerza el camino normal con destino NTSC).
  Kirby's Fun Pak (Europe) queda registrado como «No funciona» (chip SA-1).
- **2.2.2 - 10 juegos europeos más en consola NTSC, todos confirmados en
  hardware real:** Kirby's Dream Course, Kirby's Ghost Trap, Pop'n TwinBee,
  Pop'n TwinBee - Rainbow Bell Adventures, Kick Off 3 - European Challenge,
  Lucky Luke, Metal Marines, Nigel Mansell's World Championship Racing (Rev 1),
  Pac-Attack y Plok. Variantes duales PAL (solo se parchean con destino NTSC).
  Según el juego se cambia el salto por uno incondicional (`BNE/BEQ` -> `BRA`) o
  se neutraliza (`EA EA`); en Nigel Mansell se neutralizan los dos saltos de la
  rutina de medición. Revolution X (Europe) ya estaba cubierto. Los genéricos
  de «Bonkers», «Captain Commando», «Super Metroid (E)» y la versión USA de
  Nigel Mansell, que escribían al revés en estas ROMs, quedan excluidos por CRC.
- **2.2.1 - 12 juegos europeos más en consola NTSC, todos confirmados en
  hardware real:** BioMetal, Illusion of Time, Donald in Maui Mallard (Maui
  Mallard), Dragon - The Bruce Lee Story (rutina duplicada, se parchean las dos
  copias), Fever Pitch Soccer, Joe & Mac 3, Fatal Fury Special, GP-1,
  Hebereke's Popoitto, Hebereke's Popoon, International Superstar Soccer e
  International Superstar Soccer Deluxe. Son variantes duales PAL (solo se
  parchean con destino NTSC). Los genéricos que escribían bytes equivocados en
  estas ROMs («Mighty Max», «Head-On Soccer», «Eric Cantona Football?»,
  «ABC Monday Night Football», «Pac-In-Time») quedan excluidos por CRC.
  Fever Pitch Soccer se fuerza a la inicialización PAL (usa constantes de 50 Hz).
- **2.2.0 - Tu catálogo ya no se sobrescribe:** el archivo de la aplicación
  (`parches-snes-asturconsole.json`) y el tuyo (`mis-parches-snes.json`) son
  independientes; ver «Catálogo de parches conocidos». Tus marcas a mano
  siempre ganan y se guardan al instante.
- **2.1.1 - Art of Fighting (Europe) y Gokujou Parodius (Japón), confirmados
  en hardware real:** Art of Fighting (E) es una variante dual PAL; su
  comprobación (`$C0:1591`) lleva al aviso con el `BEQ`, al revés que en otros
  juegos, así que se neutraliza con `EA EA` y NO sirve `BEQ`->`BRA` (el genérico
  «EarthBound» quedó excluido para esa ROM). Gokujou Parodius compara `$213F` con
  un byte de la ROM y ya lo cubre el parche `-f` (consola PAL). uCON64 `-f` no
  toca ninguno de los dos. La semilla `mis-parches-snes.json` pasa a 734 entradas.
- **Parches guardados por consola de destino:** NTSC y PAL tienen cada una su
  ficha con sus propias casillas; lo que marcas o desmarcas se guarda al
  instante, «Necesita parche» se marca solo, y si desmarcas todas esa consola
  vuelve al estado inicial. Las fichas antiguas se convierten solas.
