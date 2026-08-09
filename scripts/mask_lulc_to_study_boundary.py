#!/usr/bin/env python3
"""Mask a categorical LULC raster to the supplied study boundary.

ENVI may assign a valid class to black/background pixels outside the imagery
footprint.  This utility retains the project reference grid and writes NoData
outside the analysis boundary, without interpolating or changing class codes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import arcpy
from arcpy.sa import ExtractByMask


def describe(path: str) -> dict[str, object]:
    data = arcpy.Describe(path)
    extent = data.extent
    sr = data.spatialReference
    return {
        "path": os.path.abspath(path),
        "spatial_reference": sr.name if sr else None,
        "cell_size": [float(data.meanCellWidth), float(data.meanCellHeight)],
        "shape": [int(data.height), int(data.width)],
        "extent": [extent.XMin, extent.YMin, extent.XMax, extent.YMax],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Canonical, aligned LULC raster")
    parser.add_argument("--mask", required=True, help="Study or mine-boundary polygon")
    parser.add_argument("--reference-grid", required=True, help="Fixed project analysis grid")
    parser.add_argument("--output", required=True, help="New masked GeoTIFF")
    parser.add_argument("--report", required=True, help="New JSON processing record")
    args = parser.parse_args()

    for label, path in (("input", args.input), ("mask", args.mask), ("reference grid", args.reference_grid)):
        if not arcpy.Exists(path):
            parser.error(f"{label} does not exist: {path}")
    if arcpy.Exists(args.output) or os.path.exists(args.report):
        parser.error("Refusing to overwrite an existing output or report")

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    arcpy.CheckOutExtension("Spatial")
    arcpy.env.overwriteOutput = False
    arcpy.env.snapRaster = args.reference_grid
    arcpy.env.extent = args.reference_grid
    arcpy.env.cellSize = args.reference_grid
    arcpy.env.outputCoordinateSystem = arcpy.Describe(args.reference_grid).spatialReference

    source = describe(args.input)
    masked = ExtractByMask(args.input, args.mask)
    masked.save(args.output)
    arcpy.management.BuildRasterAttributeTable(args.output, "Overwrite")

    record = {
        "status": "completed",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "operation": "extract_by_mask_on_fixed_analysis_grid",
        "source": source,
        "mask": os.path.abspath(args.mask),
        "reference_grid": os.path.abspath(args.reference_grid),
        "output": describe(args.output),
        "outside_boundary": "NoData",
        "class_codes_interpolated": False,
    }
    with open(args.report, "w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
