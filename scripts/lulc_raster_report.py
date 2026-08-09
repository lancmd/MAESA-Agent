#!/usr/bin/env python3
"""Create a compact, machine-readable quality report for a LULC GeoTIFF."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import arcpy


def descriptor(path: str) -> dict[str, object]:
    d = arcpy.Describe(path)
    sr = d.spatialReference
    e = d.extent
    # Some GeoTIFFs expose a generic DescribeData object in ArcGIS Pro.  Raster
    # properties are available in both cases and avoid an ArcPy-version trap.
    cell_width = float(arcpy.management.GetRasterProperties(path, "CELLSIZEX").getOutput(0))
    cell_height = float(arcpy.management.GetRasterProperties(path, "CELLSIZEY").getOutput(0))
    columns = int(arcpy.management.GetRasterProperties(path, "COLUMNCOUNT").getOutput(0))
    rows = int(arcpy.management.GetRasterProperties(path, "ROWCOUNT").getOutput(0))
    return {
        "path": os.path.abspath(path),
        "spatial_reference": sr.name if sr else None,
        "cell_size": [cell_width, cell_height],
        "shape": [rows, columns],
        "extent": [e.XMin, e.YMin, e.XMax, e.YMax],
        "pixel_type": getattr(d, "pixelType", None),
    }


def same_grid(a: dict[str, object], b: dict[str, object]) -> bool:
    return (
        a["spatial_reference"] == b["spatial_reference"]
        and a["shape"] == b["shape"]
        and all(math.isclose(x, y, abs_tol=1e-8) for x, y in zip(a["cell_size"], b["cell_size"]))
        and all(math.isclose(x, y, abs_tol=1e-8) for x, y in zip(a["extent"], b["extent"]))
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--reference-grid")
    args = p.parse_args()

    if not arcpy.Exists(args.input):
        p.error(f"Raster not found: {args.input}")
    if os.path.exists(args.report):
        p.error(f"Refusing to overwrite report: {args.report}")
    os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)

    arcpy.management.BuildRasterAttributeTable(args.input, "Overwrite")
    classes = []
    with arcpy.da.SearchCursor(args.input, ["VALUE", "COUNT"]) as rows:
        for value, count in rows:
            if value is not None and count is not None:
                classes.append({"code": int(value), "pixel_count": int(count)})
    codes = sorted(x["code"] for x in classes)
    allowed = {1, 2, 3, 4, 5, 6}
    info = descriptor(args.input)
    reference = descriptor(args.reference_grid) if args.reference_grid else None
    checks = {
        "integer_class_codes": all(float(c).is_integer() for c in codes),
        "codes_within_six_class_contract": set(codes).issubset(allowed),
        "at_least_two_classes": len(codes) >= 2,
        "grid_matches_reference": same_grid(info, reference) if reference else None,
    }
    status = "pass" if all(v is not False for v in checks.values()) else "fail"
    payload = {
        "status": status,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "raster": info,
        "reference_grid": reference,
        "classes": classes,
        "checks": checks,
        "accuracy_status": "pending_validation",
    }
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
