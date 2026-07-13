#!/usr/bin/env python3
"""Validate local raster grids, codes and carbon-table coverage before analysis."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _rasterio_info(path: Path) -> dict[str, Any]:
    import numpy as np  # type: ignore
    import rasterio  # type: ignore

    with rasterio.open(path) as src:
        values: set[int] = set()
        minimum: float | None = None
        maximum: float | None = None
        integer = all("int" in dtype or "uint" in dtype for dtype in src.dtypes)
        for _, window in src.block_windows(1):
            data = src.read(1, window=window, masked=True)
            finite = data.compressed()
            if finite.size:
                minimum = float(finite.min()) if minimum is None else min(minimum, float(finite.min()))
                maximum = float(finite.max()) if maximum is None else max(maximum, float(finite.max()))
                if len(values) <= 4096:
                    values.update(int(item) for item in np.unique(finite)[:4097])
        return {
            "path": str(path.resolve()), "inspector": "rasterio", "crs": str(src.crs) if src.crs else None,
            "width": src.width, "height": src.height, "transform": list(src.transform)[:6],
            "nodata": src.nodata, "dtypes": list(src.dtypes), "integer": integer,
            "minimum": minimum, "maximum": maximum, "values": sorted(values) if len(values) <= 4096 else None,
        }


def _gdal_info(path: Path) -> dict[str, Any]:
    executable = os.getenv("MINING_GDALINFO") or shutil.which("gdalinfo")
    if not executable:
        raise RuntimeError("no raster inspector is available; install rasterio or provide GDALINFO/MINING_GDALINFO")
    process = subprocess.run([executable, "-json", "-stats", str(path)], text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, encoding="utf-8", errors="replace", check=False)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or f"gdalinfo returned {process.returncode}")
    raw = json.loads(process.stdout)
    band = (raw.get("bands") or [{}])[0]
    data_type = str(band.get("type", "")).lower()
    return {
        "path": str(path.resolve()), "inspector": "gdalinfo", "crs": raw.get("coordinateSystem", {}).get("wkt"),
        "width": (raw.get("size") or [None, None])[0], "height": (raw.get("size") or [None, None])[1],
        "transform": raw.get("geoTransform"), "nodata": band.get("noDataValue"), "dtypes": [data_type],
        "integer": any(token in data_type for token in ("int", "byte")),
        "minimum": band.get("minimum"), "maximum": band.get("maximum"), "values": None,
    }


def inspect_raster(path: Path) -> dict[str, Any]:
    try:
        return _rasterio_info(path)
    except ModuleNotFoundError:
        return _gdal_info(path)


def _same_grid(master: dict[str, Any], item: dict[str, Any]) -> bool:
    if master.get("width") != item.get("width") or master.get("height") != item.get("height"):
        return False
    if (master.get("crs") or "") != (item.get("crs") or ""):
        return False
    left, right = master.get("transform"), item.get("transform")
    return isinstance(left, list) and isinstance(right, list) and len(left) == len(right) and all(
        math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9) for a, b in zip(left, right)
    )


def _carbon_codes(path: Path) -> set[int]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or "lucode" not in rows[0]:
        raise ValueError("carbon density table must contain lucode")
    return {int(float(row["lucode"])) for row in rows if row.get("lucode", "").strip()}


def validate(spec: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    checks: list[str] = []
    datasets = spec.get("datasets", [])
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("spatial preflight requires at least one dataset")
    inspected: dict[str, dict[str, Any]] = {}
    for entry in datasets:
        name, raw = str(entry.get("name", "dataset")), entry.get("path")
        path = Path(str(raw)).expanduser().resolve()
        if not path.exists():
            errors.append(f"{name}: file does not exist: {path}")
            continue
        try:
            info = inspect_raster(path)
            inspected[name] = info
            if not info.get("crs"):
                errors.append(f"{name}: CRS is missing")
            if not info.get("width") or not info.get("height"):
                errors.append(f"{name}: raster dimensions are invalid")
            if entry.get("kind") == "lulc":
                if not info.get("integer"):
                    errors.append(f"{name}: LULC must use an integer pixel type")
                allowed = set(entry.get("allowed_codes", []))
                values = info.get("values")
                if allowed and values is not None:
                    unknown = sorted(set(values) - allowed)
                    if unknown:
                        errors.append(f"{name}: unrecognised LULC codes: {unknown}")
            if entry.get("kind") == "subsidence_depth":
                minimum = info.get("minimum")
                if minimum is None:
                    errors.append(f"{name}: subsidence-depth minimum could not be inspected")
                elif float(minimum) < -1e-9:
                    errors.append(f"{name}: subsidence depth contains negative values under positive_down")
            checks.append(name)
        except Exception as error:
            errors.append(f"{name}: {error}")
    master_name = spec.get("master")
    if master_name and master_name in inspected:
        master = inspected[master_name]
        for entry in datasets:
            name = str(entry.get("name", "dataset"))
            if entry.get("must_align") and name in inspected and not _same_grid(master, inspected[name]):
                errors.append(f"{name}: grid differs from master {master_name}")
    elif master_name:
        errors.append(f"master dataset was not inspected: {master_name}")
    carbon_path = spec.get("carbon_density")
    lulc_names = [str(item.get("name")) for item in datasets if item.get("kind") == "lulc"]
    if carbon_path and lulc_names:
        try:
            carbon_codes = _carbon_codes(Path(str(carbon_path)).expanduser().resolve())
            for name in lulc_names:
                values = inspected.get(name, {}).get("values")
                if values is not None:
                    missing = sorted(set(values) - carbon_codes)
                    if missing:
                        errors.append(f"{name}: carbon density has no lucode for {missing}")
            checks.append("carbon-density coverage")
        except Exception as error:
            errors.append(f"carbon density: {error}")
    datum = spec.get("vertical_datum", {})
    if datum:
        dem, water = datum.get("dem"), datum.get("water_level")
        if not dem or not water:
            errors.append("DEM and water-level vertical datum must both be declared for volume calculation")
        elif str(dem).strip().lower() != str(water).strip().lower():
            errors.append("DEM and water level use different vertical datums")
        else:
            checks.append("vertical datum")
    return {"status": "failed" if errors else "completed", "checks": checks, "errors": errors,
            "datasets": inspected, "master": master_name}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8-sig"))
    report = validate(spec)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
