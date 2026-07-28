"""Check Annual Water Yield/Habitat contracts and correct service aggregation."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
import sys

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from invest_ecosystem_contract import validate  # noqa: E402
from scenario_service_table import raster_total  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    for name in ("precip.tif", "eto.tif", "root.tif", "pawc.tif", "watersheds.gpkg"):
        (root / name).write_bytes(b"fixture")
    profile = {"driver": "GTiff", "width": 2, "height": 2, "count": 1, "dtype": "int16",
               "crs": "EPSG:32650", "transform": from_origin(500000, 3700060, 30, 30), "nodata": -9999}
    for name, values in (("lulc.tif", [[1, 1], [1, 1]]), ("threat.tif", [[1, 0], [0, 1]])):
        with rasterio.open(root / name, "w", **profile) as sink:
            sink.write(np.array(values, dtype="int16"), 1)
    (root / "bio.csv").write_text("lucode,root_depth,Kc,lulc_veg\n1,1000,0.8,1\n", encoding="utf-8")
    (root / "threats.csv").write_text("threat,max_dist,weight,decay,cur_path\nroad,1000,1,linear,threat.tif\n", encoding="utf-8")
    (root / "sensitivity.csv").write_text("lulc,habitat,road\n1,1,0.5\n", encoding="utf-8")
    awy = {"args": {"lulc_path": "lulc.tif", "precipitation_path": "precip.tif", "eto_path": "eto.tif",
                    "depth_to_root_rest_layer_path": "root.tif", "pawc_path": "pawc.tif", "watersheds_path": "watersheds.gpkg",
                    "biophysical_table_path": "bio.csv", "seasonality_constant": 8.1}}
    habitat = {"args": {"lulc_cur_path": "lulc.tif", "threats_table_path": "threats.csv",
                         "sensitivity_table_path": "sensitivity.csv", "half_saturation_constant": 0.5}}
    (root / "awy.json").write_text(json.dumps(awy), encoding="utf-8"); (root / "habitat.json").write_text(json.dumps(habitat), encoding="utf-8")
    assert validate("annual_water_yield", root / "awy.json")["status"] == "completed"
    assert validate("habitat_quality", root / "habitat.json")["status"] == "completed"
    raster = root / "water_yield.tif"
    with rasterio.open(raster, "w", driver="GTiff", width=2, height=2, count=1, dtype="float32", crs="EPSG:32650",
                       transform=from_origin(0, 60, 30, 30), nodata=-9999) as dst:
        dst.write(np.full((1, 2, 2), 100.0, dtype="float32"))
    assert abs(raster_total(raster, "depth_mm_to_m3") - 360.0) < 1e-6
    assert abs(raster_total(raster, "mean") - 100.0) < 1e-6
print('{"status":"completed","checks":["AWY contract","HQ contract","mm to m3","habitat mean"]}')
