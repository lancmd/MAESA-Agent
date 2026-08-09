"""Prepare a PLUS-compatible RE development-zone mask from subsidence depth."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--threshold", type=float, default=0.0)
    args = ap.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(args.input) as src:
        data = src.read(1, masked=True)
        valid = (~np.ma.getmaskarray(data)) & np.isfinite(np.asarray(data)) & (np.asarray(data) > args.threshold)
        profile = src.profile.copy()
        profile.update(dtype="uint8", count=1, nodata=0, compress="deflate", predictor=2)
        with rasterio.open(args.output, "w", **profile) as dst:
            dst.write(valid.astype("uint8"), 1)
    print(f"wrote {args.output} ({int(valid.sum())} active cells)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
