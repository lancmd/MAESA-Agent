"""Exercise readable Carbon and Habitat Quality parameter reports."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]


def raster(path: Path, values: list[list[int]]) -> None:
    with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=1, dtype="int16",
                       crs="EPSG:32650", transform=from_origin(500000, 3700060, 30, 30), nodata=0) as sink:
        sink.write(np.asarray(values, dtype="int16"), 1)


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    lulc = root / "lulc.tif"; raster(lulc, [[1, 2], [1, 2]])
    threat = root / "road.tif"; raster(threat, [[1, 0], [0, 1]])
    carbon = root / "carbon.csv"
    carbon.write_text("lucode,c_above,c_below,c_soil,c_dead\n1,10,2,30,0\n2,20,3,40,0\n", encoding="utf-8")
    carbon_stack = root / "carbon.json"
    carbon_stack.write_text(json.dumps({"args": {"lulc_cur_path": str(lulc), "carbon_pools_path": str(carbon)}}), encoding="utf-8")
    carbon_report = root / "carbon.md"
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "invest_parameter_report.py"),
                             "--model", "carbon", "--datastack", str(carbon_stack), "--output", str(carbon_report)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr
    text = carbon_report.read_text(encoding="utf-8")
    assert "Carbon density source: user supplied CSV" in text and "Unit: Mg C/ha" in text and "Status: **PASS**" in text, text

    threats = root / "threats.csv"
    with threats.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(["threat", "max_dist", "weight", "decay", "cur_path"])
        writer.writerow(["road", 1000, 1, "linear", threat])
    sensitivity = root / "sensitivity.csv"
    with sensitivity.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(["lulc", "habitat", "road"]); writer.writerows([[1, 0.7, 0.2], [2, 0.4, 0.8]])
    habitat_stack = root / "habitat.json"
    habitat_stack.write_text(json.dumps({"args": {"lulc_cur_path": str(lulc), "threats_table_path": str(threats),
                                                   "sensitivity_table_path": str(sensitivity), "half_saturation_constant": 0.5}}), encoding="utf-8")
    habitat_report = root / "habitat.md"
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "invest_parameter_report.py"),
                             "--model", "habitat_quality", "--datastack", str(habitat_stack), "--output", str(habitat_report)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr
    text = habitat_report.read_text(encoding="utf-8")
    assert "half_saturation_constant" in text and "Habitat threats" in text and "| road |" in text and "Status: **PASS**" in text, text

print('{"status":"completed","checks":["Carbon density report","Habitat threat report","validation verdict"]}')
