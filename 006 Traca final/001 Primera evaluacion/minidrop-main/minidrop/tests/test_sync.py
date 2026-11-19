"""Pruebas de integración: un servidor real y dos clientes sobre TCP local.

Ejecutar:  python -m unittest discover -s tests -v
"""

import asyncio
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from minidrop.client import Client, STATE_FILE
from minidrop.protocol import read_sync, send_sync
from minidrop.server import Server

TOKEN = "secreto-de-prueba"


class ServerThread:
    def __init__(self, root):
        self.server = Server(root, TOKEN)
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.srv = self.loop.run_until_complete(self.server.start("127.0.0.1", 0))
        self.port = self.srv.sockets[0].getsockname()[1]
        self.ready.set()
        self.loop.run_forever()

    def start(self):
        self.thread.start()
        self.ready.wait(5)

    def stop(self):
        async def shutdown():
            self.srv.close()
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()


def files_of(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_text()
            for p in folder.rglob("*")
            if p.is_file() and p.name != STATE_FILE}


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.srv = ServerThread(base / "server")
        self.srv.start()
        self.a_dir, self.b_dir = base / "A", base / "B"
        self.a = Client(self.a_dir, "127.0.0.1", self.srv.port, TOKEN, "A")
        self.b = Client(self.b_dir, "127.0.0.1", self.srv.port, TOKEN, "B")

    def tearDown(self):
        self.a.close()
        self.b.close()
        self.srv.stop()
        self.tmp.cleanup()

    def sync_all(self, rounds=3):
        for _ in range(rounds):
            self.a.sync_once()
            self.b.sync_once()

    def test_crear_y_replicar(self):
        (self.a_dir / "sub").mkdir()
        (self.a_dir / "hola.txt").write_text("hola")
        (self.a_dir / "sub" / "x.txt").write_text("anidado")
        self.sync_all()
        self.assertEqual(files_of(self.b_dir), {"hola.txt": "hola", "sub/x.txt": "anidado"})

    def test_modificar_se_propaga(self):
        (self.a_dir / "n.txt").write_text("v1")
        self.sync_all()
        (self.b_dir / "n.txt").write_text("v2 desde B")
        self.sync_all()
        self.assertEqual(files_of(self.a_dir)["n.txt"], "v2 desde B")

    def test_borrar_se_propaga(self):
        (self.a_dir / "n.txt").write_text("v1")
        self.sync_all()
        (self.a_dir / "n.txt").unlink()
        self.sync_all()
        self.assertEqual(files_of(self.b_dir), {})

    def test_recrear_archivo_borrado(self):
        (self.a_dir / "n.txt").write_text("v1")
        self.sync_all()
        (self.a_dir / "n.txt").unlink()
        self.sync_all()
        (self.b_dir / "n.txt").write_text("de nuevo")
        self.sync_all()
        self.assertEqual(files_of(self.a_dir), {"n.txt": "de nuevo"})

    def test_conflicto_conserva_ambas_versiones(self):
        (self.a_dir / "doc.txt").write_text("base")
        self.sync_all()
        (self.a_dir / "doc.txt").write_text("edición de A")
        (self.b_dir / "doc.txt").write_text("edición de B")
        self.a.sync_once()          # A sube primero y gana
        self.sync_all(4)
        fa, fb = files_of(self.a_dir), files_of(self.b_dir)
        self.assertEqual(fa, fb)
        self.assertEqual(fa["doc.txt"], "edición de A")
        conflict = [k for k in fa if "conflicto" in k]
        self.assertEqual(len(conflict), 1)
        self.assertEqual(fa[conflict[0]], "edición de B")

    def test_modificado_local_vs_borrado_remoto_gana_lo_local(self):
        (self.a_dir / "d.txt").write_text("base")
        self.sync_all()
        (self.a_dir / "d.txt").unlink()
        self.a.sync_once()
        (self.b_dir / "d.txt").write_text("B lo editó")
        self.sync_all(4)
        self.assertEqual(files_of(self.a_dir), {"d.txt": "B lo editó"})
        self.assertEqual(files_of(self.b_dir), {"d.txt": "B lo editó"})

    def test_estado_persistente_tras_reiniciar_cliente(self):
        (self.a_dir / "p.txt").write_text("persistente")
        self.sync_all()
        a2 = Client(self.a_dir, "127.0.0.1", self.srv.port, TOKEN, "A")
        stats = a2.sync_once()
        a2.close()
        self.assertEqual(sum(stats.values()), 0)  # no re-sube ni re-baja nada

    def test_rechaza_token_incorrecto(self):
        bad = Client(self.a_dir, "127.0.0.1", self.srv.port, "token-malo", "X")
        with self.assertRaises(Exception):
            bad.sync_once()
        bad.close()

    def test_rechaza_rutas_peligrosas(self):
        s = socket.create_connection(("127.0.0.1", self.srv.port))
        send_sync(s, {"type": "hello", "token": TOKEN, "client_id": "evil"})
        read_sync(s)
        for evil in ["../escape.txt", "/etc/passwd", "a/../../b.txt"]:
            import hashlib
            data = b"x"
            send_sync(s, {"type": "push", "path": evil, "base_version": 0,
                          "sha256": hashlib.sha256(data).hexdigest()}, data)
            resp, _ = read_sync(s)
            self.assertEqual(resp["type"], "error", evil)
        s.close()
        self.assertFalse((Path(self.tmp.name) / "escape.txt").exists())

    def test_archivo_binario_grande(self):
        blob = bytes(range(256)) * 20000  # ~5 MB
        (self.a_dir / "datos.bin").write_bytes(blob)
        self.sync_all()
        self.assertEqual((self.b_dir / "datos.bin").read_bytes(), blob)


if __name__ == "__main__":
    unittest.main()
