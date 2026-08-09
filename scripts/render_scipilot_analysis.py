#!/usr/bin/env python3
"""Render publication-style analysis figures with scipilot-figure-skill.

This script intentionally works from the generated CSV tables instead of
re-reading large rasters.  It follows the skill's recommendations: temporal
values use line plots, scenario/class matrices use heatmaps, and small-
sample scenario comparisons show points rather than mean-only bars.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


SCIPILOT = Path(os.environ.get(
    "SCIPILOT_FIGURE_SKILL_SCRIPTS",
    str(Path.home() / ".codex" / "skills" / "scipilot-figure-skill" / "scripts"),
)).expanduser()
if str(SCIPILOT) not in sys.path:
    sys.path.insert(0, str(SCIPILOT))
from export_figure import export_figure  # type: ignore  # noqa: E402
from setup_style import setup_style  # type: ignore  # noqa: E402


SCENARIO_NAME = {"ND": "自然发展", "UD": "城镇发展", "EP": "生态保护", "RE": "资源开采"}
CLASS_NAMES = ["沉陷积水", "自然水体", "建设用地", "耕地", "林地", "草地", "裸地/工矿用地"]
SCENARIO_COLORS = {"ND": "#0072B2", "UD": "#D55E00", "EP": "#009E73", "RE": "#CC79A7"}


def rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [[cell.strip() for cell in row] for row in csv.reader(handle) if row]


def number(value: str) -> float:
    return float(value.replace(",", ""))


def numeric_ticks(ax, *, x: bool = True, y: bool = True) -> None:
    ticks = []
    if x:
        ticks.extend(ax.get_xticklabels())
    if y:
        ticks.extend(ax.get_yticklabels())
    for tick in ticks:
        tick.set_fontfamily("Times New Roman")


def export(fig, out: Path, stem: str, size: tuple[float, float]) -> None:
    export_figure(fig, str(out / stem), formats=["pdf", "svg", "png"], size_inches=size,
                  dpi=600, grayscale_preview=True)
    plt.close(fig)


def demand_heatmap(out: Path, demand_csv: Path) -> None:
    raw = rows(demand_csv)
    header, data = raw[0], raw[1:]
    scenarios = ["ND", "UD", "EP", "RE"]
    matrix = np.zeros((len(scenarios), len(CLASS_NAMES)), dtype=float)
    for record in data:
        scenario = record[0]
        if scenario in scenarios:
            matrix[scenarios.index(scenario), int(record[1]) - 1] = number(record[4])
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    image = ax.imshow(matrix, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(CLASS_NAMES)), CLASS_NAMES, rotation=35, ha="right")
    ax.set_yticks(range(len(scenarios)), [SCENARIO_NAME[x] for x in scenarios])
    ax.set_xlabel("土地利用类型", labelpad=18)
    ax.set_ylabel("2026情景")
    ax.set_title("2026年四情景土地利用需求（初始校准值）")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, f"{matrix[i, j]:,.0f}", ha="center", va="center", fontsize=7,
                    fontfamily="Times New Roman", color="white" if matrix[i, j] > matrix.max() * 0.55 else "black")
    cbar = fig.colorbar(image, ax=ax, pad=0.02)
    cbar.set_label("面积（hm²）")
    fig.subplots_adjust(left=0.14, right=0.90, bottom=0.26, top=0.88)
    export(fig, out, "图1_2026四情景土地利用需求热力图", (7.2, 3.8))


def historical_service_panels(out: Path, table: Path) -> None:
    raw = rows(table)
    records = raw[1:]
    years = [int(number(row[0])) for row in records]
    names = [("碳储量", "碳储量（t C）", 1, "#B2182B"),
             ("水源供给", "水源供给（m³）", 2, "#2166AC"),
             ("生境质量", "生境质量（0—1）", 3, "#1B7837"),
             ("综合生态服务", "综合生态服务价值（0—1）", 4, "#762A83")]
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.4), sharex=True)
    for ax, (title, ylabel, col, color) in zip(axes.flat, names):
        values = [number(row[col]) for row in records]
        ax.plot(years, values, marker="o", markersize=4, linewidth=1.25, color=color)
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", color="#D9D9D9", linewidth=0.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        numeric_ticks(ax)
    for ax in axes[1]:
        ax.set_xlabel("年份")
    fig.subplots_adjust(top=0.86, hspace=0.30, wspace=0.28)
    fig.suptitle("2005—2025年生态系统服务时序变化", y=0.995)
    export(fig, out, "图2_历史时期生态系统服务时序变化", (7.2, 5.4))

    # The composite index is also exported as a standalone paper-style line,
    # matching the user's reference figure without hiding the other services.
    fig, ax = plt.subplots(figsize=(5.8, 3.6))
    values = [number(row[4]) for row in records]
    ax.plot(years, values, color="#222222", marker="s", markersize=4, linewidth=1.15,
            label="综合生态系统服务价值")
    ax.set_xlabel("时间（year）")
    ax.set_ylabel("综合生态系统服务价值")
    ax.set_title("综合生态系统服务价值时间变化（2005—2025年）")
    ax.legend(loc="upper left", frameon=True)
    ax.grid(axis="y", color="#E0E0E0", linewidth=0.5)
    numeric_ticks(ax)
    export(fig, out, "图3_综合生态系统服务价值时间变化", (5.8, 3.6))


def scenario_service_points(out: Path, table: Path) -> None:
    raw = rows(table)
    records = raw[1:]
    scenarios = ["ND", "UD", "EP", "RE"]
    fields = [("碳储量", "碳储量（t C）", 2), ("水源供给", "水源供给（m³）", 3),
              ("生境质量", "生境质量（0—1）", 4), ("综合生态服务", "综合生态服务价值（0—1）", 5)]
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.2))
    for ax, (title, ylabel, col) in zip(axes.flat, fields):
        vals = {scenario: [] for scenario in scenarios}
        for row in records:
            scenario_code = row[1].split("（", 1)[0].strip()
            if scenario_code in vals:
                vals[scenario_code].append(number(row[col]))
        y = [vals[s][0] if vals[s] else np.nan for s in scenarios]
        ax.scatter(range(4), y, s=38, c=[SCENARIO_COLORS[s] for s in scenarios], zorder=3)
        ax.set_xticks(range(4), [SCENARIO_NAME[s] for s in scenarios], rotation=20)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(axis="y", color="#E0E0E0", linewidth=0.5)
        numeric_ticks(ax, y=True, x=False)
    fig.suptitle("2026年四情景生态系统服务对比", y=0.995)
    fig.subplots_adjust(top=0.86, bottom=0.16, hspace=0.35, wspace=0.28)
    export(fig, out, "图4_2026四情景生态服务对比点图", (7.2, 5.2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--analysis-root",
        type=Path,
        help="directory containing the generated CSV tables; defaults to root/outputs/论文分析结果_20260806",
    )
    parser.add_argument(
        "--figure-root",
        type=Path,
        help="directory for figures; defaults to analysis-root/scipilot_figures",
    )
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    analysis_root = (args.analysis_root or (root / "outputs" / "论文分析结果_20260806")).expanduser().resolve()
    out = (args.figure_root or (analysis_root / "scipilot_figures")).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    setup_style(journal="general", lang="zh", serif_for_zh=True, use_sciplots=False)
    demand_heatmap(out, root / "outputs" / "plus_scenario_demand_20260806" / "2026四情景土地利用需求_hm2.csv")
    historical_service_panels(out, analysis_root / "历史时期生态服务统计.csv")
    scenario_table = analysis_root / "2026年四情景生态服务统计.csv"
    if scenario_table.exists():
        scenario_service_points(out, scenario_table)
    else:
        print(f"skip scenario figure until verified PLUS outputs exist: {scenario_table}")
    print(f"wrote scipilot figures to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
