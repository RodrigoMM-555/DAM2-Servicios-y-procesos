"""
servidor.py
-----------
Garabato · pizarra colaborativa con chat.

Un mismo proceso levanta TRES servidores, cada uno en su propio hilo:

  1. Servidor TCP (puerto 5000)  -> clientes de terminal (cliente.py o nc).
     Socket "a pelo": socket.socket + bind + listen + accept.
     Cada cliente tiene DOS hilos: uno lee y otro escribe.

  2. Servidor WebSocket (puerto 8765) -> navegadores (web/).
     Librería `websockets` sobre asyncio: un solo hilo atiende a todos
     los navegadores con corrutinas.

  3. Servidor HTTP (puerto 8000) -> sirve la página web (web/).
     ThreadingHTTPServer: un hilo por petición.

Todos comparten una única "Sala": quién está conectado, el dibujo
(lista de trazos) y el historial del chat. La sala está protegida por
un cerrojo (threading.Lock) porque la tocan muchos hilos a la vez.

Protocolo: mensajes JSON. Por TCP va uno por línea (terminado en \n),
porque TCP es un flujo de bytes sin fronteras entre mensajes.
Por WebSocket, cada trama es un mensaje.

Uso:
    python3 servidor.py
    python3 servidor.py --tcp 5000 --ws 8765 --http 8000 --host 0.0.0.0
"""

import argparse
import asyncio
import json
import queue
import re
import socket
import sys
import threading
from collections import deque
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from websockets.asyncio.server import broadcast, serve
from websockets.exceptions import ConnectionClosed

CARPETA_WEB = Path(__file__).resolve().parent / "web"

MAX_MENSAJE = 8 * 1024      # bytes máximos de un mensaje (línea TCP o trama WS)
MAX_TRAZOS = 50_000         # trazos que se guardan del dibujo
MAX_CHAT = 100              # mensajes de chat que se recuerdan
MAX_COLA = 1000             # mensajes pendientes por cliente TCP antes de echarlo
MAX_NOMBRE = 20
MAX_TEXTO = 500
TIEMPO_HOLA = 10            # segundos para presentarse tras conectar

COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


# ---------------------------------------------------------------- utilidades

def log(texto):
    """Imprime con la hora y el nombre del HILO que está trabajando."""
    hilo = threading.current_thread().name
    print(f"{datetime.now():%H:%M:%S} [{hilo:<15}] {texto}", flush=True)


def hora():
    return datetime.now().strftime("%H:%M")


def a_json(mensaje):
    return json.dumps(mensaje, ensure_ascii=False, separators=(",", ":"))


def interpretar(texto):
    """Convierte lo recibido en un diccionario.

    Si no es JSON (por ejemplo, alguien conectado con `nc` que escribe
    texto normal), se trata como un mensaje de chat. Así el servidor
    también entiende la "comunicación rudimentaria".
    """
    try:
        mensaje = json.loads(texto)
    except json.JSONDecodeError:
        return {"tipo": "chat", "texto": texto}
    if not isinstance(mensaje, dict):
        return {"tipo": "chat", "texto": texto}
    return mensaje


def limpiar_nombre(nombre):
    if not isinstance(nombre, str):
        return ""
    return " ".join(nombre.split())[:MAX_NOMBRE]


