#!/usr/bin/env python3
"""Rasterise standardised PIM points to the exact grid of a master raster.

The script is used when a project receives only w.dat/w.txt.  Coordinates are
interpreted in the CRS of the master LULC grid; it refuses points outside that
grid instead of silently assigning a CRS.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", required=True, type=Path); parser.add_argument("--master", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path); parser.add_argument("--metadata", type=Path)
    parser.add_argument("--fill-nearest", action="store_true", help="Fill master-grid cells by nearest PIM sample point")
    args = parser.parse_args()
    try:
        import numpy as np  # type: ignore
        import rasterio  # type: ignore
    except ImportError as error:
        raise RuntimeError("w.dat rasterisation needs the validation dependencies (numpy and rasterio)") from error
    rows = list(csv.DictReader(args.points.open(encoding="utf-8-sig", newline="")))
    if not rows:
        raise ValueError("standardised w.dat contains no points")
    with rasterio.open(args.master) as master:
        if not master.crs or not master.crs.is_projected:
            raise ValueError("master LULC raster needs a projected CRS before w.dat rasterisation")
        sums = np.zeros((master.height, master.width), dtype="float64")
        count = np.zeros((master.height, master.width), dtype="uint32")
        outside = 0
        for number, row in enumerate(rows, start=2):
            try:
                x, y, depth = float(row["x"]), float(row["y"]), float(row["subsidence_depth_m"])
            except (KeyError, ValueError) as error:
                raise ValueError(f"invalid standardised w.dat row {number}") from error
            col, line = master.index(x, y)
            if not 0 <= col < master.height or not 0 <= line < master.width:
                outside += 1; continue
            sums[col, line] += depth; count[col, line] += 1
        if not count.any():
            raise ValueError("no w.dat points intersect the master LULC grid; check CRS and x/y columns")
        result = np.full((master.height, master.width), -9999.0, dtype="float32")
        result[count > 0] = (sums[count > 0] / count[count > 0]).astype("float32")
        if args.fill_nearest and (count == 0).any():
            sample_rows, sample_cols = np.nonzero(count > 0)
            sample_values = result[sample_rows, sample_cols]
            missing_rows, missing_cols = np.nonzero(count == 0)
            # Chunked calculation keeps memory bounded for large mine grids.
            for begin in range(0, len(missing_rows), 50_000):
                end = min(begin + 50_000, len(missing_rows))
                dr = missing_rows[begin:end, None] - sample_rows[None, :]
                dc = missing_cols[begin:end, None] - sample_cols[None, :]
                nearest = np.argmin(dr * dr + dc * dc, axis=1)
                result[missing_rows[begin:end], missing_cols[begin:end]] = sample_values[nearest]
        profile = master.profile.copy(); profile.update(dtype="float32", count=1, nodata=-9999.0, compress="deflate")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(args.output, "w", **profile) as destination:
            destination.write(result, 1)
        report = {"master": str(args.master.resolve()), "points": str(args.points.resolve()), "output": str(args.output.resolve()),
                  "crs": str(master.crs), "input_point_count": len(rows), "points_outside_grid": outside,
                  "cells_with_observed_depth": int((count > 0).sum()), "cells_filled_from_nearest_sample": int((count == 0).sum()) if args.fill_nearest else 0,
                  "cells_without_depth": 0 if args.fill_nearest else int((count == 0).sum()), "nodata": -9999.0,
                  "interpolation": "nearest_PIM_sample_on_master_grid" if args.fill_nearest else "mean_of_points_in_each_master_cell; no gap filling"}
    target = args.metadata or args.output.with_suffix(args.output.suffix + ".metadata.json")
    target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
