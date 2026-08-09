#!/usr/bin/env python3
"""Render multi-period ecosystem-service maps as one comparable panel figure.

Each period uses the same colour stretch.  This makes the figure suitable for
spatio-temporal comparison rather than five separately normalised map images.
Run with ArcGIS Pro Python because the study boundary is read with arcpy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SERVICES = {
    "carbon": ("OrRd", "\u78b3\u50a8\u91cf\uff08Mg C / 30 m \u50cf\u5143\uff09"),
    "water_yield": ("YlGnBu", "\u5e74\u4ea7\u6c34\u91cf\uff08mm\uff09"),
    "habitat_quality": ("YlGn", "\u751f\u5883\u8d28\u91cf\u6307\u6570"),
    "ecosystem_service": ("RdYlGn", "\u7efc\u5408\u751f\u6001\u670d\u52a1\u6307\u6570"),
}


def read_raster(path: Path, maximum: int = 960):
    from osgeo import gdal
    import numpy as np

    source = gdal.Open(str(path), gdal.GA_ReadOnly)
    if source is None:
        raise RuntimeError(f"cannot open raster: {path}")
    width, height = source.RasterXSize, source.RasterYSize
    scale = max(width / maximum, height / maximum, 1)
    target_width, target_height = max(1, round(width / scale)), max(1, round(height / scale))
    band = source.GetRasterBand(1)
    values = band.ReadAsArray(buf_xsize=target_width, buf_ysize=target_height).astype("float64")
    nodata = band.GetNoDataValue()
    if nodata is not None:
        values[values == nodata] = np.nan
    values[~np.isfinite(values)] = np.nan
    geo = source.GetGeoTransform()
    extent = (geo[0], geo[0] + geo[1] * width, geo[3] + geo[5] * height, geo[3])
    return values, extent


def boundary_parts(path: Path):
    import arcpy

    with arcpy.da.SearchCursor(str(path), ["SHAPE@"]) as rows:
        for (shape,) in rows:
            for part in shape:
                points = [(point.X, point.Y) for point in part if point]
                if points:
                    yield points


def north_arrow(figure) -> None:
    from matplotlib.patches import Polygon

    axis = figure.add_axes([0.023, 0.905, 0.040, 0.065])
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")
    axis.add_patch(Polygon([(0.50, 0.85), (0.30, 0.37), (0.50, 0.47)], facecolor="black", edgecolor="black", linewidth=0.65))
    axis.add_patch(Polygon([(0.50, 0.15), (0.70, 0.37), (0.50, 0.47)], facecolor="white", edgecolor="black", linewidth=0.65))
    axis.text(0.50, 0.94, "N", ha="center", va="bottom", fontsize=8.5, fontname="Times New Roman")


def parse_period(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("period must have YEAR=RASTER format")
    year, location = raw.split("=", 1)
    if not year.strip() or not location.strip():
        raise argparse.ArgumentTypeError("period must have YEAR=RASTER format")
    return year.strip(), Path(location).expanduser().resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary", type=Path, required=True)
    parser.add_argument("--period", action="append", type=parse_period, required=True, help="YEAR=RASTER; repeat for every period")
    parser.add_argument("--kind", choices=SERVICES, required=True)
    parser.add_argument("--output-base", type=Path, required=True)
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams["font.sans-serif"] = ["SimSun", "Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    boundary = args.boundary.resolve()
    parts = list(boundary_parts(boundary))
    if not parts:
        raise ValueError(f"no polygon geometry in boundary: {boundary}")
    periods = []
    for year, path in args.period:
        if not path.is_file():
            raise FileNotFoundError(path)
        values, extent = read_raster(path)
        periods.append((year, path, values, extent))
    finite = np.concatenate([values[np.isfinite(values)] for _, _, values, _ in periods])
    if finite.size == 0:
        raise ValueError("none of the service rasters contains a finite value")
    vmin, vmax = float(np.min(finite)), float(np.max(finite))
    if vmax <= vmin:
        vmax = vmin + 1.0
    xmin, xmax = min(item[3][0] for item in periods), max(item[3][1] for item in periods)
    ymin, ymax = min(item[3][2] for item in periods), max(item[3][3] for item in periods)
    dx, dy = xmax - xmin, ymax - ymin
    pad_x, pad_y = dx * 0.012, dy * 0.012
    ncols, nrows = 3, (len(periods) + 2) // 3
    figure, axes = plt.subplots(nrows, ncols, figsize=(9.2, 5.8 if nrows == 2 else 3.25 * nrows))
    axes = np.atleast_1d(axes).ravel()
    figure.subplots_adjust(left=0.065, right=0.985, bottom=0.125, top=0.925, wspace=0.075, hspace=0.13)
    palette, label = SERVICES[args.kind]
    image = None
    for index, (year, _, values, extent) in enumerate(periods):
        axis = axes[index]
        image = axis.imshow(np.ma.masked_invalid(values), extent=extent, origin="upper", interpolation="nearest",
                            cmap=palette, vmin=vmin, vmax=vmax, zorder=1)
        for points in parts:
            xs, ys = zip(*points)
            axis.plot(xs, ys, color="#303030", linewidth=0.38, zorder=2)
        axis.set_xlim(xmin - pad_x, xmax + pad_x)
        axis.set_ylim(ymin - pad_y, ymax + pad_y)
        axis.set_xticks([])
        axis.set_yticks([])
        axis.set_aspect("equal")
        axis.text(0.50, 0.035, year, transform=axis.transAxes, ha="center", va="bottom", fontsize=10.2,
                  fontname="Times New Roman",
                  color="#202020", bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.72, "pad": 0.6})
        for spine in axis.spines.values():
            spine.set_visible(False)
    for axis in axes[len(periods):]:
        axis.set_visible(False)
    north_arrow(figure)
    color_axis = figure.add_axes([0.20, 0.055, 0.60, 0.024])
    colorbar = figure.colorbar(image, cax=color_axis, orientation="horizontal")
    colorbar.set_label(label, fontsize=9.2, labelpad=4)
    colorbar.ax.tick_params(labelsize=7.7, length=2.5)
    for tick in colorbar.ax.get_xticklabels():
        tick.set_fontname("Times New Roman")
    output_base = args.output_base.resolve()
    output_base.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_base.with_suffix(".png"), dpi=360, facecolor="white")
    figure.savefig(output_base.with_suffix(".svg"), facecolor="white")
    plt.close(figure)
    output_base.with_suffix(".metadata.json").write_text(json.dumps({
        "kind": args.kind,
        "colour_range": {"minimum": vmin, "maximum": vmax},
        "boundary": str(boundary),
        "periods": [{"year": year, "raster": str(path)} for year, path, _, _ in periods],
        "normalization": "one shared linear range across all displayed periods",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
