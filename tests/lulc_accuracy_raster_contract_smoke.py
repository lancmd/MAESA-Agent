"""Verify generated-LULC accuracy never trusts a table-side prediction value."""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lulc_accuracy import evaluate  # noqa: E402


with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as temporary:
    root = Path(temporary)
    raster = root / "lulc.tif"
    with rasterio.open(raster, "w", driver="GTiff", width=2, height=2, count=1, dtype="uint8",
                       crs="EPSG:32650", transform=from_origin(500000, 3700000, 30, 30), nodata=0) as target:
        target.write(np.array([[1, 2], [2, 1]], dtype="uint8"), 1)
    samples = root / "validation.csv"
    with samples.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["reference", "x", "y", "prediction"])
        writer.writeheader()
        # The deliberately wrong column must be overwritten by the generated
        # LULC values, not used as an alternative prediction source.
        writer.writerow({"reference": 1, "x": 500015, "y": 3699985, "prediction": 7})
        writer.writerow({"reference": 2, "x": 500045, "y": 3699985, "prediction": 7})
    report = evaluate(samples, "reference", "prediction", root / "accuracy.json", raster,
                      "x", "y", "EPSG:32650", require_raster_sampling=True)
    assert report["oa"] == 1.0, report
    assert report["prediction_source"] == "classification_raster_sample", report
    assert report["preexisting_prediction_field_ignored"] is True, report
    try:
        evaluate(samples, "reference", "prediction", root / "bad.json", require_raster_sampling=True)
    except ValueError as error:
        assert "classification-raster" in str(error), error
    else:
        raise AssertionError("strict accuracy accepted table-side predictions without a LULC raster")

print('{"status":"completed","checks":["raster-sampled accuracy","prefilled prediction ignored"]}')
