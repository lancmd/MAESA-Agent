"""Compare two aligned synthetic InVEST Carbon outputs."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from invest_consistency import compare  # noqa: E402


workspace = ROOT / "outputs" / "invest_consistency_smoke"
workspace.mkdir(parents=True, exist_ok=True)
profile = {"driver": "GTiff", "width": 2, "height": 2, "count": 1, "dtype": "float32",
           "crs": "EPSG:32650", "transform": from_origin(500000, 3700000, 30, 30), "nodata": -1}
paths = []
for name, values in (("workflow", [[10, 20], [30, 40]]), ("independent", [[10, 20], [30, 40.05]])):
    path = workspace / f"{name}.tif"
    with rasterio.open(path, "w", **profile) as sink:
        sink.write(np.array(values, dtype="float32"), 1)
    paths.append(path)
report = compare(paths[0], paths[1], 0.001, workspace / "validation.json")
assert report["status"] == "completed", report
assert report["relative_difference"] < 0.001
print(report["relative_difference"])
