"""Exercise PLUS FoM, class metrics, and random-seed stability on aligned rasters."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from plus_validation import evaluate  # noqa: E402


workspace = ROOT / "outputs" / "plus_validation_smoke"
workspace.mkdir(parents=True, exist_ok=True)
profile = {"driver": "GTiff", "width": 3, "height": 3, "count": 1, "dtype": "uint8",
           "crs": "EPSG:32650", "transform": from_origin(500000, 3700000, 30, 30), "nodata": 0}
arrays = {
    "baseline": np.ones((3, 3), dtype="uint8"),
    "reference": np.array([[1, 2, 2], [1, 1, 2], [1, 1, 1]], dtype="uint8"),
    "seed_1": np.array([[1, 2, 1], [1, 1, 2], [1, 1, 1]], dtype="uint8"),
    "seed_2": np.array([[1, 2, 2], [1, 1, 1], [1, 1, 1]], dtype="uint8"),
}
paths = {}
for name, data in arrays.items():
    path = workspace / f"{name}.tif"
    with rasterio.open(path, "w", **profile) as sink:
        sink.write(data, 1)
    paths[name] = path
report = evaluate(paths["reference"], paths["seed_1"], paths["baseline"], [
    {"seed": 1, "path": str(paths["seed_1"])}, {"seed": 2, "path": str(paths["seed_2"])},
], workspace / "validation.json")
assert 0 < report["fom"] <= 1
assert len(report["seed_metrics"]) == 2
assert "seed_fom_population_stddev" in report
print(report["fom"])
