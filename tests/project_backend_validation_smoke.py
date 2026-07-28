"""Ensure project construction returns the validator result in the same MCP response."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    image, roi = root / "image.tif", root / "roi.gpkg"
    image.write_bytes(b"fixture")
    roi.write_bytes(b"fixture")
    envelope = {"operation": "project.build_from_inputs", "parameters": {
        "output_project": str(root / "project.json"), "project_id": "backend-validation", "workspace": "runtime",
        "task_type": "classification_only", "imagery_periods": [{"year": 2025, "path": str(image), "sensor": "sentinel_2_msi"}],
        "training_roi": str(roi),
    }}
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "project_backend.py")], input=json.dumps(envelope),
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    assert process.returncode == 0, process.stdout
    result = json.loads(process.stdout)
    assert result["status"] == "completed", result
    assert result["result"]["project_validation"]["status"] == "valid", result

    periods = []
    for year in (2020, 2025):
        image = root / f"image_{year}.tif"; image.write_bytes(b"fixture")
        dated_roi = root / f"roi_{year}.gpkg"; dated_roi.write_bytes(b"fixture")
        samples = root / f"samples_{year}.csv"; samples.write_text("reference,x,y\n1,500015,3701905\n", encoding="utf-8")
        periods.append({"year": year, "path": str(image),
                        "sensor": "landsat_8_oli" if year == 2020 else "sentinel_2_msi", "roi": str(dated_roi),
                        "accuracy": {"validation_samples": str(samples), "x_field": "x", "y_field": "y",
                                     "samples_crs": "EPSG:32650"}})
    carbon = root / "carbon.csv"
    carbon.write_text("lucode,c_above,c_below,c_soil,c_dead\n1,1,1,1,0\n", encoding="utf-8")
    dated = {"operation": "project.build_from_inputs", "parameters": {
        "output_project": str(root / "classification_invest.json"), "project_id": "backend-classification-invest",
        "workspace": "runtime-classification-invest", "task_type": "classification_invest",
        "imagery_periods": periods, "carbon_density": str(carbon),
    }}
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "project_backend.py")], input=json.dumps(dated),
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    assert process.returncode == 0, process.stdout
    result = json.loads(process.stdout)
    assert result["status"] == "completed", result
    assert result["result"]["project_validation"]["status"] == "valid", result

print('{"status":"completed","checks":["build invokes full project validation","classification_invest backend inputs"]}')
