#!/usr/bin/env python3
"""Render stacked carbon-storage bars for eight representative mines."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.features import geometry_mask


YEARS = [2005, 2010, 2015, 2020, 2025]
DENSITIES = np.array([0.0, 48.21, 38.05, 65.25, 82.43, 93.07, 66.28], dtype="float64")


def choose_font():
    available = {f.name for f in mpl.font_manager.fontManager.ttflist}
    for name in ("SimSun", "Microsoft YaHei", "Noto Sans CJK SC", "DejaVu Sans"):
        if name in available:
            return name
    return "DejaVu Sans"


def lulc_path(root: Path, year: int) -> Path:
    for directory in ("final_grid_v3", "final_grid_v2", "final_grid"):
        path = root / "outputs" / "classification" / directory / f"LULC_{year}_30m_masked.tif"
        if path.exists():
            return path
    raise FileNotFoundError(f"未找到 {year} 年 LULC 栅格")


def mine_mask(mine, shape, transform):
    mask = np.zeros(shape, dtype=bool)
    for geometry in mine["geometries"]:
        rings = geometry.get("rings", [])
        if not rings:
            continue
        geojson = {"type": "Polygon", "coordinates": rings}
        mask |= geometry_mask([geojson], out_shape=shape, transform=transform, invert=True, all_touched=False)
    return mask


def compute(root: Path, mine_json: Path, output_dir: Path):
    payload = json.loads(mine_json.read_text(encoding="utf-8"))
    mines = payload["mines"]
    stats = []
    for year in YEARS:
        path = lulc_path(root, year)
        with rasterio.open(path) as src:
            lulc = src.read(1)
            transform, shape, crs = src.transform, src.shape, src.crs
            if str(crs).upper() != "EPSG:32650":
                raise RuntimeError(f"{year} 年 LULC CRS 不是 EPSG:32650: {crs}")
            carbon_pixel = DENSITIES[np.clip(lulc, 0, len(DENSITIES) - 1)] * 0.09
            for mine in mines:
                mask = mine_mask(mine, shape, transform)
                valid = mask & (lulc >= 1) & (lulc <= 6)
                stats.append({
                    "year": year,
                    "mine": mine["name"],
                    "city": mine["city"],
                    "carbon_t_c": float(carbon_pixel[valid].sum()),
                    "area_ha": float(valid.sum() * 0.09),
                    "valid_pixel_count": int(valid.sum()),
                })
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "典型矿区碳储量统计_2005_2025.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(stats[0]))
        writer.writeheader(); writer.writerows(stats)
    return payload, stats, csv_path


def make_figure(payload, stats, output_dir: Path, study_name: str):
    mpl.rcParams.update({"font.family": choose_font(), "font.size": 9, "axes.unicode_minus": False})
    mines = payload["mines"]
    names = [m["name"] for m in mines]
    cities = [m["city"] for m in mines]
    lookup = {(r["year"], r["mine"]): r["carbon_t_c"] for r in stats}
    matrix = np.array([[lookup[(year, name)] for year in YEARS] for name in names]) / 1000.0
    total = matrix.sum(axis=0)
    fig, ax = plt.subplots(figsize=(7.2, 5.1), dpi=300)
    colors = ["#f3f0a3", "#e0f3db", "#c7e9c0", "#a8ddb5", "#7bccc4", "#6baed6", "#9ecae1", "#bcbddc"]
    bottom = np.zeros(len(YEARS))
    for i, (name, city) in enumerate(zip(names, cities)):
        ax.bar(YEARS, matrix[i], bottom=bottom, width=2.8, color=colors[i % len(colors)],
               edgecolor="white", linewidth=0.35, label=f"{name}（{city}）")
        bottom += matrix[i]
    ax.plot(YEARS, total, color="red", marker="^", markersize=4.3, linewidth=0.85, label="总碳储量", zorder=5)
    ax.set_title(f"{study_name}典型矿区碳储量变化（2005—2025年）", fontsize=12, pad=8)
    ax.set_xlabel("年份", fontsize=9)
    ax.set_ylabel(r"碳储量（$10^3$ t C）", fontsize=9)
    ax.set_xticks(YEARS)
    ax.set_xlim(2003, 2027)
    ax.tick_params(labelsize=8)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=6.5,
              frameon=True, framealpha=0.95, borderpad=0.4, handlelength=1.2)
    fig.tight_layout()
    for ext in ("png", "pdf", "svg"):
        fig.savefig(output_dir / f"典型矿区碳储量变化_2005_2025.{ext}", dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mines", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--study-name", default="研究区")
    args = parser.parse_args()
    mines = args.mines or (args.root / "subsidence" / "typical_mines_8_utm50n.json")
    out = args.out or (args.root / "结果" / "分析统计图与表" / "典型矿区碳储量")
    payload, stats, csv_path = compute(args.root, mines, out)
    make_figure(payload, stats, out, args.study_name)
    meta = {
        "years": YEARS,
        "mine_boundary_selection": str(mines),
        "selection_rule": payload.get("selection_rule"),
        "carbon_density_t_c_per_ha": DENSITIES[1:].tolist(),
        "lulc_codes": {1: "沉陷积水", 2: "自然水体", 3: "建设用地", 4: "耕地", 5: "林地", 6: "草地"},
        "unit": "t C; figure axis uses 10^3 t C",
        "status": "validated_spatial_alignment",
        "csv": str(csv_path),
    }
    (out / "典型矿区碳储量_来源与参数.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"figure": str(out / "典型矿区碳储量变化_2005_2025.png"), "csv": str(csv_path), "mines": [m["name"] for m in payload["mines"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
