# Resultados de aprendizaje · Prisma

**a) Se han reconocido las características de la programación concurrente y sus ámbitos de aplicación.**

El procesado de imagen es un trabajo costoso y divisible, así que se reparte entre varios workers.
Mientras ellos calculan, la interfaz sigue respondiendo, y en modo «hilo principal» se congela.

**b) Se han identificado las diferencias entre programación paralela y programación distribuida, sus ventajas e inconvenientes.**

La parte paralela son los workers que comparten la CPU del equipo, y la distribuida es el envío de resultados por HTTP a `servidor.py`.
La tabla de ejecuciones muestra la ventaja del paralelismo y su límite: más workers que núcleos no mejora el tiempo.

**c) Se han analizado las características de los procesos y de su ejecución por el sistema operativo.**

El programa detecta los núcleos con `navigator.hardwareConcurrency`, y la cola de teselas funciona como un planificador.
El panel muestra el estado de cada worker en directo: libre, ocupado o terminado.

**d) Se han caracterizado los hilos de ejecución y descrito su relación con los procesos.**

Cada Web Worker es un hilo del mismo proceso que la página, con su propia memoria y sin acceso al DOM.
En el servidor, `ThreadingHTTPServer` atiende cada petición en un hilo distinto del mismo proceso.

**e) Se han utilizado clases para programar aplicaciones que crean subprocesos.**

Los subprocesos se crean con la clase `Worker` y forman un pool que se termina con `terminate()` al cancelar.
En Python se usan `ThreadingHTTPServer`, la clase `Manejador` y `threading.Lock`.

**f) Se han utilizado mecanismos para compartir información con los subprocesos iniciados.**

El maestro envía cada tesela con `postMessage`, como buffer transferible (sin copiarlo) y con un margen de píxeles vecinos.
Los filtros se comparten cargando `filtros.js` en el hilo principal y en los workers (`importScripts`).

**g) Se han utilizado mecanismos para sincronizar y obtener el valor devuelto por los subprocesos iniciados.**

Cada worker devuelve su tesela y su tiempo, y la ejecución no termina hasta que han vuelto todas.
En el servidor, un cerrojo evita que dos hilos escriban a la vez en el CSV.

**h) Se han desarrollado aplicaciones que gestionen y utilicen procesos para la ejecución de varias tareas en paralelo.**

La aplicación crea los workers, les reparte trabajo, recoge sus resultados y permite cancelar.
Cada ejecución se mide, y la tabla calcula el speedup y la eficiencia frente a la ejecución con 1 worker.

**i) Se han depurado y documentado las aplicaciones desarrolladas.**

Se corrigieron las costuras entre teselas y una condición de carrera del ejercicio de clase del que parte, y un test lo verifica.
El código está comentado y el README explica la ejecución, la arquitectura y las decisiones técnicas.
