"""Uso:
    python -m minidrop server --root ./datos --port 8765 --token SECRETO
    python -m minidrop client --folder ~/MiniDrop --host 192.168.1.10 --token SECRETO
"""

import argparse
import asyncio
import logging
import os


def main():
    parser = argparse.ArgumentParser(prog="minidrop", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("server", help="arranca el servidor")
    s.add_argument("--root", default="./minidrop_data")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--token", default=os.environ.get("MINIDROP_TOKEN"))

    c = sub.add_parser("client", help="arranca un cliente de sincronización")
    c.add_argument("--folder", required=True)
    c.add_argument("--host", default="127.0.0.1")
    c.add_argument("--port", type=int, default=8765)
    c.add_argument("--token", default=os.environ.get("MINIDROP_TOKEN"))
    c.add_argument("--id", default=None, help="nombre de este cliente")
    c.add_argument("--interval", type=float, default=2.0, help="segundos entre ciclos")

    args = parser.parse_args()
    if not args.token:
        parser.error("falta --token (o la variable MINIDROP_TOKEN)")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.cmd == "server":
        from .server import serve
        try:
            asyncio.run(serve(args.root, args.host, args.port, args.token))
        except KeyboardInterrupt:
            pass
    else:
        from .client import Client
        try:
            Client(args.folder, args.host, args.port, args.token, args.id,
                   args.interval).run_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
