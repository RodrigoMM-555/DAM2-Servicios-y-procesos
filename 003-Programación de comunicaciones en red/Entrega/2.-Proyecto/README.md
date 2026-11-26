# Garabato · pizarra colaborativa con chat

Una pizarra en la que varias personas dibujan a la vez desde el navegador, con un chat compartido.
También puede entrar gente desde la **terminal**, por socket TCP, y escribir en el mismo chat que los navegadores.

## Requisitos

- Python 3.10 o superior
- La librería `websockets` (versión 13 o superior):

  ```bash
  pip install websockets
  ```

- Un navegador moderno

## Puesta en marcha

1. Abre una terminal en esta carpeta y arranca el servidor:

   ```bash
   python3 servidor.py
   ```

   El servidor muestra las direcciones para conectarse desde este equipo y desde otros equipos de la red.

2. **Navegador:** abre <http://localhost:8000>. Desde otro equipo, usa la IP que muestra el servidor.
3. **Terminal:** `python3 cliente.py <ip> 5000 --nombre Ana`
4. **Netcat:** `nc <ip> 5000`. Lo que escribas se envía al chat como texto plano.
5. **Bots (opcional):** `python3 bots.py --web 6 --terminal 3` llena la pizarra de dibujantes automáticos.

Para parar el servidor, pulsa `Ctrl+C`.

Para usar otros puertos: `python3 servidor.py --tcp 5000 --ws 8765 --http 8000 --host 0.0.0.0`.

> Si otros equipos no pueden conectarse, revisa el cortafuegos: hay que abrir los puertos 8000, 8765 y 5000.

### Comandos del cliente de terminal

| Comando        | Qué hace                                       |
|----------------|------------------------------------------------|
| `/usuarios`    | Lista quién está conectado y desde dónde       |
| `/nick NUEVO`  | Cambia el nombre                               |
| `/borrar`      | Borra la pizarra de todos los navegadores      |
| `/ping`        | Mide la latencia (ida y vuelta) con el servidor |
| `/salir`       | Se desconecta                                  |

## Arquitectura

```
                         servidor.py  (un proceso, varios hilos)
                ┌───────────────────────────────────────────────────┐
 cliente.py ──TCP:5000──►  hilo TCP-aceptador ── accept()            │
 cliente.py ──TCP:5000──►    ├─ TCP-lee-N  (recv)   ┐                │
 nc         ──TCP:5000──►    └─ TCP-esc-N  (sendall)│                │
                │                                   ▼                │
                │                          ┌──────────────────┐      │
                │                          │      Sala        │      │
                │                          │  miembros        │      │
                │                          │  trazos (dibujo) │◄─ cerrojo
                │                          │  chat (100 últ.) │      │
                │                          └──────────────────┘      │
                │                                   ▲                │
 navegador ─WS:8765────►  hilo WebSocket (asyncio)  │                │
 navegador ─WS:8765────►    una corrutina por navegador              │
                │                                                    │
 navegador ─HTTP:8000──►  hilo HTTP (ThreadingHTTPServer)            │
                │           sirve web/ y /config.json                │
                └───────────────────────────────────────────────────┘
```

| Archivo | Qué es |
|---|---|
| `servidor.py` | Los tres servidores y la `Sala` compartida |
| `cliente.py` | Cliente de chat por terminal, con un hilo para recibir y otro para leer el teclado |
| `web/index.html`, `web/pizarra.js`, `web/estilo.css` | Cliente web: lienzo, cursores en directo, chat y usuarios |
| `bots.py` | Generador de carga: bots web (corrutinas) y de terminal (hilos) |
| `tests/test_servidor.py` | 15 pruebas de integración contra un servidor real |

### Hilos

- **Principal:** arranca los servidores y espera a `Ctrl+C`.
- **TCP-aceptador:** se queda bloqueado en `accept()`. Por cada cliente nuevo crea dos hilos:
  - **TCP-lee-N:** bloqueado en `recv()`. Junta los bytes en líneas, interpreta cada mensaje y llama a la sala.
  - **TCP-esc-N:** saca mensajes de una `queue.Queue` y hace `sendall()`. Si un cliente lento tarda en leer, solo se bloquea su propio escritor, y no el hilo que está difundiendo a todos. Si su cola pasa de 1000 mensajes, se le desconecta.
