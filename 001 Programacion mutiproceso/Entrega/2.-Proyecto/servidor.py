"""
servidor.py
-----------
Servidor web para Prisma.

1. Sirve los archivos del proyecto (index.html, js, img.jpg...).
   Los Web Workers NO funcionan abriendo el html con file://,
   por eso hace falta un servidor.

2. Ofrece una pequeña API para guardar las mediciones:
      GET  /api/resultados  -> devuelve todas las ejecuciones (JSON)
      POST /api/resultados  -> añade una ejecución a resultados.csv

ThreadingHTTPServer atiende cada petición en un HILO distinto.
Si dos navegadores envían resultados a la vez, dos hilos podrían
escribir en el CSV al mismo tiempo y mezclar las líneas.
Para evitarlo uso un cerrojo (threading.Lock): solo un hilo
puede estar dentro de la sección crítica.

Uso:
    python3 servidor.py          (puerto 8000)
    python3 servidor.py 8080
"""

import csv
import json
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
ARCHIVO_CSV = CARPETA / "resultados.csv"

CAMPOS = [
    "fecha", "cliente", "filtro", "intensidad", "modo", "workers",
    "tesela", "teselas", "ancho", "alto", "ms", "speedup",
    "eficiencia", "nucleos",
]

cerrojo = threading.Lock()


def leer_resultados():
    if not ARCHIVO_CSV.exists():
        return []
    with ARCHIVO_CSV.open(newline="", encoding="utf-8") as archivo:
        return list(csv.DictReader(archivo))


def guardar_resultado(fila):
    # ---- SECCIÓN CRÍTICA ----
    with cerrojo:
        nuevo = not ARCHIVO_CSV.exists()
        with ARCHIVO_CSV.open("a", newline="", encoding="utf-8") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=CAMPOS)
            if nuevo:
                escritor.writeheader()
            escritor.writerow(fila)
    # ---- FIN SECCIÓN CRÍTICA ----


class Manejador(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CARPETA), **kwargs)

    def responder_json(self, codigo, datos):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path == "/api/resultados":
            with cerrojo:
                filas = leer_resultados()
            self.responder_json(200, filas)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path != "/api/resultados":
            self.responder_json(404, {"error": "ruta no encontrada"})
            return

        try:
            longitud = int(self.headers.get("Content-Length", 0))
            datos = json.loads(self.rfile.read(longitud))
            if not isinstance(datos, dict):
                raise ValueError("se esperaba un objeto JSON")
        except (ValueError, json.JSONDecodeError) as error:
            self.responder_json(400, {"error": str(error)})
            return

        fila = {campo: datos.get(campo, "") for campo in CAMPOS}
        fila["cliente"] = self.client_address[0]
        guardar_resultado(fila)

        print(f"[{threading.current_thread().name}] guardada ejecución: "
              f"{fila['filtro']} · {fila['workers']} workers · {fila['ms']} ms")

        self.responder_json(201, {"ok": True})


if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    servidor = ThreadingHTTPServer(("0.0.0.0", puerto), Manejador)
    print(f"Prisma en http://localhost:{puerto}  (Ctrl+C para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido")
