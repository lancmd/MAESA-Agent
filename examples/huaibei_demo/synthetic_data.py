#!/usr/bin/env python3
"""Generate a deterministic, anonymous GIS input set for this demonstration.

The files are deliberately small and artificial.  They are suitable for project
validation, workflow compilation, and local adapter smoke tests only; they are
not remote-sensing observations and must not be used in scientific analysis.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parent
WIDTH = 64
HEIGHT = 64
CELL_SIZE_M = 30.0
CRS = "EPSG:32650"
TRANSFORM = from_origin(500000.0, 4001920.0, CELL_SIZE_M, CELL_SIZE_M)


def write_raster(path: Path, data: np.ndarray, *, dtype: str, nodata: int | float | None = None) -> None:
    """Write one or more aligned synthetic GeoTIFF bands."""
    array = data if data.ndim == 3 else data[np.newaxis, :, :]
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=WIDTH,
        height=HEIGHT,
        count=array.shape[0],
        dtype=dtype,
        crs=CRS,
        transform=TRANSFORM,
        nodata=nodata,
        compress="deflate",
    ) as target:
        target.write(array.astype(dtype, copy=False))


def polygon(xmin: float, ymin: float, xmax: float, ymax: float) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [[[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax], [xmin, ymin]]],
    }


def write_boundary(path: Path, name: str, geometry: dict[str, object]) -> None:
    """Write a small CRS-labelled boundary placeholder for GIS adapter tests.

    RFC 7946 GeoJSON assumes WGS84, while this fixture needs to align with its
    projected 30 m raster.  The legacy ``crs`` member is retained because GDAL
    and desktop GIS clients use it for this controlled local fixture.  For a
    production project use a GeoPackage with an explicit projected CRS.
    """
    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": CRS}},
        "features": [{"type": "Feature", "properties": {"name": name, "synthetic": True}, "geometry": geometry}],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_tables(data_dir: Path) -> None:
    carbon_rows = [
        (1, "synthetic_water", 0.0, 0.0, 0.0, 0.0),
        (2, "synthetic_natural_water", 0.0, 0.0, 0.0, 0.0),
        (3, "synthetic_built_up", 5.0, 1.0, 12.0, 0.0),
        (4, "synthetic_cropland", 24.0, 5.0, 38.0, 1.0),
        (5, "synthetic_forest", 63.0, 14.0, 52.0, 4.0),
        (6, "synthetic_grassland", 12.0, 3.0, 34.0, 1.0),
        (7, "synthetic_bare_mining_land", 1.0, 0.0, 9.0, 0.0),
    ]
    with (data_dir / "carbon_density.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["lucode", "LULC_Name", "c_above", "c_below", "c_soil", "c_dead"])
        writer.writerows(carbon_rows)

    with (data_dir / "ecosystem_criteria.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["unit_id", "scenario", "carbon_storage_t_c", "annual_water_yield_m3", "habitat_quality"])
        writer.writerows([
            ("A", "ND", 5120.0, 125000.0, 0.68),
            ("B", "UD", 4860.0, 113000.0, 0.61),
            ("C", "EP", 5480.0, 132000.0, 0.78),
            ("D", "RE", 4710.0, 107000.0, 0.57),
        ])


def write_w_dat(path: Path, depth: np.ndarray) -> None:
    """Write negative-down millimetre points compatible with wdat_to_depth.py."""
    with path.open("w", encoding="utf-8") as stream:
        stream.write("# x y w_mm; deterministic synthetic PIM-style source points\n")
        for row in range(4, HEIGHT, 12):
            for col in range(4, WIDTH, 12):
                x, y = rasterio.transform.xy(TRANSFORM, row, col, offset="center")
                stream.write(f"{x:.3f} {y:.3f} {-1000.0 * float(depth[row, col]):.3f}\n")


def optional_model_package(data_dir: Path) -> Path:
    """Create a minimal portable model package when PyTorch is available."""
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("--with-model requires PyTorch; install the optional pytorch dependency first") from error

    class TinySegmentation(torch.nn.Module):
        def forward(self, image: torch.Tensor) -> torch.Tensor:
            signal = image[:, 0:1]
            return torch.cat((signal, -signal), dim=1)

    package = data_dir / "model_package"
    shutil.rmtree(package, ignore_errors=True)
    package.mkdir(parents=True)
    temporary = Path(tempfile.mkdtemp(prefix="maesa_demo_model_"))
    try:
        exported = torch.export.export(TinySegmentation().eval(), (torch.zeros(1, 4, 32, 32),))
        temporary_model = temporary / "model.pt2"
        torch.export.save(exported, temporary_model)
        model_path = package / "model.pt2"
        shutil.copy2(temporary_model, model_path)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    config = {
        "schema_version": 1,
        "model_id": "huaibei-synthetic-demo-model",
        "format": "exported_program",
        "weights": "model.pt2",
        "sha256": digest,
        "sensor": "synthetic_four_band",
        "spatial_resolution_m": CELL_SIZE_M,
        "classes": [{"id": 1, "name": "positive_signal"}, {"id": 2, "name": "negative_signal"}],
        "input": {
            "bands": ["band_1", "band_2", "band_3", "band_4"],
            "band_indexes": [1, 2, 3, 4],
            "mean": [0.0, 0.0, 0.0, 0.0],
            "std": [1.0, 1.0, 1.0, 1.0],
            "scale": 1.0,
            "offset": 0.0,
            "patch_size": 32,
            "stride": 24,
        },
        "output": {"type": "logits", "tensor_index": 0, "tensor_key": None, "class_nodata": 0, "confidence_nodata": -9999.0},
        "training": {"regions": ["synthetic"], "imagery_years": [2026], "validation_summary": "demonstration fixture"},
    }
    (package / "model_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return package


def generate(data_dir: Path, with_model: bool) -> list[Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    rows, cols = np.indices((HEIGHT, WIDTH))
    rng = np.random.default_rng(20260711)

    lulc_2020 = ((rows // 12 + cols // 12) % 7 + 1).astype("uint8")
    radius = np.hypot(rows - 32, cols - 32)
    lulc_2020[radius < 9] = 4
    lulc_2025 = lulc_2020.copy()
    lulc_2025[radius < 8] = 1
    lulc_2025[(rows < 14) & (cols > 42)] = 7

    spectral_means = np.array([
        [0.08, 0.07, 0.05, 0.03], [0.10, 0.11, 0.10, 0.08], [0.19, 0.21, 0.23, 0.24],
        [0.13, 0.18, 0.15, 0.31], [0.08, 0.15, 0.11, 0.39], [0.11, 0.19, 0.14, 0.29],
        [0.24, 0.22, 0.19, 0.16],
    ], dtype="float32")
    imagery = spectral_means[lulc_2025 - 1].transpose(2, 0, 1)
    imagery += rng.normal(0.0, 0.006, size=imagery.shape).astype("float32")
    imagery = np.clip(imagery, 0.0, 1.0)

    dem = (108.0 + cols * 0.07 - rows * 0.05).astype("float32")
    slope = (2.0 + np.hypot(cols - 30, rows - 34) * 0.06).astype("float32")
    road_distance = (np.abs(cols - 8) * CELL_SIZE_M).astype("float32")
    mine_distance = (np.maximum(radius - 14, 0.0) * CELL_SIZE_M).astype("float32")
    subsidence_depth = np.maximum(0.0, 2.4 - radius * 0.12).astype("float32")

    files = {
        "imagery_2025.tif": imagery,
        "lulc_2020.tif": lulc_2020,
        "lulc_2025.tif": lulc_2025,
        "dem.tif": dem,
        "slope.tif": slope,
        "road_distance.tif": road_distance,
        "mine_distance.tif": mine_distance,
        "subsidence_depth_m.tif": subsidence_depth,
    }
    for name, array in files.items():
        write_raster(data_dir / name, array, dtype=str(array.dtype), nodata=0 if array.dtype == np.uint8 else None)

    xmin, ymax = TRANSFORM.c, TRANSFORM.f
    xmax = xmin + WIDTH * CELL_SIZE_M
    ymin = ymax - HEIGHT * CELL_SIZE_M
    write_boundary(data_dir / "roi.geojson", "synthetic_roi", polygon(xmin, ymin, xmax, ymax))
    write_boundary(data_dir / "mine_boundary.geojson", "synthetic_mine_boundary", polygon(xmin + 240, ymin + 240, xmax - 240, ymax - 240))
    write_boundary(data_dir / "workface.geojson", "synthetic_workface", polygon(xmin + 660, ymin + 660, xmax - 660, ymax - 660))
    write_w_dat(data_dir / "external_w.dat", subsidence_depth)
    write_tables(data_dir)

    created = sorted(data_dir.glob("*"))
    if with_model:
        optional_model_package(data_dir)
        created = sorted(data_dir.glob("*"))
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data", help="Directory for regenerated synthetic inputs")
    parser.add_argument("--with-model", action="store_true", help="Also create a tiny PyTorch exported-program model package")
    args = parser.parse_args()
    created = generate(args.output_dir.expanduser().resolve(), args.with_model)
    print(json.dumps({"status": "created", "synthetic": True, "output_dir": str(args.output_dir.expanduser().resolve()),
                      "files": [item.name for item in created]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