- **WebSocket:** un bucle de eventos `asyncio` atiende a **todos** los navegadores con corrutinas, en un solo hilo.
- **HTTP:** `ThreadingHTTPServer`, que crea un hilo por petición.

Cada línea del log del servidor lleva el nombre del hilo que la escribe, así se ve qué hilo atiende cada cosa:

```
11:07:26 [TCP-lee-58134  ] entra bot-term-1 (terminal)
11:07:26 [WebSocket      ] chat bot-web-1: hola a todos
```

### Sincronización

La `Sala` tiene un único `threading.Lock`. Lo usan los hilos TCP y el hilo de asyncio.
Cualquier cambio de estado y el reparto del mensaje correspondiente se hacen **dentro del mismo cerrojo**:

- Repartir es barato: a un cliente TCP se le mete el mensaje en su cola y a los navegadores se les programa un `broadcast` con `call_soon_threadsafe`. Por eso el cerrojo se suelta enseguida.
- Así todos los clientes reciben los mensajes **en el mismo orden**.
- Un recién llegado recibe el dibujo y el chat completos, sin perder ni duplicar el mensaje que llegaba justo en ese instante.

El hilo de asyncio es el único que puede tocar las conexiones WebSocket. Desde un hilo TCP **no** se llama a `conexion.send()`: se le pide al bucle de eventos que lo haga con `bucle.call_soon_threadsafe(broadcast, conexiones, texto)`.

## Protocolo

Todos los mensajes son objetos JSON con un campo `tipo`.

- **Por TCP:** un mensaje por línea, terminado en `\n` (JSON Lines). TCP es un flujo de bytes y no conserva las fronteras entre envíos: un `recv()` puede traer medio mensaje o tres juntos. Por eso el receptor acumula los bytes en un búfer y corta por `\n`. El límite es de 8 KB por línea.
- **Por WebSocket:** cada trama de texto es un mensaje, porque el propio protocolo WebSocket ya delimita los mensajes.

| Tipo | Dirección | Campos | Notas |
|---|---|---|---|
| `hola` | C → S | `nombre` | Primer mensaje. Si el nombre ya está cogido, se le añade «(2)» |
| `bienvenida` | S → C | `nombre`, `usuarios`, `chat`, `trazos`* | Estado completo. *`trazos` solo se envía a los navegadores |
| `chat` | C ↔ S | `texto` / + `nombre`, `origen`, `hora` | Se reenvía a todos, también al autor (sirve de confirmación) |
| `trazo` | C ↔ S | `x0 y0 x1 y1` (0..1), `color` `#rrggbb`, `grosor` 1..60 | Se valida, se guarda y se reenvía a los demás navegadores |
| `cursor` | C ↔ S | `x`, `y` o `fuera` | Efímero: no se guarda |
| `borrar` | C → S, S → C | — / `nombre` | Vacía la pizarra de todos |
| `nombre` | C → S | `nombre` | Cambio de nombre. La respuesta es `renombrado` |
| `usuarios` | S → C | `lista` | Se envía cuando alguien entra, sale o cambia de nombre |
| `sistema` | S → C | `texto`, `hora` | Avisos («X se ha unido») |
| `ping` / `pong` | C → S / S → C | `t` | El servidor devuelve `t` tal cual y el cliente calcula la latencia |
| `error` | S → C | `texto` | Mensaje no válido, tipo desconocido… |

Las coordenadas van **normalizadas entre 0 y 1**, de modo que el dibujo se ve igual en pantallas de cualquier tamaño.
Si llega una línea que no es JSON, por ejemplo desde `nc`, se trata como un mensaje de chat. El primer mensaje que no es `hola` hace entrar al cliente como «invitado».

## Modelos de comunicación que se usan

