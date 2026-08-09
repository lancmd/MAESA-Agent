#!/usr/bin/env python3
"""Convert ENVI ROI XML polygons into an ArcGIS-readable training vector.

The local ENVI batch tasks consume ``e.OpenVector`` inputs.  ENVI's exported
``RegionsOfInterest`` XML is a useful editing format but is not a vector
dataset, so this converter preserves every ROI polygon in a Shapefile and
attaches an explicit MAESA class code.

Run this script with ArcGIS Pro's Python environment because it writes the
Shapefile through ArcPy.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import arcpy


CLASS_CODES = {
    # Use Unicode escapes because ArcGIS Pro's Python launcher can run with a
    # legacy Windows console code page that does not safely read CJK literals
    # from a script file.
    "\u6c89\u9677\u79ef\u6c34": (1, "subsidence_water"),
    "\u6c89\u9677\u6c34\u4f53": (1, "subsidence_water"),
    "\u81ea\u7136\u6c34\u4f53": (2, "natural_water"),
    "\u5efa\u8bbe\u7528\u5730": (3, "built_up"),
    "\u5efa\u7b51\u7528\u5730": (3, "built_up"),
    "\u5c45\u6c11\u5730\u7528\u5730": (3, "built_up"),
    "\u5c45\u6c11\u70b9\u7528\u5730": (3, "built_up"),
    "\u5c45\u6c11\u70b9": (3, "built_up"),
    "\u8015\u5730": (4, "cropland"),
    "\u6797\u5730": (5, "forest"),
    "\u8349\u5730": (6, "grassland"),
    "\u88f8\u5730/\u5de5\u77ff\u7528\u5730": (7, "bare_mining_land"),
    "\u88f8\u5730": (7, "bare_mining_land"),
    "\u5de5\u77ff\u7528\u5730": (7, "bare_mining_land"),
}


def coordinates(value: str) -> list[tuple[float, float]]:
    values = value.split()
    if len(values) < 6 or len(values) % 2:
        raise ValueError("a polygon needs at least three x/y coordinate pairs")
    return [(float(values[index]), float(values[index + 1])) for index in range(0, len(values), 2)]


def convert(source: Path, target: Path, *, overwrite: bool = False) -> dict:
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.suffix.lower() != ".shp":
        raise ValueError("target must have a .shp extension")
    tree = ET.parse(source)
    root = tree.getroot()
    regions = root.findall("Region")
    if not regions:
        raise ValueError("no Region elements found in ENVI ROI XML")
    coord_text = next((item.text for item in root.findall(".//CoordSysStr") if item.text and item.text.strip()), None)
    if not coord_text:
        raise ValueError("ROI XML does not declare a coordinate system")
    spatial_reference = arcpy.SpatialReference()
    spatial_reference.loadFromString(coord_text)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not overwrite:
            raise FileExistsError(f"existing target needs --overwrite: {target}")
        arcpy.management.Delete(str(target))
    arcpy.management.CreateFeatureclass(str(target.parent), target.name, "POLYGON", spatial_reference=spatial_reference)
    arcpy.management.AddField(str(target), "class_id", "LONG")
    arcpy.management.AddField(str(target), "class_name", "TEXT", field_length=80)
    inserted = 0
    classes: dict[str, int] = {}
    with arcpy.da.InsertCursor(str(target), ["SHAPE@", "class_id", "class_name"]) as cursor:
        for region in regions:
            label = (region.attrib.get("name") or "").strip()
            if label not in CLASS_CODES:
                raise ValueError(f"unmapped ROI class name: {label!r}")
            class_id, canonical_name = CLASS_CODES[label]
            classes[canonical_name] = class_id
            for polygon in region.findall(".//Polygon"):
                coordinate_node = polygon.find(".//Coordinates")
                if coordinate_node is None or not coordinate_node.text:
                    raise ValueError(f"ROI {label!r} has a polygon without coordinates")
                points = coordinates(coordinate_node.text)
                ring = arcpy.Array([arcpy.Point(x, y) for x, y in points])
                cursor.insertRow([arcpy.Polygon(ring, spatial_reference), class_id, canonical_name])
                inserted += 1
    return {
        "status": "completed",
        "source": str(source),
        "target": str(target),
        "coordinate_system": spatial_reference.name,
        "feature_count": inserted,
        "class_mapping": classes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = convert(args.source.resolve(), args.target.resolve(), overwrite=args.overwrite)
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
