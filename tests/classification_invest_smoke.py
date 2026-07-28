"""Compile a dated ENVI classification-to-InVEST project without PLUS."""

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


with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as temporary:
    root = Path(temporary)
    data = root / "data"; data.mkdir()
    periods: list[dict[str, object]] = []
    for year in (2000, 2005):
        image = data / f"image_{year}.tif"; image.write_bytes(b"image")
        roi = data / f"roi_{year}.gpkg"; roi.write_bytes(b"roi")
        samples = data / f"samples_{year}.csv"
        # No table-side prediction is supplied: the compiled accuracy stage
        # must sample its immediately generated LULC raster at x/y.
        samples.write_text("reference,x,y\n1,500015,3701905\n2,500045,3701875\n", encoding="utf-8")
        periods.append({"year": year, "path": str(image),
                        "sensor": "landsat_5_tm" if year == 2000 else "landsat_8_oli",
                        "roi": str(roi), "accuracy": {
            "validation_samples": str(samples), "reference_field": "reference", "x_field": "x", "y_field": "y",
            "samples_crs": "EPSG:32650",
        }})
    carbon = data / "carbon.csv"
    carbon.write_text("lucode,c_above,c_below,c_soil,c_dead\n1,1,1,1,0\n", encoding="utf-8")
    threat = data / "road_threat.tif"; threat.write_bytes(b"threat")
    habitat = data / "habitat_builder.json"
    habitat.write_text(json.dumps({"half_saturation_constant": 0.5,
                                   "threats": [{"name": "road", "raster": str(threat), "max_distance_m": 1000,
                                                "weight": 1.0, "decay": "linear"}],
                                   "sensitivity": [{"lulc": 1, "habitat": 0.8, "threats": {"road": 0.3}}]}), encoding="utf-8")
    project_file = root / "project.json"
    report = build(project_file, "classification-invest", "runtime", task_type="classification_invest",
                   imagery_periods=periods, carbon_density=str(carbon), invest_models={
                       "carbon": {"enabled": True, "service_unit": "Mg C"},
                       "habitat_quality": {"enabled": True, "datastack_builder": str(habitat), "service_unit": "index_0_to_1",
                                           "service_aggregation": "mean"},
                   })
    assert report["pending_inputs"] == [], report
    project = json.loads(project_file.read_text(encoding="utf-8"))
    assert project["task_type"] == "classification_invest"
    assert project["classification"]["enabled"] and project["invest"]["enabled"]
    assert not project["plus"]["enabled"]
    assert [item["training_roi"] for item in project["inputs"]["imagery_periods"]] == [
        str((data / "roi_2000.gpkg").resolve()), str((data / "roi_2005.gpkg").resolve())]
    assert validate(project_file)["status"] == "valid", validate(project_file)
    missing_accuracy = json.loads(json.dumps(project))
    missing_accuracy["inputs"]["imagery_periods"][1].pop("accuracy")
    missing_file = root / "missing_accuracy.json"; missing_file.write_text(json.dumps(missing_accuracy), encoding="utf-8")
    missing_report = validate(missing_file)
    assert missing_report["status"] == "invalid"
    assert any("classification_invest requires imagery_periods[1].accuracy" in error for error in missing_report["errors"]), missing_report
    compiled = compile_workflow(project_file)
    job = json.loads(Path(compiled["workflow_job"]).read_text(encoding="utf-8"))
    stages = {item["id"]: item for item in job["stages"]}
    expected = {"classification_envi_2000", "classification_envi_2005", "lulc_accuracy_2000", "lulc_accuracy_2005",
                "invest_carbon_2000", "invest_carbon_2005", "invest_habitat_quality_2000", "invest_habitat_quality_2005"}
    assert expected.issubset(stages), sorted(stages)
    assert {"invest_habitat_quality_2000_datastack_builder", "invest_habitat_quality_2005_datastack_builder"}.issubset(stages)
    assert stages["classification_envi_2000"]["env"]["MINING_TRAINING_VECTOR"].endswith("roi_2000.gpkg")
    assert stages["classification_envi_2005"]["env"]["MINING_TRAINING_VECTOR"].endswith("roi_2005.gpkg")
    assert stages["classification_envi_2000"]["classification_profile"]["sensor_id"] == "landsat_5_tm"
    assert stages["classification_envi_2005"]["classification_profile"]["sensor_id"] == "landsat_8_oli"
    for stage_id in ("classification_envi_2000", "classification_envi_2005"):
        profile = Path(stages[stage_id]["env"]["MINING_CLASSIFICATION_PROFILE"])
        assert profile.is_file() and json.loads(profile.read_text(encoding="utf-8"))["sensor_id"] == stages[stage_id]["classification_profile"]["sensor_id"]
        assert str(profile) in stages[stage_id]["inputs"]
    assert any(path.endswith("samples_2000.csv") for path in stages["lulc_accuracy_2000"]["inputs"])
    assert any(path.endswith("samples_2005.csv") for path in stages["lulc_accuracy_2005"]["inputs"])
    command = stages["lulc_accuracy_2000"]["command"]
    assert "--classification-raster" in command and "--require-raster-sampling" in command, command
    assert command[command.index("--classification-raster") + 1].endswith("LULC_2000.tif"), command
    assert command[command.index("--samples-crs") + 1] == "EPSG:32650", command
    assert command.count("--samples-crs") == 1, command
    assert "--require-training-only" in stages["roi_quality_2000"]["command"]
    assert any(path.endswith("roi_2000.gpkg") for path in stages["spatial_preflight"]["inputs"])
    assert any(path.endswith("roi_2005.gpkg") for path in stages["spatial_preflight"]["inputs"])
    assert stages["lulc_accuracy_2000"]["outputs"][0].endswith("lulc_accuracy_2000.json")
    assert stages["lulc_accuracy_2005"]["outputs"][0].endswith("lulc_accuracy_2005.json")
    assert stages["lulc_accuracy_2000"]["outputs"] != stages["lulc_accuracy_2005"]["outputs"]

    missing_coordinates = json.loads(json.dumps(project))
    missing_coordinates["inputs"]["imagery_periods"][0]["accuracy"].pop("x_field")
    missing_coordinates_file = root / "missing_coordinates.json"
    missing_coordinates_file.write_text(json.dumps(missing_coordinates), encoding="utf-8")
    coordinate_report = validate(missing_coordinates_file)
    assert coordinate_report["status"] == "invalid"
    assert any("x_field is required for raster-sampled independent accuracy" in error for error in coordinate_report["errors"]), coordinate_report

    same_sample_file = json.loads(json.dumps(project))
    same_sample_file["inputs"]["imagery_periods"][1]["accuracy"]["validation_samples"] = str(data / "samples_2000.csv")
    same_sample_path = root / "same_sample_file.json"; same_sample_path.write_text(json.dumps(same_sample_file), encoding="utf-8")
    same_sample_report = validate(same_sample_path)
    assert same_sample_report["status"] == "invalid"
    assert any("distinct validation_samples file" in error for error in same_sample_report["errors"]), same_sample_report

    mixed_source = json.loads(json.dumps(project))
    mixed_source["inputs"]["imagery_periods"][0]["accuracy"]["validation_samples"] = str(data / "roi_2000.gpkg")
    mixed_source_path = root / "mixed_source.json"; mixed_source_path.write_text(json.dumps(mixed_source), encoding="utf-8")
    mixed_source_report = validate(mixed_source_path)
    assert mixed_source_report["status"] == "invalid"
    assert any("same file for training_roi and validation_samples" in error for error in mixed_source_report["errors"]), mixed_source_report

    caller_raster = json.loads(json.dumps(project))
    caller_raster["inputs"]["imagery_periods"][0]["accuracy"]["classification_raster"] = "outputs/old_lulc.tif"
    caller_raster_path = root / "caller_raster.json"; caller_raster_path.write_text(json.dumps(caller_raster), encoding="utf-8")
    caller_raster_report = validate(caller_raster_path)
    assert caller_raster_report["status"] == "invalid"
    assert any("is assigned by the generated classification stage" in error for error in caller_raster_report["errors"]), caller_raster_report

print('{"status":"completed","checks":["classification_invest","per-period ROI","per-period accuracy","per-period InVEST"]}')
