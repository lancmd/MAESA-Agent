#!/usr/bin/env python3
"""Extract cumulative yearly workfaces from a FileGDB without altering it."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _workface_feature_class(gdb: Path) -> str:
    import arcpy

    candidates: list[str] = []
    for directory, _, names in arcpy.da.Walk(str(gdb), datatype="FeatureClass"):
        for name in names:
            candidate = os.path.join(directory, name)
            fields = {field.name for field in arcpy.ListFields(candidate)}
            if {"Year", "WF"}.issubset(fields):
                candidates.append(candidate)
    if len(candidates) != 1:
        raise RuntimeError(f"expected one workface feature class with Year/WF fields, found {len(candidates)}")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gdb", required=True, type=Path)
    parser.add_argument("--reference-grid", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--year", action="append", required=True, type=int)
    args = parser.parse_args()
    import arcpy

    gdb, reference, output = args.gdb.resolve(), args.reference_grid.resolve(), args.output_dir.resolve()
    if not gdb.is_dir() or not reference.is_file():
        raise SystemExit("FileGDB and reference grid must exist")
    output.mkdir(parents=True, exist_ok=True)
    arcpy.env.overwriteOutput = True
    source = _workface_feature_class(gdb)
    target_sr = arcpy.Describe(str(reference)).spatialReference
    records = []
    for year in sorted(set(args.year)):
        layer = arcpy.management.MakeFeatureLayer(source, f"workface_before_{year}", f"Year <= {year}").getOutput(0)
        count = int(arcpy.management.GetCount(layer)[0])
        target = output / f"workfaces_through_{year}_utm50n.shp"
        if arcpy.Exists(str(target)):
            arcpy.management.Delete(str(target))
        arcpy.management.Project(layer, str(target), target_sr)
        if "yr_through" not in {field.name for field in arcpy.ListFields(str(target))}:
            arcpy.management.AddField(str(target), "yr_through", "SHORT")
        arcpy.management.CalculateField(str(target), "yr_through", str(year), "PYTHON3")
        records.append({"year": year, "features": count, "output": str(target)})
    report = {"status": "completed", "source_gdb": str(gdb), "source_workface_class": source,
              "selection": "Year <= target year (cumulative workfaces)", "records": records}
    (output / "workface_extraction_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
