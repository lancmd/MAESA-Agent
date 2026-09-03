#!/usr/bin/env python3
"""Build unit-checked tables and publication figures for the Wanbei report.

The historical and scenario summaries are derived from the formal MAESA
outputs.  InVEST Carbon ``tot_c_cur.tif`` stores Mg C per pixel; its raster
sum is therefore already the total carbon stock and must not be multiplied by
the 30 m pixel area again.  Annual Water Yield is stored in millimetres and is
converted to cubic metres with ``depth_mm * pixel_area_m2 / 1000``.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio


YEARS = [2005, 2010, 2015, 2020, 2025]
SCENARIOS = ["ND", "UD", "EP", "RE"]
SCENARIO_CN = {"ND": "自然发展", "UD": "城镇发展", "EP": "生态保护", "RE": "资源开采"}
CLASS_CN = {1: "沉陷积水", 2: "自然水体", 3: "建设用地", 4: "耕地", 5: "林地", 6: "草地"}
COLORS = {"carbon": "#7B3294", "water": "#0086A8", "habitat": "#2E8B57", "service": "#C65D21"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def masked(path: Path):
    with rasterio.open(path) as src:
        return src.read(1, masked=True), src.transform, src.crs


def raster_sum(path: Path) -> float:
    array, _, _ = masked(path)
    return float(array.sum())


def raster_mean(path: Path) -> float:
    array, _, _ = masked(path)
    return float(array.mean())


def water_total(path: Path) -> tuple[float, float]:
    array, transform, _ = masked(path)
    area_m2 = abs(transform.a * transform.e)
    return float((array * area_m2 / 1000.0).sum()), float(array.mean())


def setup_fonts() -> None:
    matplotlib.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["SimSun", "Microsoft YaHei", "SimHei", "Arial Unicode MS"],
        "font.serif": ["Times New Roman", "SimSun"],
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "font.size": 9,
        "axes.titlesize": 10.5,
        "axes.labelsize": 9.5,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "legend.fontsize": 8.5,
    })


def save(fig, out: Path, stem: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "pdf", "svg"):
        fig.savefig(out / f"{stem}.{suffix}", dpi=600 if suffix == "png" else None,
                    bbox_inches="tight", facecolor="white")
    plt.close(fig)


def collect(root: Path) -> dict:
    stats = root / "outputs" / "statistics_harmonized_v2_common_support"
    historical_path = stats / "生态系统服务五期汇总统计_原生InVEST生境.csv"
    if not historical_path.is_file():
        raise FileNotFoundError(
            "common-support statistics are required before report generation: "
            f"{historical_path}"
        )
    by_year: dict[int, dict[str, float]] = {}
    for row in read_csv(historical_path):
        year = int(row["year"])
        by_year[year] = {
            "carbon_mg_c": float(row["carbon_storage_MgC"]),
            "water_m3": float(row["water_yield_volume_m3"]),
            "water_mean_mm": float(row["mean_water_yield_mm"]),
            "habitat_mean": float(row["mean_habitat_quality_index"]),
            "service_mean": float(row["mean_composite_ecosystem_service_index"]),
            "common_boundary_area_ha": float(row["common_boundary_area_ha"]),
        }
    missing_years = sorted(set(YEARS) - set(by_year))
    if missing_years:
        raise ValueError(f"common-support statistics omit years: {missing_years}")

    scenario = {}
    # Reports accept only the current harmonized scenario contract.  Falling
    # back to a dated legacy run would mix class meanings and support extents.
    plus_root = root / "runtime_plus_harmonized_v2" / "outputs" / "plus_harmonized_v2"
    invest_scenario_root = root / "outputs" / "invest_scenarios_harmonized_v2"
    service_scenario_root = root / "outputs" / "ecosystem_service_scenarios_harmonized_v2" / "native_ND_UD_EP_RE"

    def scenario_paths(code: str) -> tuple[Path, Path, Path, Path, Path]:
        paths = (
            plus_root / code / f"PLUS_{code}.tif",
            invest_scenario_root / code / "carbon" / "2026" / "tot_c_cur.tif",
            invest_scenario_root / code / "water" / "2026" / "output" / "per_pixel" / f"wyield_wy_2026_{code}.tif",
            invest_scenario_root / code / "habitat_318_native" / "2026" / f"quality_c_hq_2026_{code}.tif",
            service_scenario_root / f"ecosystem_service_2026_{code}.tif",
        )
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"incomplete harmonized scenario output set for {code}: {missing}")
        return paths

    source_records = {}
    for code in SCENARIOS:
        lulc, carbon, water, habitat, service = scenario_paths(code)
        array, transform, crs = masked(lulc)
        values, counts = np.unique(array.compressed().astype(np.int16), return_counts=True)
        water_m3, water_mean = water_total(water)
        scenario[code] = {
            "scenario_cn": SCENARIO_CN[code],
            "lulc_area_ha": {CLASS_CN[int(v)]: float(c * abs(transform.a * transform.e) / 10000.0)
                             for v, c in zip(values, counts) if int(v) in CLASS_CN},
            "carbon_mg_c": raster_sum(carbon),
            "water_m3": water_m3,
            "water_mean_mm": water_mean,
            "habitat_mean": raster_mean(habitat),
            "service_mean": raster_mean(service),
            "crs": str(crs),
            "pixel_size_m": abs(transform.a),
        }
        source_records[code] = {
            "plus_lulc": str(lulc), "carbon": str(carbon), "water_yield": str(water),
            "habitat_quality": str(habitat), "ecosystem_service": str(service),
            "source_mtime": {name: path.stat().st_mtime for name, path in (
                ("plus_lulc", lulc), ("carbon", carbon), ("water_yield", water),
                ("habitat_quality", habitat), ("ecosystem_service", service),
            )},
        }
    return {"historical": by_year, "scenario_2026": scenario,
            "scenario_sources": source_records,
            "scenario_source_policy": "harmonized v2 only; legacy scenario fallbacks are rejected"}


def write_tables(out: Path, data: dict) -> None:
    historical = []
    base = data["historical"][2005]
    for year, values in data["historical"].items():
        historical.append({
            "年份": year,
            "碳储量_MgC": f'{values["carbon_mg_c"]:.3f}',
            "碳储量_10^6MgC": f'{values["carbon_mg_c"] / 1e6:.6f}',
            "水源供给量_m3": f'{values["water_m3"]:.3f}',
            "水源供给量_10^6m3": f'{values["water_m3"] / 1e6:.6f}',
            "平均产水深_mm": f'{values["water_mean_mm"]:.6f}',
            "生境质量均值": f'{values["habitat_mean"]:.6f}',
            "综合生态服务指数均值": f'{values["service_mean"]:.6f}',
            "碳储量较2005年变化_%": f'{(values["carbon_mg_c"] / base["carbon_mg_c"] - 1) * 100:.3f}',
            "水源供给较2005年变化_%": f'{(values["water_m3"] / base["water_m3"] - 1) * 100:.3f}',
        })
    write_csv(out / "表_历史生态系统服务统计_单位校正.csv", historical)

    scenario_rows = []
    for code, values in data["scenario_2026"].items():
        scenario_rows.append({
            "情景代码": code,
            "情景名称": values["scenario_cn"],
            "碳储量_MgC": f'{values["carbon_mg_c"]:.3f}',
            "碳储量_10^6MgC": f'{values["carbon_mg_c"] / 1e6:.6f}',
            "水源供给量_m3": f'{values["water_m3"]:.3f}',
            "水源供给量_10^6m3": f'{values["water_m3"] / 1e6:.6f}',
            "平均产水深_mm": f'{values["water_mean_mm"]:.6f}',
            "生境质量均值": f'{values["habitat_mean"]:.6f}',
            "综合生态服务指数均值": f'{values["service_mean"]:.6f}',
        })
    write_csv(out / "表_2026四情景生态系统服务统计_单位校正.csv", scenario_rows)

    lulc_rows = []
    for code, values in data["scenario_2026"].items():
        for cls in CLASS_CN.values():
            lulc_rows.append({"情景代码": code, "情景名称": values["scenario_cn"],
                              "土地利用类型": cls, "面积_hm2": f'{values["lulc_area_ha"].get(cls, 0.0):.2f}'})
    write_csv(out / "表_2026四情景实际土地利用面积.csv", lulc_rows)


def historical_figure(out: Path, data: dict) -> None:
    years = np.array(YEARS)
    fields = [
        ("carbon_mg_c", "碳储量", "碳储量（10^6 Mg C）", 1e6, COLORS["carbon"]),
        ("water_m3", "水源供给", "水源供给量（10^6 m³）", 1e6, COLORS["water"]),
        ("habitat_mean", "生境质量", "生境质量指数", 1.0, COLORS["habitat"]),
        ("service_mean", "综合生态系统服务", "综合生态服务指数", 1.0, COLORS["service"]),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.4), constrained_layout=True)
    for ax, (field, title, ylabel, divisor, color) in zip(axes.flat, fields):
        values = np.array([data["historical"][y][field] / divisor for y in YEARS])
        ax.plot(years, values, marker="o", linewidth=1.4, markersize=4.2, color=color)
        ax.set_title(title, fontweight="bold")
        ax.set_ylabel(ylabel)
        ax.set_xticks(years)
        ax.grid(axis="y", color="#D9D9D9", linewidth=.45)
        ax.spines[["top", "right"]].set_visible(False)
    axes[1, 0].set_xlabel("年份")
    axes[1, 1].set_xlabel("年份")
    save(fig, out, "图_2005至2025年生态系统服务时间变化_单位校正")


def scenario_figure(out: Path, data: dict) -> None:
    fields = [
        ("carbon_mg_c", "碳储量", "10^6 Mg C", 1e6, COLORS["carbon"]),
        ("water_m3", "水源供给", "10^6 m³", 1e6, COLORS["water"]),
        ("habitat_mean", "生境质量", "指数", 1.0, COLORS["habitat"]),
        ("service_mean", "综合生态系统服务", "指数", 1.0, COLORS["service"]),
    ]
    x = np.arange(4)
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.2), constrained_layout=True)
    for ax, (field, title, ylabel, divisor, color) in zip(axes.flat, fields):
        values = np.array([data["scenario_2026"][s][field] / divisor for s in SCENARIOS])
        ax.scatter(x, values, color=color, s=38, zorder=3)
        for i, value in enumerate(values):
            ax.annotate(f"{value:.3f}", (i, value), xytext=(0, 6), textcoords="offset points",
                        ha="center", fontsize=7.5, fontfamily="Times New Roman")
        ax.set_xticks(x, [SCENARIO_CN[s] for s in SCENARIOS])
        ax.set_ylabel(ylabel)
        ax.set_title(title, fontweight="bold")
        ax.grid(axis="y", color="#D9D9D9", linewidth=.45)
        ax.spines[["top", "right"]].set_visible(False)
        ax.margins(y=.14)
    save(fig, out, "图_2026年四情景生态系统服务比较_单位校正")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    out = (args.output or root / "结果_重绘" / "生态系统服务综合报告" / "报告数据与图表").expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    setup_fonts()
    data = collect(root)
    write_tables(out, data)
    historical_figure(out, data)
    scenario_figure(out, data)
    (out / "report_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(out), "historical_years": YEARS, "scenarios": SCENARIOS}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
