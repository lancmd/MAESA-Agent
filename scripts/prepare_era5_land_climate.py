#!/usr/bin/env python3
"""Derive annual ERA5-Land climate rasters for a study boundary.

The CDS ``monthly averaged reanalysis`` product stores accumulated variables
as a monthly mean daily accumulation.  This program therefore multiplies each
monthly ``tp`` and ``pev`` value by the number of days in that month before
summing annual totals.  ERA5-Land potential evaporation follows ECMWF's
upward-flux sign convention, so its sign is reversed before it is written as a
positive annual PET surface.

Use ArcGIS Pro's Python environment: it supplies both xarray and GDAL.  The
tool keeps the native 0.1 degree grid, clips it to the requested boundary, and
does not invent 30 m climate detail.  Alignment to the project's 30 m analysis
grid is a later continuous-raster bilinear-resampling step.
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
from pathlib import Path
from typing import Any


REQUIRED_VARIABLES = {"tp", "pev", "t2m"}
NODATA = -9999.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_years(value: str | None, available: list[int]) -> list[int]:
    if value in (None, ""):
        return available
    try:
        requested = sorted({int(item.strip()) for item in value.split(",") if item.strip()})
    except ValueError as exc:
        raise ValueError("--years must be a comma-separated list such as 2000,2005,2010") from exc
    if not requested:
        raise ValueError("--years contains no years")
    missing = sorted(set(requested) - set(available))
    if missing:
        raise ValueError(f"Requested years are not present in the NetCDF: {missing}")
    return requested


def validate_month_coverage(dataset: Any, years: list[int]) -> dict[int, list[int]]:
    times = dataset["valid_time"]
    coverage: dict[int, list[int]] = {}
    for year in years:
        months = sorted({int(item) for item in times.where(times.dt.year == year, drop=True).dt.month.values.tolist()})
        coverage[year] = months
        if months != list(range(1, 13)):
            raise ValueError(f"ERA5-Land year {year} does not contain all 12 months: {months}")
    return coverage


def grid_metadata(dataset: Any) -> tuple[list[float], list[float], float, float, tuple[float, float, float, float, float, float]]:
    import numpy as np  # type: ignore

    latitude = np.asarray(dataset["latitude"].values, dtype=float)
    longitude = np.asarray(dataset["longitude"].values, dtype=float)
    if latitude.ndim != 1 or longitude.ndim != 1 or len(latitude) < 2 or len(longitude) < 2:
        raise ValueError("ERA5-Land latitude and longitude coordinates must each be one-dimensional with at least two values")
    lat_steps = np.diff(latitude)
    lon_steps = np.diff(longitude)
    lat_step = float(abs(lat_steps[0]))
    lon_step = float(abs(lon_steps[0]))
    if lat_step <= 0 or lon_step <= 0 or not np.allclose(abs(lat_steps), lat_step) or not np.allclose(abs(lon_steps), lon_step):
        raise ValueError("ERA5-Land latitude/longitude grid is not regular")
    if latitude[0] < latitude[-1]:
        raise ValueError("ERA5-Land latitude must be ordered north to south")
    if longitude[0] > longitude[-1]:
        raise ValueError("ERA5-Land longitude must be ordered west to east")
    transform = (
        float(longitude[0] - lon_step / 2), lon_step, 0.0,
        float(latitude[0] + lat_step / 2), 0.0, -lat_step,
    )
    return latitude.tolist(), longitude.tolist(), lat_step, lon_step, transform


def write_source_raster(gdal: Any, osr: Any, array: Any, transform: tuple[float, float, float, float, float, float],
                        output: Path) -> None:
    import numpy as np  # type: ignore

    values = np.asarray(array, dtype="float32")
    if values.ndim != 2:
        raise ValueError("Annual climate array must have latitude and longitude dimensions")
    if not np.isfinite(values).all():
        values = np.where(np.isfinite(values), values, NODATA).astype("float32")
    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(
        str(output), values.shape[1], values.shape[0], 1, gdal.GDT_Float32,
        options=["TILED=YES", "COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"],
    )
    if dataset is None:
        raise RuntimeError(f"Unable to create GeoTIFF: {output}")
    try:
        spatial_reference = osr.SpatialReference()
        spatial_reference.ImportFromEPSG(4326)
        dataset.SetGeoTransform(transform)
        dataset.SetProjection(spatial_reference.ExportToWkt())
        band = dataset.GetRasterBand(1)
        band.SetNoDataValue(NODATA)
        band.WriteArray(values)
        band.FlushCache()
        dataset.FlushCache()
    finally:
        dataset = None


def clipped_statistics(gdal: Any, path: Path) -> dict[str, Any]:
    dataset = gdal.Open(str(path))
    if dataset is None:
        raise RuntimeError(f"GDAL cannot open generated raster: {path}")
    try:
        band = dataset.GetRasterBand(1)
        minimum, maximum, mean, stddev = [float(value) for value in band.GetStatistics(False, True)]
        return {
            "width": int(dataset.RasterXSize),
            "height": int(dataset.RasterYSize),
            "statistics": {"minimum": minimum, "maximum": maximum, "mean": mean, "stddev": stddev},
            "nodata": float(band.GetNoDataValue()),
            "geotransform": list(dataset.GetGeoTransform()),
            "projection": dataset.GetProjectionRef(),
        }
    finally:
        dataset = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-netcdf", required=True, type=Path)
    parser.add_argument("--boundary", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--years", help="Optional comma-separated subset of NetCDF years")
    parser.add_argument("--prefix", default="era5_land")
    parser.add_argument("--dry-run", action="store_true", help="Validate the NetCDF and boundary without writing rasters")
    args = parser.parse_args()

    try:
        import numpy as np  # type: ignore
        import xarray as xr  # type: ignore
        from osgeo import gdal, ogr, osr  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Run with ArcGIS Pro Python; xarray, NumPy and GDAL are required") from exc

    input_path = args.input_netcdf.expanduser().resolve()
    boundary = args.boundary.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"ERA5-Land NetCDF was not found: {input_path}")
    if not boundary.is_file():
        raise FileNotFoundError(f"Study boundary was not found: {boundary}")
    vector = ogr.Open(str(boundary), 0)
    if vector is None or vector.GetLayerCount() != 1:
        raise ValueError(f"Boundary is not a readable single-layer vector dataset: {boundary}")
    layer = vector.GetLayer(0)
    if layer.GetGeomType() not in {ogr.wkbPolygon, ogr.wkbMultiPolygon} or layer.GetFeatureCount() <= 0:
        raise ValueError("Boundary must contain one or more polygon features")

    with xr.open_dataset(input_path) as dataset:
        missing_variables = sorted(REQUIRED_VARIABLES - set(dataset.data_vars))
        if missing_variables:
            raise ValueError(f"NetCDF is missing required ERA5-Land variables: {missing_variables}")
        if "valid_time" not in dataset.coords or "latitude" not in dataset.coords or "longitude" not in dataset.coords:
            raise ValueError("NetCDF must provide valid_time, latitude and longitude coordinates")
        available_years = sorted({int(value) for value in dataset["valid_time"].dt.year.values.tolist()})
        years = parse_years(args.years, available_years)
        coverage = validate_month_coverage(dataset, years)
        latitude, longitude, lat_step, lon_step, transform = grid_metadata(dataset)
        metadata = {
            "input": str(input_path),
            "input_sha256": sha256_file(input_path),
            "boundary": str(boundary),
            "boundary_feature_count": int(layer.GetFeatureCount()),
            "available_years": available_years,
            "selected_years": years,
            "month_coverage": coverage,
            "variables": {
                name: {"long_name": str(dataset[name].attrs.get("long_name", "")),
                       "units": str(dataset[name].attrs.get("units", ""))}
                for name in sorted(REQUIRED_VARIABLES)
            },
            "source_grid": {
                "crs": "EPSG:4326",
                "latitude_range": [min(latitude), max(latitude)],
                "longitude_range": [min(longitude), max(longitude)],
                "cell_size_degrees": [lon_step, lat_step],
            },
        }
        if args.dry_run:
            print(json.dumps({"status": "inspected", **metadata}, ensure_ascii=False, indent=2))
            return 0

        annual_data: dict[int, dict[str, Any]] = {}
        days = dataset["valid_time"].dt.days_in_month
        for year in years:
            selected = dataset.where(dataset["valid_time"].dt.year == year, drop=True)
            year_days = days.where(days["valid_time"].dt.year == year, drop=True)
            precipitation = (selected["tp"] * year_days * 1000.0).sum("valid_time").transpose("latitude", "longitude")
            potential_evaporation = (-selected["pev"] * year_days * 1000.0).sum("valid_time").transpose("latitude", "longitude")
            temperature = (selected["t2m"].mean("valid_time") - 273.15).transpose("latitude", "longitude")
            for name, values in {"precipitation": precipitation, "potential_evaporation": potential_evaporation,
                                 "mean_temperature": temperature}.items():
                if not np.isfinite(values.values).all():
                    raise ValueError(f"{year} {name} contains NaN or infinite values")
            if float(precipitation.min()) < -1e-6 or float(potential_evaporation.min()) < -1e-6:
                raise ValueError(f"{year} generated a negative annual precipitation or PET value")
            annual_data[year] = {
                "precipitation_mm": precipitation.values,
                "potential_evaporation_mm": potential_evaporation.values,
                "mean_temperature_c": temperature.values,
            }

    output_names = [
        output_dir / f"{args.prefix}_{year}_{suffix}.tif"
        for year in years
        for suffix in ("annual_precipitation_mm", "annual_potential_evaporation_mm", "annual_mean_temperature_c")
    ]
    report_output = output_dir / f"{args.prefix}_annual_climate_report.json"
    existing = [path for path in [*output_names, report_output] if path.exists()]
    if existing:
        raise FileExistsError("Refusing to overwrite existing output(s): " + ", ".join(str(path) for path in existing))

    output_dir.mkdir(parents=True, exist_ok=True)
    scratch = output_dir / f"_era5_land_prepare_{uuid.uuid4().hex[:10]}"
    scratch.mkdir(parents=True, exist_ok=False)
    results: dict[str, Any] = {}
    try:
        for year in years:
            yearly: dict[str, Any] = {}
            for source_key, suffix, unit, description in (
                ("precipitation_mm", "annual_precipitation_mm", "mm", "Annual total precipitation"),
                ("potential_evaporation_mm", "annual_potential_evaporation_mm", "mm", "Annual potential evaporation; positive after reversing ECMWF flux sign"),
                ("mean_temperature_c", "annual_mean_temperature_c", "degrees Celsius", "Annual mean 2 metre air temperature"),
            ):
                temporary = scratch / f"{args.prefix}_{year}_{suffix}_source.tif"
                final = output_dir / f"{args.prefix}_{year}_{suffix}.tif"
                write_source_raster(gdal, osr, annual_data[year][source_key], transform, temporary)
                options = gdal.WarpOptions(
                    format="GTiff", cutlineDSName=str(boundary), cropToCutline=True,
                    dstNodata=NODATA, multithread=True,
                    creationOptions=["TILED=YES", "COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"],
                )
                warped = gdal.Warp(str(final), str(temporary), options=options)
                if warped is None:
                    raise RuntimeError(f"GDAL failed to clip {description} for {year}")
                warped = None
                summary = clipped_statistics(gdal, final)
                stats = summary["statistics"]
                if source_key != "mean_temperature_c" and stats["minimum"] < -1e-6:
                    raise ValueError(f"Clipped {description} unexpectedly contains a negative value")
                yearly[source_key] = {
                    "path": str(final), "unit": unit, "description": description,
                    "sha256": sha256_file(final), **summary,
                }
            results[str(year)] = yearly
        report = {
            "status": "completed",
            "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "dataset": "ERA5-Land monthly averaged reanalysis",
            **metadata,
            "aggregation": {
                "precipitation": "sum(tp_monthly_mean_daily_accumulation_m × days_in_month × 1000) -> mm/year",
                "potential_evaporation": "sum(-pev_monthly_mean_daily_accumulation_m × days_in_month × 1000) -> mm/year",
                "mean_temperature": "mean(t2m_monthly_K) - 273.15 -> degrees Celsius",
                "note": (
                    "ERA5-Land potential evaporation is retained as a documented PET/ET0 proxy. "
                    "It is not automatically equivalent to a station-derived FAO-56 reference ET0."
                ),
            },
            "outputs": results,
            "validation": {
                "all_selected_years_have_twelve_months": True,
                "source_grid_is_preserved_before_later_analysis_grid_alignment": True,
                "continuous_resampling_for_later_30m_alignment": "bilinear",
                "raw_netcdf_was_not_modified": True,
            },
        }
        report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "completed", "report": str(report_output), "outputs": results}, ensure_ascii=False))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
