"""
bots.py
-------
Lanza varios "bots" que se conectan a Garabato a la vez y dibujan curvas
(y de vez en cuando escriben en el chat). Sirve para ver la pizarra con
mucha gente y comprobar que el servidor aguanta varios clientes
simultáneos.

Los bots web son corrutinas (asyncio) y los de terminal son hilos con
sockets TCP: así se usan los dos tipos de cliente a la vez.

Uso:
    python3 bots.py                          (4 web + 2 terminal, 20 s)
    python3 bots.py --web 10 --terminal 5 --segundos 30 --host 192.168.1.20
"""

import argparse
import asyncio
import json
import math
import random
import socket
import threading
import time

from websockets.asyncio.client import connect

FRASES = ["¡qué bonito!", "voy a por el círculo", "¿quién borra?",
          "estoy dibujando abajo", "hola a todos", "esto va rapidísimo"]
COLORES = ["#e11d48", "#f59e0b", "#16a34a", "#2563eb", "#9333ea", "#0891b2"]


async def bot_web(n, url, segundos):
    """Dibuja una curva de Lissajous distinta por bot."""
    a, b = random.randint(1, 5), random.randint(1, 5)
    fase = random.random() * math.pi
    cx, cy = random.uniform(.3, .7), random.uniform(.3, .7)
    radio = random.uniform(.12, .25)
    color = random.choice(COLORES)

    def punto(t):
        return (cx + radio * math.sin(a * t + fase),
                cy + radio * math.sin(b * t))

    async with connect(url) as ws:
        await ws.send(json.dumps({"tipo": "hola", "nombre": f"bot-web-{n}"}))
        fin = time.monotonic() + segundos
        t, anterior = 0.0, punto(0)
        while time.monotonic() < fin:
            t += 0.05
            actual = punto(t)
            await ws.send(json.dumps({
                "tipo": "trazo", "x0": anterior[0], "y0": anterior[1],
                "x1": actual[0], "y1": actual[1], "color": color, "grosor": 3,
            }))
            await ws.send(json.dumps({"tipo": "cursor",
                                      "x": actual[0], "y": actual[1]}))
            anterior = actual
            if random.random() < 0.005:
                await ws.send(json.dumps({"tipo": "chat",
                                          "texto": random.choice(FRASES)}))
            await asyncio.sleep(0.03)


def bot_terminal(n, host, puerto, segundos):
    """Hilo con un socket TCP que charla en el chat."""
    with socket.create_connection((host, puerto)) as s:
        def enviar(m):
            s.sendall((json.dumps(m, ensure_ascii=False) + "\n").encode())

        def descartar():
            # hay que leer lo que llega para que no se llene el búfer
            try:
                while s.recv(4096):
                    pass
            except OSError:
                pass

        threading.Thread(target=descartar, daemon=True).start()
        enviar({"tipo": "hola", "nombre": f"bot-term-{n}"})
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            time.sleep(random.uniform(2, 5))
            enviar({"tipo": "chat", "texto": random.choice(FRASES)})


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="localhost")
    p.add_argument("--ws", type=int, default=8765)
    p.add_argument("--tcp", type=int, default=5000)
    p.add_argument("--web", type=int, default=4)
    p.add_argument("--terminal", type=int, default=2)
    p.add_argument("--segundos", type=float, default=20)
    args = p.parse_args()

    hilos = [threading.Thread(target=bot_terminal,
                              args=(i, args.host, args.tcp, args.segundos),
                              daemon=True)
             for i in range(args.terminal)]
    for h in hilos:
        h.start()

    url = f"ws://{args.host}:{args.ws}"
    print(f"{args.web} bots web y {args.terminal} bots de terminal "
          f"durante {args.segundos:.0f} s…")
    await asyncio.gather(*(bot_web(i, url, args.segundos) for i in range(args.web)))
    for h in hilos:
        h.join()
    print("Bots terminados")


if __name__ == "__main__":
    asyncio.run(main())
