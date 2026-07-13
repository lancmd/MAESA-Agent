"""Verify workflow output boundaries and provenance artefacts."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from workflow_agent import JobRunner  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    inputs = root / "inputs"; inputs.mkdir(); source = inputs / "source.txt"; source.write_text("source", encoding="utf-8")
    workspace = root / "workspace"; result = workspace / "outputs" / "result.txt"
    job_file = root / "job.json"
    job = {"schema_version": 1, "project_id": "manifest-safety", "workspace": str(workspace),
           "security": {"input_roots": [str(inputs)], "output_root": str(workspace)}, "software": {}, "stages": [{
               "id": "write_result", "adapter": "command", "enabled": True,
               "command": [sys.executable, "-c", "from pathlib import Path; Path('outputs/result.txt').parent.mkdir(parents=True, exist_ok=True); Path('outputs/result.txt').write_text('ok')"],
               "inputs": [str(source)], "outputs": [str(result)], "depends_on": []}]}
    job_file.write_text(json.dumps(job), encoding="utf-8")
    runner = JobRunner(job_file); assert runner.run() == 0
    manifest = json.loads((workspace / "outputs_manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"][0]["sha256"] and manifest["artifacts"][0]["bytes"] == 2
    provenance = json.loads((workspace / "provenance.json").read_text(encoding="utf-8"))
    assert any(item["path"] == str(source.resolve()) and item["sha256"] for item in provenance["inputs"])
    unsafe = dict(job["stages"][0]); unsafe["outputs"] = [str(root / "escape.txt")]
    assert any("outside the allowed" in issue for issue in runner.validate_stage(unsafe))
print('{"status":"completed","checks":["manifest","provenance","output boundary"]}')
