#!/usr/bin/env python3
"""Compare workflow and independent InVEST Carbon raster outputs on the same grid."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio


def read(path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    with rasterio.open(path) as source:
        return source.read(1).astype("float64"), source.dataset_mask() > 0, {
            "shape": (source.height, source.width), "crs": str(source.crs), "transform": tuple(source.transform)
        }


def compare(workflow_raster: Path, independent_raster: Path, relative_tolerance: float,
            output: Path) -> dict[str, Any]:
    if not math.isfinite(relative_tolerance) or relative_tolerance < 0:
        raise ValueError("relative_tolerance must be finite and non-negative")
    workflow, workflow_valid, workflow_profile = read(workflow_raster)
    independent, independent_valid, independent_profile = read(independent_raster)
    if workflow_profile != independent_profile:
        raise ValueError("InVEST outputs are not on the same grid")
    valid = workflow_valid & independent_valid & np.isfinite(workflow) & np.isfinite(independent)
    if not valid.any():
        raise ValueError("InVEST outputs have no common valid pixels")
    workflow_total = float(workflow[valid].sum())
    independent_total = float(independent[valid].sum())
    relative_difference = abs(workflow_total - independent_total) / max(abs(independent_total), 1e-12)
    difference = workflow[valid] - independent[valid]
    passed = relative_difference <= relative_tolerance
    report = {
        "status": "completed" if passed else "failed",
        "workflow_total_t_c": workflow_total, "independent_total_t_c": independent_total,
        "relative_difference": relative_difference, "relative_tolerance": relative_tolerance,
        "rmse_t_c_per_pixel": float(np.sqrt(np.mean(difference ** 2))),
        "max_absolute_difference_t_c_per_pixel": float(np.max(np.abs(difference))),
        "common_valid_pixel_count": int(valid.sum()),
        "workflow_raster": str(workflow_raster.resolve()), "independent_raster": str(independent_raster.resolve()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["output"] = str(output.resolve())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-raster", required=True, type=Path)
    parser.add_argument("--independent-raster", required=True, type=Path)
    parser.add_argument("--relative-tolerance", type=float, default=0.001)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = compare(args.workflow_raster, args.independent_raster, args.relative_tolerance, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
