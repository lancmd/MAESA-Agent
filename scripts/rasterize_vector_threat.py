#!/usr/bin/env python3
"""Rasterize a local vector threat source to an aligned 0/1 GeoTIFF.

The source vector is projected into the reference raster coordinate system in
a scratch folder.  Source data are never modified.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector", required=True, type=Path)
    parser.add_argument("--reference-grid", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    import arcpy
    from arcpy.sa import Con, IsNull, Raster

    source, reference, output = args.vector.resolve(), args.reference_grid.resolve(), args.output.resolve()
    if not source.is_file() or not reference.is_file():
        raise SystemExit("vector source and reference grid must exist")
    workspace = (args.workspace.resolve() if args.workspace else output.parent / "vector_threat_work").resolve()
    workspace.mkdir(parents=True, exist_ok=True); output.parent.mkdir(parents=True, exist_ok=True)
    arcpy.env.overwriteOutput = True
    arcpy.env.snapRaster = str(reference); arcpy.env.cellSize = str(reference); arcpy.env.extent = str(reference)
    target_sr = arcpy.Describe(str(reference)).spatialReference
    projected = workspace / "source_projected.shp"
    source_sr = arcpy.Describe(str(source)).spatialReference
    if arcpy.Exists(str(projected)):
        arcpy.management.Delete(str(projected))
    if source_sr.exportToString() == target_sr.exportToString():
        arcpy.management.CopyFeatures(str(source), str(projected))
    else:
        arcpy.management.Project(str(source), str(projected), target_sr)
    arcpy.management.AddField(str(projected), "threat", "SHORT")
    arcpy.management.CalculateField(str(projected), "threat", "1", "PYTHON3")
    temporary = workspace / "source_cells.tif"
    if arcpy.Exists(str(temporary)):
        arcpy.management.Delete(str(temporary))
    arcpy.conversion.FeatureToRaster(str(projected), "threat", str(temporary), 30)
    if arcpy.Exists(str(output)):
        arcpy.management.Delete(str(output))
    Con(IsNull(Raster(str(temporary))), 0, 1).save(str(output))
    arcpy.management.BuildPyramidsandStatistics(str(output))
    # ArcGIS Pro 3.0 does not expose a SUM raster property.  The source-cell
    # count is obtained from the raster attribute table instead.
    arcpy.management.BuildRasterAttributeTable(str(output), "Overwrite")
    cells = 0
    with arcpy.da.SearchCursor(str(output), ["VALUE", "COUNT"]) as rows:
        for value, count in rows:
            if int(value) == 1:
                cells += int(count)
    report = {"status": "completed", "output": str(output), "source": str(source), "reference_grid": str(reference),
              "source_cells": cells, "convention": "1=threat source; 0=absence"}
    output.with_suffix(".report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
