#!/usr/bin/env python3
"""Prepare aligned static and 2025 driver factors for a mining analysis boundary.

The source inputs remain read-only.  This ArcGIS Pro tool creates a fixed 30 m
WGS 84 / UTM zone 50N grid from the supplied mining boundary and writes aligned
outputs for:

* SRTM DEM, slope and aspect (when the supplied tiles completely cover the AOI);
* VIIRS 2025 median night lights and the valid-month-count quality layer; and
* 10 km-buffered OSM road, railway and waterway Euclidean distances.

Use ArcGIS Pro's ``propy`` because spatial analyst is required for terrain and
distance processing.  It refuses to replace an existing generated raster.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


TARGET_EPSG = 32650
CELL_SIZE_M = 30.0
DISTANCE_BUFFER_M = 10_000.0
NODATA = -9999.0
COMPONENTS = {"dem", "nightlights", "distances"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def output_raster(output_dir: Path, name: str) -> Path:
    target = output_dir / name
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {target}")
    return target


def crs_summary(spatial_reference: Any) -> dict[str, Any]:
    return {
        "name": spatial_reference.name,
        "factory_code": spatial_reference.factoryCode,
        "type": spatial_reference.type,
        "linear_unit": spatial_reference.linearUnitName,
    }


def raster_geometry(arcpy: Any, path: Path | str) -> dict[str, Any]:
    """Read raster geometry from Raster, not Describe.

    ArcGIS Pro releases differ in whether Describe exposes width and
    meanCellWidth.  Raster exposes the required properties consistently.
    """
    raster = arcpy.Raster(str(path))
    return {
        "spatial_reference": raster.spatialReference,
        "width": int(raster.width),
        "height": int(raster.height),
        "cell_width": float(raster.meanCellWidth),
        "cell_height": float(raster.meanCellHeight),
        "extent": raster.extent,
    }


def raster_summary(arcpy: Any, path: Path) -> dict[str, Any]:
    geometry = raster_geometry(arcpy, path)
    statistics_rebuilt = False

    def prop(name: str) -> float | None:
        nonlocal statistics_rebuilt
        try:
            value = arcpy.management.GetRasterProperties(str(path), name).getOutput(0)
        except Exception:
            # DistanceAccumulation outputs in ArcGIS Pro 3.0 can be valid but
            # lack statistics immediately after Save.  Build them once before
            # treating the factor as invalid.
            if statistics_rebuilt:
                raise
            arcpy.management.CalculateStatistics(str(path))
            statistics_rebuilt = True
            value = arcpy.management.GetRasterProperties(str(path), name).getOutput(0)
        return None if value in {None, "", "#"} else float(value)

    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "crs": crs_summary(geometry["spatial_reference"]),
        "width": geometry["width"],
        "height": geometry["height"],
        "cell_size_m": [geometry["cell_width"], geometry["cell_height"]],
        "extent": [geometry["extent"].XMin, geometry["extent"].YMin, geometry["extent"].XMax, geometry["extent"].YMax],
        "nodata": arcpy.management.GetRasterProperties(str(path), "ANYNODATA").getOutput(0) == "1",
        "statistics": {"minimum": prop("MINIMUM"), "maximum": prop("MAXIMUM"), "mean": prop("MEAN")},
    }


@contextmanager
def raster_environment(arcpy: Any, grid: Path, mask: str | None) -> Iterator[None]:
    old = {name: getattr(arcpy.env, name) for name in
           ("snapRaster", "cellSize", "extent", "mask", "outputCoordinateSystem", "compression", "overwriteOutput")}
    try:
        grid_geometry = raster_geometry(arcpy, grid)
        arcpy.env.snapRaster = str(grid)
        arcpy.env.cellSize = str(grid)
        arcpy.env.extent = str(grid)
        arcpy.env.mask = mask
        arcpy.env.outputCoordinateSystem = grid_geometry["spatial_reference"]
        arcpy.env.compression = "LZW"
        arcpy.env.overwriteOutput = False
        yield
    finally:
        for name, value in old.items():
            setattr(arcpy.env, name, value)


def aligned_extent(extent: Any) -> Any:
    xmin = math.floor(float(extent.XMin) / CELL_SIZE_M) * CELL_SIZE_M
    ymin = math.floor(float(extent.YMin) / CELL_SIZE_M) * CELL_SIZE_M
    xmax = math.ceil(float(extent.XMax) / CELL_SIZE_M) * CELL_SIZE_M
    ymax = math.ceil(float(extent.YMax) / CELL_SIZE_M) * CELL_SIZE_M
    return xmin, ymin, xmax, ymax


def ensure_grid(arcpy: Any, boundary: Path, output_dir: Path, scratch_gdb: Path,
                reference_raster: Path | None = None) -> tuple[Path, str]:
    """Create or validate a persistent 30 m full-AOI reference raster."""
    grid = output_dir / "analysis_master_grid_30m_utm50n.tif"
    target_sr = arcpy.SpatialReference(TARGET_EPSG)
    projected_boundary = str(scratch_gdb / "wanbei_boundary_utm50n")
    arcpy.management.Project(str(boundary), projected_boundary, target_sr)
    if grid.exists():
        geometry = raster_geometry(arcpy, grid)
        if geometry["spatial_reference"].factoryCode != TARGET_EPSG:
            raise ValueError(f"Existing grid CRS is not EPSG:{TARGET_EPSG}: {grid}")
        if not math.isclose(geometry["cell_width"], CELL_SIZE_M) or not math.isclose(geometry["cell_height"], CELL_SIZE_M):
            raise ValueError(f"Existing grid cell size is not {CELL_SIZE_M:g} m: {grid}")
        return grid, projected_boundary

    if reference_raster is not None:
        if not reference_raster.is_file():
            raise FileNotFoundError(f"Reference 30 m raster not found: {reference_raster}")
        reference = raster_geometry(arcpy, reference_raster)
        if reference["spatial_reference"].factoryCode != TARGET_EPSG:
            raise ValueError(f"Reference raster must use EPSG:{TARGET_EPSG}: {reference_raster}")
        if not math.isclose(reference["cell_width"], CELL_SIZE_M) or not math.isclose(reference["cell_height"], CELL_SIZE_M):
            raise ValueError(f"Reference raster must have {CELL_SIZE_M:g} m pixels: {reference_raster}")
        boundary_extent = arcpy.Describe(projected_boundary).extent
        source_extent = reference["extent"]
        covered = (source_extent.XMin <= boundary_extent.XMin and source_extent.YMin <= boundary_extent.YMin and
                   source_extent.XMax >= boundary_extent.XMax and source_extent.YMax >= boundary_extent.YMax)
        if not covered:
            raise ValueError(
                "Reference raster does not cover the complete mine boundary after projection; "
                "choose a wider 30 m image mosaic or omit --reference-raster to create a boundary grid."
            )
        arcpy.management.CopyRaster(str(reference_raster), str(grid))
        return grid, projected_boundary

    xmin, ymin, xmax, ymax = aligned_extent(arcpy.Describe(projected_boundary).extent)
    old = {name: getattr(arcpy.env, name) for name in ("extent", "outputCoordinateSystem", "compression", "overwriteOutput")}
    try:
        arcpy.env.extent = arcpy.Extent(xmin, ymin, xmax, ymax)
        arcpy.env.outputCoordinateSystem = target_sr
        arcpy.env.compression = "LZW"
        arcpy.env.overwriteOutput = False
        arcpy.sa.CreateConstantRaster(0, "INTEGER", CELL_SIZE_M, arcpy.env.extent).save(str(grid))
    finally:
        for name, value in old.items():
            setattr(arcpy.env, name, value)
    return grid, projected_boundary


def assert_aligned(arcpy: Any, grid: Path, output: Path) -> None:
    master = raster_geometry(arcpy, grid)
    item = raster_geometry(arcpy, output)
    same = (
        master["spatial_reference"].factoryCode == item["spatial_reference"].factoryCode
        and master["width"] == item["width"] and master["height"] == item["height"]
        and math.isclose(master["cell_width"], item["cell_width"], abs_tol=1e-9)
        and math.isclose(master["cell_height"], item["cell_height"], abs_tol=1e-9)
        and all(math.isclose(float(left), float(right), abs_tol=1e-6) for left, right in zip(
            (master["extent"].XMin, master["extent"].YMin, master["extent"].XMax, master["extent"].YMax),
            (item["extent"].XMin, item["extent"].YMin, item["extent"].XMax, item["extent"].YMax),
        ))
    )
    if not same:
        raise RuntimeError(f"Output does not align to fixed 30 m grid: {output}")


def source_coverage_error(arcpy: Any, dem_tiles: list[Path], boundary: Path) -> str | None:
    """Check a conservative bounding-box coverage condition before DEM mosaicking."""
    if not dem_tiles:
        return "no DEM tiles supplied"
    source_sr = raster_geometry(arcpy, dem_tiles[0])["spatial_reference"]
    temporary = str(Path(arcpy.env.scratchGDB) / f"maesa_dem_coverage_{uuid.uuid4().hex[:10]}")
    try:
        arcpy.management.Project(str(boundary), temporary, source_sr)
        boundary_extent = arcpy.Describe(temporary).extent
        extents = [raster_geometry(arcpy, path)["extent"] for path in dem_tiles]
    finally:
        if arcpy.Exists(temporary):
            arcpy.management.Delete(temporary)
    xmin, ymin = min(item.XMin for item in extents), min(item.YMin for item in extents)
    xmax, ymax = max(item.XMax for item in extents), max(item.YMax for item in extents)
    missing: list[str] = []
    if boundary_extent.XMin < xmin - 1e-9:
        missing.append(f"west to {boundary_extent.XMin:.6f} degrees (tiles begin at {xmin:.6f})")
    if boundary_extent.XMax > xmax + 1e-9:
        missing.append(f"east to {boundary_extent.XMax:.6f} degrees (tiles end at {xmax:.6f})")
    if boundary_extent.YMin < ymin - 1e-9:
        missing.append(f"south to {boundary_extent.YMin:.6f} degrees (tiles begin at {ymin:.6f})")
    if boundary_extent.YMax > ymax + 1e-9:
        missing.append(f"north to {boundary_extent.YMax:.6f} degrees (tiles end at {ymax:.6f})")
    return "; ".join(missing) if missing else None


def reference_coverage_error(arcpy: Any, boundary: Path, reference_raster: Path | None) -> str | None:
    """Check an optional image can serve as a full analysis-grid reference."""
    if reference_raster is None:
        return None
    if not reference_raster.is_file():
        return f"reference raster does not exist: {reference_raster}"
    reference = raster_geometry(arcpy, reference_raster)
    if reference["spatial_reference"].factoryCode != TARGET_EPSG:
        return f"reference raster is not EPSG:{TARGET_EPSG}"
    if not math.isclose(reference["cell_width"], CELL_SIZE_M) or not math.isclose(reference["cell_height"], CELL_SIZE_M):
        return f"reference raster does not have {CELL_SIZE_M:g} m pixels"
    temporary = str(Path(arcpy.env.scratchGDB) / f"maesa_reference_check_{uuid.uuid4().hex[:10]}")
    try:
        arcpy.management.Project(str(boundary), temporary, reference["spatial_reference"])
        boundary_extent = arcpy.Describe(temporary).extent
        image_extent = reference["extent"]
        if (image_extent.XMin <= boundary_extent.XMin and image_extent.YMin <= boundary_extent.YMin and
                image_extent.XMax >= boundary_extent.XMax and image_extent.YMax >= boundary_extent.YMax):
            return None
        return (
            "reference raster extent does not cover the whole mine boundary: "
            f"image=[{image_extent.XMin:.1f},{image_extent.YMin:.1f},{image_extent.XMax:.1f},{image_extent.YMax:.1f}], "
            f"boundary=[{boundary_extent.XMin:.1f},{boundary_extent.YMin:.1f},{boundary_extent.XMax:.1f},{boundary_extent.YMax:.1f}]"
        )
    finally:
        if arcpy.Exists(temporary):
            arcpy.management.Delete(temporary)


def prepare_dem(arcpy: Any, dem_dir: Path, boundary: Path, grid: Path, projected_boundary: str,
                output_dir: Path, scratch_gdb: Path) -> dict[str, Any]:
    tiles = sorted(path.resolve() for path in dem_dir.glob("n??_e???_1arc_v3.tif"))
    if not tiles:
        raise FileNotFoundError(f"No SRTM 1 arc-second TIFF tiles found in {dem_dir}")
    coverage_error = source_coverage_error(arcpy, tiles, boundary)
    if coverage_error:
        raise ValueError(
            "SRTM tiles do not cover the complete analysis boundary: " + coverage_error + ". "
            "Download the missing SRTM tiles before generating terrain outputs."
        )
    dem_output = output_raster(output_dir, "dem_30m_utm50n.tif")
    slope_output = output_raster(output_dir, "slope_degree_30m_utm50n.tif")
    aspect_output = output_raster(output_dir, "aspect_degree_30m_utm50n.tif")
    mosaic = str(scratch_gdb / "srtm_mosaic_wgs84")
    projected_dem = str(scratch_gdb / "srtm_projected_utm50n")
    source_geometry = raster_geometry(arcpy, tiles[0])
    arcpy.management.MosaicToNewRaster([str(path) for path in tiles], str(scratch_gdb), "srtm_mosaic_wgs84",
                                        source_geometry["spatial_reference"], "16_BIT_SIGNED", source_geometry["cell_width"],
                                        1, "FIRST", "FIRST")
    # ProjectRaster may expand the output envelope by one or more cells at a
    # coordinate-system boundary.  Project first, then write through a Spatial
    # Analyst operation under the fixed grid.  In ArcGIS Pro 3.0, Resample can
    # retain the expanded envelope even when Snap Raster is set; Spatial Analyst
    # respects both the fixed origin and the exact processing extent.
    arcpy.management.ProjectRaster(mosaic, projected_dem, raster_geometry(arcpy, grid)["spatial_reference"],
                                   "BILINEAR", CELL_SIZE_M)
    with raster_environment(arcpy, grid, projected_boundary):
        arcpy.sa.Times(arcpy.sa.Raster(projected_dem), 1).save(str(dem_output))
        arcpy.sa.Slope(arcpy.sa.Raster(str(dem_output)), "DEGREE", 1, "PLANAR").save(str(slope_output))
        arcpy.sa.Aspect(arcpy.sa.Raster(str(dem_output)), "PLANAR").save(str(aspect_output))
    for output in (dem_output, slope_output, aspect_output):
        assert_aligned(arcpy, grid, output)
    report = {
        "status": "completed", "source_tile_count": len(tiles), "source_tiles": [str(path) for path in tiles],
        "source_unit": "metres", "resampling": "bilinear", "outputs": {
            "dem": raster_summary(arcpy, dem_output), "slope_degree": raster_summary(arcpy, slope_output),
            "aspect_degree": raster_summary(arcpy, aspect_output),
        },
    }
    report_path = output_dir / "dem_terrain_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report"] = str(report_path)
    return report


def prepare_nightlights(arcpy: Any, radiance: Path, valid_month_count: Path, grid: Path, projected_boundary: str,
                        output_dir: Path, scratch_gdb: Path) -> dict[str, Any]:
    for path in (radiance, valid_month_count):
        if not path.is_file():
            raise FileNotFoundError(f"Night-light input not found: {path}")
    radiance_output = output_raster(output_dir, "nightlights_2025_median_radiance_30m.tif")
    count_output = output_raster(output_dir, "nightlights_2025_valid_month_count_30m.tif")
    radiance_projected = str(scratch_gdb / "nightlights_radiance_projected_utm50n")
    count_projected = str(scratch_gdb / "nightlights_valid_month_count_projected_utm50n")
    target_sr = raster_geometry(arcpy, grid)["spatial_reference"]
    # Apply the appropriate interpolation before the final fixed-grid write.
    # ProjectRaster itself can expand the envelope; the Spatial Analyst write
    # below enforces the master-grid dimensions and origin.
    arcpy.management.ProjectRaster(str(radiance), radiance_projected, target_sr, "BILINEAR", CELL_SIZE_M)
    arcpy.management.ProjectRaster(str(valid_month_count), count_projected, target_sr, "NEAREST", CELL_SIZE_M)
    with raster_environment(arcpy, grid, projected_boundary):
        arcpy.sa.Times(arcpy.sa.Raster(radiance_projected), 1).save(str(radiance_output))
        arcpy.sa.Times(arcpy.sa.Raster(count_projected), 1).save(str(count_output))
    for output in (radiance_output, count_output):
        assert_aligned(arcpy, grid, output)
    report = {
        "status": "completed", "source": {"radiance": str(radiance), "valid_month_count": str(valid_month_count)},
        "source_resolution": "approximately 500 m", "radiance_resampling": "bilinear",
        "quality_layer_resampling": "nearest", "interpretation": (
            "30 m alignment does not create 30 m night-light observations; use the valid-month-count layer for quality control."
        ),
        "outputs": {"radiance": raster_summary(arcpy, radiance_output), "valid_month_count": raster_summary(arcpy, count_output)},
    }
    report_path = output_dir / "nightlights_2025_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report"] = str(report_path)
    return report


def prepare_distances(arcpy: Any, sources: dict[str, Path], boundary: Path, grid: Path, projected_boundary: str,
                      output_dir: Path, scratch_gdb: Path) -> dict[str, Any]:
    target_sr = raster_geometry(arcpy, grid)["spatial_reference"]
    boundary_source_sr = arcpy.Describe(str(boundary)).spatialReference
    buffer_utm = str(scratch_gdb / "analysis_buffer_10km_utm50n")
    buffer_source = str(scratch_gdb / "analysis_buffer_10km_source")
    arcpy.analysis.Buffer(projected_boundary, buffer_utm, f"{DISTANCE_BUFFER_M:g} Meters", dissolve_option="ALL")
    arcpy.management.Project(buffer_utm, buffer_source, boundary_source_sr)
    outputs: dict[str, Any] = {}
    for name, source in sources.items():
        if not source.is_file():
            raise FileNotFoundError(f"{name} source vector is missing: {source}")
        clipped_source = str(scratch_gdb / f"{name}_within_10km_source")
        projected_source = str(scratch_gdb / f"{name}_within_10km_utm50n")
        arcpy.analysis.PairwiseClip(str(source), buffer_source, clipped_source)
        feature_count = int(arcpy.management.GetCount(clipped_source).getOutput(0))
        if feature_count == 0:
            raise ValueError(f"No {name} features occur within the 10 km boundary buffer")
        arcpy.management.Project(clipped_source, projected_source, target_sr)
        output = output_raster(output_dir, f"{name}_distance_30m.tif")
        source_cells = str(scratch_gdb / f"{name}_source_cells_30m")
        with raster_environment(arcpy, grid, None):
            oid_field = arcpy.Describe(projected_source).OIDFieldName
            arcpy.conversion.PolylineToRaster(projected_source, oid_field, source_cells, "MAXIMUM_LENGTH", "", CELL_SIZE_M)

        # The installed ArcGIS Pro 3.0 environment returns all-NoData output
        # for EucDistance and DistanceAccumulation even when their source
        # raster is non-empty.  Use the equivalent local EDT on that checked
        # 30 m source grid.  The source-cell representation limits positional
        # error to the analysis-cell scale and keeps all factors on one grid.
        import numpy as np
        from scipy.ndimage import distance_transform_edt

        source_array = arcpy.RasterToNumPyArray(source_cells, nodata_to_value=0)
        source_mask = np.asarray(source_array != 0)
        if not bool(source_mask.any()):
            raise RuntimeError(f"{name} line raster is empty after projection and 30 m rasterization")
        distance_array = distance_transform_edt(~source_mask, sampling=(CELL_SIZE_M, CELL_SIZE_M)).astype(np.float32)
        grid_extent = raster_geometry(arcpy, grid)["extent"]
        distance_raster = arcpy.NumPyArrayToRaster(
            distance_array,
            arcpy.Point(grid_extent.XMin, grid_extent.YMin),
            CELL_SIZE_M,
            CELL_SIZE_M,
        )
        distance_raster.save(str(output))
        # NumPyArrayToRaster preserves the grid geometry but not its CRS tag.
        # Coordinates are already UTM metres, so DefineProjection is the
        # correct metadata assignment; it does not move or resample pixels.
        arcpy.management.DefineProjection(str(output), target_sr)
        assert_aligned(arcpy, grid, output)
        outputs[name] = {
            "source": str(source), "buffered_feature_count": feature_count, "distance_buffer_m": DISTANCE_BUFFER_M,
            "output": raster_summary(arcpy, output),
        }
    report = {
        "status": "completed", "source_snapshot": "User-supplied Geofabrik anhui-260802-free extract",
        "method": "30 m PolylineToRaster followed by local Euclidean distance transform; planar metres in WGS 84 / UTM zone 50N. Mine-boundary masking is applied by the analysis stage.",
        "outputs": outputs,
    }
    report_path = output_dir / "osm_distance_factors_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report"] = str(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary", required=True, type=Path)
    parser.add_argument("--dem-dir", required=True, type=Path)
    parser.add_argument("--nightlights-radiance", required=True, type=Path)
    parser.add_argument("--nightlights-valid-month-count", required=True, type=Path)
    parser.add_argument("--roads", required=True, type=Path)
    parser.add_argument("--railways", required=True, type=Path)
    parser.add_argument("--waterways", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--reference-raster", type=Path,
                        help="Optional 30 m EPSG:32650 raster that fully covers the analysis boundary and defines the grid.")
    parser.add_argument("--components", default="dem,nightlights,distances",
                        help="Comma-separated subset of dem,nightlights,distances")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        import arcpy  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Run with ArcGIS Pro propy; arcpy is unavailable") from exc
    if arcpy.CheckExtension("Spatial") != "Available":
        raise RuntimeError("ArcGIS Pro Spatial Analyst is required")

    requested = {item.strip().lower() for item in args.components.split(",") if item.strip()}
    if not requested or not requested <= COMPONENTS:
        raise ValueError(f"--components must be a comma-separated subset of {sorted(COMPONENTS)}")
    boundary = args.boundary.expanduser().resolve()
    if not boundary.is_file():
        raise FileNotFoundError(f"Boundary not found: {boundary}")
    if arcpy.Describe(str(boundary)).shapeType != "Polygon":
        raise ValueError("Boundary must have polygon geometry")
    output_dir = args.output_dir.expanduser().resolve()
    dem_dir = args.dem_dir.expanduser().resolve()
    inputs = {
        "dem_dir": str(dem_dir),
        "nightlights_radiance": str(args.nightlights_radiance.expanduser().resolve()),
        "nightlights_valid_month_count": str(args.nightlights_valid_month_count.expanduser().resolve()),
        "roads": str(args.roads.expanduser().resolve()), "railways": str(args.railways.expanduser().resolve()),
        "waterways": str(args.waterways.expanduser().resolve()),
    }

    if args.dry_run:
        dem_tiles = sorted(path.resolve() for path in dem_dir.glob("n??_e???_1arc_v3.tif"))
        coverage = source_coverage_error(arcpy, dem_tiles, boundary) if dem_tiles else "no SRTM TIFFs found"
        reference = args.reference_raster.expanduser().resolve() if args.reference_raster else None
        print(json.dumps({"status": "inspected", "components": sorted(requested), "boundary": str(boundary),
                          "target_crs": f"EPSG:{TARGET_EPSG}", "cell_size_m": CELL_SIZE_M,
                          "dem_tile_count": len(dem_tiles), "dem_coverage_error": coverage,
                          "reference_raster": str(reference) if reference else None,
                          "reference_coverage_error": reference_coverage_error(arcpy, boundary, reference),
                          "inputs": inputs},
                         ensure_ascii=False, indent=2))
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    scratch_root = output_dir / f"_static_drivers_{uuid.uuid4().hex[:10]}"
    scratch_root.mkdir(parents=True, exist_ok=False)
    scratch_gdb = scratch_root / "scratch.gdb"
    arcpy.management.CreateFileGDB(str(scratch_root), scratch_gdb.name)
    arcpy.CheckOutExtension("Spatial")
    try:
        grid, projected_boundary = ensure_grid(
            arcpy, boundary, output_dir, scratch_gdb,
            args.reference_raster.expanduser().resolve() if args.reference_raster else None,
        )
        results: dict[str, Any] = {"master_grid": raster_summary(arcpy, grid)}
        if "dem" in requested:
            results["dem"] = prepare_dem(arcpy, dem_dir, boundary, grid, projected_boundary, output_dir, scratch_gdb)
        if "nightlights" in requested:
            results["nightlights"] = prepare_nightlights(
                arcpy, args.nightlights_radiance.expanduser().resolve(),
                args.nightlights_valid_month_count.expanduser().resolve(), grid, projected_boundary, output_dir, scratch_gdb,
            )
        if "distances" in requested:
            results["distances"] = prepare_distances(
                arcpy,
                {"road": args.roads.expanduser().resolve(), "railway": args.railways.expanduser().resolve(),
                 "river": args.waterways.expanduser().resolve()},
                boundary, grid, projected_boundary, output_dir, scratch_gdb,
            )
        print(json.dumps({"status": "completed", "components": sorted(requested), "results": results}, ensure_ascii=False))
    finally:
        arcpy.CheckInExtension("Spatial")
        shutil.rmtree(scratch_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
