#!/usr/bin/env python3
"""Build a continuous hydrology DEM on a project analysis grid from SRTM tiles.

This is intentionally separate from a mine-masked DEM.  Flow direction and
watershed delineation require continuous elevation around the study area; a
DEM masked to disconnected mining polygons is not a valid hydrologic surface.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TILE = re.compile(r"n(?P<lat>\d{1,2})_e(?P<lon>\d{1,3}).*\.tif$", re.IGNORECASE)


def _target_wgs_bounds(reference: Path) -> tuple[float, float, float, float]:
    import arcpy

    desc = arcpy.Describe(str(reference))
    sr, extent, wgs84 = desc.spatialReference, desc.extent, arcpy.SpatialReference(4326)
    points = [arcpy.PointGeometry(arcpy.Point(x, y), sr).projectAs(wgs84).firstPoint
              for x in (extent.XMin, extent.XMax) for y in (extent.YMin, extent.YMax)]
    return min(p.X for p in points), min(p.Y for p in points), max(p.X for p in points), max(p.Y for p in points)


def _matching_tiles(directory: Path, bounds: tuple[float, float, float, float]) -> list[Path]:
    lon_min, lat_min, lon_max, lat_max = bounds
    selected: list[Path] = []
    for candidate in directory.glob("*.tif"):
        match = TILE.match(candidate.name)
        if not match:
            continue
        south, west = int(match.group("lat")), int(match.group("lon"))
        if west < lon_max and west + 1 > lon_min and south < lat_max and south + 1 > lat_min:
            selected.append(candidate)
    return sorted(selected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tile-dir", required=True, type=Path)
    parser.add_argument("--reference-grid", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()

    import arcpy

    tile_dir, reference, output = args.tile_dir.resolve(), args.reference_grid.resolve(), args.output.resolve()
    if not tile_dir.is_dir() or not reference.is_file():
        raise SystemExit("tile directory and reference grid must exist")
    bounds = _target_wgs_bounds(reference)
    tiles = _matching_tiles(tile_dir, bounds)
    if not tiles:
        raise SystemExit(f"no SRTM tiles cover WGS84 bounds {bounds}")
    workspace = (args.workspace.resolve() if args.workspace else output.parent / "hydrology_dem_work").resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    mosaic = workspace / "srtm_continuous_mosaic.tif"
    target_sr = arcpy.Describe(str(reference)).spatialReference
    arcpy.env.overwriteOutput = True
    arcpy.env.snapRaster = str(reference)
    arcpy.env.cellSize = str(reference)
    arcpy.env.extent = str(reference)
    if arcpy.Exists(str(mosaic)):
        arcpy.management.Delete(str(mosaic))
    arcpy.management.MosaicToNewRaster([str(path) for path in tiles], str(workspace), mosaic.name,
                                       arcpy.SpatialReference(4326), "16_BIT_SIGNED", None, 1, "LAST", "FIRST")
    if arcpy.Exists(str(output)):
        arcpy.management.Delete(str(output))
    arcpy.management.ProjectRaster(str(mosaic), str(output), target_sr, "BILINEAR", 30)
    arcpy.management.CalculateStatistics(str(output))
    report = {
        "status": "completed", "output": str(output), "reference_grid": str(reference),
        "source_tiles": [str(path) for path in tiles], "source_wgs84_bounds": bounds,
        "minimum": float(arcpy.management.GetRasterProperties(str(output), "MINIMUM")[0]),
        "maximum": float(arcpy.management.GetRasterProperties(str(output), "MAXIMUM")[0]),
        "note": "Continuous SRTM DEM generated for hydrologic preprocessing; do not replace terrain drivers without a separate comparison.",
    }
    report_path = output.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
