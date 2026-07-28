"""Ensure dated ENVI classifications carry executable sensor-profile contracts."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_builder import build  # noqa: E402
from project_validator import validate  # noqa: E402
from project_workflow import compile_workflow  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    roi = root / "training.gpkg"; roi.write_bytes(b"roi")
    periods = []
    for year, sensor, method in (
        (2000, "Landsat 5", "maximum_likelihood"),
        (2015, "landsat_8_oli", "minimum_distance"),
        (2025, "Sentinel-2", "maximum_likelihood"),
    ):
        image = root / f"image_{year}.tif"; image.write_bytes(b"image")
        periods.append({"year": year, "path": str(image), "sensor": sensor, "envi_method": method})
    project_file = root / "project.json"
    build(project_file, "sensor-profiles", "runtime", task_type="classification_only",
          imagery_periods=periods, training_roi=str(roi), scheme="standard_6class")
    project = json.loads(project_file.read_text(encoding="utf-8"))
    assert [item["sensor"] for item in project["inputs"]["imagery_periods"]] == [
        "landsat_5_tm", "landsat_8_oli", "sentinel_2_msi"]
    assert [item["envi_method"] for item in project["inputs"]["imagery_periods"]] == [
        "maximum_likelihood", "minimum_distance", "maximum_likelihood"]
    assert validate(project_file)["status"] == "valid", validate(project_file)

    compiled = compile_workflow(project_file)
    job = json.loads(Path(compiled["workflow_job"]).read_text(encoding="utf-8"))
    stages = {item["id"]: item for item in job["stages"]}
    expected = {
        2000: ("landsat_5_tm", "maximum_likelihood", "SR_B7"),
        2015: ("landsat_8_oli", "minimum_distance", "SR_B7"),
        2025: ("sentinel_2_msi", "maximum_likelihood", "B12"),
    }
    classification_ids = [item["id"] for item in job["stages"] if item["id"].startswith("classification_envi_")]
    assert classification_ids == ["classification_envi_2000", "classification_envi_2015", "classification_envi_2025"]
    for year, (sensor_id, method, last_band) in expected.items():
        stage = stages[f"classification_envi_{year}"]
        profile = stage["classification_profile"]
        profile_file = Path(stage["env"]["MINING_CLASSIFICATION_PROFILE"])
        assert profile["sensor_id"] == sensor_id
        assert profile["classification_method"]["method"] == method
        assert profile["source_bands"][-1] == last_band
        assert profile_file.is_file() and json.loads(profile_file.read_text(encoding="utf-8")) == profile
        assert str(profile_file) in stage["inputs"]
        assert ("envi_minimum_distance.pro" in stage["batch_file"]) == (method == "minimum_distance")

    invalid = json.loads(json.dumps(project))
    invalid["inputs"]["imagery_periods"][1]["sensor"] = "MODIS"
    invalid_file = root / "invalid_sensor.json"; invalid_file.write_text(json.dumps(invalid), encoding="utf-8")
    invalid_report = validate(invalid_file)
    assert invalid_report["status"] == "invalid"
    assert any("unsupported sensor" in error for error in invalid_report["errors"]), invalid_report

print('{"status":"completed","checks":["dated Landsat/Sentinel profiles","ENVI profile artifact","sensor validation"]}')