- **Cliente-servidor:** los clientes nunca se hablan directamente, todo pasa por el servidor, que es el que tiene el estado.
- **Publicación-suscripción (difusión):** cada mensaje que llega se reenvía a todos los suscritos a la sala. Es el mismo patrón que un *broker*.
- **Petición-respuesta:** HTTP para descargar la página y `/config.json`, y `ping`/`pong` dentro del WebSocket.
- **Comunicación continua y bidireccional:** tanto la conexión TCP como el WebSocket se quedan abiertas, y el servidor envía datos cuando quiere (*push*), sin que el cliente pregunte.

Junto a la versión de terminal hay una versión web. Un navegador no puede abrir sockets TCP: WebSocket arranca como una petición HTTP (`Upgrade: websocket`) y después la misma conexión TCP se queda abierta para enviar tramas en los dos sentidos.

## Seguridad y robustez

- Hay límites de tamaño: 8 KB por mensaje, 500 caracteres por texto de chat, 20 por nombre y 50 000 trazos.
- Todo lo que llega se valida: tipos, rangos de las coordenadas (también se descartan `NaN`), color con expresión regular y grosor.
- El cliente web pinta el chat con `textContent` y nunca con `innerHTML`, así nadie puede inyectar HTML ni scripts.
- Si un cliente no saluda en 10 segundos por WebSocket, se le cierra la conexión.
- Si un cliente TCP es demasiado lento y su cola se llena, se le desconecta. Así no frena a los demás.
- El cliente web se reconecta solo cuando se cae la conexión, esperando cada vez más (1 s, 2 s, 4 s… hasta 10 s), y al volver recibe el estado completo.

## Pruebas

```bash
python3 -m unittest discover tests -v
```

Cada prueba arranca un servidor real en puertos libres y se conecta con sockets y WebSockets de verdad. Se comprueba:

- La bienvenida, los nombres duplicados y el cambio de nombre.
- El chat de la terminal al navegador y al revés.
- Que el dibujo se reenvía en directo y que se guarda para los que llegan tarde.
- Que se rechazan los trazos no válidos y que `/borrar` desde la terminal llega a los navegadores.
- Texto plano tipo `nc`, mensajes partidos en trozos de 3 bytes y varios mensajes en un solo envío.
- Que una línea demasiado larga corta la conexión.
- **20 clientes enviando a la vez desde 20 hilos**: llegan los 200 mensajes y cada cliente conserva su orden.
- Que se avisa a los demás cuando alguien se desconecta, y que el servidor HTTP responde.

## Depuración: problemas de los ejercicios de clase que se corrigen

- **Mensajes pegados o partidos en TCP.** El chat de clase (`servidorchat.py`) hace `recv(1024)` y trata lo recibido como un mensaje entero. Funciona en local con mensajes cortos, pero falla cuando llegan dos mensajes juntos o uno a medias. Aquí se resuelve con el búfer con corte por `\n` de `leer_lineas()`, y dos pruebas lo verifican: `test_mensaje_partido_en_trozos` y `test_varios_mensajes_en_un_envio`.
- **Un cliente lento bloquea a todos.** El multiservidor de clase hace `sendall()` a cada cliente dentro del bucle de reenvío, así que si un cliente no lee, el hilo que difunde se queda bloqueado. Aquí cada cliente tiene su propia cola y su propio hilo escritor.
- **Enviar a un WebSocket desde otro hilo.** Mezclar hilos y asyncio tiene una trampa: las conexiones de `websockets` solo se pueden usar desde el hilo de su bucle de eventos. Por eso los hilos TCP no llaman a `send()`: usan `call_soon_threadsafe` y la función `broadcast` de la librería.
- **Condición de carrera al entrar.** Si alguien escribe justo mientras otro entra y el mensaje se guarda y se reparte en dos secciones críticas distintas, el recién llegado puede perderlo o recibirlo dos veces. Aquí guardar y repartir van en la misma sección crítica. `test_muchos_clientes_a_la_vez` comprueba que con 20 hilos simultáneos no se pierde ni se desordena nada.
