#!/usr/bin/env python3
"""Create a Chinese-labelled land-use area evolution figure from MAESA CSV."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


LABELS = {1: "沉陷积水", 2: "自然水体", 3: "建设用地", 4: "耕地", 5: "林地", 6: "草地"}
COLORS = {1: "#225ea8", 2: "#41b6c4", 3: "#d73027", 4: "#fdae61", 5: "#1a9850", 6: "#a6d96a"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows: dict[int, dict[int, float]] = defaultdict(dict)
    with args.input.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            rows[int(row["year"])][int(row["lucode"])] = float(row["area_ha"])
    years = sorted(rows)
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 1, figsize=(11.7, 8.3), gridspec_kw={"height_ratios": [2.2, 1]}, constrained_layout=True)
    for code in sorted(LABELS):
        axes[0].plot(years, [rows[year].get(code, 0) for year in years], marker="o", linewidth=2.1,
                     color=COLORS[code], label=LABELS[code])
    axes[0].set_title("2005—2025年矿区土地利用面积演变", fontsize=16, fontweight="bold")
    axes[0].set_ylabel("面积（ha）")
    axes[0].grid(alpha=0.22)
    axes[0].legend(ncol=3, frameon=False)
    bottom = [0.0] * len(years)
    for code in sorted(LABELS):
        values = [rows[year].get(code, 0) for year in years]
        axes[1].bar(years, values, bottom=bottom, color=COLORS[code], width=3.4, label=LABELS[code])
        bottom = [left + right for left, right in zip(bottom, values)]
    axes[1].set_ylabel("面积（ha）")
    axes[1].set_xlabel("年份")
    axes[1].grid(axis="y", alpha=0.22)
    fig.text(0.01, 0.01, "土地利用分类结果；独立精度验证状态：pending_validation。", fontsize=8, color="#374151")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output.with_suffix(".png"), dpi=300, facecolor="white")
    fig.savefig(args.output.with_suffix(".svg"), facecolor="white")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
