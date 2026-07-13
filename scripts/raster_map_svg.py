#!/usr/bin/env python3
"""Render a local GeoTIFF to a self-contained SVG map with legend and metadata."""

from __future__ import annotations

import argparse
import html
from pathlib import Path


LULC = {
    "standard_6class": [(1, "Water", "#2b83ba"), (2, "Built-up", "#d7191c"), (3, "Cropland", "#fdae61"), (4, "Forest", "#1a9641"), (5, "Grassland", "#a6d96a"), (6, "Bare/mining", "#8c510a")],
    "high_water_coal_7class": [(1, "Subsidence water", "#225ea8"), (2, "Natural water", "#41b6c4"), (3, "Built-up", "#d73027"), (4, "Cropland", "#fdae61"), (5, "Forest", "#1a9850"), (6, "Grassland", "#a6d96a"), (7, "Bare/mining", "#8c510a")],
}


def colour(value: float, minimum: float, maximum: float) -> str:
    ratio = 0.5 if maximum <= minimum else min(1.0, max(0.0, (value - minimum) / (maximum - minimum)))
    # A compact blue-green-yellow ramp with no external palette dependency.
    anchors = ((37, 52, 148), (35, 138, 141), (253, 231, 37))
    step = 0 if ratio <= 0.5 else 1; local = ratio * 2 if step == 0 else (ratio - 0.5) * 2
    left, right = anchors[step], anchors[step + 1]
    return "#%02x%02x%02x" % tuple(round(a + (b - a) * local) for a, b in zip(left, right))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raster", required=True, type=Path); parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", required=True); parser.add_argument("--kind", choices=("lulc", "continuous"), required=True)
    parser.add_argument("--scheme", choices=sorted(LULC), default="standard_6class")
    args = parser.parse_args()
    try:
        import numpy as np  # type: ignore
        import rasterio  # type: ignore
    except ImportError as error:
        raise RuntimeError("map rendering needs numpy and rasterio") from error
    with rasterio.open(args.raster) as source:
        step = max(1, int(max(source.width, source.height) / 600))
        data = source.read(1)[::step, ::step]; nodata = source.nodata
        valid = np.isfinite(data) & (data != nodata if nodata is not None else True)
        if not valid.any():
            raise ValueError("raster contains no drawable cells")
        minimum, maximum = float(data[valid].min()), float(data[valid].max())
        crs, resolution = str(source.crs), (abs(source.transform.a) * step, abs(source.transform.e) * step)
    cell, x0, y0 = 1.0, 55.0, 80.0
    legend_x = x0 + data.shape[1] + 30
    palette = {code: (name, color) for code, name, color in LULC[args.scheme]}
    pixels: list[str] = []
    for row in range(data.shape[0]):
        for col in range(data.shape[1]):
            value = data[row, col]
            if not valid[row, col]:
                continue
            fill = palette.get(int(value), ("unknown", "#9e9e9e"))[1] if args.kind == "lulc" else colour(float(value), minimum, maximum)
            pixels.append(f'<rect x="{x0+col*cell:.1f}" y="{y0+row*cell:.1f}" width="1" height="1" fill="{fill}"/>')
    legend = []
    if args.kind == "lulc":
        for index, (_, name, color_value) in enumerate(LULC[args.scheme]):
            legend.append(f'<rect x="{legend_x}" y="{y0+index*24}" width="16" height="16" fill="{color_value}"/><text x="{legend_x+22}" y="{y0+index*24+13}">{html.escape(name)}</text>')
    else:
        legend.append(f'<text x="{legend_x}" y="{y0}">low {minimum:.4g}</text><text x="{legend_x}" y="{y0+28}">high {maximum:.4g}</text>')
    width, height = int(legend_x + 240), int(max(y0 + data.shape[0] + 65, 240))
    document = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>text{{font:13px sans-serif}}.title{{font:700 22px sans-serif}}</style><rect width="100%" height="100%" fill="white"/>
<text x="{width/2}" y="34" text-anchor="middle" class="title">{html.escape(args.title)}</text><g shape-rendering="crispEdges">{''.join(pixels)}</g>
<rect x="{x0}" y="{y0}" width="{data.shape[1]}" height="{data.shape[0]}" fill="none" stroke="#222"/>{''.join(legend)}
<text x="{x0}" y="{height-25}">CRS: {html.escape(crs)} | displayed resolution: {resolution[0]:.4g} × {resolution[1]:.4g}</text></svg>'''
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(document, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
