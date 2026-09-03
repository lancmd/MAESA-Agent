#!/usr/bin/env python3
"""Rebuild six-class land-use and native InVEST analysis tables.

The utility intentionally recalculates transition area from the categorical
rasters instead of trusting previously exported tables.  It also summarises
2026 PLUS scenarios within the same common-support mask as the five historical
periods, so figures and report tables share one spatial-statistics contract.
"""
from __future__ import annotations

import argparse
import csv
import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any


CLASSES = {
    1: "沉陷积水", 2: "自然水体", 3: "建设用地",
    4: "耕地", 5: "林地", 6: "草地",
}
YEARS = (2005, 2010, 2015, 2020, 2025)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def valid(array, nodata):
    import numpy as np
    mask = np.isfinite(array)
    if nodata is not None:
        mask &= array != nodata
    return mask


def historical_tables(project: Path, output: Path) -> tuple[Path, Path]:
    import numpy as np
    import rasterio

    stats = project / "outputs" / "statistics_harmonized_v2_common_support"
    lulc_root = stats / "lulc"
    support_path = lulc_root / "共同生态服务统计支撑区_30m.tif"
    if not support_path.is_file():
        raise FileNotFoundError(support_path)
    with rasterio.open(support_path) as support:
        support_values = support.read(1)
        support_mask = valid(support_values, support.nodata) & (support_values > 0)
        pixel_area_ha = abs(float(support.transform.a * support.transform.e)) / 10000.0
        common_area_ha = float(support_mask.sum()) * pixel_area_ha
        reference_grid = (support.crs, support.width, support.height, support.transform)
    area_rows: list[dict[str, Any]] = []
    sources: dict[int, Path] = {}
    arrays: dict[int, Any] = {}
    for year in YEARS:
        source = lulc_root / f"LULC_{year}_30m_masked.tif"
        with rasterio.open(source) as raster:
            grid = (raster.crs, raster.width, raster.height, raster.transform)
            if grid != reference_grid:
                raise ValueError(f"{source} does not match common-support grid")
            data = raster.read(1)
            mask = support_mask & valid(data, raster.nodata)
            arrays[year] = data
            sources[year] = source
            for code, name in CLASSES.items():
                pixels = int((mask & (data == code)).sum())
                area_rows.append({"year": year, "code": code, "class": name, "pixel_count": pixels,
                                  "area_ha": round(pixels * pixel_area_ha, 6),
                                  "common_support_area_ha": round(common_area_ha, 6)})
    areas_path = output / "土地利用分类" / "五期六类土地利用面积统计_共同支撑区.csv"
    write_csv(areas_path, ["year", "code", "class", "pixel_count", "area_ha", "common_support_area_ha"], area_rows)

    transition_root = output / "土地利用转移矩阵"
    transition_rows: list[dict[str, Any]] = []
    pairs = list(zip(YEARS[:-1], YEARS[1:])) + [(2005, 2025)]
    for source_year, target_year in pairs:
        source = arrays[source_year]
        target = arrays[target_year]
        matrix_rows: list[dict[str, Any]] = []
        for source_code, source_name in CLASSES.items():
            for target_code, target_name in CLASSES.items():
                pixels = int((support_mask & (source == source_code) & (target == target_code)).sum())
                row = {"source_year": source_year, "target_year": target_year,
                       "source_code": source_code, "source_name": source_name,
                       "target_code": target_code, "target_name": target_name,
                       "pixel_count": pixels, "area_ha": round(pixels * pixel_area_ha, 6),
                       "is_persistent": int(source_code == target_code)}
                matrix_rows.append(row)
                transition_rows.append(row)
        path = transition_root / f"{source_year}_{target_year}_六类土地利用转移矩阵.csv"
        write_csv(path, list(matrix_rows[0]), matrix_rows)
    all_path = transition_root / "五期相邻及首末期六类土地利用转移矩阵_共同支撑区.csv"
    write_csv(all_path, list(transition_rows[0]), transition_rows)
    return areas_path, all_path


