"""Validate the documented PLUS V1.4.1 GUI hand-off without launching a GUI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "scripts" / "plus_v141_bridge.py"


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    executable = root / "PLUS v1.4.1_boxed.exe"
    executable.write_bytes(b"test executable placeholder")
    workspace = root / "workspace" / "outputs" / "plus" / "ND"
    expected = workspace / "PLUS_ND.tif"
    envelope = {
        "protocol_version": "1.0",
        "request_id": "v141_nd",
        "operation": "plus.run_scenario",
        "parameters": {
            "scenario": "ND",
            "workspace": str(workspace),
            "dry_run": True,
            "parameters": {"output_directory": str(workspace), "expected_output": str(expected)},
        },
    }
    env = os.environ.copy()
    env["PLUS_V141_EXECUTABLE"] = str(executable)
    env["MINING_PLUS_OUTPUT_ROOT"] = str(root)
    process = subprocess.run([sys.executable, str(BRIDGE)], input=json.dumps(envelope), text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=False)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["status"] == "prepared", result
    handoff = workspace / "plus_v141_gui_handoff_ND.json"
    state = workspace / "plus_execution_state.json"
    assert handoff.is_file() and state.is_file()
    metadata = json.loads(handoff.read_text(encoding="utf-8"))
    state_payload = json.loads(state.read_text(encoding="utf-8"))
    assert metadata["launch_command"] == [str(executable)]
    assert metadata["launch_arguments"] == []
    assert metadata["expected_output"] == str(expected)
    assert state_payload["status"] == "prepared"

print('{"status":"completed","checks":["V1.4.1 GUI hand-off","no invented CLI arguments","scenario manifest"]}')
