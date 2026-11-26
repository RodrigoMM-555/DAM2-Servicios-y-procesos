"""
cliente.py
----------
Cliente de terminal de Garabato (chat por socket TCP).

Usa DOS hilos:
  - el principal lee del teclado (input() bloquea) y envía;
  - un hilo receptor escucha el socket (recv() bloquea) e imprime.
Sin el segundo hilo, no veríamos los mensajes de los demás mientras
estamos escribiendo.

Uso:
    python3 cliente.py                       (localhost:5000)
    python3 cliente.py 192.168.1.20 5000 --nombre Ana

Comandos: /usuarios  /nick NUEVO  /borrar  /ping  /ayuda  /salir
"""

import _thread
import argparse
import json
import socket
import threading
import time
import zlib

COLORES = [31, 32, 33, 34, 35, 36, 91, 92, 93, 94, 95, 96]
AYUDA = """Comandos:
  /usuarios      quién está conectado
  /nick NUEVO    cambiar de nombre
  /borrar        borrar la pizarra de todos
  /ping          medir la latencia con el servidor
  /salir         desconectarse
Cualquier otra cosa se envía al chat."""

usuarios = []
mi_nombre = None


def color(nombre):
    """Siempre el mismo color para el mismo nombre."""
    codigo = COLORES[zlib.crc32(nombre.encode()) % len(COLORES)]
    return f"\033[{codigo}m{nombre}\033[0m"


def mostrar(texto):
    # \r\033[K borra la línea del prompt, se imprime y se vuelve a pintar
    print(f"\r\033[K{texto}\n> ", end="", flush=True)


def enviar(conexion, mensaje):
    linea = json.dumps(mensaje, ensure_ascii=False) + "\n"
    conexion.sendall(linea.encode("utf-8"))


def pintar(mensaje):
    global usuarios, mi_nombre
    tipo = mensaje.get("tipo")

    if tipo == "bienvenida":
        mi_nombre = mensaje["nombre"]
        usuarios = mensaje["usuarios"]
        for anterior in mensaje.get("chat", []):
            pintar(anterior)
        mostrar(f"\033[1mConectado como {color(mi_nombre)}\033[1m. "
                f"Escribe /ayuda para ver los comandos.\033[0m")
    elif tipo == "chat":
        etiqueta = "web" if mensaje["origen"] == "web" else "term"
        mostrar(f"\033[2m{mensaje['hora']} [{etiqueta}]\033[0m "
                f"{color(mensaje['nombre'])}: {mensaje['texto']}")
    elif tipo == "sistema":
        mostrar(f"\033[2m{mensaje['hora']} · {mensaje['texto']}\033[0m")
    elif tipo == "usuarios":
        usuarios = mensaje["lista"]
    elif tipo == "renombrado":
        mi_nombre = mensaje["nombre"]
    elif tipo == "pong":
        ms = (time.perf_counter() - mensaje["t"]) * 1000
        mostrar(f"pong: {ms:.1f} ms de ida y vuelta")
    elif tipo == "error":
        mostrar(f"\033[31mError del servidor: {mensaje['texto']}\033[0m")


def recibir(conexion):
    """Hilo receptor: trocea el flujo TCP en líneas JSON."""
    pendiente = b""
    try:
        while True:
            datos = conexion.recv(4096)
            if not datos:
                break
            pendiente += datos
            while b"\n" in pendiente:
                linea, pendiente = pendiente.split(b"\n", 1)
                try:
                    pintar(json.loads(linea))
                except (json.JSONDecodeError, KeyError, TypeError):
                    mostrar(f"(mensaje no entendido: {linea[:80]!r})")
    except OSError:
        pass
    mostrar("\033[31mConexión cerrada por el servidor\033[0m")
    _thread.interrupt_main()        # despierta al input() del hilo principal


def main():
    parser = argparse.ArgumentParser(description="Cliente de chat de Garabato")
    parser.add_argument("host", nargs="?", default="localhost")
    parser.add_argument("puerto", nargs="?", type=int, default=5000)
    parser.add_argument("--nombre")
    args = parser.parse_args()

    nombre = args.nombre or input("Tu nombre: ").strip()

    conexion = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        conexion.connect((args.host, args.puerto))
    except OSError as error:
        print(f"No se pudo conectar a {args.host}:{args.puerto}: {error}")
        return

    enviar(conexion, {"tipo": "hola", "nombre": nombre})
    threading.Thread(target=recibir, args=(conexion,), daemon=True).start()

    try:
        while True:
            texto = input("> ").strip()
            if not texto:
                continue
            if texto == "/salir":
                break
            elif texto == "/ayuda":
                mostrar(AYUDA)
            elif texto == "/usuarios":
                lista = ", ".join(f"{color(u['nombre'])} ({u['origen']})"
                                  for u in usuarios)
                mostrar(f"Conectados ({len(usuarios)}): {lista}")
            elif texto.startswith("/nick "):
                enviar(conexion, {"tipo": "nombre", "nombre": texto[6:]})
            elif texto == "/borrar":
                enviar(conexion, {"tipo": "borrar"})
            elif texto == "/ping":
                enviar(conexion, {"tipo": "ping", "t": time.perf_counter()})
            elif texto.startswith("/"):
                mostrar("Comando desconocido. Escribe /ayuda")
            else:
                enviar(conexion, {"tipo": "chat", "texto": texto})
    except (KeyboardInterrupt, EOFError, OSError):
        pass
    finally:
        conexion.close()
        print("\nHasta luego")


if __name__ == "__main__":
    main()
