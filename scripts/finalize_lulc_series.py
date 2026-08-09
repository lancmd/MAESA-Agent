#!/usr/bin/env python3
"""Mask and validate a multi-period LULC series on the MAESA 30 m grid.

Inputs must already be thematic, integer-coded MAESA LULC rasters.  Each
output is clipped by mask without interpolation; the reference grid is used
for snap, extent, cell size and coordinate system.  The tool writes a single
area-statistics table for downstream change, carbon and ecosystem-service
steps.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import arcpy
from arcpy.sa import ExtractByMask


CLASS_NAMES = {
    1: "subsidence_water",
    2: "natural_water",
    3: "built_up",
    4: "cropland",
    5: "forest",
    6: "grassland",
}


def parse_series(items: list[str]) -> list[tuple[int, str]]:
    parsed: list[tuple[int, str]] = []
    for item in items:
        try:
            year_text, path = item.split("=", 1)
            year = int(year_text)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("Use YEAR=PATH, for example 2020=C:\\LULC_2020.tif") from exc
        if not arcpy.Exists(path):
            raise argparse.ArgumentTypeError(f"LULC raster not found: {path}")
        parsed.append((year, path))
    years = [year for year, _ in parsed]
    if len(years) != len(set(years)):
        raise argparse.ArgumentTypeError("Every year may occur only once")
    return sorted(parsed)


def describe(path: str) -> dict[str, object]:
    d = arcpy.Describe(path)
    extent = d.extent
    sr = d.spatialReference
    # GeoTIFFs may be represented by ArcPy's generic DescribeData, which does
    # not expose meanCellWidth/meanCellHeight.  Raster properties work for
    # both generic and RasterDataset descriptions.
    cell_width = float(arcpy.management.GetRasterProperties(path, "CELLSIZEX").getOutput(0))
    cell_height = float(arcpy.management.GetRasterProperties(path, "CELLSIZEY").getOutput(0))
    rows = int(arcpy.management.GetRasterProperties(path, "ROWCOUNT").getOutput(0))
    columns = int(arcpy.management.GetRasterProperties(path, "COLUMNCOUNT").getOutput(0))
    return {
        "path": os.path.abspath(path),
        "spatial_reference": sr.name,
        "factory_code": getattr(sr, "factoryCode", None),
        "cell_size": [cell_width, cell_height],
        "shape": [rows, columns],
        "extent": [extent.XMin, extent.YMin, extent.XMax, extent.YMax],
    }


def same_grid(one: dict[str, object], two: dict[str, object]) -> bool:
    return (
        one["factory_code"] == two["factory_code"]
        and one["cell_size"] == two["cell_size"]
        and one["shape"] == two["shape"]
        and all(abs(a - b) < 1e-9 for a, b in zip(one["extent"], two["extent"]))
    )


def raster_counts(path: str) -> dict[int, int]:
    arcpy.management.BuildRasterAttributeTable(path, "Overwrite")
    counts: dict[int, int] = {}
    with arcpy.da.SearchCursor(path, ["VALUE", "COUNT"]) as cursor:
        for value, count in cursor:
            if value is not None and count is not None:
                counts[int(value)] = int(count)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, help="YEAR=aligned LULC GeoTIFF; repeat per year")
    parser.add_argument("--mask", required=True)
    parser.add_argument("--reference-grid", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if not arcpy.Exists(args.mask):
        parser.error(f"Mask not found: {args.mask}")
    if not arcpy.Exists(args.reference_grid):
        parser.error(f"Reference grid not found: {args.reference_grid}")
    try:
        series = parse_series(args.input)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    reference = describe(args.reference_grid)

    arcpy.CheckOutExtension("Spatial")
    arcpy.env.overwriteOutput = bool(args.overwrite)
    arcpy.env.snapRaster = args.reference_grid
    arcpy.env.extent = args.reference_grid
    arcpy.env.cellSize = args.reference_grid
    arcpy.env.outputCoordinateSystem = arcpy.Describe(args.reference_grid).spatialReference

    statistics: list[dict[str, object]] = []
    validations: list[dict[str, object]] = []
    pixel_area_ha = reference["cell_size"][0] * reference["cell_size"][1] / 10000.0

    for year, source in series:
        source_info = describe(source)
        if not same_grid(source_info, reference):
            raise RuntimeError(f"{year} is not exactly aligned to the fixed analysis grid: {source_info}")
        output = output_dir / f"LULC_{year}_30m_masked.tif"
        if arcpy.Exists(str(output)):
            if not args.overwrite:
                raise RuntimeError(f"Refusing to overwrite existing output: {output}")
            arcpy.management.Delete(str(output))
        # ArcGIS Pro 3.0.1's Spatial Analyst extension may raise "Class not
        # registered" for selected GeoTIFFs even though the same vector and
        # grid work for the remaining periods.  Raster Clip with clipping
        # geometry and MAINTAIN_EXTENT is an equivalent thematic operation:
        # it assigns NoData outside the polygon and does not interpolate
        # categorical pixels.  The follow-up grid/code checks are retained.
        mask_method = "extract_by_mask"
        try:
            result = ExtractByMask(source, args.mask)
            result.save(str(output))
        except arcpy.ExecuteError:
            mask_method = "clip_geometry_maintain_extent_fallback"
            if arcpy.Exists(str(output)):
                arcpy.management.Delete(str(output))
            arcpy.management.Clip(
                source,
                "#",
                str(output),
                args.mask,
                "#",
                "ClippingGeometry",
                "MAINTAIN_EXTENT",
            )
        output_info = describe(str(output))
        if not same_grid(output_info, reference):
            raise RuntimeError(f"Masked output grid drifted from the reference grid for {year}")
        counts = raster_counts(str(output))
        unexpected = sorted(set(counts) - set(CLASS_NAMES))
        if unexpected:
            raise RuntimeError(f"Unexpected LULC codes in {year}: {unexpected}")
        for code, name in CLASS_NAMES.items():
            count = counts.get(code, 0)
            statistics.append(
                {
                    "year": year,
                    "lucode": code,
                    "landuse": name,
                    "pixel_count": count,
                    "area_ha": round(count * pixel_area_ha, 6),
                }
            )
        validations.append(
            {
                "year": year,
                "source": source_info,
                "output": output_info,
                "codes_found": sorted(counts),
                "mask_method": mask_method,
                "grid_check": "PASS",
                "accuracy_status": "pending_validation",
            }
        )

    csv_path = output_dir / "landuse_area_statistics.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["year", "lucode", "landuse", "pixel_count", "area_ha"])
        writer.writeheader()
        writer.writerows(statistics)

    payload = {
        "status": "completed",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "operation": "extract_by_mask_on_fixed_30m_analysis_grid",
        "reference_grid": reference,
        "mask": os.path.abspath(args.mask),
        "outside_boundary": "NoData",
        "class_codes_interpolated": False,
        "pixel_area_ha": pixel_area_ha,
        "periods": validations,
        "area_statistics_csv": str(csv_path),
        "accuracy_status": "pending_validation",
    }
    report = output_dir / "lulc_series_finalization.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
