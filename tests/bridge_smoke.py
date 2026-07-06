"""Verify one complete socket bridge request and response."""

from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bridge_server import ThreadedServer, request_handler  # noqa: E402


def echo(envelope: dict) -> dict:
    return {"status": "completed", "result": envelope["parameters"]}


server = ThreadedServer(("127.0.0.1", 0), request_handler(echo))
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    envelope = {"protocol_version": "1.0", "request_id": "bridge-smoke",
                "operation": "test.echo", "parameters": {"value": 42}}
    with socket.create_connection(server.server_address, timeout=5) as client:
        client.sendall(json.dumps(envelope).encode("utf-8") + b"\n")
        response = json.loads(client.makefile("r", encoding="utf-8").readline())
    assert response["status"] == "completed"
    assert response["request_id"] == "bridge-smoke"
    assert response["result"]["value"] == 42
    print(json.dumps(response))
finally:
    server.shutdown()
    server.server_close()
