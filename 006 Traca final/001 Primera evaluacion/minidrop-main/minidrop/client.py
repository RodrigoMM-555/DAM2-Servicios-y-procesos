"""Cliente MiniDrop.

Mantiene una carpeta local sincronizada con el servidor. Guarda en
`.minidrop_state.json` el último estado sincronizado (por ruta: sha256 y
versión). Comparando ese estado con (a) el disco y (b) los cambios del
servidor se decide qué subir, qué bajar y dónde hay conflicto.
"""

import hashlib
import json
import logging
import os
import socket
import time
from pathlib import Path

from .protocol import ProtocolError, read_sync, send_sync

log = logging.getLogger("minidrop.client")

STATE_FILE = ".minidrop_state.json"
TMP_SUFFIX = ".minidrop-tmp"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Client:
    def __init__(self, folder, host="127.0.0.1", port=8765, token="", client_id=None,
                 interval=2.0):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.host, self.port, self.token = host, port, token
        self.client_id = client_id or socket.gethostname()
        self.interval = interval
        self.sock = None
        self._hash_cache = {}  # ruta -> (mtime_ns, size, sha256)
        self.state = {"rev": 0, "files": {}}
        state_path = self.folder / STATE_FILE
        if state_path.exists():
            self.state = json.loads(state_path.read_text())

    # ---------- red ----------

    def connect(self):
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=30)
        send_sync(self.sock, {"type": "hello", "token": self.token,
                              "client_id": self.client_id})
        resp, _ = read_sync(self.sock)
        if resp.get("type") != "hello":
            raise ProtocolError(resp.get("message", "el servidor rechazó la conexión"))

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def request(self, header, payload=b""):
        if self.sock is None:
            self.connect()
        send_sync(self.sock, header, payload)
        resp, data = read_sync(self.sock)
        if resp.get("type") == "error":
            raise ProtocolError(resp.get("message", "error del servidor"))
        return resp, data

    # ---------- disco ----------

    def _save_state(self):
        path = self.folder / STATE_FILE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        os.replace(tmp, path)

    def _ignored(self, name: str) -> bool:
        return name == STATE_FILE or name.endswith(TMP_SUFFIX) or name.startswith(".")

    def scan(self) -> dict:
        """Devuelve {ruta_relativa_posix: sha256} de todos los archivos."""
        result = {}
        for dirpath, dirnames, filenames in os.walk(self.folder):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if self._ignored(name):
                    continue
                full = Path(dirpath) / name
                rel = full.relative_to(self.folder).as_posix()
                try:
                    st = full.stat()
                    cached = self._hash_cache.get(rel)
                    if cached and cached[:2] == (st.st_mtime_ns, st.st_size):
                        result[rel] = cached[2]
                        continue
                    digest = sha256_bytes(full.read_bytes())
                except FileNotFoundError:
                    continue  # desapareció durante el escaneo
                self._hash_cache[rel] = (st.st_mtime_ns, st.st_size, digest)
                result[rel] = digest
        return result

    def _write_atomic(self, rel: str, data: bytes):
        full = self.folder / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        tmp = full.with_name(full.name + TMP_SUFFIX)
        tmp.write_bytes(data)
        os.replace(tmp, full)
        st = full.stat()
        self._hash_cache[rel] = (st.st_mtime_ns, st.st_size, sha256_bytes(data))

    def _conflict_name(self, rel: str) -> str:
        p = Path(rel)
        n = 0
        while True:
            suffix = f" (conflicto de {self.client_id}{'' if n == 0 else f' {n}'})"
            candidate = p.with_name(f"{p.stem}{suffix}{p.suffix}").as_posix()
            if not (self.folder / candidate).exists():
                return candidate
            n += 1

    # ---------- sincronización ----------

    def sync_once(self) -> dict:
        stats = {"uploaded": 0, "downloaded": 0, "deleted_local": 0,
                 "deleted_remote": 0, "conflicts": 0}
        known = self.state["files"]
        local = self.scan()
        local_changed = {p for p, s in local.items()
                         if known.get(p, {}).get("sha256") != s}
        local_deleted = {p for p, k in known.items()
                         if k["sha256"] is not None and p not in local}

        # 1) Bajar cambios del servidor
        resp, _ = self.request({"type": "changes", "since": self.state["rev"]})
        for path, meta in resp["files"].items():
            k = known.get(path)
            if k and k["version"] == meta["version"]:
                continue  # es un cambio que hicimos nosotros mismos

            if meta["deleted"]:
                if path in local_changed:
                    # modificado aquí y borrado allí: gana lo local (se vuelve a subir)
                    known[path] = {"sha256": None, "version": meta["version"]}
                else:
                    f = self.folder / path
                    if f.exists():
                        f.unlink()
                        stats["deleted_local"] += 1
                    known[path] = {"sha256": None, "version": meta["version"]}
                    self._hash_cache.pop(path, None)
                    local_deleted.discard(path)
                continue

            if path in local_changed and local[path] != meta["sha256"]:
                # conflicto: se conserva la copia local con otro nombre
                new_rel = self._conflict_name(path)
                (self.folder / new_rel).parent.mkdir(parents=True, exist_ok=True)
                os.replace(self.folder / path, self.folder / new_rel)
                self._hash_cache.pop(path, None)
                local_changed.discard(path)
                stats["conflicts"] += 1
                log.warning("conflicto en %s; copia local guardada como %s", path, new_rel)

            if path in local_changed and local[path] == meta["sha256"]:
                pass  # mismo contenido en ambos lados: solo actualizar versión
            else:
                r, data = self.request({"type": "pull", "path": path})
                if sha256_bytes(data) != meta["sha256"]:
                    raise ProtocolError(f"descarga corrupta: {path}")
                self._write_atomic(path, data)
                stats["downloaded"] += 1
            known[path] = {"sha256": meta["sha256"], "version": meta["version"]}
            local_changed.discard(path)
            local_deleted.discard(path)
        self.state["rev"] = resp["rev"]
        self._save_state()

        # 2) Subir cambios locales (re-escaneo de nombres afectados por conflictos)
        for path in sorted(local_changed):
            f = self.folder / path
            try:
                data = f.read_bytes()
            except FileNotFoundError:
                continue
            digest = sha256_bytes(data)
            base = known.get(path, {}).get("version", 0)
            r, _ = self.request({"type": "push", "path": path, "base_version": base,
                                 "sha256": digest}, data)
            if r["type"] == "ok":
                known[path] = {"sha256": digest, "version": r["version"]}
                stats["uploaded"] += 1
            # si hay "conflict", el próximo ciclo traerá el cambio remoto y lo resolverá

        for path in sorted(local_deleted):
            base = known[path]["version"]
            r, _ = self.request({"type": "delete", "path": path, "base_version": base})
            if r["type"] == "ok":
                known[path] = {"sha256": None, "version": r["version"]}
                stats["deleted_remote"] += 1

        self._save_state()
        return stats

    def run_forever(self):
        backoff = 1.0
        while True:
            try:
                stats = self.sync_once()
                if any(stats.values()):
                    log.info("sync: %s", stats)
                backoff = 1.0
                time.sleep(self.interval)
            except (ConnectionError, OSError, ProtocolError) as exc:
                log.warning("sin conexión (%s); reintentando en %.0fs", exc, backoff)
                self.close()
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
