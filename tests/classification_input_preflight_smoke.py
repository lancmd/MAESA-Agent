"""Verify that bad sample inputs block a classifier before its backend stage."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    samples = root / "validation.csv"
    with samples.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["reference", "x", "y"])
        writer.writeheader()
        writer.writerows([
            {"reference": 1, "x": 500015, "y": 3700045},
            {"reference": 2, "x": 500045, "y": 3700015},
        ])
    output = root / "preflight.json"
    command = [sys.executable, str(ROOT / "scripts" / "classification_input_preflight.py"),
               "--roi", str(ROOT / "tests" / "fixtures" / "roi_quality.geojson"),
               "--class-field", "class_id", "--role-field", "sample_role",
               "--expected-class", "1", "--expected-class", "2", "--minimum-rois-per-class", "1",
               "--validation-samples", str(samples), "--reference-field", "reference",
               "--x-field", "x", "--y-field", "y", "--samples-crs", "EPSG:32650",
               "--require-raster-sampling", "--output", str(output)]
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", check=False)
    assert process.returncode == 0, process.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "completed", report
    assert report["roi"]["class_counts"] == {"1": 2, "2": 2}, report
    assert report["validation_samples"]["class_counts"] == {"1": 1, "2": 1}, report

    invalid = root / "invalid.geojson"
    invalid.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"wrong_field": 1}, "geometry": None},
    ]}), encoding="utf-8")
    failed_output = root / "failed.json"
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "classification_input_preflight.py"),
                              "--roi", str(invalid), "--class-field", "class_id", "--output", str(failed_output)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", check=False)
    assert process.returncode == 1
    failed = json.loads(failed_output.read_text(encoding="utf-8"))
    assert any("class field is missing" in item for item in failed["errors"]), failed
    assert any("at least two" in item for item in failed["errors"]), failed
    assert any("CRS" in item for item in failed["errors"]), failed

print('{"status":"completed","checks":["ROI class field","ROI geometry and CRS","per-class validation samples"]}')
