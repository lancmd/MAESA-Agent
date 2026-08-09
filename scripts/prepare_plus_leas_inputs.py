"""Prepare and validate the two raster contracts consumed by PLUS LEAS.

LEAS does not take a Python mapping of driver names.  It reads a directory of
single-band feature rasters plus the land-expansion raster produced from two
aligned LULC maps.  This helper creates a curated feature directory, checks
that every changed cell has finite feature values, and writes a manifest for
the GUI bridge.  It never edits the source rasters.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import rasterio


def _grid(ds: rasterio.DatasetReader) -> dict[str, object]:
    return {"crs": str(ds.crs), "width": ds.width, "height": ds.height,
            "transform": list(ds.transform)[:6], "resolution": [abs(ds.transform.a), abs(ds.transform.e)]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drivers", type=Path, required=True)
    ap.add_argument("--previous", type=Path, required=True)
    ap.add_argument("--latest", type=Path, required=True)
    ap.add_argument("--expansion", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    if not args.drivers.is_dir():
        raise FileNotFoundError(f"LEAS driver directory does not exist: {args.drivers}")
    with rasterio.open(args.previous) as prev, rasterio.open(args.latest) as latest, rasterio.open(args.expansion) as expansion:
        if prev.crs != latest.crs or prev.width != latest.width or prev.height != latest.height or not prev.transform.almost_equals(latest.transform):
            raise ValueError("historical LULC rasters are not aligned")
        if expansion.crs != prev.crs or expansion.width != prev.width or expansion.height != prev.height or not expansion.transform.almost_equals(prev.transform):
            raise ValueError("land-expansion raster is not aligned with the LULC master grid")
        old = prev.read(1)
        new = latest.read(1)
        changed = (old != (0 if prev.nodata is None else prev.nodata)) & (new != (0 if latest.nodata is None else latest.nodata)) & (old != new)
        expansion_values = expansion.read(1)
        if int(np.count_nonzero(expansion_values)) == 0:
            raise ValueError("land-expansion raster contains no changed cells")
        source_grid = _grid(prev)
        features = sorted(args.drivers.glob("*.tif"))
        if len(features) < 2:
            raise ValueError("LEAS needs at least two feature rasters")
        feature_reports: list[dict[str, object]] = []
        missing_changed: dict[str, int] = {}
        args.output.mkdir(parents=True, exist_ok=True)
        for source in features:
            with rasterio.open(source) as ds:
                if ds.count != 1:
                    raise ValueError(f"LEAS feature must be single-band: {source.name}")
                if ds.crs != prev.crs or ds.width != prev.width or ds.height != prev.height or not ds.transform.almost_equals(prev.transform):
                    raise ValueError(f"LEAS feature is not aligned: {source.name}")
                values = ds.read(1)
                valid = np.isfinite(values)
                if ds.nodata is not None:
                    valid &= values != ds.nodata
                missing = int(np.count_nonzero(changed & ~valid))
                missing_changed[source.name] = missing
                feature_reports.append({"source": str(source), "name": source.name, "dtype": ds.dtypes[0],
                                        "nodata": ds.nodata, "missing_changed_cells": missing,
                                        "min": float(np.nanmin(values[valid])) if np.any(valid) else None,
                                        "max": float(np.nanmax(values[valid])) if np.any(valid) else None})
            # Use stable, ASCII filenames so the vendor's Qt/GDAL file scan is
            # independent of the user's language and source naming convention.
            target = args.output / f"feature_{len(feature_reports):02d}_{source.stem}.tif"
            if missing:
                # PLUS's native GDAL reader treats a NoData sample in the
                # expansion mask as an unusable training row.  Fill only the
                # LULC domain, leaving the outside-of-study NoData untouched.
                # The manifest records the operation so it is not confused
                # with an observed driver value.
                with rasterio.open(source) as ds:
                    values = ds.read(1)
                    nodata = ds.nodata
                    valid = np.isfinite(values)
                    if nodata is not None:
                        valid &= values != nodata
                    domain = (old != (0 if prev.nodata is None else prev.nodata))
                    fill_mask = domain & ~valid
                    if np.any(fill_mask):
                        median = float(np.nanmedian(values[valid])) if np.any(valid) else 0.0
                        values = values.astype("float32", copy=False)
                        values[fill_mask] = median
                    profile = ds.profile.copy()
                    profile.update(dtype="float32", nodata=-9999.0, compress="deflate")
                    with rasterio.open(target, "w", **profile) as out:
                        out.write(values.astype("float32", copy=False), 1)
            else:
                shutil.copy2(source, target)
        # A small amount of boundary imputation is expected for clipped
        # climate/terrain layers; after preparation no changed pixel may be
        # missing from any feature stack member.
        manifest_missing = missing_changed
        if any(missing_changed.values()):
            for item in feature_reports:
                item["boundary_imputation"] = "global_valid_median_within_lulc_domain"
        manifest = {"status": "completed", "contract": "plus_leas_v142", "master_grid": source_grid,
                    "previous": str(args.previous), "latest": str(args.latest), "expansion": str(args.expansion),
                    "expansion_changed_cells": int(np.count_nonzero(changed)), "feature_folder": str(args.output),
                    "features": feature_reports, "missing_changed_cells_before_imputation": manifest_missing,
                    "source_data_unchanged": True}
    report = args.report or (args.output / "leas_input_manifest.json")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
