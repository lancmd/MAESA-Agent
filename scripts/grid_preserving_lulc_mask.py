#!/usr/bin/env python3
"""Create grid-preserving, mine-boundary-masked LULC rasters with GDAL.

This is a compatibility path for installations where ArcGIS Spatial Analyst's
Extract By Mask fails on a valid GeoTIFF.  It rasterizes the study boundary
directly on the declared master grid, copies each integer LULC value unchanged
inside the boundary and writes NoData=0 outside.  No resampling or class-code
interpolation occurs.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr


gdal.UseExceptions()
ogr.UseExceptions()

CLASS_NAMES = {
    1: "subsidence_water",
    2: "natural_water",
    3: "built_up",
    4: "cropland",
    5: "forest",
    6: "grassland",
}


def parse_inputs(items: list[str]) -> list[tuple[int, Path]]:
    result: list[tuple[int, Path]] = []
    for item in items:
        try:
            year_text, raw_path = item.split("=", 1)
            year = int(year_text)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("Use YEAR=PATH") from exc
        path = Path(raw_path).resolve()
        if not path.is_file():
            raise argparse.ArgumentTypeError(f"Raster not found: {path}")
        result.append((year, path))
    if len({year for year, _ in result}) != len(result):
        raise argparse.ArgumentTypeError("Each year must appear once")
    return sorted(result)


def metadata(dataset: gdal.Dataset) -> dict[str, object]:
    gt = dataset.GetGeoTransform()
    return {
        "columns": dataset.RasterXSize,
        "rows": dataset.RasterYSize,
        "geotransform": list(gt),
        "projection": dataset.GetProjectionRef(),
        "extent": [
            gt[0],
            gt[3] + gt[5] * dataset.RasterYSize,
            gt[0] + gt[1] * dataset.RasterXSize,
            gt[3],
        ],
    }


def grids_match(left: dict[str, object], right: dict[str, object]) -> bool:
    left_srs = osr.SpatialReference()
    right_srs = osr.SpatialReference()
    left_srs.ImportFromWkt(str(left["projection"]))
    right_srs.ImportFromWkt(str(right["projection"]))
    return (
        left["columns"] == right["columns"]
        and left["rows"] == right["rows"]
        and bool(left_srs.IsSame(right_srs))
        and np.allclose(left["geotransform"], right["geotransform"], rtol=0.0, atol=1e-10)
    )


def boundary_mask(mask_path: Path, reference: gdal.Dataset) -> np.ndarray:
    source = ogr.Open(str(mask_path), 0)
    if source is None:
        raise RuntimeError(f"Unable to read boundary: {mask_path}")
    layer = source.GetLayer(0)
    ref_srs = osr.SpatialReference()
    ref_srs.ImportFromWkt(reference.GetProjectionRef())
    layer_srs = layer.GetSpatialRef()
    if layer_srs is None:
        raise RuntimeError("Boundary has no CRS; define its true CRS before masking")

    mask_ds = gdal.GetDriverByName("MEM").Create(
        "", reference.RasterXSize, reference.RasterYSize, 1, gdal.GDT_Byte
    )
    mask_ds.SetGeoTransform(reference.GetGeoTransform())
    mask_ds.SetProjection(reference.GetProjectionRef())
    if layer_srs.IsSame(ref_srs):
        gdal.RasterizeLayer(mask_ds, [1], layer, burn_values=[1], options=["ALL_TOUCHED=FALSE"])
    else:
        # Reproject boundary geometry in memory only.  The user's source shp
        # stays intact and the mask is burned exactly on the target grid.
        transform = osr.CoordinateTransformation(layer_srs, ref_srs)
        memory_source = ogr.GetDriverByName("Memory").CreateDataSource("mask_boundary")
        memory_layer = memory_source.CreateLayer("boundary", ref_srs, ogr.wkbUnknown)
        feature_definition = memory_layer.GetLayerDefn()
        feature_count = 0
        for feature in layer:
            geometry = feature.GetGeometryRef()
            if geometry is None:
                continue
            transformed = geometry.Clone()
            transformed.Transform(transform)
            memory_feature = ogr.Feature(feature_definition)
            memory_feature.SetGeometry(transformed)
            memory_layer.CreateFeature(memory_feature)
            memory_feature = None
            feature_count += 1
        if feature_count == 0:
            raise RuntimeError("Boundary contains no valid polygon geometry")
        gdal.RasterizeLayer(mask_ds, [1], memory_layer, burn_values=[1], options=["ALL_TOUCHED=FALSE"])
        memory_layer = None
        memory_source = None
    values = mask_ds.GetRasterBand(1).ReadAsArray().astype(bool)
    source = None
    mask_ds = None
    if not values.any():
        raise RuntimeError("Boundary rasterization produced no inside pixels")
    return values


def write_masked(source_path: Path, output_path: Path, reference: dict[str, object], mask: np.ndarray) -> Counter:
    source = gdal.Open(str(source_path), gdal.GA_ReadOnly)
    source_meta = metadata(source)
    if not grids_match(source_meta, reference):
        raise RuntimeError(f"Input is not exactly aligned to the reference grid: {source_path}")
    source_band = source.GetRasterBand(1)
    datatype = source_band.DataType
    source_nodata = source_band.GetNoDataValue()
    output = gdal.GetDriverByName("GTiff").Create(
        str(output_path),
        source.RasterXSize,
        source.RasterYSize,
        1,
        datatype,
        options=["TILED=YES", "COMPRESS=DEFLATE", "PREDICTOR=2", "BIGTIFF=IF_SAFER"],
    )
    output.SetGeoTransform(source.GetGeoTransform())
    output.SetProjection(source.GetProjectionRef())
    output.SetMetadataItem("MAESA_LULC_CONTRACT", "six_class_1_to_6; outside_boundary=NoData(0)")
    output_band = output.GetRasterBand(1)
    output_band.SetNoDataValue(0)

    counts: Counter[int] = Counter()
    block_rows = 512
    for offset in range(0, source.RasterYSize, block_rows):
        rows = min(block_rows, source.RasterYSize - offset)
        values = source_band.ReadAsArray(0, offset, source.RasterXSize, rows)
        inside = mask[offset : offset + rows, :]
        values = np.asarray(values).copy()
        if source_nodata is not None:
            if np.isnan(source_nodata):
                values[np.isnan(values)] = 0
            else:
                values[values == source_nodata] = 0
        values[~inside] = 0
        codes, totals = np.unique(values[(inside) & (values != 0)], return_counts=True)
        for code, total in zip(codes, totals):
            counts[int(code)] += int(total)
        output_band.WriteArray(values, 0, offset)
    output_band.FlushCache()
    output.FlushCache()
    output_band = None
    output = None
    source_band = None
    source = None
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, help="YEAR=aligned GeoTIFF; repeat")
    parser.add_argument("--mask", required=True)
    parser.add_argument("--reference-grid", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        inputs = parse_inputs(args.input)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    mask_path = Path(args.mask).resolve()
    reference_path = Path(args.reference_grid).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not mask_path.exists() or not reference_path.is_file():
        parser.error("Mask or reference grid is missing")
    output_dir.mkdir(parents=True, exist_ok=True)

    reference_ds = gdal.Open(str(reference_path), gdal.GA_ReadOnly)
    reference = metadata(reference_ds)
    mask = boundary_mask(mask_path, reference_ds)
    reference_ds = None
    pixel_area_ha = abs(reference["geotransform"][1] * reference["geotransform"][5]) / 10000.0

    records: list[dict[str, object]] = []
    areas: list[dict[str, object]] = []
    for year, source in inputs:
        output = output_dir / f"LULC_{year}_30m_masked.tif"
        if output.exists():
            raise RuntimeError(f"Refusing to overwrite output: {output}")
        counts = write_masked(source, output, reference, mask)
        unknown = sorted(set(counts) - set(CLASS_NAMES))
        if unknown:
            raise RuntimeError(f"Unexpected class codes in {year}: {unknown}")
        verified = gdal.Open(str(output), gdal.GA_ReadOnly)
        verified_meta = metadata(verified)
        verified = None
        if not grids_match(verified_meta, reference):
            raise RuntimeError(f"Output grid drifted for {year}")
        records.append({
            "year": year,
            "source": str(source),
            "output": str(output),
            "codes_found": sorted(counts),
            "grid_check": "PASS",
            "mask_method": "gdal_rasterize_then_nodata_mask",
            "accuracy_status": "pending_validation",
        })
        for code, name in CLASS_NAMES.items():
            areas.append({
                "year": year,
                "lucode": code,
                "landuse": name,
                "pixel_count": counts.get(code, 0),
                "area_ha": round(counts.get(code, 0) * pixel_area_ha, 6),
            })

    table = output_dir / "landuse_area_statistics.csv"
    with table.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["year", "lucode", "landuse", "pixel_count", "area_ha"])
        writer.writeheader()
        writer.writerows(areas)
    report = {
        "status": "completed",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "operation": "gdal_rasterize_boundary_then_nodata_mask_on_fixed_30m_grid",
        "reference_grid": reference,
        "boundary": str(mask_path),
        "inside_pixel_count": int(mask.sum()),
        "outside_boundary": "NoData=0",
        "class_codes_interpolated": False,
        "pixel_area_ha": pixel_area_ha,
        "periods": records,
        "area_statistics_csv": str(table),
        "accuracy_status": "pending_validation",
    }
    (output_dir / "lulc_series_finalization.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
