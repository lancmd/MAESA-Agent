"""Summarize five-period native InVEST carbon storage for representative mines.

The ten mines are selected reproducibly as the ten largest 2025 carbon-storage
contributors among the supplied mine-boundary features.  The output is a mine
comparison dataset, not a replacement for the regional common-support total.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import fiona
import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.warp import transform_geom


YEARS = (2005, 2010, 2015, 2020, 2025)


def native_carbon_path(project: Path, year: int) -> Path:
    return project / "outputs" / "invest" / "carbon_series_harmonized_v2" / str(year) / "tot_c_cur.tif"


def read_features(boundary: Path, target_crs: object) -> list[dict]:
    records: list[dict] = []
    with fiona.open(boundary) as source:
        source_crs = source.crs_wkt or source.crs
        if not source_crs:
            raise ValueError(f"矿区边界缺少坐标系：{boundary}")
        for feature_index, feature in enumerate(source):
            geometry = feature.get("geometry")
            if not geometry:
                continue
            records.append(
                {
                    "feature_index": feature_index,
                    "mine_name": str(feature["properties"].get("Coalmine") or f"矿区{feature_index + 1}"),
                    "city": str(feature["properties"].get("City") or "未标注城市"),
                    "geometry": transform_geom(source_crs, target_crs, geometry, precision=6),
                }
            )
    return records


def zonal_total_carbon(raster_path: Path, geometry: dict) -> float:
    with rasterio.open(raster_path) as src:
        try:
            clipped, _ = mask(src, [geometry], crop=True, filled=False)
        except ValueError:
            return 0.0
        data = clipped[0]
        valid = np.ma.compressed(data)
        if valid.size == 0:
            return 0.0
        # InVEST total-carbon rasters are Mg C per pixel, numerically tonnes C.
        return float(valid.sum(dtype=np.float64) / 1.0e4)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--result-root", required=True, type=Path)
    parser.add_argument("--top-n", default=10, type=int)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    result_root = args.result_root.expanduser().resolve()
    first_raster = native_carbon_path(project, YEARS[-1])
    if not first_raster.exists():
        raise FileNotFoundError(first_raster)
    with rasterio.open(first_raster) as ref:
        features = read_features(project / "boundaries" / "mine_boundary.shp", ref.crs)

    rows: list[dict] = []
    for feature in features:
        row = {"feature_index": feature["feature_index"], "矿区": feature["mine_name"], "地市": feature["city"]}
        for year in YEARS:
            row[f"{year}年碳储量（10^4 t C）"] = zonal_total_carbon(native_carbon_path(project, year), feature["geometry"])
        rows.append(row)

    key = f"{YEARS[-1]}年碳储量（10^4 t C）"
    selected = sorted(rows, key=lambda row: row[key], reverse=True)[: args.top_n]
    output_dir = result_root / "分析统计图与表" / "典型矿区"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "典型矿区2005至2025年碳储量变化_原生InVEST.csv"
    headers = ["feature_index", "矿区", "地市"] + [f"{year}年碳储量（10^4 t C）" for year in YEARS]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(selected)

    manifest = {
        "status": "completed",
        "selection_rule": "按2025年原生InVEST碳储量从97个矿界要素中取前10个",
        "unit": "10^4 t C",
        "years": YEARS,
        "source_rasters": [str(native_carbon_path(project, year)) for year in YEARS],
        "boundary": str(project / "boundaries" / "mine_boundary.shp"),
        "note": "矿界可能相互叠置；本表用于典型矿区对比，不能与区域总量直接相加。",
    }
    (output_dir / "典型矿区碳储量统计说明.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
