#!/usr/bin/env python3
"""Create aligned LULC transition statistics and a publication-style Sankey.

The diagram follows the two-column format commonly used in land-use-change
figures: source and target classes form the two vertical columns, and every
ribbon retains the colour of its source class.  Both SVG and PNG are exported
from the same calculated transition table.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


SCHEMES: dict[str, list[tuple[int, str, str]]] = {
    "subsidence_water_6class": [
        (4, "\u8015\u5730", "#f2ae72"),
        (5, "\u6797\u5730", "#159447"),
        (3, "\u5efa\u8bbe\u7528\u5730", "#e9acd7"),
        (6, "\u8349\u5730", "#78bd67"),
        (2, "\u81ea\u7136\u6c34\u4f53", "#67c7d5"),
        (1, "\u6c89\u9677\u79ef\u6c34", "#176c76"),
    ],
    "standard_6class": [
        (3, "\u8015\u5730", "#f2ae72"),
        (4, "\u6797\u5730", "#159447"),
        (2, "\u5efa\u8bbe\u7528\u5730", "#e9acd7"),
        (5, "\u8349\u5730", "#78bd67"),
        (1, "\u6c34\u4f53", "#67c7d5"),
        (6, "\u88f8\u5730/\u5de5\u77ff\u7528\u5730", "#b58655"),
    ],
    "high_water_coal_7class": [
        (4, "\u8015\u5730", "#f2ae72"),
        (5, "\u6797\u5730", "#159447"),
        (3, "\u5efa\u8bbe\u7528\u5730", "#e9acd7"),
        (6, "\u8349\u5730", "#78bd67"),
        (2, "\u81ea\u7136\u6c34\u4f53", "#67c7d5"),
        (1, "\u6c89\u9677\u79ef\u6c34", "#176c76"),
        (7, "\u88f8\u5730/\u5de5\u77ff\u7528\u5730", "#b58655"),
    ],
}


def transitions(before: Path, after: Path, scheme: str) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    try:
        import numpy as np  # type: ignore
    except ImportError as error:
        raise RuntimeError("transition Sankey needs numpy") from error
    classes = {code: (name, color) for code, name, color in SCHEMES[scheme]}
    # Rasterio is convenient in the standalone virtual environment; ArcGIS Pro
    # ships GDAL instead, so fall back without changing the statistical method.
    try:
        import rasterio  # type: ignore
    except ImportError:
        rasterio = None
    if rasterio is not None:
        left = rasterio.open(before)
        right = rasterio.open(after)
        try:
            if (left.width, left.height, left.transform, left.crs) != (right.width, right.height, right.transform, right.crs):
                raise ValueError("the two LULC rasters must already be on the same grid")
            if not left.crs or not left.crs.is_projected:
                raise ValueError("Sankey area statistics require a projected LULC grid")
            windows = ((window.col_off, window.row_off, window.width, window.height) for _, window in left.block_windows(1))
            read = lambda source, item: source.read(1, window=rasterio.windows.Window(*item))
            width, height = left.width, left.height
            transform, crs = left.transform, str(left.crs)
            iterator = list(windows)
        finally:
            # Keep datasets alive until after the loop below by retaining them;
            # closing is handled after aggregation.
            pass
    else:
        from osgeo import gdal, osr

        left = gdal.Open(str(before), gdal.GA_ReadOnly)
        right = gdal.Open(str(after), gdal.GA_ReadOnly)
        if left is None or right is None:
            raise RuntimeError("could not open one of the LULC rasters")
        transform = left.GetGeoTransform()
        projection = left.GetProjection()
        if (left.RasterXSize, left.RasterYSize, transform, projection) != (right.RasterXSize, right.RasterYSize, right.GetGeoTransform(), right.GetProjection()):
            raise ValueError("the two LULC rasters must already be on the same grid")
        spatial_ref = osr.SpatialReference()
        spatial_ref.ImportFromWkt(projection)
        if not projection or not spatial_ref.IsProjected():
            raise ValueError("Sankey area statistics require a projected LULC grid")
        width, height, crs = left.RasterXSize, left.RasterYSize, spatial_ref.ExportToProj4().strip()
        block_height = 512
        iterator = [(0, row, width, min(block_height, height - row)) for row in range(0, height, block_height)]
        read = lambda source, item: source.GetRasterBand(1).ReadAsArray(item[0], item[1], item[2], item[3])
    try:
        counts: dict[tuple[int, int], int] = defaultdict(int)
        for item in iterator:
            old, new = read(left, item), read(right, item)
            valid = np.isin(old, list(classes)) & np.isin(new, list(classes))
            if not valid.any():
                continue
            pairs, values = np.unique(np.stack((old[valid], new[valid]), axis=1), axis=0, return_counts=True)
            for pair, value in zip(pairs, values):
                counts[(int(pair[0]), int(pair[1]))] += int(value)
        area_ha = abs(float(transform[1] * transform[5])) / 10000.0
        metadata = {"crs": crs, "cell_area_ha": area_ha, "width": width, "height": height}
    finally:
        left.close() if rasterio is not None else None
        right.close() if rasterio is not None else None
    rows = [{"source_code": old, "source_name": classes[old][0], "target_code": new,
             "target_name": classes[new][0], "pixel_count": count, "area_ha": count * area_ha}
            for (old, new), count in sorted(counts.items())]
    return rows, area_ha, metadata


def render(rows: list[dict[str, Any]], scheme: str, before_year: str, after_year: str, output_base: Path) -> None:
    """Render a clean, uncaptioned two-sided Sankey in PNG and SVG."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.path import Path as MplPath
    from matplotlib.patches import PathPatch, Rectangle

    plt.rcParams["font.sans-serif"] = ["SimSun", "Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    classes = {code: (name, color) for code, name, color in SCHEMES[scheme]}
    codes = [code for code, _, _ in SCHEMES[scheme]]
    incoming = {code: sum(float(row["area_ha"]) for row in rows if row["target_code"] == code) for code in codes}
    outgoing = {code: sum(float(row["area_ha"]) for row in rows if row["source_code"] == code) for code in codes}
    total = max(sum(outgoing.values()), 1e-12)
    figure, axis = plt.subplots(figsize=(11.5, 7.7))
    figure.subplots_adjust(left=0.025, right=0.975, top=0.985, bottom=0.035)
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")

    top, bottom, gap = 0.97, 0.04, 0.012
    usable = top - bottom - gap * (len(codes) - 1)
    scale = usable / total

    def positions(values: dict[int, float]) -> dict[int, tuple[float, float]]:
        cursor, result = top, {}
        for code in codes:
            height = values[code] * scale
            result[code] = (cursor - height, cursor)
            cursor -= height + gap
        return result

    left, right = positions(outgoing), positions(incoming)
    left_cursor = {code: values[0] for code, values in left.items()}
    right_cursor = {code: values[0] for code, values in right.items()}
    # Stack all ribbons in a deterministic class order at both ends.
    order = {(source, target): index for index, (source, target) in enumerate((s, t) for s in codes for t in codes)}
    ordered_rows = sorted(rows, key=lambda row: order[(int(row["source_code"]), int(row["target_code"]))])
    x_left, x_right, node_width = 0.020, 0.962, 0.018
    for row in ordered_rows:
        source, target = int(row["source_code"]), int(row["target_code"])
        height = float(row["area_ha"]) * scale
        if height <= 0:
            continue
        ly0, ly1 = left_cursor[source], left_cursor[source] + height
        ry0, ry1 = right_cursor[target], right_cursor[target] + height
        left_cursor[source], right_cursor[target] = ly1, ry1
        vertices = [(x_left + node_width, ly0), (0.40, ly0), (0.60, ry0), (x_right, ry0),
                    (x_right, ry1), (0.60, ry1), (0.40, ly1), (x_left + node_width, ly1), (x_left + node_width, ly0)]
        codes_path = [MplPath.MOVETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
                      MplPath.LINETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4, MplPath.CLOSEPOLY]
        axis.add_patch(PathPatch(MplPath(vertices, codes_path), facecolor=classes[source][1],
                                 edgecolor="none", alpha=0.53, zorder=1))

    for x, positions_, year, side in ((x_left, left, before_year, "left"), (x_right, right, after_year, "right")):
        for code in codes:
            y0, y1 = positions_[code]
            if y1 <= y0:
                continue
            axis.add_patch(Rectangle((x, y0), node_width, y1 - y0, facecolor=classes[code][1],
                                     edgecolor="#5f5f5f", linewidth=0.65, zorder=3))
            label_x = x + node_width + 0.005 if side == "left" else x - 0.006
            anchor = "left" if side == "left" else "right"
            axis.text(label_x, (y0 + y1) / 2, f"{year}{classes[code][0]}", ha=anchor, va="center",
                      fontsize=10.4, color="#202020", zorder=4)
    output_base.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_base.with_suffix(".png"), dpi=330, facecolor="white")
    figure.savefig(output_base.with_suffix(".svg"), facecolor="white")
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-raster", required=True, type=Path)
    parser.add_argument("--to-raster", required=True, type=Path)
    parser.add_argument("--from-year", required=True)
    parser.add_argument("--to-year", required=True)
    parser.add_argument("--scheme", choices=sorted(SCHEMES), required=True)
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument("--output-base", type=Path, help="Figure path without extension.")
    parser.add_argument("--output-svg", type=Path, help="Legacy SVG path; its stem becomes output-base.")
    args = parser.parse_args()
    if not args.output_base and not args.output_svg:
        parser.error("one of --output-base or --output-svg is required")
    output_base = args.output_base or args.output_svg.with_suffix("")
    rows, area, metadata = transitions(args.from_raster.resolve(), args.to_raster.resolve(), args.scheme)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["source_code", "source_name", "target_code", "target_name", "pixel_count", "area_ha"])
        writer.writeheader()
        writer.writerows(rows)
    metadata.update({"from_raster": str(args.from_raster.resolve()), "to_raster": str(args.to_raster.resolve()),
                     "from_year": args.from_year, "to_year": args.to_year, "scheme": args.scheme,
                     "transition_count": len(rows), "total_area_ha": sum(float(row["area_ha"]) for row in rows)})
    args.output_csv.with_suffix(args.output_csv.suffix + ".metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render(rows, args.scheme, args.from_year, args.to_year, output_base.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
