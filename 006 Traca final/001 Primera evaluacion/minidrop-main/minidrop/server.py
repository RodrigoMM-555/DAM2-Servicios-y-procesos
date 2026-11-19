"""Servidor MiniDrop (asyncio).

Guarda la copia "oficial" de los archivos y un índice con, por cada ruta:
sha256, tamaño, versión (se incrementa en cada cambio) y rev (contador
global de revisiones). Los clientes preguntan "dame lo que cambió desde la
revisión N", lo que permite sincronizar de forma incremental.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path, PurePosixPath

from .protocol import ProtocolError, aread, asend

log = logging.getLogger("minidrop.server")


class Store:
    """Almacenamiento + índice persistente. Todas las operaciones son
    síncronas y cortas; al correr en un único hilo de asyncio no hay
    condiciones de carrera entre clientes."""

    def __init__(self, root):
        self.root = Path(root)
        self.files_dir = (self.root / "files").resolve()
        self.index_path = self.root / "index.json"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.rev = 0
        self.files = {}
        if self.index_path.exists():
            data = json.loads(self.index_path.read_text())
            self.rev = data["rev"]
            self.files = data["files"]

    # -- utilidades --

    def _full_path(self, rel: str) -> Path:
        """Convierte una ruta relativa del cliente en una ruta segura
        dentro de files_dir (evita '../', rutas absolutas, etc.)."""
        if not isinstance(rel, str) or not rel or "\\" in rel or "\x00" in rel:
            raise ValueError("ruta inválida")
        p = PurePosixPath(rel)
        if p.is_absolute() or ".." in p.parts or "." in p.parts:
            raise ValueError("ruta no permitida")
        full = (self.files_dir / Path(*p.parts)).resolve()
        if self.files_dir not in full.parents:
            raise ValueError("ruta fuera del almacén")
        return full

    def _save_index(self):
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"rev": self.rev, "files": self.files}))
        os.replace(tmp, self.index_path)

    # -- operaciones --

    def changes_since(self, rev: int) -> dict:
        changed = {p: m for p, m in self.files.items() if m["rev"] > rev}
        return {"rev": self.rev, "files": changed}

    def put(self, path, base_version, data: bytes, sha256: str) -> dict:
        full = self._full_path(path)
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError("el hash no coincide con el contenido")
        cur = self.files.get(path)
        cur_version = cur["version"] if cur else 0
        if base_version != cur_version:
            if cur and not cur["deleted"] and cur["sha256"] == sha256:
                return {"type": "ok", "version": cur_version, "noop": True}
            return {"type": "conflict", "current": cur}
        full.parent.mkdir(parents=True, exist_ok=True)
        tmp = full.with_name(full.name + ".minidrop-tmp")
        tmp.write_bytes(data)
        os.replace(tmp, full)
        self.rev += 1
        self.files[path] = {
            "sha256": sha256, "size": len(data), "version": cur_version + 1,
            "rev": self.rev, "deleted": False,
        }
        self._save_index()
        return {"type": "ok", "version": cur_version + 1}

    def delete(self, path, base_version) -> dict:
        full = self._full_path(path)
        cur = self.files.get(path)
        if not cur or cur["deleted"]:
            return {"type": "ok", "version": cur["version"] if cur else 0, "noop": True}
        if base_version != cur["version"]:
            return {"type": "conflict", "current": cur}
        if full.exists():
            full.unlink()
        self.rev += 1
        self.files[path] = {
            "sha256": None, "size": 0, "version": cur["version"] + 1,
            "rev": self.rev, "deleted": True,
        }
        self._save_index()
        return {"type": "ok", "version": cur["version"] + 1}

    def get(self, path) -> bytes:
        full = self._full_path(path)
        meta = self.files.get(path)
        if not meta or meta["deleted"] or not full.is_file():
            raise ValueError("el archivo no existe")
        return full.read_bytes()


class Server:
    def __init__(self, root, token: str):
        self.store = Store(root)
        self.token = token

    async def handle(self, reader, writer):
        peer = writer.get_extra_info("peername")
        try:
            header, _ = await aread(reader)
            ok = header.get("type") == "hello" and hmac.compare_digest(
                str(header.get("token", "")), self.token)
            if not ok:
                await asend(writer, {"type": "error", "message": "autenticación fallida"})
                log.warning("auth fallida desde %s", peer)
                return
            client_id = str(header.get("client_id", "?"))
            await asend(writer, {"type": "hello", "rev": self.store.rev})
            log.info("cliente conectado: %s (%s)", client_id, peer)

            while True:
                header, payload = await aread(reader)
                try:
                    resp, out = self.dispatch(header, payload)
                except (KeyError, ValueError, TypeError) as exc:
                    resp, out = {"type": "error", "message": str(exc)}, b""
                await asend(writer, resp, out)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        except ProtocolError as exc:
            log.warning("error de protocolo de %s: %s", peer, exc)
        finally:
            writer.close()
            log.info("cliente desconectado: %s", peer)

    def dispatch(self, h: dict, payload: bytes):
        t = h.get("type")
        if t == "changes":
            return {"type": "changes", **self.store.changes_since(int(h["since"]))}, b""
        if t == "push":
            return self.store.put(h["path"], int(h["base_version"]), payload,
                                  h["sha256"]), b""
        if t == "delete":
            return self.store.delete(h["path"], int(h["base_version"])), b""
        if t == "pull":
            return {"type": "file"}, self.store.get(h["path"])
        raise ValueError(f"tipo de mensaje desconocido: {t!r}")

    async def start(self, host="0.0.0.0", port=8765):
        return await asyncio.start_server(self.handle, host, port)


async def serve(root, host, port, token):
    server = await Server(root, token).start(host, port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    log.info("MiniDrop escuchando en %s", addrs)
    async with server:
        await server.serve_forever()
