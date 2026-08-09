#!/usr/bin/env python3
"""Scale a gridded GDP raster to supplied city-level GDP totals.

The input raster supplies the within-city spatial pattern.  Each city's cells
are multiplied by one factor so that their output sum equals the supplied
target GDP.  It is therefore an auditable downscaled estimate, not a new
observed gridded GDP product.

Run this script with ArcGIS Pro's ``propy`` because it uses Spatial Analyst.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
import uuid
from pathlib import Path


def parse_targets(value: str) -> dict[str, float]:
    """Read a JSON object mapping city name to total GDP in 100 million CNY."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("--targets-json must be a JSON object") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise ValueError("--targets-json must contain at least one city")
    targets: dict[str, float] = {}
    for city, amount in parsed.items():
        if not isinstance(city, str) or not city.strip():
            raise ValueError("GDP target names must be non-empty strings")
        try:
            numeric = float(amount)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"GDP target for {city!r} is not numeric") from exc
        if numeric <= 0:
            raise ValueError(f"GDP target for {city!r} must be positive")
        targets[city.strip()] = numeric
    return targets


def load_targets(inline_json: str | None, target_file: Path | None) -> dict[str, float]:
    """Load city totals from one explicit source."""
    if bool(inline_json) == bool(target_file):
        raise ValueError("Provide exactly one of --targets-json or --targets-file")
    if target_file:
        path = target_file.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"GDP target file not found: {path}")
        return parse_targets(path.read_text(encoding="utf-8-sig"))
    return parse_targets(inline_json or "")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scale a base gridded GDP raster to city totals using ArcGIS Pro."
    )
    parser.add_argument("--input-raster", required=True, type=Path)
    parser.add_argument("--city-boundary", required=True,
                        help="Feature class or vector dataset with one feature per city.")
    parser.add_argument("--city-field", required=True)
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--targets-json",
                              help="City-to-GDP totals in 100 million CNY, e.g. {\"A市\": 123.4}")
    target_group.add_argument("--targets-file", type=Path,
                              help="UTF-8 JSON file containing city-to-GDP totals in 100 million CNY.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    try:
        import arcpy  # type: ignore
        from arcpy.sa import Con, Raster, Times, ZonalStatisticsAsTable  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Run with ArcGIS Pro propy; arcpy is unavailable") from exc

    targets_100m = load_targets(args.targets_json, args.targets_file)
    source = args.input_raster.expanduser().resolve()
    output = args.output.expanduser().resolve()
    report = args.report.expanduser().resolve()
    boundary = str(args.city_boundary)
    if not arcpy.Exists(str(source)):
        raise FileNotFoundError(f"Input raster not found: {source}")
    if not arcpy.Exists(boundary):
        raise FileNotFoundError(f"City boundary not found: {boundary}")
    if args.city_field not in {field.name for field in arcpy.ListFields(boundary)}:
        raise ValueError(f"City field not found: {args.city_field}")
    if arcpy.CheckExtension("Spatial") != "Available":
        raise RuntimeError("ArcGIS Spatial Analyst extension is required")

    source_desc = arcpy.Describe(str(source))
    raster_sr = source_desc.spatialReference
    if not raster_sr or raster_sr.name in {"Unknown", ""}:
        raise ValueError("Input raster has no valid coordinate system")
    cell_size = float(source_desc.meanCellWidth)
    if cell_size <= 0:
        raise ValueError("Input raster has invalid cell size")

    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    if report.exists():
        raise FileExistsError(f"Refusing to overwrite existing report: {report}")

    scratch_root = output.parent / f"_gdp_scale_{uuid.uuid4().hex[:10]}"
    scratch_gdb = scratch_root / "scratch.gdb"
    scratch_root.mkdir(parents=True, exist_ok=False)
    arcpy.management.CreateFileGDB(str(scratch_root), scratch_gdb.name)
    projected_cities = str(scratch_gdb / "cities_albers")
    base_zonal = str(scratch_gdb / "base_city_sum")
    output_zonal = str(scratch_gdb / "output_city_sum")
    factor_raster = str(scratch_gdb / "city_scale_factor")

    old_env = {
        "snapRaster": arcpy.env.snapRaster,
        "cellSize": arcpy.env.cellSize,
        "extent": arcpy.env.extent,
        "mask": arcpy.env.mask,
        "outputCoordinateSystem": arcpy.env.outputCoordinateSystem,
        "overwriteOutput": arcpy.env.overwriteOutput,
    }
    arcpy.CheckOutExtension("Spatial")
    try:
        arcpy.management.Project(boundary, projected_cities, raster_sr)
        actual_cities = {row[0] for row in arcpy.da.SearchCursor(projected_cities, [args.city_field])}
        missing = sorted(set(targets_100m) - actual_cities)
        unexpected = sorted(actual_cities - set(targets_100m))
        if missing or unexpected:
            message = []
            if missing:
                message.append(f"target cities absent from boundary: {missing}")
            if unexpected:
                message.append(f"boundary cities absent from targets: {unexpected}")
            raise ValueError("; ".join(message))

        arcpy.env.snapRaster = str(source)
        arcpy.env.cellSize = str(source)
        arcpy.env.extent = projected_cities
        arcpy.env.outputCoordinateSystem = raster_sr
        arcpy.env.overwriteOutput = True

        # GDP cannot be negative. Some floating-point gridded products contain
        # tiny negative artefacts at their low end, so clamp them before both
        # deriving the city factor and writing the result.
        base_raster = Con(Raster(str(source)) < 0, 0, Raster(str(source)))
        ZonalStatisticsAsTable(projected_cities, args.city_field, base_raster, base_zonal,
                               "DATA", "SUM")
        base_sums = {
            row[0]: float(row[1])
            for row in arcpy.da.SearchCursor(base_zonal, [args.city_field, "SUM"])
        }
        for city, base_sum in base_sums.items():
            if base_sum <= 0:
                raise ValueError(f"Base GDP sum for {city} is not positive: {base_sum}")

        scale_field = "GDP_SCALE"
        arcpy.management.AddField(projected_cities, scale_field, "DOUBLE")
        with arcpy.da.UpdateCursor(projected_cities, [args.city_field, scale_field]) as rows:
            for row in rows:
                city = row[0]
                target_million_cny = targets_100m[city] * 100.0
                row[1] = target_million_cny / base_sums[city]
                rows.updateRow(row)

        arcpy.conversion.PolygonToRaster(projected_cities, scale_field, factor_raster,
                                         "CELL_CENTER", "", cell_size)
        Times(base_raster, Raster(factor_raster)).save(str(output))

        ZonalStatisticsAsTable(projected_cities, args.city_field, Raster(str(output)), output_zonal,
                               "DATA", "SUM")
        output_sums = {
            row[0]: float(row[1])
            for row in arcpy.da.SearchCursor(output_zonal, [args.city_field, "SUM"])
        }
        cities = []
        for city in sorted(targets_100m):
            target_million = targets_100m[city] * 100.0
            actual_million = output_sums.get(city)
            relative_error = None if actual_million is None else (actual_million - target_million) / target_million
            cities.append({
                "city": city,
                "target_gdp_100m_cny": targets_100m[city],
                "target_gdp_million_cny": target_million,
                "base_2020_sum_million_cny": base_sums[city],
                "scale_factor": target_million / base_sums[city],
                "output_2025_sum_million_cny": actual_million,
                "relative_error": relative_error,
            })

        output_desc = arcpy.Describe(str(output))
        payload = {
            "status": "completed",
            "method": "city_total_proportional_scaling",
            "interpretation": (
                "Estimated 2025 gridded GDP. It preserves the input raster's within-city "
                "spatial pattern and scales each city to a supplied 2025 GDP total; it is not "
                "an independently observed 2025 GDP grid."
            ),
            "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "input_raster": str(source),
            "input_unit": "million CNY per cell",
            "negative_input_values_clamped_to_zero": True,
            "city_boundary": boundary,
            "city_field": args.city_field,
            "output": str(output),
            "output_unit": "million CNY per cell",
            "output_crs": output_desc.spatialReference.exportToString(),
            "output_cell_size_m": [output_desc.meanCellWidth, output_desc.meanCellHeight],
            "cities": cities,
            "validation": {
                "maximum_absolute_relative_error": max(abs(item["relative_error"] or 0.0) for item in cities),
                "target_total_million_cny": sum(item["target_gdp_million_cny"] for item in cities),
                "output_total_million_cny": sum(item["output_2025_sum_million_cny"] for item in cities),
            },
        }
        report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        csv_path = report.with_suffix(".csv")
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(cities[0]))
            writer.writeheader()
            writer.writerows(cities)
        print(json.dumps({"status": "completed", "output": str(output), "report": str(report),
                          "validation": payload["validation"]}, ensure_ascii=False))
    finally:
        for name, value in old_env.items():
            setattr(arcpy.env, name, value)
        arcpy.CheckInExtension("Spatial")
        if scratch_root.exists():
            shutil.rmtree(scratch_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
