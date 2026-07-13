"""A resumed GUI hand-off must reuse a live PLUS PID instead of launching again."""

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
    executable = root / "renamed_vendor_binary.exe"
    executable.write_bytes(b"local test executable")
    workspace = root / "outputs" / "plus" / "ND"
    workspace.mkdir(parents=True)
    expected = workspace / "PLUS_ND.tif"
    (workspace / "plus_execution_state.json").write_text(json.dumps({
        "scenario": "ND", "status": "waiting_interactive", "bridge": "plus_v141_gui_handoff", "process_id": os.getpid(),
    }), encoding="utf-8")
    envelope = {"protocol_version": "1.0", "request_id": "reuse", "operation": "plus.run_scenario",
                "parameters": {"scenario": "ND", "workspace": str(workspace),
                               "parameters": {"output_directory": str(workspace), "expected_output": str(expected)}}}
    env = os.environ.copy()
    env.update({"PLUS_V141_EXECUTABLE": str(executable), "PLUS_V141_VERSION": "PLUS V1.4.1",
                "MINING_GIS_LOCAL_PATHS": str(root / "absent.json"), "MINING_PLUS_OUTPUT_ROOT": str(root)})
    process = subprocess.run([sys.executable, str(BRIDGE)], input=json.dumps(envelope), text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=False)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["status"] == "waiting_interactive" and result["process_id"] == os.getpid(), result
    assert not expected.exists()

print('{"status":"completed","checks":["renamed executable accepted by version declaration","live GUI session reused"]}')
