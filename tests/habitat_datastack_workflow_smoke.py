"""Compile a dated Carbon + auto-built Habitat Quality InVEST workflow."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_workflow import compile_workflow  # noqa: E402


def raster(path: Path, values: list[list[int]]) -> None:
    with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=1, dtype="int16",
                       crs="EPSG:32650", transform=from_origin(500000, 3700060, 30, 30), nodata=0) as sink:
        sink.write(np.asarray(values, dtype="int16"), 1)


with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as temporary:
    root = Path(temporary); data = root / "data"; data.mkdir()
    raster(data / "lulc_2000.tif", [[1, 2], [1, 2]])
    raster(data / "lulc_2005.tif", [[1, 2], [2, 1]])
    raster(data / "road.tif", [[0, 1], [1, 0]])
    (data / "carbon.csv").write_text(
        "lucode,c_above,c_below,c_soil,c_dead\n1,1,1,1,0\n2,2,1,1,0\n", encoding="utf-8")
    habitat = {
        "half_saturation_constant": 0.5,
        "threats": [{"name": "road", "raster": "road.tif", "max_distance_m": 1000, "weight": 1, "decay": "linear"}],
        "sensitivity": [{"lulc": 1, "habitat": 0.7, "threats": {"road": 0.2}},
                        {"lulc": 2, "habitat": 0.3, "threats": {"road": 0.8}}],
    }
    (data / "habitat.json").write_text(json.dumps(habitat), encoding="utf-8")
    project = {
        "schema_version": 2, "project_id": "dated-habitat", "task_type": "invest_only", "workspace": "runtime",
        "security": {"input_roots": ["data"], "output_root": "."},
        "inputs": {"historical_lulc_periods": [{"year": 2000, "path": "data/lulc_2000.tif"},
                                                    {"year": 2005, "path": "data/lulc_2005.tif"}],
                   "lulc_baseline": "data/lulc_2005.tif", "carbon_density": "data/carbon.csv", "imagery": [],
                   "driver_factors": {}},
        "classification": {"enabled": False}, "plus": {"enabled": False},
        "invest": {"enabled": True, "output_workspace": "outputs/invest", "models": {
            "carbon": {"enabled": True, "service_unit": "Mg C"},
            "habitat_quality": {"enabled": True, "datastack_builder": "data/habitat.json",
                                "service_unit": "index_0_to_1", "service_aggregation": "mean"},
        }},
        "subsidence_water": {"enabled": False}, "ecosystem_service": {"enabled": False},
        "gis_outputs": {"enabled": False}, "validation": {"enabled": False},
    }
    project_path = root / "project.json"; project_path.write_text(json.dumps(project), encoding="utf-8")
    result = compile_workflow(project_path)
    job = json.loads(Path(result["workflow_job"]).read_text(encoding="utf-8"))
    stages = {item["id"]: item for item in job["stages"]}
    expected = {
        "invest_carbon_2000", "invest_carbon_2005", "invest_habitat_quality_2000_datastack_builder",
        "invest_habitat_quality_2005_datastack_builder", "invest_habitat_quality_2000_input_contract",
        "invest_habitat_quality_2005_input_contract", "invest_habitat_quality_2000", "invest_habitat_quality_2005",
        "invest_multiperiod_summary",
    }
    assert expected.issubset(stages), sorted(stages)
    builder = stages["invest_habitat_quality_2000_datastack_builder"]
    assert "--lulc" in builder["command"] and any("LULC_2000.tif" in item for item in builder["command"])
    assert stages["invest_habitat_quality_2000"]["outputs"][0].endswith("quality_c.tif")
    summary = stages["invest_multiperiod_summary"]["command"]
    assert any("carbon_storage_t_c" in item for item in summary) and any("habitat_quality" in item for item in summary)

print('{"status":"completed","checks":["dated Habitat datastacks","Carbon-Habitat summary","auto quality output"]}')
