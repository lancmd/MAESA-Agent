#!/usr/bin/env python3
"""Export a dated GDB subsidence cloud to the MAESA positive-down grid."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _find_cloud(gdb: Path, year: int) -> str:
    import arcpy

    candidates: list[str] = []
    for directory, _, names in arcpy.da.Walk(str(gdb), datatype="RasterDataset"):
        for name in names:
            # Exact annual cloud: avoid multi-year products such as 2024_2026.
            if str(year) in name and "_" not in name:
                candidates.append(os.path.join(directory, name))
    if len(candidates) != 1:
        raise RuntimeError(f"expected one exact annual {year} subsidence raster, found {len(candidates)}")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gdb", required=True, type=Path)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--reference-grid", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    import arcpy
    from arcpy.sa import Times

    gdb, reference, output = args.gdb.resolve(), args.reference_grid.resolve(), args.output.resolve()
    if not gdb.is_dir() or not reference.is_file():
        raise SystemExit("FileGDB and reference grid must exist")
    source = _find_cloud(gdb, args.year)
    source_min = float(arcpy.management.GetRasterProperties(source, "MINIMUM")[0])
    source_max = float(arcpy.management.GetRasterProperties(source, "MAXIMUM")[0])
    if source_max > 0:
        raise RuntimeError("source cloud includes positive values; sign convention is ambiguous and was not changed")
    workspace = (args.workspace.resolve() if args.workspace else output.parent / "gdb_subsidence_work").resolve()
    workspace.mkdir(parents=True, exist_ok=True); output.parent.mkdir(parents=True, exist_ok=True)
    arcpy.env.overwriteOutput = True
    positive = workspace / f"subsidence_{args.year}_positive_down_source.tif"
    Times(arcpy.Raster(source), -1).save(str(positive))
    arcpy.env.snapRaster = str(reference); arcpy.env.cellSize = str(reference); arcpy.env.extent = str(reference)
    if arcpy.Exists(str(output)):
        arcpy.management.Delete(str(output))
    target_sr = arcpy.Describe(str(reference)).spatialReference
    arcpy.management.ProjectRaster(str(positive), str(output), target_sr, "BILINEAR", 30)
    arcpy.management.CalculateStatistics(str(output))
    report = {"status": "completed", "year": args.year, "source": source, "output": str(output),
              "source_value_range": [source_min, source_max],
              "output_value_range": [float(arcpy.management.GetRasterProperties(str(output), "MINIMUM")[0]),
                                     float(arcpy.management.GetRasterProperties(str(output), "MAXIMUM")[0])],
              "unit": "m", "convention": "positive_down", "resampling": "bilinear_to_30m"}
    output.with_suffix(".report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
