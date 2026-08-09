#!/usr/bin/env python3
"""Delineate DEM-based drainage units for InVEST reporting.

The resulting polygons are clipped to the declared study boundary.  They are
therefore suitable for reporting annual water yield within a mining study area,
but are not a substitute for an externally validated catchment data product.
An optional waterway layer is overlaid and recorded as a traceability field.

Run with ArcGIS Pro Python::

    python derive_watershed_units.py --dem dem.tif --study-boundary mine.shp \
      --reference-grid lulc.tif --waterways waterways.shp --output units.shp
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _project_if_needed(source: Path, target: Path, target_sr) -> Path:
    import arcpy

    source_sr = arcpy.Describe(str(source)).spatialReference
    if source_sr and source_sr.name != "Unknown" and source_sr.exportToString() == target_sr.exportToString():
        return source
    if arcpy.Exists(str(target)):
        arcpy.management.Delete(str(target))
    arcpy.management.Project(str(source), str(target), target_sr)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem", required=True, type=Path)
    parser.add_argument("--study-boundary", required=True, type=Path)
    parser.add_argument("--reference-grid", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--waterways", type=Path)
    parser.add_argument("--allow-reporting-unit-fallback", action="store_true",
                        help="Use projected study polygons as InVEST aggregation units if ArcGIS returns an empty basin raster.")
    parser.add_argument("--workspace", type=Path,
                        help="Scratch workspace; defaults to the output directory.")
    args = parser.parse_args()

    import arcpy
    from arcpy.sa import Basin, Fill, FlowDirection

    dem, boundary, reference, output = (args.dem.resolve(), args.study_boundary.resolve(),
                                        args.reference_grid.resolve(), args.output.resolve())
    if not all(path.is_file() for path in (dem, boundary, reference)):
        raise SystemExit("DEM, study boundary, and reference grid must exist")
    if args.waterways and not args.waterways.resolve().is_file():
        raise SystemExit(f"waterway layer does not exist: {args.waterways}")
    workspace = (args.workspace.resolve() if args.workspace else output.parent / "watershed_work").resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    target_sr = arcpy.Describe(str(reference)).spatialReference
    arcpy.env.overwriteOutput = True
    arcpy.env.workspace = str(workspace)
    arcpy.env.snapRaster = str(reference)
    arcpy.env.cellSize = str(reference)
    arcpy.env.extent = str(reference)
    boundary_utm = _project_if_needed(boundary, workspace / "study_boundary_utm.shp", target_sr)
    waterways_utm = None
    if args.waterways:
        waterways_utm = _project_if_needed(args.waterways.resolve(), workspace / "waterways_utm.shp", target_sr)

    arcpy.CheckOutExtension("Spatial")
    filled = workspace / "filled_dem.tif"
    direction = workspace / "flow_direction.tif"
    basins = workspace / "drainage_basins.tif"
    polygon = workspace / "drainage_basins_polygon.shp"
    Fill(str(dem)).save(str(filled))
    FlowDirection(str(filled), "NORMAL").save(str(direction))
    Basin(str(direction)).save(str(basins))
    arcpy.conversion.RasterToPolygon(str(basins), str(polygon), "NO_SIMPLIFY", "VALUE", "SINGLE_OUTER_PART")
    if arcpy.Exists(str(output)):
        arcpy.management.Delete(str(output))
    arcpy.analysis.Intersect([str(polygon), str(boundary_utm)], str(output), "ALL", None, "INPUT")
    hydrologic_status = "dem_delineated"
    if int(arcpy.management.GetCount(str(output))[0]) == 0:
        if not args.allow_reporting_unit_fallback:
            raise RuntimeError("FlowDirection/Basin produced no polygons; do not use the empty output as InVEST watersheds")
        arcpy.management.Delete(str(output))
        arcpy.management.CopyFeatures(str(boundary_utm), str(output))
        hydrologic_status = "reporting_unit_fallback"
    # Shapefile fields are limited to ten characters.
    if "basin_id" not in {field.name for field in arcpy.ListFields(str(output))}:
        arcpy.management.AddField(str(output), "basin_id", "LONG")
    fields = {field.name for field in arcpy.ListFields(str(output))}
    expression = "!gridcode!" if "gridcode" in fields else "!FID! + 1"
    arcpy.management.CalculateField(str(output), "basin_id", expression, "PYTHON3")
    if "ws_id" not in {field.name for field in arcpy.ListFields(str(output))}:
        arcpy.management.AddField(str(output), "ws_id", "LONG")
    arcpy.management.CalculateField(str(output), "ws_id", "!FID! + 1", "PYTHON3")
    waterway_hits = 0
    if waterways_utm:
        clipped_waterways = workspace / "waterways_in_study.shp"
        arcpy.analysis.Clip(str(waterways_utm), str(boundary_utm), str(clipped_waterways))
        hit = workspace / "subbasin_waterway_join.shp"
        arcpy.analysis.SpatialJoin(str(output), str(clipped_waterways), str(hit), "JOIN_ONE_TO_ONE", "KEEP_ALL",
                                   match_option="INTERSECT")
        arcpy.management.Delete(str(output))
        arcpy.management.CopyFeatures(str(hit), str(output))
        if "wtr_hit" not in {field.name for field in arcpy.ListFields(str(output))}:
            arcpy.management.AddField(str(output), "wtr_hit", "SHORT")
        arcpy.management.CalculateField(str(output), "wtr_hit", "1 if !Join_Count! > 0 else 0", "PYTHON3")
        with arcpy.da.SearchCursor(str(output), ["wtr_hit"]) as rows:
            waterway_hits = sum(int(value or 0) for (value,) in rows)
    # InVEST/GDAL on Windows can fail to copy Chinese source attributes into
    # its result vector.  Keep only the contract fields it needs.
    clean = workspace / "invest_aggregation_units_clean.shp"
    if arcpy.Exists(str(clean)):
        arcpy.management.Delete(str(clean))
    arcpy.management.CreateFeatureclass(str(clean.parent), clean.name, "POLYGON", spatial_reference=target_sr)
    arcpy.management.AddField(str(clean), "ws_id", "LONG")
    arcpy.management.AddField(str(clean), "basin_id", "LONG")
    arcpy.management.AddField(str(clean), "wtr_hit", "SHORT")
    source_fields = {field.name for field in arcpy.ListFields(str(output))}
    read_fields = ["SHAPE@", "ws_id", "basin_id"] + (["wtr_hit"] if "wtr_hit" in source_fields else [])
    with arcpy.da.SearchCursor(str(output), read_fields) as source, arcpy.da.InsertCursor(
            str(clean), ["SHAPE@", "ws_id", "basin_id", "wtr_hit"]) as target:
        for row in source:
            target.insertRow([row[0], row[1], row[2], row[3] if len(row) > 3 else 0])
    arcpy.management.Delete(str(output))
    arcpy.management.CopyFeatures(str(clean), str(output))
    count = int(arcpy.management.GetCount(str(output))[0])
    report = {
        "status": "completed", "output": str(output), "subbasin_count": count,
        "hydrologic_status": hydrologic_status,
        "subbasins_intersecting_waterways": waterway_hits,
        "dem": str(dem), "reference_grid": str(reference), "study_boundary": str(boundary),
        "waterways": str(args.waterways.resolve()) if args.waterways else None,
        "interpretation": (
            "DEM-derived drainage reporting units clipped to the study boundary; verify against an authoritative watershed dataset before basin-scale claims."
            if hydrologic_status == "dem_delineated" else
            "ArcGIS FlowDirection/Basin returned no usable drainage polygons in this runtime. Projected study polygons are supplied only as InVEST aggregation units; pixel water yield can be evaluated, but results must not be described as hydrologic-basin totals."
        ),
    }
    report_path = output.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
