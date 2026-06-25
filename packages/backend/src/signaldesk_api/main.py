from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable
from typing import Any, cast
from wsgiref.simple_server import WSGIServer, make_server

from signaldesk_api.app import create_app, openapi_schema

WsgiApp = Callable[[dict[str, Any], Callable[..., Any]], Iterable[bytes]]


class ReusableWsgiServer(WSGIServer):
    allow_reuse_address = True


def _serve(host: str, port: int) -> None:
    app = cast(WsgiApp, create_app())
    with make_server(host, port, app, server_class=ReusableWsgiServer) as server:
        actual_host, actual_port = server.server_address[:2]
        host_text = actual_host.decode() if isinstance(actual_host, bytes) else str(actual_host)
        print(f"SignalDesk API serving host={host_text} port={actual_port}", flush=True)
        server.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SignalDesk API utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Run the local SignalDesk API server")
    serve.add_argument("--host", default="127.0.0.1", help="Interface to bind")
    serve.add_argument("--port", type=int, default=8000, help="TCP port to bind")
    subparsers.add_parser("openapi", help="Print the generated OpenAPI document")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "openapi":
        print(json.dumps(openapi_schema(), indent=2, sort_keys=True))
        return 0
    if args.command == "serve":
        _serve(args.host, args.port)
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
