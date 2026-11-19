"""Protocolo de red de MiniDrop.

Cada mensaje en el cable tiene este formato:

    [4 bytes: longitud de la cabecera, big-endian]
    [cabecera JSON en UTF-8]
    [payload binario, de longitud header["size"]]

La cabecera siempre lleva "type". El payload (contenido de un archivo)
es opcional. Hay helpers asíncronos (servidor) y síncronos (cliente).
"""

import json
import struct

MAX_HEADER = 1 << 20          # 1 MiB
MAX_PAYLOAD = 512 * (1 << 20)  # 512 MiB por archivo en este MVP


class ProtocolError(Exception):
    """Error de protocolo o respuesta de error del otro extremo."""


def encode(header: dict, payload: bytes = b"") -> bytes:
    header = dict(header, size=len(payload))
    raw = json.dumps(header).encode("utf-8")
    return struct.pack("!I", len(raw)) + raw + payload


def _parse_header(raw: bytes) -> dict:
    try:
        header = json.loads(raw)
    except ValueError as exc:
        raise ProtocolError("cabecera JSON inválida") from exc
    if not isinstance(header, dict):
        raise ProtocolError("la cabecera debe ser un objeto JSON")
    size = header.get("size", 0)
    if not isinstance(size, int) or size < 0 or size > MAX_PAYLOAD:
        raise ProtocolError("tamaño de payload inválido")
    return header


# ---------- versión asíncrona (servidor) ----------

async def aread(reader):
    (n,) = struct.unpack("!I", await reader.readexactly(4))
    if n > MAX_HEADER:
        raise ProtocolError("cabecera demasiado grande")
    header = _parse_header(await reader.readexactly(n))
    size = header["size"]
    payload = await reader.readexactly(size) if size else b""
    return header, payload


async def asend(writer, header: dict, payload: bytes = b""):
    writer.write(encode(header, payload))
    await writer.drain()


# ---------- versión síncrona (cliente) ----------

def _recv_exact(sock, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(65536, n - len(buf)))
        if not chunk:
            raise ConnectionError("conexión cerrada por el servidor")
        buf.extend(chunk)
    return bytes(buf)


def read_sync(sock):
    (n,) = struct.unpack("!I", _recv_exact(sock, 4))
    if n > MAX_HEADER:
        raise ProtocolError("cabecera demasiado grande")
    header = _parse_header(_recv_exact(sock, n))
    size = header["size"]
    payload = _recv_exact(sock, size) if size else b""
    return header, payload


def send_sync(sock, header: dict, payload: bytes = b""):
    sock.sendall(encode(header, payload))
