#!/usr/bin/env python3
"""Export representative mine polygons from the local boundary shapefile.

Run with ArcGIS Pro's Python (the input shapefile is UTF-8 but ArcPy keeps the
Chinese mine/city names intact).  One largest mine is retained for each city,
then the largest remaining mines are added until eight typical mines exist.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import arcpy


def export(boundary: Path, output: Path, count: int = 8):
    groups = defaultdict(lambda: {"name": "", "city": "", "area_m2": 0.0, "geometries": []})
    fields = ["Coalmine", "City", "SHAPE@JSON", "SHAPE@AREA"]
    with arcpy.da.SearchCursor(str(boundary), fields) as rows:
        for name, city, geometry_json, area in rows:
            if not name or not geometry_json:
                continue
            item = groups[str(name)]
            item["name"] = str(name)
            item["city"] = str(city or "").strip()
            item["area_m2"] += float(area or 0.0)
            item["geometries"].append(json.loads(geometry_json))
    all_mines = sorted(groups.values(), key=lambda x: x["area_m2"], reverse=True)
    selected = []
    cities = set()
    # Keep one large representative from every city represented in the data.
    for item in all_mines:
        if item["city"] not in cities:
            selected.append(item); cities.add(item["city"])
        if len(selected) >= count:
            break
    for item in all_mines:
        if len(selected) >= count:
            break
        if item not in selected:
            selected.append(item)
    selected.sort(key=lambda x: x["area_m2"], reverse=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"source": str(boundary), "selection_rule": "one largest mine per city, then largest remaining; total eight", "mines": selected[:count]}
    # Keep Chinese names as JSON escapes because ArcGIS Pro's Python process
    # may apply the system code page while writing non-ASCII text files.
    output.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "mines": [(x["name"], x["city"], x["area_m2"]) for x in selected[:count]]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--boundary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=8)
    args = parser.parse_args()
    export(args.boundary, args.output, args.count)