def scenario_tables(project: Path, output: Path) -> Path:
    import numpy as np
    import rasterio
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling

    service_root = project / "outputs" / "ecosystem_service_scenarios_harmonized_v2"
    manifest = read_json(service_root / "scenario_service_manifest_ND_UD_EP.json")
    report = read_json(service_root / "native_ND_UD_EP" / "ecosystem_service_series_report.json")
    composite_by_year = {entry["year"]: Path(entry["output"]) for entry in report["outputs"]}
    support_path = project / "outputs" / "statistics_harmonized_v2_common_support" / "lulc" / "共同生态服务统计支撑区_30m.tif"
    rows: list[dict[str, Any]] = []
    for period in manifest["periods"]:
        year = str(period["year"])
        scenario = str(period["scenario"])
        paths = {"carbon": Path(period["carbon"]), "water_yield": Path(period["water_yield"]),
                 "habitat_quality": Path(period["habitat_quality"]), "ecosystem_service": composite_by_year[year]}
        with ExitStack() as stack:
            support = stack.enter_context(rasterio.open(support_path))
            support_values = support.read(1)
            support_mask = valid(support_values, support.nodata) & (support_values > 0)
            readers = {}
            for criterion, source_path in paths.items():
                source = stack.enter_context(rasterio.open(source_path))
                same = (source.crs == support.crs and source.width == support.width and source.height == support.height
                        and source.transform.almost_equals(support.transform))
                readers[criterion] = source if same else stack.enter_context(WarpedVRT(
                    source, crs=support.crs, transform=support.transform, width=support.width,
                    height=support.height, resampling=Resampling.bilinear, nodata=source.nodata))
            counts = {key: 0 for key in paths}
            sums = {key: 0.0 for key in paths}
            for _, window in support.block_windows(1):
                local_support = support_mask[window.toslices()]
                for criterion, reader in readers.items():
                    values = reader.read(1, window=window).astype("float64", copy=False)
                    mask = local_support & valid(values, reader.nodata)
                    counts[criterion] += int(mask.sum())
                    sums[criterion] += float(values[mask].sum())
            pixel_area_m2 = abs(float(support.transform.a * support.transform.e))
        rows.append({"scenario": scenario, "year": 2026,
                     "carbon_storage_MgC": sums["carbon"],
                     "carbon_storage_10ktC": sums["carbon"] / 10000.0,
                     "mean_water_yield_mm": sums["water_yield"] / counts["water_yield"],
                     "water_yield_volume_m3": sums["water_yield"] / 1000.0 * pixel_area_m2,
                     "mean_habitat_quality_index": sums["habitat_quality"] / counts["habitat_quality"],
                     "mean_composite_ecosystem_service_index": sums["ecosystem_service"] / counts["ecosystem_service"],
                     "carbon_valid_pixels": counts["carbon"], "water_valid_pixels": counts["water_yield"],
                     "habitat_valid_pixels": counts["habitat_quality"], "composite_valid_pixels": counts["ecosystem_service"],
                     "input_assumption": "2025气候和土壤；2026累积工作面威胁"})
    path = output / "综合生态系统服务" / "2026三情景生态系统服务汇总_原生InVEST.csv"
    write_csv(path, list(rows[0]), rows)
    return path


def scenario_land_demand_table(project: Path, output: Path) -> Path:
    """Export requested versus realised CARS class demand without hiding gaps."""
    runtime = project / "runtime_plus_harmonized_v2" / "outputs" / "plus_harmonized_v2"
    rows: list[dict[str, Any]] = []
    for scenario in ("ND", "UD", "EP"):
        report = read_json(runtime / scenario / "plus_land_demand_validation.json")
        for item in report.get("rows", []):
            code = int(item["code"])
            requested = int(item["requested_cells"])
            actual = int(item["actual_cells"])
            rows.append({"scenario": scenario, "code": code, "class": CLASSES[code],
                         "requested_cells": requested, "actual_cells": actual,
                         "requested_area_ha": requested * 0.09, "actual_area_ha": actual * 0.09,
                         "delta_cells": int(item["delta_cells"]),
                         "delta_area_ha": int(item["delta_cells"]) * 0.09,
                         "delta_percent_of_requested": float(item["delta_percent_of_requested"]),
                         "validation_status": report.get("status", "unknown")})
    path = output / "土地利用分类" / "2026三情景PLUS土地需求与实际实现量.csv"
    write_csv(path, list(rows[0]), rows)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    output = args.output.expanduser().resolve()
    areas, transitions = historical_tables(project, output)
    scenarios = scenario_tables(project, output)
    land_demand = scenario_land_demand_table(project, output)
    manifest = {"status": "completed", "classification_contract": CLASSES,
                "historical_years": list(YEARS), "area_table": str(areas),
                "transition_table": str(transitions), "scenario_service_table": str(scenarios),
                "scenario_land_demand_table": str(land_demand),
                "notes": ["所有统计均使用共同生态服务统计支撑区", "情景汇总仅含已完成原生模型的ND、UD、EP"]}
    (output / "分析数据集重算说明.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
