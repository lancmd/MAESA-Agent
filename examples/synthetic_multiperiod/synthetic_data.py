#!/usr/bin/env python3
"""Create deterministic anonymous inputs for the six-period example project."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CRS = "EPSG:32650"
ORIGIN_X, ORIGIN_Y, CELLS = 500000.0, 3701920.0, 64
YEARS = ((2000, 30, "landsat_5_tm"), (2005, 30, "landsat_5_tm"), (2010, 30, "landsat_5_tm"),
         (2015, 30, "landsat_8_oli"), (2020, 10, "sentinel_2_msi"), (2025, 10, "sentinel_2_msi"))


def write_raster(path: Path, values: np.ndarray, resolution: int, *, nodata: float | int | None = None) -> None:
    array = values if values.ndim == 3 else values[np.newaxis, :, :]
    height, width = array.shape[-2:]
    profile = {"driver": "GTiff", "width": width, "height": height, "count": array.shape[0], "dtype": str(array.dtype),
               "crs": CRS, "transform": from_origin(ORIGIN_X, ORIGIN_Y, resolution, resolution),
               "nodata": nodata, "compress": "deflate"}
    with rasterio.open(path, "w", **profile) as target:
        target.write(array)


def feature_polygon(row: int, col: int, resolution: int) -> dict[str, object]:
    x0, y0 = ORIGIN_X + col * resolution, ORIGIN_Y - row * resolution
    x1, y1 = x0 + resolution, y0 - resolution
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def write_roi(path: Path, lulc: np.ndarray, resolution: int) -> None:
    features: list[dict[str, object]] = []
    for code in range(1, 8):
        locations = np.argwhere(lulc == code)[:2]
        for row, col in locations:
            features.append({"type": "Feature", "properties": {"class_id": code, "sample_role": "training"},
                             "geometry": feature_polygon(int(row), int(col), resolution)})
    payload = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": CRS}}, "features": features}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_accuracy(path: Path, lulc: np.ndarray, resolution: int) -> None:
    """Write a held-out reference-point table without table-side predictions.

    The workflow samples the classified raster at these coordinates.  Points
    come from the far end of each class' synthetic grid so they do not reuse
    the two training ROI pixels written by :func:`write_roi`.
    """
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["reference", "x", "y"])
        writer.writeheader()
        for code in range(1, 8):
            locations = np.argwhere(lulc == code)[-2:]
            for row, col in locations:
                writer.writerow({"reference": code, "x": ORIGIN_X + (float(col) + 0.5) * resolution,
                                 "y": ORIGIN_Y - (float(row) + 0.5) * resolution})


def base_lulc(year: int) -> np.ndarray:
    rows, cols = np.indices((CELLS, CELLS))
    value = ((rows // 9 + cols // 11 + (year - 2000) // 5) % 7 + 1).astype("uint8")
    radius = np.hypot(rows - 31, cols - 32)
    value[radius < max(5, 13 - (year - 2000) // 5)] = 1
    value[(rows < 11) & (cols > 43)] = 7
    return value


def image_from_lulc(lulc: np.ndarray, year: int, resolution: int) -> np.ndarray:
    means = np.array([
        [0.08, 0.07, 0.06, 0.04, 0.03, 0.02], [0.10, 0.11, 0.10, 0.08, 0.07, 0.06],
        [0.20, 0.21, 0.23, 0.24, 0.25, 0.23], [0.13, 0.18, 0.15, 0.32, 0.18, 0.12],
        [0.07, 0.15, 0.10, 0.42, 0.21, 0.13], [0.11, 0.19, 0.14, 0.30, 0.16, 0.10],
        [0.24, 0.22, 0.19, 0.16, 0.14, 0.12],
    ], dtype="float32")
    if resolution == 10:
        lulc = np.repeat(np.repeat(lulc, 3, axis=0), 3, axis=1)
    image = means[lulc - 1].transpose(2, 0, 1)
    rng = np.random.default_rng(year)
    return np.clip(image + rng.normal(0, 0.004, size=image.shape).astype("float32"), 0, 1)


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    for year, resolution, sensor in YEARS:
        coarse = base_lulc(year)
        output_lulc = np.repeat(np.repeat(coarse, 3, axis=0), 3, axis=1) if resolution == 10 else coarse
        image = image_from_lulc(coarse, year, resolution)
        image_path = DATA / f"imagery_{year}.tif"
        write_raster(image_path, image.astype("float32"), resolution, nodata=-9999.0)
        with rasterio.open(image_path, "r+") as target:
            target.update_tags(sensor=sensor)
        write_roi(DATA / f"roi_{year}.geojson", output_lulc, resolution)
        write_accuracy(DATA / f"accuracy_{year}.csv", output_lulc, resolution)
    rows, cols = np.indices((CELLS, CELLS))
    road = ((cols == 8) | (rows == 41)).astype("uint8")
    write_raster(DATA / "road_30m.tif", road, 30, nodata=255)
    with (DATA / "carbon_density.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(["lucode", "c_above", "c_below", "c_soil", "c_dead"])
        for code in range(1, 8):
            writer.writerow([code, code * 2, code, code * 3, 0])
    habitat = {"half_saturation_constant": 0.5,
               "threats": [{"name": "road", "raster": "road_30m.tif", "max_distance_m": 1000, "weight": 1.0, "decay": "linear"}],
               "sensitivity": [{"lulc": code, "habitat": round(code / 8, 3), "threats": {"road": round((8 - code) / 8, 3)}} for code in range(1, 8)]}
    (DATA / "habitat_quality.json").write_text(json.dumps(habitat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "completed", "synthetic": True, "periods": [year for year, _, _ in YEARS], "data": str(DATA)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
