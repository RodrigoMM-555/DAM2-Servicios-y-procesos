# Resultados de aprendizaje · Garabato

**a) Se han identificado escenarios que precisan establecer comunicación en red entre varias aplicaciones.**

Una pizarra compartida es un caso típico de comunicación en red, porque varias personas en equipos distintos tienen que ver el mismo dibujo y el mismo chat al instante.
Además se comunican aplicaciones diferentes: un navegador, un programa de terminal en Python, `nc` y los bots.
Cada una necesita un canal adecuado, así que el proyecto usa TCP, WebSocket y HTTP según el tipo de cliente.

**b) Se han identificado los roles de cliente y de servidor y sus funciones asociadas.**

El servidor (`servidor.py`) escucha en puertos fijos, guarda el estado (usuarios, trazos y chat), valida lo que recibe y lo reparte.
Los clientes (`cliente.py`, `web/pizarra.js`, `bots.py`) inician la conexión, se presentan con `hola`, envían las acciones del usuario y pintan lo que les llega.
Los clientes nunca se hablan entre sí: el servidor es el único intermediario y la única fuente de verdad.

**c) Se han reconocido librerías y mecanismos del lenguaje de programación que permiten programar aplicaciones en red.**

En Python se usa el módulo `socket` a bajo nivel para TCP, `http.server` (`ThreadingHTTPServer`) para servir la web y la librería `websockets` sobre `asyncio` para los navegadores.
En el navegador se usan la API `WebSocket` y `fetch`. Para pasar mensajes entre hilos se usan `threading`, `queue` y `call_soon_threadsafe`.
El README explica por qué se elige cada una: un navegador no puede abrir un socket TCP, pero sí un WebSocket.

**d) Se ha analizado el concepto de socket, sus tipos y características.**

Se usan sockets de flujo (`SOCK_STREAM`, TCP), que son fiables y ordenados pero no respetan las fronteras entre mensajes. Por eso se diseñó un protocolo de líneas JSON con búfer y corte por `\n`, y las pruebas lo verifican con mensajes partidos y pegados.
También se usa un socket de datagramas (`SOCK_DGRAM`, UDP) para averiguar la IP local sin enviar nada.
Y se explica que un WebSocket es un socket TCP que empieza como HTTP y después intercambia tramas en los dos sentidos.

**e) Se han utilizado sockets para programar una aplicación cliente que se comunique con un servidor.**

`cliente.py` abre un socket TCP con `connect()`, se presenta y mantiene la conexión abierta para chatear, con comandos como `/usuarios`, `/nick`, `/borrar` o `/ping`.
Usa un hilo para recibir y el hilo principal para leer el teclado, así se ven los mensajes de los demás mientras escribes.
El cliente web hace lo mismo con un WebSocket, y además se reconecta solo esperando cada vez más tiempo entre intentos.

**f) Se ha desarrollado una aplicación servidor en red y verificado su funcionamiento.**

`servidor.py` levanta tres servidores en un mismo proceso: TCP en el 5000, WebSocket en el 8765 y HTTP en el 8000. Se puede usar desde otros equipos de la red local.
Para verificarlo hay 15 pruebas de integración que arrancan un servidor real en puertos libres y se conectan con sockets y WebSockets de verdad.
También se ha probado a mano con `nc`, con el cliente de terminal, con el navegador y con `bots.py`.

**g) Se han desarrollado aplicaciones que utilizan sockets para intercambiar información.**

El proyecto intercambia información continuamente en los dos sentidos: trazos del dibujo, posiciones de los cursores, mensajes de chat, la lista de usuarios y ping/pong para medir la latencia.
Hay un protocolo propio, documentado en una tabla, con trece tipos de mensaje. Todo lo recibido se valida (rangos, colores, tamaños) y se responde con `error` si no es correcto.
Además, el chat une los dos mundos: lo que se escribe por TCP en la terminal llega por WebSocket al navegador, y al revés.

**i) Se han utilizado hilos para posibilitar la comunicación simultánea de varios clientes con el servidor.**

Por cada cliente TCP el servidor crea dos hilos: uno lector, bloqueado en `recv()`, y uno escritor, que vacía una `Queue`. Así un cliente lento no frena a los demás.
Los navegadores se atienden con corrutinas en un hilo de asyncio, y el servidor HTTP crea un hilo por petición. Todos comparten la `Sala`, protegida por un `Lock`.
Una prueba lanza 20 clientes desde 20 hilos a la vez y comprueba que llegan los 200 mensajes y que cada cliente conserva su orden.

**j) Se han caracterizado los modelos de comunicación más usuales en las arquitecturas de aplicaciones distribuidas.**

El proyecto combina varios modelos: cliente-servidor centralizado, publicación-suscripción (cada mensaje se difunde a toda la sala), petición-respuesta (HTTP y `ping`/`pong`) y *push* sobre conexiones persistentes.
También compara dos formas de atender la concurrencia: un hilo por cliente con sockets bloqueantes (TCP) y un solo hilo con E/S asíncrona (asyncio).
El README explica cada modelo y en qué parte del proyecto se usa.

**k) Se han depurado y documentado las aplicaciones desarrolladas.**

Se han corregido fallos de los ejercicios de clase: mensajes TCP partidos o pegados, el bloqueo de todos por un cliente lento y una condición de carrera al entrar en la sala. Cada uno tiene su prueba automática.
El log del servidor muestra el nombre del hilo en cada línea, así se ve qué hilo hace cada cosa.
El código está comentado, y el README explica la instalación, la arquitectura, el protocolo, los hilos, la sincronización y las pruebas.
