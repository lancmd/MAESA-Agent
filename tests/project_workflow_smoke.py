"""Check that one local project can be compiled without maintaining workflow_job.json by hand."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_workflow import compile_workflow  # noqa: E402


project = ROOT / "tests" / "fixtures" / "local_project" / "project.json"
output = ROOT / "outputs" / "project_workflow_smoke" / "workflow_job.json"
report = compile_workflow(project, output)
job = json.loads(output.read_text(encoding="utf-8"))
assert job["schema_version"] == 1
assert "classification_pytorch" in report["stage_ids"]
assert "invest_carbon" in report["stage_ids"]
print(json.dumps(report, ensure_ascii=False))
