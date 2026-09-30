"""The ``view`` verb: start the web interface, or find and stop one.

Wired into ``run.py`` by ``add_parser`` so the command line has one shape:

    python run.py view [--port 8765] [--no-browser] [--input inputs]
    python run.py view --list
    python run.py view --stop --port 8765
    python run.py view --replace

The port is never quietly changed.  A port that is already taken is an
answer, not a problem to route around: ``--list`` says what holds it and
``--replace`` takes it over.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PORT = 8765


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("view", help="start the web interface")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--input", default="inputs")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument("--no-write-api", action="store_true",
                        help="refuse upload and sync from the page (403)")
    parser.add_argument("--idle-timeout", type=float, default=None,
                        help="stop after this many seconds without a request; 0 disables")
    parser.add_argument("--list", action="store_true", help="show the servers this checkout started")
    parser.add_argument("--stop", action="store_true", help="stop the server on --port")
    parser.add_argument("--replace", action="store_true", help="stop whatever holds --port, then start")
    parser.set_defaults(func=main)


def main(args) -> int:
    from web import server

    root = getattr(args, "root", None) or ROOT

    if getattr(args, "list", False):
        return _list(root)

    if getattr(args, "stop", False):
        stopped, detail = server.stop(args.port)
        print(f"[web] {detail}")
        if stopped:
            server.clear_lock(Path(root), args.port)
        return 0 if stopped else 1

    if getattr(args, "replace", False):
        if server.probe(args.port) is not None:
            stopped, detail = server.stop(args.port)
            print(f"[web] {detail}")
            if not stopped:
                return 1

    return server.serve(
        root, port=args.port, open_browser=not args.no_browser,
        allow_write=not args.no_write_api, input_path=args.input,
        idle_timeout=args.idle_timeout)


def _list(root) -> int:
    from web import server

    directory = server.lock_dir(Path(root))
    locks = sorted(directory.glob("port-*.json")) if directory.is_dir() else []
    if not locks:
        print("[web] no server has been started from this checkout")
        return 0
    for path in locks:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        port = record.get("port")
        live = server.probe(port) if port else None
        state = "answering" if live else "gone (stale lock)"
        print(f"[web] port {port:<6} pid {record.get('pid')}  started {record.get('startedAt')}  {state}")
        if live is None and port:
            server.clear_lock(Path(root), port)
    return 0