def coordenada(valor):
    """Devuelve el valor como float entre 0 y 1, o None si no vale."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    if not 0 <= valor <= 1:          # también descarta NaN
        return None
    return round(float(valor), 4)


def validar_trazo(mensaje):
    """Un trazo es un segmento de (x0,y0) a (x1,y1) con coordenadas
    normalizadas 0..1, para que se vea igual en pantallas distintas."""
    trazo = {"tipo": "trazo"}
    for clave in ("x0", "y0", "x1", "y1"):
        valor = coordenada(mensaje.get(clave))
        if valor is None:
            return None
        trazo[clave] = valor

    color = mensaje.get("color")
    grosor = mensaje.get("grosor")
    if not isinstance(color, str) or not COLOR.match(color):
        return None
    if isinstance(grosor, bool) or not isinstance(grosor, (int, float)):
        return None
    if not 1 <= grosor <= 60:
        return None

    trazo["color"] = color.lower()
    trazo["grosor"] = round(float(grosor), 1)
    return trazo


# ------------------------------------------------------------------ miembros

class MiembroTCP:
    """Cliente de terminal conectado por un socket TCP.

    Para no bloquear nunca al hilo que difunde un mensaje, enviar() solo
    deja el texto en una cola. Un hilo escritor propio de este cliente lo
    saca de la cola y hace el sendall(). Si el cliente es tan lento que la
    cola se llena, se le desconecta.
    """

    origen = "terminal"

    def __init__(self, conexion, direccion):
        self.conexion = conexion
        self.direccion = direccion
        self.nombre = None
        self.cola = queue.Queue(maxsize=MAX_COLA)

    def enviar(self, texto):
        try:
            self.cola.put_nowait(texto)
        except queue.Full:
            log(f"{self.nombre}: cliente demasiado lento, se desconecta")
            self.cerrar()

    def cerrar(self):
        # shutdown() despierta al hilo lector (su recv devuelve b"")
        try:
            self.conexion.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def bucle_escritura(self):
        """Hilo escritor: vacía la cola hacia el socket."""
        while True:
            texto = self.cola.get()
            if texto is None:            # señal de fin
                return
            try:
                self.conexion.sendall((texto + "\n").encode("utf-8"))
            except OSError:
                self.cerrar()
                return


class MiembroWeb:
    """Navegador conectado por WebSocket.

    La conexión vive en el hilo de asyncio. Desde otro hilo NO se puede
    llamar a sus métodos directamente: hay que pedirle al bucle de
    eventos que lo haga con call_soon_threadsafe().
    """

    origen = "web"

    def __init__(self, conexion, bucle):
        self.conexion = conexion
        self.bucle = bucle
        self.nombre = None

    def enviar(self, texto):
        self.bucle.call_soon_threadsafe(broadcast, [self.conexion], texto)

    def cerrar(self):
        pass


# ---------------------------------------------------------------------- sala

class Sala:
    """Estado compartido por todos los hilos.

    Regla: todo lo que lee o modifica el estado, y el reparto de mensajes,
    se hace dentro del cerrojo. Repartir es barato (meter en una cola o
    programar un envío), así que el cerrojo se suelta enseguida, y a
    cambio todos los clientes reciben los mensajes en el MISMO orden.
    """

    def __init__(self):
        self.cerrojo = threading.Lock()
        self.miembros = []
        self.trazos = []
        self.chat = deque(maxlen=MAX_CHAT)
        self.bucle_web = None        # bucle asyncio del hilo WebSocket

    # --- internos (llamar SIEMPRE con el cerrojo cogido) ---

    def _repartir(self, mensaje, solo_web=False, excepto=None):
        texto = a_json(mensaje)
        navegadores = []
        for miembro in self.miembros:
            if miembro is excepto:
                continue
            if miembro.origen == "web":
                navegadores.append(miembro.conexion)
            elif not solo_web:
                miembro.enviar(texto)
        # un único broadcast para todos los navegadores
        if navegadores:
            self.bucle_web.call_soon_threadsafe(broadcast, navegadores, texto)

    def _lista_usuarios(self):
        return [{"nombre": m.nombre, "origen": m.origen} for m in self.miembros]

    def _nombre_libre(self, pedido, prefijo):
        base = limpiar_nombre(pedido) or prefijo
        usados = {m.nombre.lower() for m in self.miembros if m.nombre}
        nombre, n = base, 2
        while nombre.lower() in usados:
            nombre = f"{base} ({n})"
            n += 1
        return nombre

    def _sistema(self, texto):
        mensaje = {"tipo": "sistema", "texto": texto, "hora": hora()}
        self.chat.append(mensaje)
        self._repartir(mensaje)

    # --- API pública (cualquier hilo) ---

    def entrar(self, miembro, nombre_pedido):
        with self.cerrojo:
            miembro.nombre = self._nombre_libre(nombre_pedido, "invitado")
            self.miembros.append(miembro)

            bienvenida = {
                "tipo": "bienvenida",
                "nombre": miembro.nombre,
                "usuarios": self._lista_usuarios(),
                "chat": list(self.chat),
            }
            if miembro.origen == "web":           # la terminal no dibuja
                bienvenida["trazos"] = self.trazos
            miembro.enviar(a_json(bienvenida))

            self._sistema(f"{miembro.nombre} se ha unido desde {miembro.origen}")
            self._repartir({"tipo": "usuarios", "lista": self._lista_usuarios()})
        log(f"entra {miembro.nombre} ({miembro.origen})")

    def salir(self, miembro):
        with self.cerrojo:
            if miembro not in self.miembros:
                return
            self.miembros.remove(miembro)
            self._sistema(f"{miembro.nombre} se ha ido")
            self._repartir({"tipo": "usuarios", "lista": self._lista_usuarios()})
        log(f"sale {miembro.nombre} ({miembro.origen})")

    def procesar(self, miembro, mensaje):
        """Decide qué hacer con cada mensaje según su tipo."""
        tipo = mensaje.get("tipo")

        if tipo == "chat":
            texto = mensaje.get("texto")
            if not isinstance(texto, str) or not texto.strip():
                return
            salida = {
                "tipo": "chat",
                "nombre": miembro.nombre,
                "origen": miembro.origen,
                "texto": texto.strip()[:MAX_TEXTO],
                "hora": hora(),
            }
            with self.cerrojo:
                self.chat.append(salida)
                self._repartir(salida)          # también al autor: confirma
            log(f"chat {miembro.nombre}: {salida['texto']}")

        elif tipo == "trazo":
            trazo = validar_trazo(mensaje)
            if trazo is None:
                self.error(miembro, "trazo no válido")
                return
            with self.cerrojo:
                if len(self.trazos) >= MAX_TRAZOS:
                    self.error(miembro, "la pizarra está llena, bórrala")
                    return
                self.trazos.append(trazo)
                # el autor ya lo pintó en local: no se le reenvía
                self._repartir(trazo, solo_web=True, excepto=miembro)

        elif tipo == "cursor":
            x, y = coordenada(mensaje.get("x")), coordenada(mensaje.get("y"))
            salida = {"tipo": "cursor", "nombre": miembro.nombre}
            if x is None or y is None:
                salida["fuera"] = True
            else:
                salida["x"], salida["y"] = x, y
            with self.cerrojo:                   # efímero: no se guarda
                self._repartir(salida, solo_web=True, excepto=miembro)

        elif tipo == "borrar":
            with self.cerrojo:
                self.trazos = []
                self._repartir({"tipo": "borrar", "nombre": miembro.nombre},
                               solo_web=True)
                self._sistema(f"{miembro.nombre} ha borrado la pizarra")
            log(f"{miembro.nombre} borra la pizarra")

        elif tipo == "nombre":
            with self.cerrojo:
                antiguo = miembro.nombre
                nuevo = limpiar_nombre(mensaje.get("nombre"))
                if not nuevo or nuevo == antiguo:
                    return
                miembro.nombre = None            # para que no choque consigo
                miembro.nombre = self._nombre_libre(nuevo, antiguo)
                miembro.enviar(a_json({"tipo": "renombrado",
                                       "nombre": miembro.nombre}))
                self._sistema(f"{antiguo} ahora se llama {miembro.nombre}")
                self._repartir({"tipo": "usuarios",
                                "lista": self._lista_usuarios()})

        elif tipo == "ping":
            # se devuelve tal cual el instante del cliente para medir latencia
            miembro.enviar(a_json({"tipo": "pong", "t": mensaje.get("t")}))

        elif tipo == "hola":
            self.error(miembro, "ya estás conectado")

        else:
            self.error(miembro, f"tipo de mensaje desconocido: {tipo!r}")

    def error(self, miembro, texto):
        miembro.enviar(a_json({"tipo": "error", "texto": texto}))


# ----------------------------------------------------------- servidor TCP

def leer_lineas(conexion):
    """Generador que trocea el flujo TCP en líneas.

    recv() puede devolver medio mensaje o tres mensajes juntos: TCP no
    respeta fronteras. Por eso se acumula en un búfer y se corta por \\n.
    """
    pendiente = b""
    while True:
        datos = conexion.recv(4096)
        if not datos:                    # el otro extremo cerró
            return
        pendiente += datos
        while b"\n" in pendiente:
            linea, pendiente = pendiente.split(b"\n", 1)
            if len(linea) > MAX_MENSAJE:
                raise ValueError("línea demasiado larga")
            linea = linea.decode("utf-8", errors="replace").strip()
            if linea:
                yield linea
        if len(pendiente) > MAX_MENSAJE:
            raise ValueError("línea demasiado larga")


def atender_tcp(sala, conexion, direccion):
    """Hilo LECTOR de un cliente de terminal."""
    miembro = MiembroTCP(conexion, direccion)
    escritor = threading.Thread(
        target=miembro.bucle_escritura,
        name=f"TCP-esc-{direccion[1]}",
        daemon=True,
    )
    escritor.start()
    log(f"conexión TCP desde {direccion[0]}:{direccion[1]}")

    try:
        for linea in leer_lineas(conexion):
            mensaje = interpretar(linea)

            if miembro.nombre is None:
                # El primer mensaje debería ser {"tipo":"hola","nombre":...}.
                # Si no lo es (p. ej. nc), entra como invitado y se procesa.
                if mensaje.get("tipo") == "hola":
                    sala.entrar(miembro, mensaje.get("nombre"))
                    continue
                sala.entrar(miembro, None)

            sala.procesar(miembro, mensaje)

    except ValueError as error:
        log(f"{direccion[0]}:{direccion[1]}: {error}, se cierra")
        miembro.enviar(a_json({"tipo": "error", "texto": str(error)}))
    except OSError:
        pass
    finally:
        sala.salir(miembro)
        try:
            miembro.cola.put(None, timeout=1)   # que el escritor termine
        except queue.Full:
            pass
        escritor.join(timeout=2)
        conexion.close()
        log(f"conexión TCP cerrada {direccion[0]}:{direccion[1]}")


def hilo_aceptador(sala, servidor):
    """Bucle de accept(): un hilo nuevo por cada cliente que llega."""
    while True:
        conexion, direccion = servidor.accept()
        threading.Thread(
            target=atender_tcp,
            args=(sala, conexion, direccion),
            name=f"TCP-lee-{direccion[1]}",
            daemon=True,
        ).start()


def crear_servidor_tcp(host, puerto):
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind((host, puerto))
    servidor.listen()
    return servidor


# ----------------------------------------------------- servidor WebSocket

async def atender_web(sala, conexion):
    """Corrutina que atiende a un navegador (todas en el mismo hilo)."""
    miembro = MiembroWeb(conexion, asyncio.get_running_loop())
    direccion = conexion.remote_address
    log(f"conexión WebSocket desde {direccion[0]}:{direccion[1]}")

    try:
        primero = await asyncio.wait_for(conexion.recv(), TIEMPO_HOLA)
        hola = interpretar(primero) if isinstance(primero, str) else {}
        sala.entrar(miembro, hola.get("nombre"))

        async for texto in conexion:
            if not isinstance(texto, str):
                sala.error(miembro, "solo se aceptan mensajes de texto")
                continue
            sala.procesar(miembro, interpretar(texto))

    except (ConnectionClosed, TimeoutError):
        pass
    finally:
        sala.salir(miembro)
        log(f"conexión WebSocket cerrada {direccion[0]}:{direccion[1]}")


def hilo_websocket(sala, host, puerto, listo, fallo):
    async def principal():
        sala.bucle_web = asyncio.get_running_loop()
        async with serve(partial(atender_web, sala), host, puerto,
                         max_size=MAX_MENSAJE):
            listo.set()
            await asyncio.Future()          # para siempre

    try:
        asyncio.run(principal())
    except OSError as error:
        fallo.append(error)
        listo.set()


# ---------------------------------------------------------- servidor HTTP

class ManejadorHTTP(SimpleHTTPRequestHandler):
    """Sirve web/ y además /config.json con el puerto del WebSocket."""

    puerto_ws = 8765

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CARPETA_WEB), **kwargs)

    def do_GET(self):
        if self.path == "/config.json":
            cuerpo = a_json({"ws": self.puerto_ws}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
        else:
            super().do_GET()

    def log_message(self, formato, *args):
        log(f"HTTP {self.address_string()} {formato % args}")


# ------------------------------------------------------------------ arranque

def ip_local():
    """IP de este equipo en la red local (para que se conecten otros).
    Un socket UDP con connect() no envía nada: solo elige la interfaz."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main():
    parser = argparse.ArgumentParser(description="Garabato: pizarra + chat")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--tcp", type=int, default=5000)
    parser.add_argument("--ws", type=int, default=8765)
    parser.add_argument("--http", type=int, default=8000)
    args = parser.parse_args()

    threading.current_thread().name = "principal"
    sala = Sala()

    # 1) WebSocket en su hilo con su propio bucle asyncio
    listo, fallo = threading.Event(), []
    threading.Thread(
        target=hilo_websocket,
        args=(sala, args.host, args.ws, listo, fallo),
        name="WebSocket",
        daemon=True,
    ).start()
    listo.wait()
    if fallo:
        sys.exit(f"No se pudo abrir el puerto WebSocket {args.ws}: {fallo[0]}")

    # 2) TCP: el socket se crea aquí para ver los errores de bind al momento
    try:
        servidor_tcp = crear_servidor_tcp(args.host, args.tcp)
    except OSError as error:
        sys.exit(f"No se pudo abrir el puerto TCP {args.tcp}: {error}")
    threading.Thread(
        target=hilo_aceptador, args=(sala, servidor_tcp),
        name="TCP-aceptador", daemon=True,
    ).start()

    # 3) HTTP
    ManejadorHTTP.puerto_ws = args.ws
    try:
        servidor_http = ThreadingHTTPServer((args.host, args.http), ManejadorHTTP)
    except OSError as error:
        sys.exit(f"No se pudo abrir el puerto HTTP {args.http}: {error}")
    servidor_http.daemon_threads = True
    threading.Thread(
        target=servidor_http.serve_forever, name="HTTP", daemon=True,
    ).start()

    ip = ip_local()
    print(f"""
  Garabato listo
  ---------------------------------------------
  Web (pizarra):  http://localhost:{args.http}   ·  http://{ip}:{args.http}
  Terminal:       python3 cliente.py {ip} {args.tcp}
  Con netcat:     nc {ip} {args.tcp}
  WebSocket:      ws://{ip}:{args.ws}
  Ctrl+C para parar
""", flush=True)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nServidor detenido")


if __name__ == "__main__":
    main()
