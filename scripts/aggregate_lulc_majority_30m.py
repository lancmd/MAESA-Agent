#!/usr/bin/env python3
"""Aggregate a 10 m categorical LULC GeoTIFF to a fixed 30 m grid by majority.

The implementation uses GDAL and NumPy only.  It does not invoke ArcPy and
never interpolates class codes.  NoData=0 is retained where a 30 m cell has no
valid 10 m LULC pixels.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from osgeo import gdal, osr


gdal.UseExceptions()
CLASS_CODES = np.arange(1, 7, dtype=np.uint8)


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--reference-grid", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--factor", type=int, default=3)
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    options = args()
    source_path = Path(options.input).resolve()
    grid_path = Path(options.reference_grid).resolve()
    output_path = Path(options.output).resolve()
    report_path = Path(options.report).resolve()
    require(source_path.is_file(), f"Input not found: {source_path}")
    require(grid_path.is_file(), f"Reference grid not found: {grid_path}")
    require(not output_path.exists(), f"Output already exists: {output_path}")
    require(not report_path.exists(), f"Report already exists: {report_path}")
    require(options.factor > 1, "factor must be > 1")
    source = gdal.Open(str(source_path), gdal.GA_ReadOnly)
    reference = gdal.Open(str(grid_path), gdal.GA_ReadOnly)
    require(source.RasterCount == 1, "Input must be a one-band categorical raster")
    require(source.RasterXSize == reference.RasterXSize * options.factor and
            source.RasterYSize == reference.RasterYSize * options.factor,
            "Input dimensions are not an integer factor of the reference grid")
    source_gt = source.GetGeoTransform()
    reference_gt = reference.GetGeoTransform()
    require(abs(source_gt[0] - reference_gt[0]) < 1e-6 and abs(source_gt[3] - reference_gt[3]) < 1e-6,
            "Input and reference grid origins differ")
    require(abs(source_gt[1] * options.factor - reference_gt[1]) < 1e-6 and
            abs(source_gt[5] * options.factor - reference_gt[5]) < 1e-6,
            "Input pixel size is incompatible with the reference grid")
    source_srs = osr.SpatialReference()
    reference_srs = osr.SpatialReference()
    source_srs.ImportFromWkt(source.GetProjection())
    reference_srs.ImportFromWkt(reference.GetProjection())
    require(bool(source_srs.IsSame(reference_srs)), "Input and reference CRS differ")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output = gdal.GetDriverByName("GTiff").Create(
        str(output_path), reference.RasterXSize, reference.RasterYSize, 1, gdal.GDT_Byte,
        options=["TILED=YES", "COMPRESS=LZW"],
    )
    output.SetGeoTransform(reference_gt)
    output.SetProjection(reference.GetProjection())
    output_band = output.GetRasterBand(1)
    output_band.SetNoDataValue(0)
    input_band = source.GetRasterBand(1)
    output_counts = {str(code): 0 for code in CLASS_CODES}
    source_rows_per_block = 192
    source_rows_per_block -= source_rows_per_block % options.factor
    for source_y in range(0, source.RasterYSize, source_rows_per_block):
        source_rows = min(source_rows_per_block, source.RasterYSize - source_y)
        require(source_rows % options.factor == 0, "Block rows must divide exactly by factor")
        array = input_band.ReadAsArray(0, source_y, source.RasterXSize, source_rows).astype(np.uint8, copy=False)
        out_rows = source_rows // options.factor
        grouped = array.reshape(out_rows, options.factor, reference.RasterXSize, options.factor)
        scores = np.stack([(grouped == code).sum(axis=(1, 3)) for code in CLASS_CODES], axis=0)
        maximum = scores.max(axis=0)
        result = CLASS_CODES[np.argmax(scores, axis=0)]
        result[maximum == 0] = 0
        output_band.WriteArray(result, 0, source_y // options.factor)
        values, counts = np.unique(result, return_counts=True)
        for value, count in zip(values, counts):
            if int(value) in CLASS_CODES:
                output_counts[str(int(value))] += int(count)
    output_band.FlushCache()
    output.FlushCache()
    output = None
    report = {
        "status": "completed",
        "operation": "categorical_majority_10m_to_30m",
        "input": str(source_path),
        "reference_grid": str(grid_path),
        "output": str(output_path),
        "factor": options.factor,
        "output_class_pixel_counts": output_counts,
        "nodata": 0,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
