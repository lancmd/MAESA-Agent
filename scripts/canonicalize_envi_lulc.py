#!/usr/bin/env python3
"""Convert an ENVI maximum-likelihood result to the MAESA LULC contract.

The ENVI task lists the selected ROI classes from ``Class 6`` to ``Class 1``.
Its output values therefore have the reverse ordering of the MAESA six-class
contract.  This small ArcPy utility performs that explicit remap and writes a
GeoTIFF without modifying the original ENVI result.

For Sentinel-2 classifications it can additionally aggregate 10 m thematic
pixels to the 30 m analysis grid using the majority rule.  Continuous rasters
must not be passed to this utility.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import arcpy
from arcpy.sa import Aggregate, Reclassify, RemapValue


# ENVI class order selected in the GUI -> project-wide canonical class code.
# The default matches the 2005 run.  Other years can select ROIs in a
# different order, so the mapping is deliberately a command-line contract
# rather than an implicit assumption.
DEFAULT_ENVI_TO_MAESA = [[1, 6], [2, 5], [3, 4], [4, 3], [5, 2], [6, 1]]
CLASS_NAMES = {
    1: "subsidence_water",
    2: "natural_water",
    3: "built_up",
    4: "cropland",
    5: "forest",
    6: "grassland",
}


def _describe(path: str) -> dict[str, object]:
    d = arcpy.Describe(path)
    sr = d.spatialReference
    extent = d.extent
    return {
        "path": os.path.abspath(path),
        "spatial_reference": sr.name if sr else None,
        "factory_code": getattr(sr, "factoryCode", None),
        "cell_width": float(d.meanCellWidth),
        "cell_height": float(d.meanCellHeight),
        "columns": int(d.width),
        "rows": int(d.height),
        "extent": [extent.XMin, extent.YMin, extent.XMax, extent.YMax],
    }


def _parse_mapping(value: str) -> list[list[int]]:
    """Parse ``ENVI_CODE:MAESA_CODE`` pairs and validate a six-class mapping."""
    pairs: list[list[int]] = []
    try:
        for item in value.split(","):
            source, target = item.strip().split(":", 1)
            pairs.append([int(source), int(target)])
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "Use comma-separated ENVI_CODE:MAESA_CODE pairs, for example "
            "1:4,2:3,3:6,4:5,5:1,6:2"
        ) from exc

    if sorted(source for source, _ in pairs) != [1, 2, 3, 4, 5, 6]:
        raise argparse.ArgumentTypeError("ENVI source codes must contain 1 through 6 exactly once")
    if sorted(target for _, target in pairs) != [1, 2, 3, 4, 5, 6]:
        raise argparse.ArgumentTypeError("MAESA target codes must contain 1 through 6 exactly once")
    return pairs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, help="ENVI classified raster")
    p.add_argument("--output", required=True, help="New canonical GeoTIFF")
    p.add_argument(
        "--majority-factor",
        type=int,
        default=1,
        help="Integer aggregation factor; use 3 for a 10 m -> 30 m LULC result",
    )
    p.add_argument(
        "--snap-raster",
        help="Optional canonical 30 m analysis grid used only for alignment checks",
    )
    p.add_argument(
        "--envi-to-maesa",
        default="1:6,2:5,3:4,4:3,5:2,6:1",
        type=_parse_mapping,
        help=(
            "Explicit mapping from ENVI output values to canonical MAESA codes. "
            "Default is the 2005 selection order."
        ),
    )
    p.add_argument("--report", help="Optional JSON processing report")
    p.add_argument(
        "--report-existing-output",
        action="store_true",
        help="Write a missing report for an already-created canonical output; no raster is changed.",
    )
    args = p.parse_args()

    if args.majority_factor < 1:
        p.error("--majority-factor must be at least 1")
    if not arcpy.Exists(args.input):
        p.error(f"Input raster does not exist: {args.input}")
    output_exists = arcpy.Exists(args.output)
    if output_exists and not args.report_existing_output:
        p.error(f"Refusing to overwrite an existing output: {args.output}")
    if args.report_existing_output and not output_exists:
        p.error("--report-existing-output requires an existing --output raster")

    arcpy.CheckOutExtension("Spatial")
    arcpy.env.overwriteOutput = False
    arcpy.env.snapRaster = args.snap_raster or None

    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)

    input_info = _describe(args.input)
    if not output_exists:
        canonical = Reclassify(args.input, "Value", RemapValue(args.envi_to_maesa), "NODATA")
        if args.majority_factor > 1:
            # For thematic data only: no bilinear interpolation or nearest-pixel
            # shortcut is used here.
            canonical = Aggregate(
                canonical,
                args.majority_factor,
                "MAJORITY",
                "EXPAND",
                "DATA",
            )
        canonical.save(args.output)
        arcpy.management.BuildRasterAttributeTable(args.output, "Overwrite")

    output_info = _describe(args.output)
    report = {
        "status": "completed",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": input_info,
        "output": output_info,
        "operation": {
            "type": "thematic_reclassify_then_majority_aggregate",
            "envi_to_maesa": args.envi_to_maesa,
            "maesa_classes": CLASS_NAMES,
            "majority_factor": args.majority_factor,
            "snap_raster": os.path.abspath(args.snap_raster) if args.snap_raster else None,
            "report_only_existing_output": bool(args.report_existing_output),
        },
    }
    report_path = args.report or f"{args.output}.processing.json"
    if os.path.exists(report_path):
        p.error(f"Refusing to overwrite an existing report: {report_path}")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
