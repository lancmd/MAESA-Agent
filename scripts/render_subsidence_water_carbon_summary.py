#!/usr/bin/env python3
"""Create the four-panel subsidence-water/carbon time-series figure.

The project has no full-area aquatic-vegetation or bottom-sediment masks.  The
script therefore uses the available high-water LULC class (1) and the aligned
2025 positive-down subsidence raster.  Shallow water (<=1 m) and deeper water
(>1 m) are reported as transparent proxy areas; the assumptions are written to
the CSV/JSON sidecars next to the figure.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import rasterio


YEARS = [2005, 2010, 2015, 2020, 2025]


def choose_font():
    names = {f.name for f in mpl.font_manager.fontManager.ttflist}
    for name in ("SimSun", "Microsoft YaHei", "Noto Sans CJK SC", "DejaVu Sans"):
        if name in names:
            return name
    return "DejaVu Sans"


def read_candidate_densities(path: Path):
    values = {"water": [], "aquatic_vegetation": [], "bottom_sediment_40cm": []}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = row["component"]
            if key in values:
                values[key].append(float(row["skill_value"]))
    return {k: float(np.mean(v)) if v else float("nan") for k, v in values.items()}


def array_stats(path: Path):
    with rasterio.open(path) as src:
        data = src.read(1, masked=True)
        return data, src


def load_lulc(root: Path, year: int):
    candidates = [
        root / "outputs" / "classification" / "final_grid_v3" / f"LULC_{year}_30m_masked.tif",
        root / "outputs" / "classification" / "final_grid_v2" / f"LULC_{year}_30m_masked.tif",
        root / "outputs" / "classification" / "final_grid" / f"LULC_{year}_30m_masked.tif",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"未找到 {year} 年六类土地利用栅格")


def compute(root: Path, depth_path: Path, output_dir: Path):
    density_path = root / "invest" / "prepared_inputs" / "carbon" / "subsidence_water_carbon_measurement_summary.csv"
    densities = read_candidate_densities(density_path)
    depth, depth_src = array_stats(depth_path)
    depth_arr = depth.filled(np.nan).astype("float64")
    valid_depth = np.isfinite(depth_arr) & (depth_arr > 0)
    pixel_area_m2 = abs(depth_src.transform.a * depth_src.transform.e)
    pixel_area_ha = pixel_area_m2 / 10000.0
    pixel_area_km2 = pixel_area_m2 / 1_000_000.0
    rows = []
    for year in YEARS:
        lulc_path = load_lulc(root, year)
        with rasterio.open(lulc_path) as src:
            lulc = src.read(1)
            if src.shape != depth.shape or src.transform != depth_src.transform or src.crs != depth_src.crs:
                raise RuntimeError(f"{year} 年 LULC 与沉陷深度栅格未严格对齐")
        water = (lulc == 1) & valid_depth
        shallow = water & (depth_arr <= 1.0)
        deep = water & (depth_arr > 1.0)
        volume_m3 = float(np.nansum(depth_arr[water]) * pixel_area_m2)
        water_area_km2 = float(water.sum() * pixel_area_km2)
        aquatic_area_km2 = float(shallow.sum() * pixel_area_km2)
        sediment_area_km2 = float(deep.sum() * pixel_area_km2)
        # Candidate field is g C/m3; convert grams to metric tonnes.
        water_carbon_t = volume_m3 * densities["water"] / 1_000_000.0
        vegetation_carbon_t = shallow.sum() * pixel_area_ha * densities["aquatic_vegetation"]
        sediment_carbon_t = deep.sum() * pixel_area_ha * densities["bottom_sediment_40cm"]
        rows.append({
            "year": year,
            "lulc": str(lulc_path),
            "water_area_km2": water_area_km2,
            "water_volume_m3": volume_m3,
            "aquatic_vegetation_proxy_area_km2": aquatic_area_km2,
            "bottom_sediment_proxy_area_km2": sediment_area_km2,
            "water_carbon_t_c": water_carbon_t,
            "aquatic_vegetation_carbon_t_c": vegetation_carbon_t,
            "bottom_sediment_carbon_t_c": sediment_carbon_t,
            "composite_carbon_t_c": water_carbon_t + vegetation_carbon_t + sediment_carbon_t,
            "valid_water_pixel_count": int(water.sum()),
        })
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "沉陷积水库容_水生植被底泥_复合碳储量统计.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    return rows, densities, csv_path, pixel_area_m2


def make_figure(rows, densities, output_dir: Path, pixel_area_m2: float):
    mpl.rcParams.update({
        "font.family": choose_font(), "font.size": 9, "axes.unicode_minus": False,
        "axes.linewidth": 0.8, "xtick.direction": "out", "ytick.direction": "out",
    })
    years = np.array([r["year"] for r in rows])
    volume = np.array([r["water_volume_m3"] for r in rows]) / 1e6
    aquatic = np.array([r["aquatic_vegetation_proxy_area_km2"] for r in rows])
    sediment = np.array([r["bottom_sediment_proxy_area_km2"] for r in rows])
    carbon = np.array([r["composite_carbon_t_c"] for r in rows]) / 1e3
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.4), dpi=300, constrained_layout=True)
    panels = [
        (axes[0, 0], volume, "积水区水体库容", r"$10^6$ m$^3$", "#71bff0", "#2a78b8"),
        (axes[0, 1], aquatic, "水生植被覆盖面积", "km²", "#98e8c2", "#22a768"),
        (axes[1, 0], sediment, "底泥覆盖面积", "km²", "#f5dfab", "#c38d27"),
        (axes[1, 1], carbon, "沉陷积水复合碳储量", r"$10^3$ t C", "#47a33a", "#228522"),
    ]
    for ax, values, title, unit, color, edge in panels:
        ax.fill_between(years, values, color=color, alpha=0.78, linewidth=0)
        ax.plot(years, values, color=edge, linewidth=1.0, marker="o", markersize=2.8)
        ax.set_title(title, fontsize=10, pad=5)
        ax.set_ylabel(unit, fontsize=8)
        ax.set_xlim(years.min() - 1, years.max() + 1)
        ax.set_xticks(years)
        ax.set_xticklabels([str(y) for y in years], fontsize=7)
        ax.tick_params(axis="y", labelsize=7)
        ax.grid(False)
        ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
        ax.margins(y=0.08)
    axes[1, 0].set_xlabel("年份", fontsize=8); axes[1, 1].set_xlabel("年份", fontsize=8)
    fig.suptitle("皖北六市采煤沉陷区水体库容、覆盖面积及复合碳储量变化", fontsize=12, y=1.02)
    fig.text(0.01, -0.035,
             "注：库容和覆盖面积使用各期沉陷积水 LULC（编码1）与2025年30 m沉陷深度栅格；水生植被≤1 m、底泥>1 m为水深代理。碳密度为候选实测参数均值。",
             fontsize=6.5, color="#555555")
    for ext in ("png", "pdf", "svg"):
        fig.savefig(output_dir / f"皖北六市沉陷积水库容与复合碳储量时间序列.{ext}", dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--depth", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    depth = args.depth or (args.root / "subsidence" / "aligned" / "subsidence_depth_2025_positive_down_30m_utm50n.tif")
    out = args.out or (args.root / "结果" / "沉陷水体与碳储量")
    rows, densities, csv_path, pixel_area_m2 = compute(args.root, depth, out)
    make_figure(rows, densities, out, pixel_area_m2)
    metadata = {
        "years": YEARS,
        "depth_raster": str(depth),
        "pixel_area_m2": pixel_area_m2,
        "water_class": 1,
        "shallow_proxy_threshold_m": 1.0,
        "density_source": str(args.root / "invest" / "prepared_inputs" / "carbon" / "subsidence_water_carbon_measurement_summary.csv"),
        "candidate_density_means": densities,
        "status": "proxy_estimate_pending_boundary_validation",
        "limitations": [
            "未提供各期独立沉陷深度栅格，因此各期库容使用同一2025深度栅格与各期水面掩膜组合估算。",
            "未提供水生植被和底泥边界，面积按水深阈值代理，不应当作实测覆盖面积。",
            "碳密度汇总仍为 candidate_only，正式论文结果应由用户选择代表性采样组或提供区域加权方案。",
            "工作区未找到2000年六类LULC栅格，本图从2005年开始。",
        ],
        "csv": str(csv_path),
    }
    (out / "沉陷水体与复合碳储量_计算说明.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"figure": str(out / "皖北六市沉陷积水库容与复合碳储量时间序列.png"), "csv": str(csv_path), "status": metadata["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
