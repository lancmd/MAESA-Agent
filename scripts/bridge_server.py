#!/usr/bin/env python3
"""Expose a software-specific handler through the mining GIS socket protocol."""

from __future__ import annotations

import argparse
import importlib
import json
import socketserver
from typing import Any, Callable


Handler = Callable[[dict[str, Any]], dict[str, Any]]


def load_handler(locator: str) -> Handler:
    module_name, separator, function_name = locator.partition(":")
    if not separator:
        raise ValueError("handler must use module:function syntax")
    function = getattr(importlib.import_module(module_name), function_name)
    if not callable(function):
        raise TypeError(f"handler is not callable: {locator}")
    return function


class ThreadedServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def request_handler(handler: Handler) -> type[socketserver.StreamRequestHandler]:
    class JsonRequestHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            raw = self.rfile.readline()
            request_id = None
            try:
                envelope = json.loads(raw.decode("utf-8"))
                request_id = envelope.get("request_id")
                if envelope.get("protocol_version") != "1.0":
                    raise ValueError("unsupported protocol version")
                response = handler(envelope)
                response.setdefault("protocol_version", "1.0")
                response.setdefault("request_id", request_id)
                response.setdefault("status", "completed")
            except Exception as error:
                response = {"protocol_version": "1.0", "request_id": request_id,
                            "status": "failed", "error": str(error)}
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")

    return JsonRequestHandler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handler", required=True, help="Python module:function that handles one request")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    handler = load_handler(args.handler)
    with ThreadedServer((args.host, args.port), request_handler(handler)) as server:
        print(json.dumps({"status": "ready", "host": args.host, "port": args.port,
                          "handler": args.handler}, ensure_ascii=False), flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
