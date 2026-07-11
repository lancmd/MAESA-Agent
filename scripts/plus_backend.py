#!/usr/bin/env python3
"""Local-only PLUS bridge wrapper.

The configured bridge reads one protocol envelope from standard input and emits one
protocol response on standard output.  The repository does not infer a PLUS GUI or
command-line interface: a locally installed PLUS version needs an explicit bridge.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VALID_STATUSES = {"accepted", "running", "completed", "prepared", "pending_validation", "waiting_interactive", "failed", "cancelled"}


def response(envelope: dict[str, Any], status: str, **values: Any) -> dict[str, Any]:
    return {"protocol_version": "1.0", "request_id": envelope.get("request_id"), "status": status, **values}


def bridge_command() -> list[str]:
    value = os.getenv("MINING_PLUS_BRIDGE_COMMAND", "").strip()
    if not value:
        configured = Path(os.getenv("MINING_GIS_LOCAL_PATHS", ROOT / "config" / "local_paths.json")).expanduser()
        if configured.exists():
            payload = json.loads(configured.read_text(encoding="utf-8-sig"))
            command = payload.get("plus_bridge_command", [])
            if isinstance(command, list) and all(isinstance(item, str) and item for item in command):
                return [os.path.expandvars(item) for item in command]
    if not value:
        return []
    if value.startswith("["):
        parsed = json.loads(value)
        if not isinstance(parsed, list) or not all(isinstance(item, str) and item for item in parsed):
            raise ValueError("MINING_PLUS_BRIDGE_COMMAND JSON value must be a non-empty command array")
        return parsed
    return shlex.split(value, posix=False)


def write_request_pack(envelope: dict[str, Any]) -> str:
    parameters = envelope.get("parameters", {})
    workspace = Path(parameters.get("workspace", ROOT / "outputs" / "plus_prepared")).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    pack = workspace / "plus_local_request.json"
    pack.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(pack)


def main() -> int:
    envelope: dict[str, Any] = {}
    try:
        envelope = json.load(sys.stdin)
        operation = envelope.get("operation")
        if envelope.get("protocol_version") != "1.0":
            result = response(envelope, "failed", error="unsupported protocol version")
        elif operation == "system.capabilities":
            command = bridge_command()
            result = response(envelope, "completed", result={
                "backend": "plus", "mode": "local-command-bridge", "local_only": True,
                "bridge_configured": bool(command),
                "operations": ["system.capabilities", "plus.run_scenario"],
            })
        elif operation != "plus.run_scenario":
            result = response(envelope, "failed", error=f"unsupported PLUS operation: {operation}")
        else:
            command = bridge_command()
            if not command:
                pack = write_request_pack(envelope)
                result = response(envelope, "prepared", outputs=[pack],
                                  message="local PLUS bridge is not configured; task pack is ready for the installed PLUS version")
            else:
                process = subprocess.run(command, input=json.dumps(envelope, ensure_ascii=True), text=True,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                                         errors="replace", timeout=3600, check=False)
                if process.returncode:
                    result = response(envelope, "failed", error=process.stderr.strip() or f"local PLUS bridge returned {process.returncode}")
                else:
                    result = json.loads(process.stdout)
                    if result.get("status") not in VALID_STATUSES:
                        raise ValueError("local PLUS bridge returned an unsupported status")
                    result.setdefault("protocol_version", "1.0")
                    result.setdefault("request_id", envelope.get("request_id"))
    except Exception as error:
        result = response(envelope, "failed", error=str(error))
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
