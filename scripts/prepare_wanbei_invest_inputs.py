#!/usr/bin/env python3
"""Prepare traceable InVEST input templates for the Wanbei six-city project.

The script never modifies source spreadsheets.  It normalises the user-supplied
carbon-pool CSV, summarises the measured subsidence-water carbon workbook, and
turns the processed road/railway grids into InVEST threat-source rasters.  It
does not invent local biophysical or habitat-sensitivity parameters: those are
written as explicit calibration templates.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HIGH_WATER_CLASSES = [
    (1, "subsidence_water"),
    (2, "natural_water"),
    (3, "built_up"),
    (4, "cropland"),
    (5, "forest"),
    (6, "grassland"),
    (7, "bare_mining_land"),
]


def write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_carbon(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    required = {"lucode", "lulc_name", "c_above", "c_below", "c_soil", "c_dead"}
    if not rows or not rows[0]:
        raise ValueError(f"carbon pools table has no data rows: {path}")
    lookup = {str(name).casefold(): str(name) for name in rows[0] if name is not None}
    missing = required - set(lookup)
    if missing:
        raise ValueError("carbon pools table misses: " + ", ".join(sorted(missing)))
    output: list[dict[str, str]] = []
    for row in rows:
        output.append({key: (row.get(lookup[key], "") or "").strip() for key in sorted(required)})
    return output


def group_summary(workbook: Path, sheet: str, site_column: str, value_column: str,
                  factor: float, destination_unit: str, component: str) -> list[dict[str, Any]]:
    import pandas as pd  # type: ignore

    frame = pd.read_excel(workbook, sheet_name=sheet, header=1)
    if site_column not in frame.columns or value_column not in frame.columns:
        raise ValueError(f"{sheet} does not contain {site_column!r} and {value_column!r}")
    frame[site_column] = frame[site_column].ffill()
    frame[value_column] = pd.to_numeric(frame[value_column], errors="coerce")
    rows: list[dict[str, Any]] = []
    for site, values in frame.groupby(site_column, dropna=True)[value_column]:
        numeric = values.dropna()
        if numeric.empty:
            continue
        mean = float(numeric.mean())
        rows.append({
            "site": str(site), "component": component,
            "source_mean": round(mean, 8),
            "source_unit": str(value_column).split("/")[-1],
            "skill_value": round(mean * factor, 8),
            "skill_unit": destination_unit,
            "sample_count": int(numeric.count()),
            "conversion": f"source mean × {factor:g}",
            "selection_status": "candidate_only",
        })
    return rows


def threat_source(distance_path: Path, output: Path) -> dict[str, Any]:
    """Create a 0/1 source raster from the zero-distance cells of a line grid."""
    import numpy as np  # type: ignore
    import rasterio  # type: ignore

    with rasterio.open(distance_path) as source:
        data = source.read(1, masked=True)
        values = data.filled(math.nan)
        valid = ~data.mask
        result = np.zeros(values.shape, dtype="uint8")
        # Distances originated from rasterised centre lines: zero marks a source cell.
        result[valid & np.isfinite(values) & np.isclose(values, 0.0, atol=1e-6)] = 1
        result[~valid] = 255
        profile = source.profile.copy()
        profile.update(dtype="uint8", count=1, nodata=255, compress="deflate")
        with rasterio.open(output, "w", **profile) as target:
            target.write(result, 1)
    return {"source": str(distance_path), "output": str(output), "source_cells": int((result == 1).sum()),
            "nodata": 255, "convention": "1=threat source; 0=absence"}


def ensure_new(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing output: {path}; rerun with --overwrite")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True,
                        help="folder containing the user-supplied carbon table and measurement workbook")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    root = args.data_root.expanduser().resolve()
    sources = args.source_dir.expanduser().resolve()
    output = root / "invest" / "prepared_inputs"
    output.mkdir(parents=True, exist_ok=True)
    carbon_dir = output / "carbon"; water_dir = output / "water_yield"; habitat_dir = output / "habitat_quality"
    threat_dir = habitat_dir / "threat_sources"
    for directory in (carbon_dir, water_dir, habitat_dir, threat_dir):
        directory.mkdir(parents=True, exist_ok=True)

    carbon_source = sources / "carbon_pools.csv"
    workbook = sources / "各部分有机碳密度汇总.xlsx"
    for required in (carbon_source, workbook):
        if not required.is_file():
            raise FileNotFoundError(required)

    carbon = read_carbon(carbon_source)
    six_class = carbon_dir / "carbon_pools_6class_invest.csv"
    ensure_new(six_class, args.overwrite)
    write_csv(six_class, ["lucode", "LULC_Name", "c_above", "c_below", "c_soil", "c_dead"], carbon)

    by_code = {int(row["lucode"]): row for row in carbon}
    enhanced_rows: list[dict[str, Any]] = []
    for code, name in HIGH_WATER_CLASSES:
        source = by_code.get(code)
        enhanced_rows.append({
            "lucode": code, "LULC_Name": name,
            "c_above": source.get("c_above", "") if source else "",
            "c_below": source.get("c_below", "") if source else "",
            "c_soil": source.get("c_soil", "") if source else "",
            "c_dead": source.get("c_dead", "") if source else "",
            "parameter_status": "source_supplied" if source else "missing_user_value",
        })
    enhanced = carbon_dir / "carbon_pools_high_water_7class_template.csv"
    ensure_new(enhanced, args.overwrite)
    write_csv(enhanced, ["lucode", "LULC_Name", "c_above", "c_below", "c_soil", "c_dead", "parameter_status"], enhanced_rows)

    summary_rows = []
    summary_rows += group_summary(workbook, "水体有机碳密度", "样地名称", "平均碳密度/g/m3", 1.0, "g C/m3", "water")
    summary_rows += group_summary(workbook, "水草有机碳密度", "样地名称", "平均碳密度/g/m2", 0.01, "t C/ha", "aquatic_vegetation")
    summary_rows += group_summary(workbook, "底泥有机碳密度", "样地名称", "底泥碳密度/kg/m2", 10.0, "t C/ha", "bottom_sediment_40cm")
    summary = carbon_dir / "subsidence_water_carbon_measurement_summary.csv"
    ensure_new(summary, args.overwrite)
    write_csv(summary, ["site", "component", "source_mean", "source_unit", "skill_value", "skill_unit", "sample_count", "conversion", "selection_status"], summary_rows)
    composite = carbon_dir / "subsidence_water_composite_parameters.template.json"
    ensure_new(composite, args.overwrite)
    write_json(composite, {
        "status": "requires_user_selection",
        "source_measurement_summary": str(summary),
        "selection_rule": "Choose a representative local sampling group or calculate an area-weighted mean; do not average unrelated mine/lake groups without justification.",
        "water_carbon_density_g_c_m3": None,
        "aquatic_vegetation_carbon_density_t_c_ha": None,
        "bottom_sediment_carbon_density_t_c_ha": None,
        "bottom_sediment_basis": "40 cm in source workbook; verify that this depth matches the study design",
    })

    biophysical = water_dir / "water_yield_biophysical_7class.template.csv"
    ensure_new(biophysical, args.overwrite)
    write_csv(biophysical, ["lucode", "lulc_name", "root_depth", "kc", "lulc_veg", "parameter_status"], [
        {"lucode": code, "lulc_name": name, "root_depth": "", "kc": "", "lulc_veg": 0 if code in {1, 2, 3, 7} else 1,
         "parameter_status": "requires_local_literature_or_measurement"}
        for code, name in HIGH_WATER_CLASSES
    ])
    water_template = water_dir / "annual_water_yield_datastack.template.json"
    ensure_new(water_template, args.overwrite)
    write_json(water_template, {
        "status": "requires_calibration",
        "model_name": "natcap.invest.annual_water_yield",
        "paper_basis": {
            "method": "Budyko annual water yield; use subsidence-water volume to calibrate seasonality constant",
            "reference_only": "The thesis calibrated Z=8.1 for one 2021 study area. It is not inserted as a Wanbei six-city default."
        },
        "args": {
            "lulc_path": "SET_AFTER_LULC_IS_AVAILABLE",
            "precipitation_path": "SET_TO_ANNUAL_PRECIPITATION_RASTER",
            "eto_path": "SET_TO_VALIDATED_REFERENCE_ET0_RASTER",
            "depth_to_root_rest_layer_path": "REQUIRES_SOIL_DEPTH_RASTER_MM",
            "pawc_path": "REQUIRES_PAWC_FRACTION_RASTER",
            "watersheds_path": "REQUIRES_HYDROLOGIC_WATERSHED_POLYGONS",
            "biophysical_table_path": str(biophysical),
            "seasonality_constant": None,
        },
    })

    road_distance = root / "drivers" / "derived" / "mine_static_drivers_30m_distances_ready" / "road_distance_30m.tif"
    rail_distance = root / "drivers" / "derived" / "mine_static_drivers_30m_distances_ready" / "railway_distance_30m.tif"
    threats: list[dict[str, Any]] = []
    for name, source in (("road", road_distance), ("railway", rail_distance)):
        target = threat_dir / f"{name}_threat_source_30m.tif"
        if source.is_file():
            try:
                ensure_new(target, args.overwrite)
                report = threat_source(source, target)
                threats.append({"threat": name, "source_raster": str(target), "status": "source_raster_ready", **report})
            except ModuleNotFoundError:
                threats.append({"threat": name, "source_raster": "",
                                "status": "requires_local_gis_runtime",
                                "source": str(source),
                                "convention": "Generate a 0/1 source raster from zero-distance cells with ArcGIS Pro or rasterio."})
        else:
            threats.append({"threat": name, "source_raster": "", "status": "missing_distance_input"})
    threats.append({"threat": "mining_disturbance", "source_raster": "", "status": "requires_mine_disturbance_or_workface_raster_per_period"})
    threat_inventory = habitat_dir / "threat_source_inventory.csv"
    ensure_new(threat_inventory, args.overwrite)
    write_csv(threat_inventory, ["threat", "source_raster", "status", "source", "output", "source_cells", "nodata", "convention"], threats)

    sensitivity = habitat_dir / "habitat_sensitivity_7class.template.csv"
    ensure_new(sensitivity, args.overwrite)
    write_csv(sensitivity, ["lulc", "lulc_name", "habitat", "road", "railway", "mining_disturbance", "parameter_status"], [
        {"lulc": code, "lulc_name": name, "habitat": "", "road": "", "railway": "", "mining_disturbance": "",
         "parameter_status": "requires_expert_or_literature_parameterization"}
        for code, name in HIGH_WATER_CLASSES
    ])
    habitat_template = habitat_dir / "habitat_quality_builder.template.json"
    ensure_new(habitat_template, args.overwrite)
    write_json(habitat_template, {
        "status": "requires_parameterization",
        "paper_basis": {
            "method": "Habitat Quality evaluates land-cover habitat suitability and external threats.",
            "half_saturation_rule": "Set k to one half of the maximum degradation score after threat weights and sensitivities are selected.",
            "normalization_constant": 2.5,
        },
        "lulc_path": "SET_AFTER_LULC_IS_AVAILABLE",
        "half_saturation_constant": None,
        "threats": [
            {"name": row["threat"], "raster": row.get("source_raster", ""), "max_distance_m": None, "weight": None,
             "decay": "linear", "parameter_status": "requires_local_parameterization"}
            for row in threats
        ],
        "sensitivity_table_path": str(sensitivity),
    })

    guidance = output / "README_投入模型前检查.md"
    ensure_new(guidance, args.overwrite)
    guidance.write_text("""# 皖北六市 InVEST 预制输入\n\n本目录由 `prepare_wanbei_invest_inputs.py` 根据用户提供的碳密度 CSV、实测有机碳工作簿、已处理道路/铁路距离栅格生成。源文件保持在原位置，所有生成数据可从本目录重新创建。\n\n## 可直接复核的结果\n\n- `carbon/carbon_pools_6class_invest.csv`：保持原始六类碳密度数值，字段已规范为 InVEST 所需的小写碳库字段。\n- `carbon/subsidence_water_carbon_measurement_summary.csv`：汇总水体、水草和 40 cm 底泥的实测候选值，并统一到沉陷积水复合碳模块所用单位。\n- `habitat_quality/threat_sources/`：将已处理道路、铁路距离栅格的零距离线元转换为 0/1 威胁源栅格；它们尚未包含威胁距离和权重。\n\n## 不能自动假定的参数\n\n论文说明了方法，但没有给出可迁移到皖北六市的 Kc、根系深度、PAWC、土层厚度、生境威胁权重或各地类敏感性。因此这些值均保留为空，不能把模板直接交给 InVEST 运行。\n\n- 水源供给还需要：逐期 LULC、经确认的参考 ET0、土层有效深度、PAWC、真实水文分区，以及用沉陷积水体积或径流观测校准的 Z。论文中 Z=8.1 是单一研究区 2021 年的校准结果，仅供比对。\n- 生境质量还需要：逐期 LULC、矿业扰动威胁源（可由逐期矿业用地/工作面生成）、每种威胁的最大影响距离/权重/衰减类型，以及每个地类的生境适宜性和敏感性。\n- 高潜水位七类分类还缺第 7 类 `bare_mining_land` 的四碳库密度；在补齐前，`carbon_pools_high_water_7class_template.csv` 不应执行。\n\n模板的 `requires_*` 状态是有意保留的科学检查点，不表示程序错误。\n""", encoding="utf-8")

    manifest = output / "prepared_inputs_manifest.json"
    ensure_new(manifest, args.overwrite)
    write_json(manifest, {
        "status": "prepared_pending_parameterization",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_root": str(root),
        "sources": {"carbon_pools_csv": str(carbon_source), "organic_carbon_workbook": str(workbook)},
        "outputs": [str(path) for path in sorted(output.rglob("*")) if path.is_file()],
        "notes": [
            "Source carbon values are retained separately from thesis case-study values.",
            "No thesis-specific water-yield seasonality or habitat parameters were made a Wanbei default.",
            "Run the MAESA spatial preflight after each LULC period is available."
        ],
    })
    print(json.dumps({"status": "prepared_pending_parameterization", "output": str(output), "manifest": str(manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
