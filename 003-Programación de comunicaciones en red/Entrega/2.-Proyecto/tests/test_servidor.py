"""
Pruebas de integración de Garabato.

Cada prueba arranca un servidor REAL en puertos libres (subproceso) y se
conecta con sockets TCP y WebSockets de verdad.

    python3 -m unittest discover tests -v
"""

import json
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from websockets.sync.client import connect as conectar_ws

SERVIDOR = Path(__file__).resolve().parent.parent / "servidor.py"
ESPERA = 3


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ClienteTCP:
    """Cliente de pruebas que habla JSON por líneas."""

    def __init__(self, puerto, nombre=None, saludar=True):
        self.s = socket.create_connection(("127.0.0.1", puerto), timeout=ESPERA)
        self.pendiente = b""
        if saludar:
            self.enviar({"tipo": "hola", "nombre": nombre})

    def enviar(self, mensaje):
        self.crudo((json.dumps(mensaje) + "\n").encode())

    def crudo(self, datos):
        self.s.sendall(datos)

    def recibir(self):
        while b"\n" not in self.pendiente:
            datos = self.s.recv(4096)
            if not datos:
                raise ConnectionError("cerrado")
            self.pendiente += datos
        linea, self.pendiente = self.pendiente.split(b"\n", 1)
        return json.loads(linea)

    def esperar(self, tipo, condicion=lambda m: True):
        limite = time.monotonic() + ESPERA
        while time.monotonic() < limite:
            m = self.recibir()
            if m["tipo"] == tipo and condicion(m):
                return m
        raise TimeoutError(tipo)

    def cerrar(self):
        self.s.close()


class ClienteWeb:
    def __init__(self, puerto, nombre):
        self.ws = conectar_ws(f"ws://127.0.0.1:{puerto}").__enter__()
        self.enviar({"tipo": "hola", "nombre": nombre})

    def enviar(self, mensaje):
        self.ws.send(json.dumps(mensaje))

    def esperar(self, tipo, condicion=lambda m: True):
        limite = time.monotonic() + ESPERA
        while time.monotonic() < limite:
            m = json.loads(self.ws.recv(timeout=ESPERA))
            if m["tipo"] == tipo and condicion(m):
                return m
        raise TimeoutError(tipo)

    def cerrar(self):
        self.ws.close()


TRAZO = {"tipo": "trazo", "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5,
         "color": "#FF0000", "grosor": 5}


