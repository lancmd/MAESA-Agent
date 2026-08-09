#!/usr/bin/env python3
"""Prepare a clipped GHS-POP population-density driver with ArcGIS Pro.

GHS-POP tiles store estimated resident-population counts per raster cell.  This
tool discovers one epoch's tiles, clips their intersection with a supplied
study boundary, mosaics the clipped pieces, and writes both the population
count raster and a people-per-square-kilometre density raster.  It never edits
the downloaded source tiles.

Run with ArcGIS Pro's ``propy`` because Extract by Mask requires Spatial
Analyst.  For the 2025 GHS-POP 100 m Mollweide product, the density conversion
is ``count * 1,000,000 / cell_area_m2``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def spatial_reference_summary(spatial_reference: Any) -> dict[str, Any]:
    return {
        "name": spatial_reference.name,
        "factory_code": spatial_reference.factoryCode,
        "type": spatial_reference.type,
        "linear_unit": spatial_reference.linearUnitName,
    }


def extent_overlaps(first: Any, second: Any) -> bool:
    """Return whether two ArcPy extents overlap without allocating geometry."""
    return not (
        first.XMax <= second.XMin
        or first.XMin >= second.XMax
        or first.YMax <= second.YMin
        or first.YMin >= second.YMax
    )


def raster_stats(arcpy: Any, raster: str) -> dict[str, float | None]:
    def property_value(name: str) -> float | None:
        value = arcpy.management.GetRasterProperties(raster, name).getOutput(0)
        return None if value in {"", "#", None} else float(value)

    return {
        "minimum": property_value("MINIMUM"),
        "maximum": property_value("MAXIMUM"),
        "mean": property_value("MEAN"),
    }


def discover_tiles(source_directory: Path, pattern: str) -> list[Path]:
    tiles = sorted(path.resolve() for path in source_directory.rglob(pattern) if path.is_file())
    if not tiles:
        raise FileNotFoundError(
            f"No source tiles matching {pattern!r} were found below {source_directory}"
        )
    return tiles


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clip 2025 GHS-POP tiles and derive a population-density driver."
    )
    parser.add_argument("--tiles-dir", required=True, type=Path)
    parser.add_argument("--boundary", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--tile-glob", default="GHS_POP_E2025_GLOBE_R2023A_*.tif")
    parser.add_argument("--prefix", default="population_2025")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect inputs and spatial overlap only; do not create output files.",
    )
    args = parser.parse_args()

    try:
        import arcpy  # type: ignore
        from arcpy.sa import ExtractByMask, Raster, Times  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Run this tool with ArcGIS Pro propy; arcpy is unavailable") from exc

    tiles_dir = args.tiles_dir.expanduser().resolve()
    boundary = args.boundary.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not tiles_dir.is_dir():
        raise NotADirectoryError(f"Tile directory not found: {tiles_dir}")
    if not boundary.is_file():
        raise FileNotFoundError(f"Boundary dataset not found: {boundary}")
    if not arcpy.Exists(str(boundary)):
        raise ValueError(f"ArcGIS Pro cannot read boundary dataset: {boundary}")

    tiles = discover_tiles(tiles_dir, args.tile_glob)
    boundary_desc = arcpy.Describe(str(boundary))
    if boundary_desc.shapeType != "Polygon":
        raise ValueError(f"Boundary must be polygon geometry, got {boundary_desc.shapeType}")
    if int(arcpy.management.GetCount(str(boundary)).getOutput(0)) == 0:
        raise ValueError("Boundary has no features")
    boundary_sr = boundary_desc.spatialReference
    if not boundary_sr or boundary_sr.name in {"", "Unknown"}:
        raise ValueError("Boundary has no valid coordinate system")

    first_desc = arcpy.Describe(str(tiles[0]))
    source_sr = first_desc.spatialReference
    if not source_sr or source_sr.name in {"", "Unknown"}:
        raise ValueError(f"Source tile has no valid coordinate system: {tiles[0]}")
    cell_width = float(first_desc.meanCellWidth)
    cell_height = float(first_desc.meanCellHeight)
    if cell_width <= 0 or cell_height <= 0:
        raise ValueError("Source tile has invalid cell size")
    if source_sr.type != "Projected" or source_sr.linearUnitName.lower() not in {"meter", "metre"}:
        raise ValueError(
            "Population-density conversion needs a metre-based projected source raster; "
            f"got {source_sr.name} ({source_sr.type}, {source_sr.linearUnitName})"
        )

    tile_info: list[dict[str, Any]] = []
    for tile in tiles:
        desc = arcpy.Describe(str(tile))
        tile_sr = desc.spatialReference
        if tile_sr.exportToString() != source_sr.exportToString():
            raise ValueError(f"Tile CRS differs from the first tile: {tile}")
        if abs(float(desc.meanCellWidth) - cell_width) > 1e-9 or abs(float(desc.meanCellHeight) - cell_height) > 1e-9:
            raise ValueError(f"Tile cell size differs from the first tile: {tile}")
        tile_info.append(
            {
                "path": str(tile),
                "sha256": sha256_file(tile),
                "cell_size_m": [float(desc.meanCellWidth), float(desc.meanCellHeight)],
                "extent": {
                    "xmin": desc.extent.XMin,
                    "ymin": desc.extent.YMin,
                    "xmax": desc.extent.XMax,
                    "ymax": desc.extent.YMax,
                },
            }
        )

    # Project does not support the in_memory workspace in this ArcGIS Pro
    # release, so use its managed scratch geodatabase for the short preflight.
    memory_boundary = str(Path(arcpy.env.scratchGDB) / f"population_boundary_{uuid.uuid4().hex[:10]}")
    try:
        arcpy.management.Project(str(boundary), memory_boundary, source_sr)
        projected_boundary_desc = arcpy.Describe(memory_boundary)
        overlapping_tile_paths = [
            str(tile)
            for tile in tiles
            if extent_overlaps(arcpy.Describe(str(tile)).extent, projected_boundary_desc.extent)
        ]
        projected_boundary_extent = {
            "xmin": projected_boundary_desc.extent.XMin,
            "ymin": projected_boundary_desc.extent.YMin,
            "xmax": projected_boundary_desc.extent.XMax,
            "ymax": projected_boundary_desc.extent.YMax,
        }
    finally:
        if arcpy.Exists(memory_boundary):
            arcpy.management.Delete(memory_boundary)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "inspected",
                    "tile_count": len(tiles),
                    "tile_glob": args.tile_glob,
                    "source_crs": spatial_reference_summary(source_sr),
                    "source_cell_size_m": [cell_width, cell_height],
                    "boundary": str(boundary),
                    "boundary_crs": spatial_reference_summary(boundary_sr),
                    "boundary_feature_count": int(arcpy.management.GetCount(str(boundary)).getOutput(0)),
                    "boundary_extent_in_source_crs": projected_boundary_extent,
                    "overlapping_tile_count": len(overlapping_tile_paths),
                    "overlapping_tiles": overlapping_tile_paths,
                    "tiles": tile_info,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    count_name = f"{args.prefix}_wanbei_six_cities_count_100m.tif"
    density_name = f"{args.prefix}_wanbei_six_cities_density_100m_people_per_km2.tif"
    report_name = f"{args.prefix}_wanbei_six_cities_population_report.json"
    count_output = output_dir / count_name
    density_output = output_dir / density_name
    report_output = output_dir / report_name
    existing = [path for path in (count_output, density_output, report_output) if path.exists()]
    if existing:
        rendered = ", ".join(str(path) for path in existing)
        raise FileExistsError(f"Refusing to overwrite existing output(s): {rendered}")

    output_dir.mkdir(parents=True, exist_ok=True)
    scratch_root = output_dir / f"_population_prepare_{uuid.uuid4().hex[:10]}"
    scratch_gdb = scratch_root / "scratch.gdb"
    scratch_root.mkdir(parents=True, exist_ok=False)
    arcpy.management.CreateFileGDB(str(scratch_root), scratch_gdb.name)
    projected_boundary = str(scratch_gdb / "boundary_source_crs")

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
        arcpy.management.Project(str(boundary), projected_boundary, source_sr)
        projected_desc = arcpy.Describe(projected_boundary)
        arcpy.env.snapRaster = str(tiles[0])
        arcpy.env.cellSize = str(tiles[0])
        arcpy.env.outputCoordinateSystem = source_sr
        arcpy.env.extent = projected_desc.extent
        arcpy.env.overwriteOutput = False

        clipped_rasters: list[str] = []
        intersecting_tiles: list[Path] = []
        for index, tile in enumerate(tiles):
            desc = arcpy.Describe(str(tile))
            if not extent_overlaps(desc.extent, projected_desc.extent):
                continue
            clipped = str(scratch_gdb / f"clip_{index:02d}")
            ExtractByMask(str(tile), projected_boundary).save(clipped)
            if arcpy.management.GetRasterProperties(clipped, "ALLNODATA").getOutput(0) == "1":
                arcpy.management.Delete(clipped)
                continue
            clipped_rasters.append(clipped)
            intersecting_tiles.append(tile)

        if not clipped_rasters:
            raise ValueError(
                "None of the supplied GHS-POP tiles overlap the study boundary; "
                "check the boundary CRS and selected global tiles."
            )

        arcpy.management.MosaicToNewRaster(
            clipped_rasters,
            str(output_dir),
            count_name,
            source_sr,
            "32_BIT_FLOAT",
            cell_width,
            1,
            "FIRST",
            "FIRST",
        )
        count_stats = raster_stats(arcpy, str(count_output))
        if count_stats["minimum"] is not None and count_stats["minimum"] < 0:
            raise ValueError(
                f"Population count output contains a negative valid value: {count_stats['minimum']}"
            )

        cell_area_m2 = cell_width * cell_height
        density_factor = 1_000_000.0 / cell_area_m2
        Times(Raster(str(count_output)), density_factor).save(str(density_output))
        density_stats = raster_stats(arcpy, str(density_output))
        count_desc = arcpy.Describe(str(count_output))
        density_desc = arcpy.Describe(str(density_output))
        payload = {
            "status": "completed",
            "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "dataset": "GHS-POP R2023A epoch 2025",
            "interpretation": (
                "The GHS-POP 2025 epoch is an estimated/projection population surface. "
                "The density raster is suitable as a continuous socioeconomic driver, not as "
                "a population census or a true 30 m observation."
            ),
            "boundary": {
                "path": str(boundary),
                "feature_count": int(arcpy.management.GetCount(str(boundary)).getOutput(0)),
                "source_crs": spatial_reference_summary(boundary_sr),
            },
            "source_tiles": [item for item in tile_info if Path(item["path"]) in intersecting_tiles],
            "all_discovered_tile_count": len(tiles),
            "intersecting_tile_count": len(intersecting_tiles),
            "analysis_crs": spatial_reference_summary(source_sr),
            "cell_size_m": [cell_width, cell_height],
            "cell_area_m2": cell_area_m2,
            "outputs": {
                "population_count": {
                    "path": str(count_output),
                    "unit": "estimated residents per 100 m cell",
                    "sha256": sha256_file(count_output),
                    "statistics": count_stats,
                    "crs": spatial_reference_summary(count_desc.spatialReference),
                    "cell_size_m": [float(count_desc.meanCellWidth), float(count_desc.meanCellHeight)],
                },
                "population_density": {
                    "path": str(density_output),
                    "unit": "estimated residents per square kilometre",
                    "formula": "population_count * 1,000,000 / cell_area_m2",
                    "sha256": sha256_file(density_output),
                    "statistics": density_stats,
                    "crs": spatial_reference_summary(density_desc.spatialReference),
                    "cell_size_m": [float(density_desc.meanCellWidth), float(density_desc.meanCellHeight)],
                },
            },
            "validation": {
                "source_tiles_share_crs": True,
                "source_tiles_share_cell_size": True,
                "output_count_minimum_nonnegative": count_stats["minimum"] is None or count_stats["minimum"] >= 0,
                "resampling": "none; source 100 m grid preserved",
                "next_step": (
                    "Align this continuous driver to the fixed 30 m analysis grid with bilinear "
                    "resampling only after the master LULC grid is available."
                ),
            },
        }
        report_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "completed", "outputs": payload["outputs"], "report": str(report_output)}, ensure_ascii=False))
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
