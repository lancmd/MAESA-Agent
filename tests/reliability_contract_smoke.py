"""Exercise regressions fixed in the local workflow reliability pass."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analysis_validation import validate_results  # noqa: E402
from ecosystem_service import scenario_compare  # noqa: E402
from job_manager import outputs, status, submit  # noqa: E402
from project_validator import validate  # noqa: E402
from project_workflow import compile_workflow  # noqa: E402
from scenario_service_table import build  # noqa: E402
from workflow_agent import JobRunner  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    baseline = root / "provided_lulc.tif"; baseline.write_bytes(b"placeholder")
    project = {
        "schema_version": 2, "project_id": "provided-lulc", "workspace": str(root / "runtime"),
        "security": {"input_roots": [str(root)], "output_root": str(root / "runtime")},
        "inputs": {"lulc_baseline": str(baseline)},
        "classification": {"enabled": True, "engine": "provided_lulc", "scheme": "standard_6class"},
        "plus": {"enabled": False}, "invest": {"enabled": False}, "subsidence_water": {"enabled": False},
        "ecosystem_service": {"enabled": False}, "gis_outputs": {"enabled": False}, "validation": {"enabled": False},
    }
    project_file = root / "project.json"; project_file.write_text(json.dumps(project), encoding="utf-8")
    assert validate(project_file)["status"] == "valid"
    compiled = compile_workflow(project_file)
    assert "lulc_output_validation" in compiled["stage_ids"] and "classification_pytorch" not in compiled["stage_ids"]

    invalid_evidence = root / "invalid_evidence.json"
    invalid_evidence.write_text(json.dumps({"schema_version": 1, "required_sections": ["ecosystem"], "reports": {
        "ecosystem": {"method": "minmax", "normalised_ranges": {"service": [0, 1]}, "sensitivity": {"available": False}}}}), encoding="utf-8")
    assert validate_results(invalid_evidence)["status"] == "failed"

    direct_lulc = root / "direct_lulc.json"
    direct_lulc.write_text(json.dumps({"schema_version": 1, "required_sections": ["lulc"], "reports": {
        "lulc": {"oa": 1.0, "f1": 1.0, "iou": 1.0, "classes": {"1": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "iou": 1.0}}}}}), encoding="utf-8")
    assert validate_results(direct_lulc)["status"] == "completed"

    raster_a, raster_b = root / "a.tif", root / "b.tif"
    profile = {"driver": "GTiff", "width": 4, "height": 4, "count": 1, "dtype": "float32", "crs": "EPSG:32650",
               "transform": from_origin(500000, 3700000, 10, 10), "nodata": -9999.0}
    for path, value in ((raster_a, 1.0), (raster_b, 2.0)):
        with rasterio.open(path, "w", **profile) as sink:
            sink.write(np.full((1, 4, 4), value, dtype="float32"))
    table, geometry = root / "services.csv", root / "units.geojson"
    spatial = build({"ND": {"carbon": raster_a}, "UD": {"carbon": raster_b}}, None, table,
                    grid_cell_pixels=2, service_units={"carbon": "Mg C"}, grid_geometry=geometry)
    assert spatial["aggregation"] == "sum_of_valid_pixel_values" and geometry.is_file()
    assert len(json.loads(geometry.read_text(encoding="utf-8"))["features"]) == 4

    scores = root / "scores.csv"
    with scores.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["scenario", "unit_id", "score"]); writer.writeheader()
        writer.writerows([{"scenario": "ND", "unit_id": "a", "score": 1}, {"scenario": "ND", "unit_id": "b", "score": 2},
                          {"scenario": "UD", "unit_id": "a", "score": 2}, {"scenario": "UD", "unit_id": "b", "score": 4}])
    comparison = root / "comparison.csv"
    scenario_compare(scores, "scenario", "ND", ["score"], comparison, "unit_id")
    rows = list(csv.DictReader(comparison.open(encoding="utf-8-sig")))
    assert next(row for row in rows if row["scenario"] == "UD")["paired_unit_count"] == "2"

    workspace = root / "jobs"; source = root / "source.txt"; source.write_text("source", encoding="utf-8")
    artifact = workspace / "outputs" / "artifact.txt"; job_file = root / "workflow_job.json"
    job_file.write_text(json.dumps({"schema_version": 1, "project_id": "output-artifacts", "workspace": str(workspace),
        "security": {"input_roots": [str(root)], "output_root": str(workspace)}, "software": {}, "stages": [{
            "id": "write", "adapter": "command", "enabled": True, "inputs": [str(source)], "outputs": [str(artifact)],
            "command": [sys.executable, "-c", "from pathlib import Path; Path('outputs').mkdir(exist_ok=True); Path('outputs/artifact.txt').write_text('ok')"], "depends_on": []}]}), encoding="utf-8")
    record = submit(job_file)
    for _ in range(100):
        current = status(record["job_id"])
        if current["status"] != "running":
            break
        time.sleep(0.05)
    listed = outputs(record["job_id"])
    assert listed["status"] == "completed" and listed["outputs"] and listed["outputs"][0]["path"] == str(artifact.resolve())

    retry_workspace = root / "retry"; retry_output = retry_workspace / "outputs" / "retry.txt"; retry_job = root / "retry_job.json"
    retry_job.write_text(json.dumps({"schema_version": 1, "project_id": "retry", "workspace": str(retry_workspace),
        "security": {"input_roots": [str(root)], "output_root": str(retry_workspace)}, "software": {}, "stages": [{
            "id": "retry_once", "adapter": "command", "enabled": True, "inputs": [], "outputs": [str(retry_output)], "retries": 1,
            "command": [sys.executable, "-c", "from pathlib import Path; p=Path('retry.marker'); (Path('outputs').mkdir(exist_ok=True), Path('outputs/retry.txt').write_text('ok')) if p.exists() else (p.write_text('1'), (_ for _ in ()).throw(SystemExit(1)))"], "depends_on": []}]}), encoding="utf-8")
    assert JobRunner(retry_job).run() == 0
    retry_state = json.loads((retry_workspace / "agent_state.json").read_text(encoding="utf-8"))
    assert retry_state["stages"]["retry_once"]["attempts"] == 2

    timeout_workspace = root / "timeout"; timeout_job = root / "timeout_job.json"
    timeout_job.write_text(json.dumps({"schema_version": 1, "project_id": "timeout", "workspace": str(timeout_workspace),
        "security": {"input_roots": [str(root)], "output_root": str(timeout_workspace)}, "software": {}, "stages": [{
            "id": "timeout", "adapter": "command", "enabled": True, "inputs": [], "outputs": [], "timeout_seconds": 0.05,
            "command": [sys.executable, "-c", "import time; time.sleep(0.2)"], "depends_on": []}]}), encoding="utf-8")
    timeout_runner = JobRunner(timeout_job)
    assert timeout_runner.run() == 1
    assert timeout_runner.state["stages"]["timeout"]["status"] == "failed"

    lock_workspace = root / "lock"; lock_job = root / "lock_job.json"
    lock_job.write_text(json.dumps({"schema_version": 1, "project_id": "lock", "workspace": str(lock_workspace),
        "security": {"input_roots": [str(root)], "output_root": str(lock_workspace)}, "software": {}, "stages": [{
            "id": "wait", "adapter": "command", "enabled": True, "inputs": [], "outputs": [],
            "command": [sys.executable, "-c", "import time; time.sleep(0.4)"], "depends_on": []}]}), encoding="utf-8")
    active = submit(lock_job)
    try:
        submit(lock_job)
        raise AssertionError("same-workspace concurrent job was accepted")
    except RuntimeError:
        pass
    for _ in range(100):
        current = status(active["job_id"])
        if current["status"] != "running":
            break
        time.sleep(0.05)
    assert current["status"] == "completed"

print('{"status":"completed","checks":["provided-lulc","sensitivity","LULC evidence","grid geometry","paired comparison","artifact outputs","retry","timeout","workspace lock"]}')
