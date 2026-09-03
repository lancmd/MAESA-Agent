#!/usr/bin/env python3
"""Summarise InVEST-equivalent carbon totals by LULC class and render a figure."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


LABELS = {1: "沉陷积水", 2: "自然水体", 3: "建设用地", 4: "耕地", 5: "林地", 6: "草地"}
COLORS = {1: "#225ea8", 2: "#41b6c4", 3: "#d73027", 4: "#fdae61", 5: "#1a9850", 6: "#a6d96a"}


def parse_series(values: list[str]) -> list[tuple[int, Path]]:
    result = []
    for value in values:
        year, marker, raster = value.partition("=")
        if not marker:
            raise ValueError("--lulc uses YEAR=PATH")
        result.append((int(year), Path(raster).resolve()))
    return sorted(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--carbon-pools", required=True, type=Path)
    parser.add_argument("--lulc", action="append", default=[])
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument("--output-figure", required=True, type=Path)
    args = parser.parse_args()
    pools: dict[int, float] = {}
    with args.carbon_pools.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            pools[int(float(row["lucode"]))] = sum(float(row[field]) for field in ("c_above", "c_below", "c_soil", "c_dead"))
    import numpy as np
    try:
        import rasterio
    except ImportError:
        rasterio = None
        from osgeo import gdal
    rows = []
    for year, raster in parse_series(args.lulc):
        counts: Counter[int] = Counter()
        if rasterio is not None:
            with rasterio.open(raster) as source:
                area = abs(float(source.transform.a * source.transform.e)) / 10000.0
                for _, window in source.block_windows(1):
                    data = source.read(1, window=window, masked=True).compressed()
                    # ``np.unique`` alone only contributed one occurrence per
                    # class per block, which understated all rasterio-derived
                    # areas and carbon totals.  Count every matching pixel.
                    for value in np.unique(data):
                        code = int(value)
                        if code in LABELS:
                            counts[code] += int(np.count_nonzero(data == value))
        else:
            dataset = gdal.Open(str(raster))
            if dataset is None:
                raise RuntimeError(f"Cannot open raster: {raster}")
            transform = dataset.GetGeoTransform()
            area = abs(float(transform[1] * transform[5])) / 10000.0
            band = dataset.GetRasterBand(1)
            block_x, block_y = band.GetBlockSize()
            block_x = block_x or min(1024, dataset.RasterXSize)
            block_y = block_y or min(1024, dataset.RasterYSize)
            nodata = band.GetNoDataValue()
            for yoff in range(0, dataset.RasterYSize, block_y):
                height = min(block_y, dataset.RasterYSize - yoff)
                for xoff in range(0, dataset.RasterXSize, block_x):
                    width = min(block_x, dataset.RasterXSize - xoff)
                    data = band.ReadAsArray(xoff, yoff, width, height)
                    if nodata is not None:
                        data = data[data != nodata]
                    for value in np.unique(data):
                        code = int(value)
                        if code in LABELS:
                            counts[code] += int(np.count_nonzero(data == value))
            dataset = None
        for code in sorted(LABELS):
            pixel_count = counts[code]
            rows.append({"year": year, "lucode": code, "landuse": LABELS[code], "pixel_count": pixel_count,
                         "area_ha": pixel_count * area, "carbon_density_mg_c_ha": pools[code],
                         "carbon_storage_mg_c": pixel_count * area * pools[code]})
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    years = sorted({row["year"] for row in rows})
    fig, axis = plt.subplots(figsize=(11.7, 6.6), constrained_layout=True)
    bottom = [0.0] * len(years)
    for code in sorted(LABELS):
        values = [next(row["carbon_storage_mg_c"] for row in rows if row["year"] == year and row["lucode"] == code) / 1e6 for year in years]
        axis.bar(years, values, bottom=bottom, width=3.4, color=COLORS[code], label=LABELS[code])
        bottom = [left + right for left, right in zip(bottom, values)]
    axis.set_title("2005—2025年各土地利用类型碳储量", fontsize=16, fontweight="bold")
    axis.set_xlabel("年份"); axis.set_ylabel("碳储量（million Mg C）")
    axis.grid(axis="y", alpha=0.22); axis.legend(ncol=3, frameon=False)
    fig.text(0.01, 0.01, "按用户提供碳密度表计算；土地利用分类独立精度验证状态：pending_validation。", fontsize=8, color="#374151")
    fig.savefig(args.output_figure.with_suffix(".png"), dpi=300, facecolor="white")
    fig.savefig(args.output_figure.with_suffix(".svg"), facecolor="white")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
