#!/usr/bin/env python3
"""Render a paper-style 2026 subsidence cloud overview with six zoom panels.

The source layer is the 2026 subsidence-class polygon feature class in the
local OpenFileGDB.  The renderer intentionally keeps the original ``Degree``
interval sign convention instead of inventing a new depth value.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import fiona
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.collections import PatchCollection
from matplotlib.patches import Polygon as MplPolygon, Rectangle


def font_name() -> str:
    """Pick a Chinese-capable font while keeping numerals publication friendly."""
    candidates = ["SimSun", "Microsoft YaHei", "Noto Sans CJK SC", "DejaVu Sans"]
    available = {f.name for f in mpl.font_manager.fontManager.ttflist}
    return next((name for name in candidates if name in available), "DejaVu Sans")


def iter_rings(geometry):
    if not geometry:
        return
    typ = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if typ == "Polygon":
        for ring in coords[:1]:
            if len(ring) >= 3:
                yield ring
    elif typ == "MultiPolygon":
        for poly in coords:
            for ring in poly[:1]:
                if len(ring) >= 3:
                    yield ring
    elif typ == "LineString":
        yield coords
    elif typ == "MultiLineString":
        for line in coords:
            yield line


def patch_from_geometry(geometry, transform=None):
    patches = []
    for ring in iter_rings(geometry):
        points = []
        for x, y, *rest in ring:
            if transform:
                x, y = transform(x, y)
            points.append((x, y))
        if len(points) >= 3:
            patches.append(MplPolygon(points, closed=True))
    return patches


def geometry_center(geometry):
    pts = [(x, y) for ring in iter_rings(geometry) for x, y, *_ in ring]
    if not pts:
        return (float("nan"), float("nan"))
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def parse_degree(value: str) -> float:
    """Return the interval midpoint from Degree, retaining negative sign."""
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", str(value))
    if len(nums) >= 2:
        return (float(nums[0]) + float(nums[1])) / 2.0
    return float(nums[0]) if nums else float("nan")


def load_gdb_layer(gdb: Path, index: int = 8):
    layers = fiona.listlayers(str(gdb))
    if len(layers) <= index:
        raise RuntimeError(f"GDB 图层数量不足，无法读取索引 {index}: {len(layers)}")
    name = layers[index]
    with fiona.open(str(gdb), layer=name) as src:
        features = list(src)
        return name, src.crs_wkt or src.crs, features, src.bounds, src.schema


def load_vector(path: Path):
    with fiona.open(str(path)) as src:
        return list(src), src.crs_wkt or src.crs, src.bounds


def load_raster(path: Path):
    with rasterio.open(path) as src:
        data = src.read(1, masked=True)
        bounds = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
        return data, src.crs, bounds, src.nodata, src.transform


def choose_zoom_boxes(features, bounds):
    """Choose six distinct representative cloud locations for A--F."""
    points = []
    for f in features:
        cx, cy = geometry_center(f["geometry"])
        if math.isfinite(cx) and math.isfinite(cy):
            degree = parse_degree(list(f["properties"].values())[1])
            points.append((cx, cy, degree))
    xmin, ymin, xmax, ymax = bounds
    sx, sy = xmax - xmin, ymax - ymin
    targets = {
        "A": (0.48, 0.86),
        "B": (0.32, 0.58),
        "C": (0.62, 0.58),
        "D": (0.34, 0.32),
        "E": (0.62, 0.32),
        "F": (0.83, 0.30),
    }
    selected = []
    for label, (tx, ty) in targets.items():
        ranked = sorted(
            points,
            key=lambda p: ((p[0] - (xmin + tx * sx)) / sx) ** 2
            + ((p[1] - (ymin + ty * sy)) / sy) ** 2,
        )
        for candidate in ranked:
            if all((candidate[0] - p[0]) ** 2 + (candidate[1] - p[1]) ** 2 > (0.045 * sx) ** 2 for p in selected):
                selected.append(candidate)
                break
        else:
            selected.append(ranked[0])
    # Fixed, readable boxes; use the same extent for all panels.
    # Smaller panels keep the overview readable and prevent the A--F frames
    # from colliding with the legend/scale bar at the foot of the map.
    bw, bh = 0.15 * sx, 0.15 * sy
    boxes = {}
    for label, point in zip(targets, selected):
        cx, cy = point[:2]
        x0 = min(max(cx - bw / 2, xmin), xmax - bw)
        y0 = min(max(cy - bh / 2, ymin), ymax - bh)
        boxes[label] = (x0, y0, x0 + bw, y0 + bh)
    return boxes


def polygon_collection(features, cmap, norm, value_index=1):
    patches, values = [], []
    for f in features:
        vals = list(f["properties"].values())
        value = parse_degree(vals[value_index])
        if not math.isfinite(value):
            continue
        ps = patch_from_geometry(f["geometry"])
        patches.extend(ps)
        values.extend([value] * len(ps))
    coll = PatchCollection(patches, cmap=cmap, norm=norm, linewidth=0.18, edgecolor=(1, 1, 1, 0.15))
    coll.set_array(np.asarray(values, dtype=float))
    return coll


def add_north_arrow(ax):
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    x = xmin + 0.11 * (xmax - xmin)
    y = ymax - 0.11 * (ymax - ymin)
    ax.annotate("", xy=(x, y + 0.055 * (ymax - ymin)), xytext=(x, y - 0.045 * (ymax - ymin)),
                arrowprops=dict(width=1.5, headwidth=9, headlength=12, facecolor="black", edgecolor="black"))
    ax.text(x, y + 0.065 * (ymax - ymin), "N", ha="center", va="bottom", fontsize=12, fontweight="bold")


def add_scale_bar(ax, length_km=20):
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    # EPSG:4527 metres; the map is CGCS2000 3-degree GK zone 39.
    length = length_km * 1000.0
    x0 = xmin + 0.58 * (xmax - xmin)
    y0 = ymin + 0.045 * (ymax - ymin)
    h = 0.012 * (ymax - ymin)
    for i in range(4):
        ax.add_patch(Rectangle((x0 + i * length / 4, y0), length / 4, h,
                               facecolor="black" if i % 2 == 0 else "white", edgecolor="black", linewidth=0.6, zorder=20))
    for i, label in enumerate(["0", "5", "10", "15", "20"]):
        ax.text(x0 + i * length / 4, y0 - 0.018 * (ymax - ymin), label,
                ha="center", va="top", fontsize=7)
    ax.text(x0 + length + 0.01 * (xmax - xmin), y0 + h / 2, "km", ha="left", va="center", fontsize=8)


def make_figure(gdb: Path, city_path: Path, workface_path: Path, out_dir: Path, raster_path: Path | None = None):
    layer_name, cloud_crs, cloud, cloud_bounds, cloud_schema = load_gdb_layer(gdb, 8)
    workfaces, workface_crs, _ = load_vector(workface_path)
    city, city_crs, _ = load_vector(city_path)
    # All primary inputs are in EPSG:4527.  The city boundary is projected once
    # by the calling preparation step; keeping the renderer free of a second
    # projection library avoids silently changing the local datum.
    if "4527" not in str(city_crs):
        raise RuntimeError("城市边界需要先投影到 EPSG:4527 后再渲染；请使用 --city 指向投影后的边界。")
    city_to_cloud = None
    raster_data = raster_crs = raster_nodata = raster_transform = None
    if raster_path:
        raster_data, raster_crs, cloud_bounds, raster_nodata, raster_transform = load_raster(raster_path)
    cloud_names = list(cloud_schema["properties"].keys())
    degree_field = cloud_names[1]
    area_field = cloud_names[2]
    if raster_data is not None:
        degree_values = raster_data.compressed().astype(float).tolist()
    else:
        degree_values = [parse_degree(list(f["properties"].values())[1]) for f in cloud]
        degree_values = [v for v in degree_values if math.isfinite(v)]
    raw_vmin, raw_vmax = min(degree_values), max(degree_values)
    # A one-year display should not be stretched by the two deepest outliers.
    # The raw range remains in the sidecar; values below -4 m are clipped only
    # for the colour ramp, not discarded from the map geometry.
    vmin, vmax = max(raw_vmin, -4.0), 0.0
    norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax, clip=True)
    cmap = mpl.colors.LinearSegmentedColormap.from_list("subsidence", ["#061b9b", "#0077e6", "#00d6d6", "#ffe84a", "#fff4a6"])
    boxes = choose_zoom_boxes(cloud, cloud_bounds)

    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": font_name(), "axes.unicode_minus": False, "mathtext.fontset": "stix"})
    fig = plt.figure(figsize=(13.5, 9.2), dpi=300, facecolor="white")
    gs = fig.add_gridspec(2, 4, width_ratios=[1.58, 1, 1, 1], wspace=0.06, hspace=0.08,
                          left=0.045, right=0.985, bottom=0.07, top=0.91)
    overview = fig.add_subplot(gs[:, 0])
    panels = [fig.add_subplot(gs[r, c]) for r in range(2) for c in range(1, 4)]
    xmin, ymin, xmax, ymax = cloud_bounds
    pad_x, pad_y = 0.03 * (xmax - xmin), 0.03 * (ymax - ymin)
    overview.set_xlim(xmin - pad_x, xmax + pad_x)
    overview.set_ylim(ymin - pad_y, ymax + pad_y)
    overview.set_aspect("equal")
    overview.set_facecolor("white")
    for f in city:
        for p in patch_from_geometry(f["geometry"], city_to_cloud):
            p.set(facecolor="#f6f7f8", edgecolor="#a6abb2", linewidth=0.8, zorder=1)
            overview.add_patch(p)
    if raster_data is not None:
        overview.imshow(raster_data, extent=(xmin, xmax, ymin, ymax), origin="upper",
                        cmap=cmap, norm=norm, interpolation="nearest", zorder=3)
    else:
        cloud_coll = polygon_collection(cloud, cmap, norm)
        cloud_coll.set_zorder(3)
        overview.add_collection(cloud_coll)
    for f in workfaces:
        for p in patch_from_geometry(f["geometry"]):
            p.set(facecolor="none", edgecolor="#a4e4f4", linewidth=0.35, zorder=4)
            overview.add_patch(p)
    for label, (x0, y0, x1, y1) in boxes.items():
        overview.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="#e31a1c", linewidth=1.1, zorder=20))
        overview.text(x0 + 0.012 * (x1 - x0), y1 - 0.012 * (y1 - y0), label, color="#d7191c", fontsize=12, fontweight="bold", va="top", zorder=21)
    overview.set_xticks([]); overview.set_yticks([])
    for side in overview.spines.values(): side.set_color("#555555"); side.set_linewidth(0.8)
    add_north_arrow(overview)
    add_scale_bar(overview, 20)
    # Legend: continuous interval with the raw negative sign retained.
    cax = overview.inset_axes([0.09, 0.15, 0.055, 0.38])
    cb = fig.colorbar(mpl.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax, orientation="vertical")
    cb.set_label("沉陷值（m）", fontsize=8, labelpad=3)
    cb.ax.tick_params(labelsize=7, length=2)
    cb.set_ticks(np.linspace(vmin, vmax, 5))
    cb.set_ticklabels([f"{x:.1f}" for x in np.linspace(vmin, vmax, 5)])
    for i, (label, (x0, y0, x1, y1)) in enumerate(boxes.items()):
        ax = panels[i]
        ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal")
        ax.set_facecolor("white")
        for f in workfaces:
            for p in patch_from_geometry(f["geometry"]):
                p.set(facecolor="none", edgecolor="#a4e4f4", linewidth=0.55, zorder=1)
                ax.add_patch(p)
        if raster_data is not None:
            ax.imshow(raster_data, extent=(xmin, xmax, ymin, ymax), origin="upper",
                      cmap=cmap, norm=norm, interpolation="nearest", zorder=3)
        else:
            coll = polygon_collection(cloud, cmap, norm)
            coll.set_zorder(3)
            ax.add_collection(coll)
        ax.text(0.02, 0.97, label, transform=ax.transAxes, ha="left", va="top", fontsize=13, color="#d7191c", fontweight="bold")
        ax.set_xticks([]); ax.set_yticks([])
        for side in ax.spines.values(): side.set_color("#777777"); side.set_linewidth(0.6)
    fig.suptitle("概率积分法预计2026年皖北六市矿区沉陷云图", fontsize=16, y=0.955, fontweight="bold")
    png = out_dir / "2026年皖北六市矿区沉陷云图_A-F.png"
    pdf = out_dir / "2026年皖北六市矿区沉陷云图_A-F.pdf"
    svg = out_dir / "2026年皖北六市矿区沉陷云图_A-F.svg"
    fig.savefig(png, dpi=300, facecolor="white")
    fig.savefig(pdf, facecolor="white")
    fig.savefig(svg, facecolor="white")
    plt.close(fig)
    metadata = {
        "source_gdb": str(gdb),
        "source_layer_index": 8,
        "source_layer_name_as_read": layer_name,
        "source_crs": str(cloud_crs),
        "source_raster": str(raster_path) if raster_path else None,
        "source_raster_crs": str(raster_crs) if raster_crs else None,
        "cloud_field": degree_field,
        "area_field_not_used_for_color": area_field,
        "degree_min_m_raw": raw_vmin,
        "degree_max_m_raw": raw_vmax,
        "display_min_m": vmin,
        "display_max_m": vmax,
        "workface_source": str(workface_path),
        "city_boundary_source": str(city_path),
        "zoom_boxes_epsg4527": {k: list(map(float, v)) for k, v in boxes.items()},
        "display_note": "颜色按 Degree 区间中点显示；原始负号和区间语义保留，未将面积字段误作为沉陷值。色带显示范围为 -4–0 m，低于 -4 m 的极少数值仅在颜色上截断。",
        "outputs": [str(png), str(pdf), str(svg)],
    }
    (out_dir / "2026年沉陷云图_来源与参数.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return png, metadata


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gdb", type=Path, required=True)
    ap.add_argument("--city", type=Path, required=True)
    ap.add_argument("--workface", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--raster", type=Path, default=None, help="从 GDB 导出的 2026 连续沉陷栅格 GeoTIFF")
    args = ap.parse_args()
    png, meta = make_figure(args.gdb, args.city, args.workface, args.out, args.raster)
    print(json.dumps({"png": str(png), "vmin": meta["display_min_m"], "vmax": meta["display_max_m"], "raw_min": meta["degree_min_m_raw"], "raw_max": meta["degree_max_m_raw"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
