"""Build a real tiny Habitat Quality datastack and audit Carbon code coverage."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from carbon_density_contract import compare_codes  # noqa: E402
from invest_datastack_builder import build_habitat_quality_datastack  # noqa: E402
from invest_ecosystem_contract import validate  # noqa: E402
from spatial_preflight import validate as spatial_validate  # noqa: E402


def raster(path: Path, values: list[list[int]]) -> None:
    with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=1, dtype="int16",
                       crs="EPSG:32650", transform=from_origin(500000, 3700060, 30, 30), nodata=-9999) as sink:
        sink.write(np.array(values, dtype="int16"), 1)


with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as temporary:
    root = Path(temporary)
    lulc = root / "lulc.tif"; threat = root / "road.tif"
    raster(lulc, [[1, 2], [1, 2]]); raster(threat, [[1, 0], [0, 1]])
    carbon = root / "carbon.csv"
    with carbon.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(["lucode", "c_above", "c_below", "c_soil", "c_dead"])
        writer.writerows([[1, 1, 1, 1, 0], [2, 2, 2, 2, 0], [3, 3, 3, 3, 0]])
    config = {
        "lulc_path": str(lulc), "half_saturation_constant": 0.5,
        "threats": [{"name": "road", "raster": str(threat), "max_distance_m": 1000, "weight": 1, "decay": "linear"}],
        "sensitivity": [
            {"lulc": 1, "habitat": 0.8, "threats": {"road": 0.3}},
            {"lulc": 2, "habitat": 0.4, "threats": {"road": 0.7}},
            {"lulc": 3, "habitat": 0.2, "threats": {"road": 0.9}},
        ],
    }
    report = build_habitat_quality_datastack(config, root / "habitat")
    assert report["status"] == "completed", report
    assert Path(report["datastack"]).is_file() and Path(report["threats_table"]).is_file()
    assert any("absent from this raster" in item for item in report["warnings"]), report["warnings"]
    assert validate("habitat_quality", Path(report["datastack"]))["status"] == "completed"
    try:
        build_habitat_quality_datastack(config, root / "habitat")
    except FileExistsError:
        pass
    else:
        raise AssertionError("Habitat Quality builder overwrote outputs without confirmation")
    assert build_habitat_quality_datastack(config, root / "habitat", allow_overwrite=True)["status"] == "completed"

    coverage = compare_codes(lulc, carbon)
    assert coverage["status"] == "completed" and coverage["extra_carbon_codes"] == [3], coverage
    exact = compare_codes(lulc, carbon, require_exact_codes=True)
    assert exact["status"] == "failed" and exact["extra_carbon_codes"] == [3], exact
    missing = root / "carbon_missing.csv"
    missing.write_text("lucode,c_above,c_below,c_soil,c_dead\n1,1,1,1,0\n", encoding="utf-8")
    missing_report = compare_codes(lulc, missing)
    assert missing_report["status"] == "failed" and missing_report["missing_carbon_codes"] == [2], missing_report
    preflight = spatial_validate({"master": "lulc", "datasets": [{"name": "lulc", "path": str(lulc), "kind": "lulc", "allowed_codes": [1, 2]}],
                                  "carbon_density": str(carbon)})
    assert preflight["status"] == "completed" and preflight["carbon_density"]["lulc"]["extra_carbon_codes"] == [3], preflight

    # The local backend can construct/validate contracts without a licensed
    # InVEST executable; only actual model execution requires that software.
    backend_workspace = ROOT / "outputs" / "mcp" / "invest_datastack_backend_smoke"
    shutil.rmtree(backend_workspace, ignore_errors=True)
    request = {"protocol_version": "1.0", "request_id": "hq-builder-smoke", "operation": "invest.build_habitat_datastack",
               "parameters": {"habitat_config": config, "workspace": str(backend_workspace)}}
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "local_backend.py"), "--backend", "invest"],
                             input=json.dumps(request), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert process.returncode == 0, process.stderr
    backend = json.loads(process.stdout)
    assert backend["status"] == "completed", backend

    bad_stack = root / "bad_carbon_datastack.json"
    bad_stack.write_text(json.dumps({"model_name": "natcap.invest.carbon", "args": {
        "lulc_cur_path": str(lulc), "carbon_pools_path": str(missing),
    }}), encoding="utf-8")
    carbon_request = {"protocol_version": "1.0", "request_id": "carbon-coverage-smoke", "operation": "invest.run_carbon",
                      "parameters": {"datastack": str(bad_stack), "workspace": str(backend_workspace)}}
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "local_backend.py"), "--backend", "invest"],
                             input=json.dumps(carbon_request), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert process.returncode == 0, process.stderr
    carbon_backend = json.loads(process.stdout)
    assert carbon_backend["status"] == "failed" and carbon_backend["result"]["input_contract"]["missing_carbon_codes"] == [2], carbon_backend

print('{"status":"completed","checks":["Habitat datastack build","Habitat contract","Carbon code coverage","local InVEST builder backend","Carbon run preflight"]}')
