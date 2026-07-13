"""Exercise per-scenario PLUS request packs and local-output adoption."""

from __future__ import annotations

import tempfile
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from plus_backend import adopt_existing_output, normalize_bridge_result, write_request_pack  # noqa: E402


def envelope(workspace: Path, scenario: str) -> dict[str, object]:
    output = workspace / f"PLUS_{scenario}.tif"
    return {"protocol_version": "1.0", "request_id": f"plus_{scenario}", "operation": "plus.run_scenario",
            "parameters": {"scenario": scenario, "workspace": str(workspace), "parameters": {
                "output_directory": str(workspace), "expected_output": str(output)}}}


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    os.environ["MINING_PLUS_OUTPUT_ROOT"] = str(root)
    nd = envelope(root / "ND", "ND")
    re = envelope(root / "RE", "RE")
    nd_pack, _ = write_request_pack(nd)
    re_pack, _ = write_request_pack(re)
    assert Path(nd_pack).name == "plus_local_request_ND.json"
    assert Path(re_pack).name == "plus_local_request_RE.json"
    assert Path(nd_pack) != Path(re_pack)
    output = root / "ND" / "PLUS_ND.tif"
    output.write_bytes(b"local plus output")
    result = adopt_existing_output(nd)
    assert result and result["status"] == "completed" and result["outputs"] == [str(output)]
    bridge_result = normalize_bridge_result(nd, {"status": "completed", "outputs": [str(output)]})
    assert bridge_result["status"] == "completed" and bridge_result["outputs"] == [str(output)]
    os.environ.pop("MINING_PLUS_OUTPUT_ROOT", None)
print('{"status":"completed","checks":["independent packs","local output takeover"]}')
