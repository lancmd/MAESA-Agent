#!/usr/bin/env python3
"""Copy a thematic raster and assign the CRS of a verified reference grid.

This is intended for ENVI results whose coordinates, cells and extent already
match a trusted grid but whose GeoTIFF metadata names the projection only as
``UTM_Zone_50N``.  It does *not* resample pixels or overwrite its input.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import arcpy


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--reference-grid", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--report", required=True)
    args = p.parse_args()
    for label, path in (("input", args.input), ("reference grid", args.reference_grid)):
        if not arcpy.Exists(path):
            p.error(f"{label} not found: {path}")
    if arcpy.Exists(args.output) or os.path.exists(args.report):
        p.error("Output or report already exists; refusing to overwrite it")
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    source = arcpy.Describe(args.input)
    reference = arcpy.Describe(args.reference_grid)
    # This is deliberately a precondition check.  Defining a CRS is safe only
    # where the grid geometry already agrees exactly.
    same_geometry = (
        abs(float(source.meanCellWidth) - float(arcpy.management.GetRasterProperties(args.reference_grid, "CELLSIZEX").getOutput(0))) < 1e-9
        and abs(float(source.meanCellHeight) - float(arcpy.management.GetRasterProperties(args.reference_grid, "CELLSIZEY").getOutput(0))) < 1e-9
        and all(
            abs(a - b) < 1e-9
            for a, b in zip(
                [source.extent.XMin, source.extent.YMin, source.extent.XMax, source.extent.YMax],
                [reference.extent.XMin, reference.extent.YMin, reference.extent.XMax, reference.extent.YMax],
            )
        )
    )
    if not same_geometry:
        p.error("Input and reference geometry differ; use Project Raster with Nearest instead")

    arcpy.management.CopyRaster(args.input, args.output)
    arcpy.management.DefineProjection(args.output, reference.spatialReference)
    arcpy.management.BuildRasterAttributeTable(args.output, "Overwrite")
    out = arcpy.Describe(args.output)
    payload = {
        "status": "completed",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "input": os.path.abspath(args.input),
        "output": os.path.abspath(args.output),
        "reference_grid": os.path.abspath(args.reference_grid),
        "operation": "copy_then_define_projection_from_verified_matching_grid",
        "output_spatial_reference": out.spatialReference.name,
    }
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
