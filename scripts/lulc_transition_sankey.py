#!/usr/bin/env python3
"""Create a land-use transition table and a portable SVG Sankey figure.

The figure is deliberately written as SVG with the Python standard library so a
local project does not need a browser, a cloud chart service, or a GUI.  The CSV
is the authoritative result; the SVG is a view of the same rows.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


SCHEMES: dict[str, list[tuple[int, str, str]]] = {
    "standard_6class": [
        (1, "Water", "#2b83ba"), (2, "Built-up", "#d7191c"), (3, "Cropland", "#fdae61"),
        (4, "Forest", "#1a9641"), (5, "Grassland", "#a6d96a"), (6, "Bare/mining land", "#8c510a"),
    ],
    "high_water_coal_7class": [
        (1, "Subsidence water", "#225ea8"), (2, "Natural water", "#41b6c4"), (3, "Built-up", "#d73027"),
        (4, "Cropland", "#fdae61"), (5, "Forest", "#1a9850"), (6, "Grassland", "#a6d96a"),
        (7, "Bare/mining land", "#8c510a"),
    ],
}


def transitions(before: Path, after: Path, scheme: str) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    try:
        import numpy as np  # type: ignore
        import rasterio  # type: ignore
    except ImportError as error:
        raise RuntimeError("transition Sankey needs the validation dependencies (numpy and rasterio)") from error
    classes = {code: (name, color) for code, name, color in SCHEMES[scheme]}
    with rasterio.open(before) as left, rasterio.open(after) as right:
        if (left.width, left.height, left.transform, left.crs) != (right.width, right.height, right.transform, right.crs):
            raise ValueError("the two LULC rasters must already be on the same grid")
        if not left.crs or not left.crs.is_projected:
            raise ValueError("Sankey area statistics require a projected LULC grid")
        counts: dict[tuple[int, int], int] = defaultdict(int)
        for _, window in left.block_windows(1):
            old, new = left.read(1, window=window), right.read(1, window=window)
            valid = np.isin(old, list(classes)) & np.isin(new, list(classes))
            if not valid.any():
                continue
            pairs, values = np.unique(np.stack((old[valid], new[valid]), axis=1), axis=0, return_counts=True)
            for pair, value in zip(pairs, values):
                counts[(int(pair[0]), int(pair[1]))] += int(value)
        area_ha = abs(float(left.transform.a * left.transform.e)) / 10000.0
        metadata = {"crs": str(left.crs), "cell_area_ha": area_ha, "width": left.width, "height": left.height}
    rows = [{"source_code": old, "source_name": classes[old][0], "target_code": new,
             "target_name": classes[new][0], "pixel_count": count, "area_ha": count * area_ha}
            for (old, new), count in sorted(counts.items())]
    return rows, area_ha, metadata


def svg(rows: list[dict[str, Any]], scheme: str, before_year: str, after_year: str, output: Path) -> None:
    classes = {code: (name, color) for code, name, color in SCHEMES[scheme]}
    codes = [code for code, _, _ in SCHEMES[scheme]]
    incoming = {code: sum(float(row["area_ha"]) for row in rows if row["target_code"] == code) for code in codes}
    outgoing = {code: sum(float(row["area_ha"]) for row in rows if row["source_code"] == code) for code in codes}
    total = max(sum(outgoing.values()), 1e-12)
    width, height, top, bottom = 1400, 900, 110, 90
    usable, gap = height - top - bottom, 12
    scale = max((usable - gap * (len(codes) - 1)) / total, 0.01)

    def positions(values: dict[int, float]) -> dict[int, tuple[float, float]]:
        current = float(top); result = {}
        for code in codes:
            size = max(values[code] * scale, 2.0 if values[code] else 0.0)
            result[code] = (current, current + size); current += size + gap
        return result

    left, right = positions(outgoing), positions(incoming)
    left_cursor = {key: value[0] for key, value in left.items()}
    right_cursor = {key: value[0] for key, value in right.items()}
    paths: list[str] = []
    for row in rows:
        old, new, value = int(row["source_code"]), int(row["target_code"]), float(row["area_ha"])
        thickness = max(value * scale, 1.0)
        ly0, ly1 = left_cursor[old], left_cursor[old] + thickness
        ry0, ry1 = right_cursor[new], right_cursor[new] + thickness
        left_cursor[old], right_cursor[new] = ly1, ry1
        color = classes[old][1]
        paths.append(f'<path d="M 230 {ly0:.2f} C 560 {ly0:.2f}, 840 {ry0:.2f}, 1170 {ry0:.2f} '
                     f'L 1170 {ry1:.2f} C 840 {ry1:.2f}, 560 {ly1:.2f}, 230 {ly1:.2f} Z" '
                     f'fill="{color}" fill-opacity="0.45" stroke="none"><title>{html.escape(row["source_name"])} → '
                     f'{html.escape(row["target_name"])}: {value:.2f} ha</title></path>')
    nodes: list[str] = []
    for x, values, year, side in ((170, left, before_year, "left"), (1170, right, after_year, "right")):
        nodes.append(f'<text x="{x + (0 if side == "left" else 60)}" y="72" text-anchor="middle" class="year">{html.escape(year)}</text>')
        for code in codes:
            y0, y1 = values[code]
            if y1 <= y0:
                continue
            label_x = x - 8 if side == "left" else x + 68
            anchor = "end" if side == "left" else "start"
            nodes.append(f'<rect x="{x}" y="{y0:.2f}" width="60" height="{y1-y0:.2f}" fill="{classes[code][1]}"/>')
            nodes.append(f'<text x="{label_x}" y="{(y0+y1)/2:.2f}" text-anchor="{anchor}" class="label">'
                         f'{html.escape(classes[code][0])}</text>')
    document = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>.title{{font:700 26px sans-serif}}.year{{font:700 20px sans-serif}}.label{{font:14px sans-serif;dominant-baseline:middle}}</style>
<rect width="100%" height="100%" fill="white"/><text x="700" y="38" text-anchor="middle" class="title">Land-use transition Sankey ({html.escape(before_year)}–{html.escape(after_year)})</text>
{''.join(paths)}{''.join(nodes)}<text x="700" y="860" text-anchor="middle" class="label">Flow width represents area (ha); values exclude NoData and unrecognised codes.</text></svg>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-raster", required=True, type=Path); parser.add_argument("--to-raster", required=True, type=Path)
    parser.add_argument("--from-year", required=True); parser.add_argument("--to-year", required=True)
    parser.add_argument("--scheme", choices=sorted(SCHEMES), required=True)
    parser.add_argument("--output-csv", required=True, type=Path); parser.add_argument("--output-svg", required=True, type=Path)
    args = parser.parse_args()
    rows, area, metadata = transitions(args.from_raster.resolve(), args.to_raster.resolve(), args.scheme)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["source_code", "source_name", "target_code", "target_name", "pixel_count", "area_ha"])
        writer.writeheader(); writer.writerows(rows)
    metadata.update({"from_raster": str(args.from_raster.resolve()), "to_raster": str(args.to_raster.resolve()),
                     "from_year": args.from_year, "to_year": args.to_year, "scheme": args.scheme,
                     "transition_count": len(rows), "total_area_ha": sum(float(row["area_ha"]) for row in rows)})
    args.output_csv.with_suffix(args.output_csv.suffix + ".metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    svg(rows, args.scheme, args.from_year, args.to_year, args.output_svg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
