"""Opt-in acceptance run for an owner-supplied six-period classification/InVEST project.

Set only ``MAESA_REAL_SIX_PERIOD_PROJECT`` to an absolute or user-relative
``project.json`` path.  The project itself declares all local data paths and
software configuration; this test never embeds a workstation-specific path.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_validator import validate  # noqa: E402
from project_workflow import compile_workflow  # noqa: E402
from workflow_agent import JobRunner  # noqa: E402


raw_project = os.getenv("MAESA_REAL_SIX_PERIOD_PROJECT")
if not raw_project:
    print(json.dumps({"status": "completed", "execution": "skipped",
                      "reason": "set MAESA_REAL_SIX_PERIOD_PROJECT to run a local six-period acceptance project"}))
    raise SystemExit(0)

project_path = Path(raw_project).expanduser().resolve()
project = json.loads(project_path.read_text(encoding="utf-8-sig"))
assert project.get("task_type") == "classification_invest", project.get("task_type")
periods = project.get("inputs", {}).get("imagery_periods", [])
assert isinstance(periods, list) and len(periods) == 6, "acceptance project must declare exactly six dated imagery periods"
for index, period in enumerate(periods):
    assert isinstance(period, dict) and (period.get("training_roi") or period.get("roi")), f"period {index} lacks a dated ROI"
    accuracy = period.get("accuracy") if isinstance(period, dict) else None
    assert isinstance(accuracy, dict) and accuracy.get("enabled") and accuracy.get("validation_samples"), f"period {index} lacks independent validation"
    assert all(accuracy.get(key) for key in ("x_field", "y_field", "samples_crs")), \
        f"period {index} lacks raster-sampled validation coordinates/CRS"
models = project.get("invest", {}).get("models", {})
assert isinstance(models, dict) and models.get("carbon", {}).get("enabled"), "Carbon must be enabled"
assert models.get("habitat_quality", {}).get("enabled"), "Habitat Quality must be enabled"
report = validate(project_path)
assert report["status"] == "valid", report
compiled = compile_workflow(project_path)
compiled_job = json.loads(Path(compiled["workflow_job"]).read_text(encoding="utf-8"))
compiled_stages = {item["id"]: item for item in compiled_job["stages"]}
for year in (int(item["year"]) for item in periods):
    accuracy_command = compiled_stages[f"lulc_accuracy_{year}"]["command"]
    assert "--classification-raster" in accuracy_command and "--require-raster-sampling" in accuracy_command, accuracy_command
runner = JobRunner(Path(compiled["workflow_job"]), confirm_overwrite=False)
assert runner.run() == 0
state = json.loads(runner.state_path.read_text(encoding="utf-8"))
assert state.get("workflow", {}).get("status") == "completed", state
for year in (int(item["year"]) for item in periods):
    for stage_id in (f"classification_envi_{year}", f"lulc_accuracy_{year}",
                     f"invest_carbon_{year}", f"invest_habitat_quality_{year}"):
        record = state.get("stages", {}).get(stage_id, {})
        assert record.get("status") == "completed", (stage_id, record)
for name in ("outputs_manifest.json", "provenance.json", "validation_summary.json"):
    assert (runner.workspace / name).is_file(), name
print(json.dumps({"status": "completed", "project": str(project_path), "workspace": str(runner.workspace)}, ensure_ascii=False))
