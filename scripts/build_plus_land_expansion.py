"""Create a PLUS land-expansion raster from two aligned LULC maps.

PLUS expects an expansion map in which unchanged cells are zero and changed
cells carry the new land-use code.  The operation is a deterministic
transition derivative; it is not a forecast and is recorded separately from
the model output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--previous", type=Path, required=True)
    p.add_argument("--latest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    with rasterio.open(args.previous) as a, rasterio.open(args.latest) as b:
        if (a.crs != b.crs or a.width != b.width or a.height != b.height
                or not a.transform.almost_equals(b.transform)):
            raise ValueError("previous and latest LULC rasters are not aligned")
        old = a.read(1)
        new = b.read(1)
        nodata = 0 if a.nodata is None else a.nodata
        valid = (old != nodata) & (new != nodata)
        # PLUS V1.4.2's LEAS importer accepts an unsigned-char expansion map;
        # land-use codes in this project are 1..7, so uint8 is lossless.
        if np.nanmax(new[valid]) > 255:
            raise ValueError("LULC codes exceed uint8 range required by PLUS")
        expansion = np.where(valid & (old != new), new, 0).astype(np.uint8)
        profile = a.profile.copy()
        profile.update(dtype="uint8", count=1, nodata=0, compress="deflate")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(args.output, "w", **profile) as dst:
            dst.write(expansion, 1)
        changed = int(np.count_nonzero(expansion))
        summary = {
            "previous": str(args.previous), "latest": str(args.latest),
            "output": str(args.output), "changed_cells": changed,
            "width": a.width, "height": a.height, "crs": str(a.crs),
            "transform": list(a.transform)[:6], "nodata": 0,
            "meaning": "0=unchanged; positive value=new LULC class",
        }
    args.output.with_suffix(args.output.suffix + ".json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