class PruebasGarabato(unittest.TestCase):

    def setUp(self):
        self.tcp, self.ws, self.http = puerto_libre(), puerto_libre(), puerto_libre()
        self.proceso = subprocess.Popen(
            [sys.executable, "-u", str(SERVIDOR), "--host", "127.0.0.1",
             "--tcp", str(self.tcp), "--ws", str(self.ws), "--http", str(self.http)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        for linea in self.proceso.stdout:            # esperar a que arranque
            if "Garabato listo" in linea:
                break
        else:
            self.fail("el servidor no arrancó")
        # vaciar la salida en segundo plano para que no se llene la tubería
        threading.Thread(target=self.proceso.stdout.read, daemon=True).start()
        self.clientes = []

    def tearDown(self):
        for c in self.clientes:
            try:
                c.cerrar()
            except Exception:
                pass
        self.proceso.terminate()
        self.proceso.wait()
        self.proceso.stdout.close()

    def nuevo_tcp(self, nombre=None, **kw):
        c = ClienteTCP(self.tcp, nombre, **kw)
        self.clientes.append(c)
        return c

    def nuevo_web(self, nombre):
        c = ClienteWeb(self.ws, nombre)
        self.clientes.append(c)
        return c

    # ---------------------------------------------------------------

    def test_bienvenida_por_tcp(self):
        ana = self.nuevo_tcp("Ana")
        m = ana.esperar("bienvenida")
        self.assertEqual(m["nombre"], "Ana")
        self.assertEqual(m["usuarios"], [{"nombre": "Ana", "origen": "terminal"}])
        self.assertNotIn("trazos", m)          # la terminal no recibe el dibujo

    def test_nombres_duplicados(self):
        self.nuevo_tcp("Ana").esperar("bienvenida")
        m = self.nuevo_web("ana").esperar("bienvenida")
        self.assertEqual(m["nombre"], "ana (2)")

    def test_chat_de_terminal_a_web_y_al_reves(self):
        terminal = self.nuevo_tcp("Terminal")
        terminal.esperar("bienvenida")
        web = self.nuevo_web("Navegador")
        web.esperar("bienvenida")

        terminal.enviar({"tipo": "chat", "texto": "hola desde TCP"})
        m = web.esperar("chat")
        self.assertEqual((m["nombre"], m["origen"], m["texto"]),
                         ("Terminal", "terminal", "hola desde TCP"))

        web.enviar({"tipo": "chat", "texto": "hola desde WebSocket"})
        m = terminal.esperar("chat", lambda m: m["origen"] == "web")
        self.assertEqual(m["texto"], "hola desde WebSocket")

    def test_el_dibujo_se_guarda_para_los_que_llegan_tarde(self):
        pintor = self.nuevo_web("Pintor")
        pintor.esperar("bienvenida")
        pintor.enviar(TRAZO)
        pintor.enviar({"tipo": "ping", "t": 1})
        pintor.esperar("pong")                # el trazo ya está procesado

        m = self.nuevo_web("Tardón").esperar("bienvenida")
        self.assertEqual(len(m["trazos"]), 1)
        self.assertEqual(m["trazos"][0]["color"], "#ff0000")

    def test_trazo_en_directo_a_los_demas(self):
        a = self.nuevo_web("A")
        a.esperar("bienvenida")
        b = self.nuevo_web("B")
        b.esperar("bienvenida")
        a.enviar(TRAZO)
        m = b.esperar("trazo")
        self.assertEqual(m["x1"], 0.5)

    def test_trazo_no_valido(self):
        web = self.nuevo_web("Tramposo")
        web.esperar("bienvenida")
        web.enviar({**TRAZO, "x0": 5})
        self.assertIn("no válido", web.esperar("error")["texto"])
        web.enviar({**TRAZO, "color": "red; drop table"})
        web.esperar("error")

    def test_borrar_desde_la_terminal(self):
        web = self.nuevo_web("Web")
        web.esperar("bienvenida")
        web.enviar(TRAZO)
        terminal = self.nuevo_tcp("Terminal")
        terminal.esperar("bienvenida")
        terminal.enviar({"tipo": "borrar"})
        self.assertEqual(web.esperar("borrar")["nombre"], "Terminal")
        self.assertEqual(self.nuevo_web("Nuevo").esperar("bienvenida")["trazos"], [])

    def test_netcat_texto_plano(self):
        # como si fuera `nc`: sin JSON y sin saludar
        nc = self.nuevo_tcp(saludar=False)
        nc.crudo("hola mundo\n".encode())
        m = nc.esperar("bienvenida")
        self.assertEqual(m["nombre"], "invitado")
        self.assertEqual(nc.esperar("chat")["texto"], "hola mundo")

    def test_mensaje_partido_en_trozos(self):
        # TCP puede entregar un mensaje en varios recv(): el servidor lo junta
        c = self.nuevo_tcp("Trozos")
        c.esperar("bienvenida")
        linea = (json.dumps({"tipo": "chat", "texto": "partido"}) + "\n").encode()
        for i in range(0, len(linea), 3):
            c.crudo(linea[i:i + 3])
            time.sleep(0.01)
        self.assertEqual(c.esperar("chat")["texto"], "partido")

    def test_varios_mensajes_en_un_envio(self):
        c = self.nuevo_tcp("Juntos")
        c.esperar("bienvenida")
        c.crudo(b'{"tipo":"chat","texto":"uno"}\n{"tipo":"chat","texto":"dos"}\n')
        self.assertEqual(c.esperar("chat")["texto"], "uno")
        self.assertEqual(c.esperar("chat")["texto"], "dos")

    def test_linea_demasiado_larga(self):
        c = self.nuevo_tcp("Grande")
        c.esperar("bienvenida")
        c.crudo(b"x" * 20_000)
        self.assertIn("demasiado larga", c.esperar("error")["texto"])
        with self.assertRaises(ConnectionError):
            while True:
                c.recibir()

    def test_muchos_clientes_a_la_vez(self):
        """20 clientes TCP envían 10 mensajes cada uno EN PARALELO.
        Un observador web debe recibir los 200, y cada cliente en su orden."""
        observador = self.nuevo_web("Observador")
        observador.esperar("bienvenida")

        clientes = [self.nuevo_tcp(f"c{i}") for i in range(20)]
        for c in clientes:
            c.esperar("bienvenida")

        def charlar(i, c):
            for n in range(10):
                c.enviar({"tipo": "chat", "texto": f"{i}:{n}"})

        hilos = [threading.Thread(target=charlar, args=(i, c))
                 for i, c in enumerate(clientes)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        vistos = {}
        for _ in range(200):
            m = observador.esperar("chat")
            i, n = map(int, m["texto"].split(":"))
            self.assertEqual(n, vistos.get(i, -1) + 1, "orden roto")
            vistos[i] = n
        self.assertEqual(vistos, {i: 9 for i in range(20)})

    def test_desconexion_avisa_a_los_demas(self):
        web = self.nuevo_web("Queda")
        web.esperar("bienvenida")
        se_va = self.nuevo_tcp("SeVa")
        se_va.esperar("bienvenida")
        web.esperar("usuarios", lambda m: len(m["lista"]) == 2)
        se_va.cerrar()
        m = web.esperar("usuarios", lambda m: len(m["lista"]) == 1)
        self.assertEqual(m["lista"][0]["nombre"], "Queda")

    def test_cambiar_de_nombre(self):
        c = self.nuevo_tcp("Viejo")
        c.esperar("bienvenida")
        c.enviar({"tipo": "nombre", "nombre": "Nuevo"})
        self.assertEqual(c.esperar("renombrado")["nombre"], "Nuevo")

    def test_http_sirve_la_web_y_la_configuracion(self):
        base = f"http://127.0.0.1:{self.http}"
        with urllib.request.urlopen(base + "/config.json", timeout=ESPERA) as r:
            self.assertEqual(json.load(r), {"ws": self.ws})
        with urllib.request.urlopen(base + "/", timeout=ESPERA) as r:
            self.assertIn(b"Garabato", r.read())


if __name__ == "__main__":
    unittest.main()
