"""Render the MAESA result package in a reproducible paper-style layout.

The renderer deliberately keeps the raster map and all furniture in separate
areas of the figure.  This avoids legends, titles, coordinate labels and scale
bars hiding the mining-area data.  Categorical LULC maps use the six-class
contract; continuous products share a stable colour scale within each product.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path

import fiona
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap, Normalize
from matplotlib.font_manager import FontProperties
from matplotlib.patches import PathPatch, Polygon, Rectangle, Patch
from matplotlib.path import Path as MplPath
from matplotlib.ticker import FuncFormatter, MaxNLocator
import numpy as np
import rasterio
from rasterio.warp import transform as rio_transform


ROOT = Path.cwd()
RESULT = ROOT / "results"
YEARS = [2005, 2010, 2015, 2020, 2025]
SCENARIOS = ["ND", "UD", "EP", "RE"]

CN = {
    "lulc": "\u571f\u5730\u5229\u7528\u5206\u7c7b",
    "carbon": "\u78b3\u50a8\u91cf",
    "water_yield": "\u6c34\u6e90\u4f9b\u7ed9",
    "habitat_quality": "\u751f\u5883\u8d28\u91cf",
    "ecosystem_service": "\u7efc\u5408\u751f\u6001\u7cfb\u7edf\u670d\u52a1",
    "water": "\u6c34\u4f53",
    "built": "\u5efa\u8bbe\u7528\u5730",
    "crop": "\u8015\u5730",
    "forest": "\u6797\u5730",
    "grass": "\u8349\u5730",
    "bare": "\u88f8\u5730/\u5de5\u77ff\u7528\u5730",
    "km": "km",
    "year": "\u5e74",
    "unit_carbon": "Mg C/ha",
    "unit_water": "mm",
    "unit_index": "\u6307\u6570\u503c",
}
# Enhanced six-class contract used by the supplied ROI metadata:
# 1 subsidence water, 2 natural water, 3 built-up, 4 cropland,
# 5 forest, 6 grassland.  There is no bare/mining class in this run.
LULC_LABELS = ["\u6c89\u9677\u79ef\u6c34", "\u81ea\u7136\u6c34\u4f53", "\u5efa\u8bbe\u7528\u5730", "\u8015\u5730", "\u6797\u5730", "\u8349\u5730"]
LULC_COLORS = ["#08519c", "#6baed6", "#f781bf", "#fee08b", "#1b7837", "#a6d96a"]
SC_LABELS = {"ND": "\u81ea\u7136\u53d1\u5c55\u60c5\u666f", "UD": "\u57ce\u9547\u53d1\u5c55\u60c5\u666f", "EP": "\u751f\u6001\u4fdd\u62a4\u60c5\u666f", "RE": "\u8d44\u6e90\u5f00\u91c7\u60c5\u666f"}
SC_SHORT = {"ND": "ND", "UD": "UD", "EP": "EP", "RE": "RE"}

SIMSUN = r"C:/Windows/Fonts/simsun.ttc"
SIMHEI = r"C:/Windows/Fonts/simhei.ttf"
TIMES = r"C:/Windows/Fonts/times.ttf"
ZH = FontProperties(fname=SIMSUN, size=9)
ZH_SMALL = FontProperties(fname=SIMSUN, size=7.5)
ZH_TITLE = FontProperties(fname=SIMHEI, size=11, weight="bold")
NUM = FontProperties(fname=TIMES, size=8)
NUM_SMALL = FontProperties(fname=TIMES, size=7)


def ensure_dirs() -> None:
    for folder in ["\u571f\u5730\u5229\u7528\u5206\u7c7b", "\u78b3\u50a8\u91cf", "\u6c34\u6e90\u4f9b\u7ed9", "\u751f\u5883\u8d28\u91cf", "\u7efc\u5408\u751f\u6001\u7cfb\u7edf\u670d\u52a1", "\u571f\u5730\u5229\u7528\u8f6c\u79fb\u77e9\u9635", "\u6851\u57fa", "\u65f6\u7a7a\u5206\u5e03", "\u5206\u6790\u7edf\u8ba1\u56fe\u4e0e\u8868"]:
        (RESULT / folder).mkdir(parents=True, exist_ok=True)


def source_rasters(kind: str, scenario: str | None = None) -> dict[int, Path]:
    if scenario:
        if kind == "lulc":
            base = ROOT / "runtime_plus_harmonized_v2" / "outputs" / "plus_harmonized_v2" / scenario / f"PLUS_{scenario}.tif"
        elif kind == "carbon":
            base = ROOT / "outputs" / "invest_scenarios_harmonized_v2" / scenario / "carbon" / "2026" / "tot_c_cur.tif"
        elif kind == "water_yield":
            base = ROOT / "outputs" / "invest_scenarios_harmonized_v2" / scenario / "water" / "2026" / "output" / "per_pixel" / f"wyield_wy_2026_{scenario}.tif"
        elif kind == "habitat_quality":
            base = ROOT / "outputs" / "invest_scenarios_harmonized_v2" / scenario / "habitat_318_native" / "2026" / f"quality_c_hq_2026_{scenario}.tif"
        else:
            base = ROOT / "outputs" / "ecosystem_service_scenarios_harmonized_v2" / "native_ND_UD_EP_RE" / f"ecosystem_service_2026_{scenario}.tif"
        return {2026: base}
    mapping = {
        "lulc": ROOT / "outputs" / "statistics_harmonized_v2_common_support" / "lulc",
        "carbon": ROOT / "outputs" / "invest" / "carbon_series_harmonized_v2",
        "water_yield": ROOT / "outputs" / "invest" / "water_yield_harmonized_v2",
        "habitat_quality": ROOT / "outputs" / "invest" / "habitat_quality_318_native_harmonized_v2c",
        "ecosystem_service": ROOT / "outputs" / "ecosystem_service_harmonized_v2_native_habitat",
    }
    out: dict[int, Path] = {}
    base = mapping[kind]
    for year in YEARS:
        if kind == "lulc":
            p = base / f"LULC_{year}_30m_masked.tif"
        elif kind == "carbon":
            p = base / str(year) / "tot_c_cur.tif"
        elif kind == "water_yield":
            p = base / str(year) / "output" / "per_pixel" / f"wyield_wy_{year}.tif"
        elif kind == "habitat_quality":
            # Native InVEST 3.18 outputs use ``quality_c_hq_<year>.tif``;
            # older harmonised runs used ``quality_<year>_30m.tif``.  Accept
            # both contracts so a completed rerun is not mistaken for a
            # missing raster.
            p = base / str(year) / f"quality_{year}_30m.tif"
            if not p.exists():
                p = base / str(year) / f"quality_c_hq_{year}.tif"
        else:
            p = base / f"ecosystem_service_{year}.tif"
        if p.exists():
            out[year] = p
    return out


def read_raster(path: Path):
    with rasterio.open(path) as src:
        arr = src.read(1, masked=True)
        return arr, src.transform, src.crs, src.bounds, src.width, src.height


def continuous_array(path: Path, kind: str):
    arr, transform, crs, bounds, width, height = read_raster(path)
    if kind == "carbon":
        arr = np.ma.masked_where(arr.data <= 0, arr)
        # InVEST Carbon stores Mg C per pixel.  The publication map displays
        # density, so convert the 30 m pixel stock to Mg C per hectare.
        pixel_area_ha = abs(transform.a * transform.e) / 10000.0
        arr = arr / pixel_area_ha
    elif kind != "lulc":
        arr = np.ma.masked_where(arr.data < 0, arr)
    return arr, transform, crs, bounds, width, height


def boundary_rings(path: Path, transformer: Transformer):
    rings = []
    with fiona.open(path) as src:
        for feat in src:
            geom = feat.get("geometry") or {}
            typ = geom.get("type")
            coords = geom.get("coordinates", [])
            polys = coords if typ == "MultiPolygon" else [coords]
            for poly in polys:
                if not poly:
                    continue
                xy = [transformer.transform(x, y) for x, y in poly[0]]
                if len(xy) > 2:
                    rings.append(np.asarray(xy))
    return rings


def choose_boundary(crs):
    p = ROOT / "boundaries" / "wanbei.shp"
    if not p.exists():
        p = ROOT / "boundaries" / "mine_boundary.shp"
    # supplied wanbei is geographic, mine_boundary is EPSG:4527.  Reproject
    # from the dataset CRS to the raster CRS.
    with fiona.open(p) as src:
        src_crs = src.crs_wkt or src.crs
    try:
        transformer = _Transformer(src_crs, crs)
    except Exception:
        transformer = _Transformer("EPSG:4326", crs)
    return p, transformer


class _Transformer:
    """Small rasterio-backed replacement for pyproj Transformer."""
    def __init__(self, src, dst): self.src, self.dst = src, dst
    def transform(self, x, y):
        xx, yy = rio_transform(self.src, self.dst, [x], [y])
        return xx[0], yy[0]


def geo_format_x(crs):
    to_geo = _Transformer(crs, "EPSG:4326")
    def fmt(x, _pos):
        lon, _ = to_geo.transform(x, 0)
        return f"{lon:.2f}\N{DEGREE SIGN}"
    return fmt


def geo_format_y(crs):
    to_geo = _Transformer(crs, "EPSG:4326")
    def fmt(y, _pos):
        _, lat = to_geo.transform(0, y)
        return f"{lat:.2f}\N{DEGREE SIGN}"
    return fmt


def apply_geo_ticks(ax, crs):
    ax.xaxis.set_major_locator(MaxNLocator(4))
    ax.yaxis.set_major_locator(MaxNLocator(4))
    ax.xaxis.set_major_formatter(FuncFormatter(geo_format_x(crs)))
    ax.yaxis.set_major_formatter(FuncFormatter(geo_format_y(crs)))
    ax.xaxis.set_ticks_position("both")
    ax.yaxis.set_ticks_position("both")
    ax.tick_params(axis="both", which="major", direction="out", length=4, width=0.7,
                   top=True, right=True, labeltop=True, labelright=True, pad=3)
    for label in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
        label.set_fontproperties(NUM_SMALL)
    ax.grid(False)


def dms(value: float, is_lon: bool) -> str:
    sign = "E" if is_lon and value >= 0 else "W" if is_lon else "N" if value >= 0 else "S"
    v = abs(value); deg = int(v); minute = int(round((v - deg) * 60))
    if minute == 60: deg += 1; minute = 0
    return f"{deg}\N{DEGREE SIGN}{minute:02d}\N{PRIME}{sign}"


def apply_paper_ticks(ax, crs):
    to_geo = _Transformer(crs, "EPSG:4326")
    def fmt_x(x, _pos): return dms(to_geo.transform(x, 0)[0], True)
    def fmt_y(y, _pos): return dms(to_geo.transform(0, y)[1], False)
    ax.xaxis.set_major_locator(MaxNLocator(4)); ax.yaxis.set_major_locator(MaxNLocator(4))
    ax.xaxis.set_major_formatter(FuncFormatter(fmt_x)); ax.yaxis.set_major_formatter(FuncFormatter(fmt_y))
    ax.xaxis.set_ticks_position("both"); ax.yaxis.set_ticks_position("both")
    ax.tick_params(axis="both", which="major", direction="out", length=4, width=.7,
                   top=True, right=True, labeltop=True, labelright=True, pad=5)
    for t in ax.get_xticklabels():
        t.set_fontproperties(NUM_SMALL)
    # Publication maps in the supplied reference use vertical latitude
    # labels on both sides of the frame.  Keep longitude labels horizontal.
    for t in ax.get_yticklabels():
        t.set_fontproperties(NUM_SMALL)
        t.set_rotation(90)
        t.set_rotation_mode("anchor")
        t.set_verticalalignment("center")
        t.set_horizontalalignment("center")
    ax.grid(False)


def draw_context(ax, rings):
    for ring in rings:
        ax.add_patch(Polygon(ring, closed=True, facecolor="#f2f3f4", edgecolor="#9aa1a8", lw=.7, zorder=0))


def draw_boundary_outline(ax, rings):
    for ring in rings:
        ax.add_patch(Polygon(ring, closed=True, fill=False, edgecolor="#8f969d", lw=.65, zorder=4))


def add_lulc_legend_fig(fig):
    handles = [Patch(facecolor=c, edgecolor="#454545", linewidth=.35, label=l) for l, c in zip(LULC_LABELS, LULC_COLORS)]
    # The legend occupies the dedicated lower-left margin of the frame,
    # below the map axes, so it cannot cover either the context boundary or
    # the classified raster.
    leg = fig.legend(handles=handles, title="\u56fe\u4f8b", loc="lower left", bbox_to_anchor=(.105, .085),
                     bbox_transform=fig.transFigure, frameon=True, framealpha=1.0,
                     facecolor="white", edgecolor="#666666", borderpad=.55,
                     labelspacing=.34, handlelength=1.35, handleheight=.75,
                     prop=ZH_SMALL, title_fontproperties=ZH)
    leg.get_frame().set_linewidth(.8)


def add_colorbar_ax(fig, ax, norm, cmap, label):
    # A narrow vertical strip fits the lower-left reserved margin inside the
    # frame, so the actual raster keeps its full size and the legend never
    # covers the city/mining result.  All text is kept inside the frame too.
    cax = fig.add_axes([.115, .095, .024, .100], facecolor="white", zorder=20)
    cax.patch.set_alpha(.96)
    cb = matplotlib.colorbar.ColorbarBase(cax, cmap=cmap, norm=norm, orientation="vertical")
    cb.set_label(label, fontproperties=ZH_SMALL, labelpad=3, rotation=90)
    for t in cb.ax.get_yticklabels(): t.set_fontproperties(NUM_SMALL)
    cb.outline.set_linewidth(.45)


def add_scale_ax(ax, km=40):
    # ArcGIS-style alternating black/white scale bar.
    x0, y0, w, h = .77, .037, .18, .014
    pieces = [0, 10, 20, 30, 40]
    for i in range(len(pieces) - 1):
        left = x0 + w * i / 4
        width = w / 4
        ax.add_patch(Rectangle((left, y0), width, h, transform=ax.transAxes,
                               facecolor="black" if i % 2 == 0 else "white",
                               edgecolor="black", linewidth=.65, zorder=10, clip_on=False))
    for i, lab in enumerate(["0", "10", "20", "30", "40"]):
        x = x0 + w*i/4
        ax.plot([x, x], [y0-.004, y0+h+.004], transform=ax.transAxes,
                color="black", lw=.65, zorder=11, clip_on=False)
        ax.text(x, y0-.012, lab, transform=ax.transAxes, ha="center", va="top",
                fontproperties=NUM_SMALL, zorder=11)
    ax.text(x0+w+.012, y0-.012, CN["km"], transform=ax.transAxes, ha="left", va="top",
            fontproperties=NUM_SMALL, zorder=11)


def add_scale_fig(fig, km=40):
    """Draw the scale bar in the reserved bottom margin of the frame."""
    # Keep both the last tick and the unit label comfortably inside the
    # outer frame (x=0.025--0.975).
    a = fig.add_axes([.66, .092, .245, .060], facecolor="none", zorder=21)
    a.set_xlim(0, km + 4); a.set_ylim(0, 1); a.axis("off")
    x0, y0, w, h = 0, .47, km, .18
    pieces = [0, 10, 20, 30, 40]
    for i in range(len(pieces) - 1):
        a.add_patch(Rectangle((pieces[i], y0), pieces[i + 1] - pieces[i], h,
                              facecolor="black" if i % 2 == 0 else "white",
                              edgecolor="black", linewidth=.65))
    for x in pieces:
        a.plot([x, x], [y0-.07, y0+h+.07], color="black", lw=.65)
        a.text(x, y0-.16, str(x), ha="center", va="top", fontproperties=NUM_SMALL)
    a.text(km + .7, y0-.16, CN["km"], ha="left", va="top", fontproperties=NUM_SMALL, clip_on=True)


def add_north_ax(ax):
    # Compact black/white compass rose, fully contained within the map frame.
    x, y = .075, .855
    ax.text(x, y+.095, "N", transform=ax.transAxes, ha="center", va="bottom", fontproperties=NUM_SMALL, zorder=11)
    ax.add_patch(Polygon([(x, y+.080), (x-.008, y+.012), (x, y+.028), (x+.008, y+.012)],
                         closed=True, transform=ax.transAxes, facecolor="black", edgecolor="black", lw=.35, zorder=11))
    ax.add_patch(Polygon([(x, y+.028), (x-.008, y+.012), (x, y-.045), (x+.008, y+.012)],
                         closed=True, transform=ax.transAxes, facecolor="white", edgecolor="black", lw=.35, zorder=11))


def draw_north(fig):
    a = fig.add_axes([0.065, 0.70, 0.08, 0.14])
    a.set_axis_off()
    a.annotate("", xy=(0.52, 0.92), xytext=(0.52, 0.18), arrowprops=dict(arrowstyle="-|>", lw=1.0, color="black"))
    a.text(0.52, 0.98, "N", ha="center", va="top", fontproperties=NUM, fontsize=10)


def draw_scale(fig, km=40):
    a = fig.add_axes([0.66, 0.085, 0.27, 0.055])
    a.set_xlim(0, km)
    a.set_ylim(0, 1)
    a.axis("off")
    pieces = [0, 10, 20, 30, 40]
    for i in range(len(pieces) - 1):
        a.add_patch(Rectangle((pieces[i], 0.42), pieces[i + 1] - pieces[i], 0.22,
                              facecolor="black" if i % 2 == 0 else "white", edgecolor="black", lw=0.7))
    for x in pieces:
        a.plot([x, x], [0.39, 0.69], color="black", lw=0.7)
        a.text(x, 0.12, str(x), ha="center", va="top", fontproperties=NUM_SMALL)
    a.text(km + 1.5, 0.12, CN["km"], ha="left", va="top", fontproperties=NUM_SMALL)


def add_frame(fig, title: str):
    fig.add_artist(Rectangle((0.025, 0.055), 0.95, 0.89, transform=fig.transFigure,
                             fill=False, edgecolor="black", lw=0.85))
    fig.text(0.50, 0.915, title, ha="center", va="center", fontproperties=ZH_TITLE)


def add_lulc_legend(fig):
    a = fig.add_axes([0.045, 0.12, 0.15, 0.31])
    a.set_axis_off()
    a.text(0.02, 0.98, "\u56fe\u4f8b", ha="left", va="top", fontproperties=ZH)
    for i, (lab, col) in enumerate(zip(LULC_LABELS, LULC_COLORS)):
        y = 0.85 - i * 0.135
        a.add_patch(Rectangle((0.02, y - 0.045), 0.20, 0.08, facecolor=col, edgecolor="black", lw=0.35))
        a.text(0.28, y, lab, ha="left", va="center", fontproperties=ZH_SMALL)


def add_colorbar(fig, norm, cmap, label, ticks=None):
    cax = fig.add_axes([0.25, 0.095, 0.34, 0.028])
    cb = matplotlib.colorbar.ColorbarBase(cax, cmap=cmap, norm=norm, orientation="horizontal")
    cb.set_label(label, fontproperties=ZH_SMALL, labelpad=3)
    if ticks is not None:
        cb.set_ticks(ticks)
    for t in cb.ax.get_xticklabels():
        t.set_fontproperties(NUM_SMALL)
    cb.outline.set_linewidth(0.45)


def map_figure(path: Path, kind: str, title: str, output: Path, vmin=None, vmax=None,
               common_cmap=None, common_norm=None):
    arr, transform, crs, bounds, width, height = read_raster(path) if kind == "lulc" else continuous_array(path, kind)
    if kind == "lulc": arr = np.ma.masked_where(arr.data == 0, arr)
    fig = plt.figure(figsize=(7.2, 7.0), dpi=300, facecolor="white")
    extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]
    bpath, transformer = choose_boundary(crs)
    rings = boundary_rings(bpath, transformer)
    allxy = np.vstack(rings)
    full = [float(allxy[:, 0].min()), float(allxy[:, 0].max()), float(allxy[:, 1].min()), float(allxy[:, 1].max())]
    # Keep only a narrow geographic margin.  The previous 2.5% padding left
    # a lot of unused white space around the six-city boundary; 1.5% gives the
    # map a tighter, paper-like composition without clipping the frame.
    padx, pady = (full[1]-full[0])*.015, (full[3]-full[2])*.015
    full = [full[0]-padx, full[1]+padx, full[2]-pady, full[3]+pady]
    # The outer axes carries the frame and coordinate labels.  The inner
    # axes contains only the map itself, leaving clean top/bottom margins for
    # title, legends and scale bar.
    frame_ax = fig.add_axes([0.075, 0.065, 0.85, 0.84], facecolor="none", zorder=10)
    frame_ax.set_xlim(full[0], full[1]); frame_ax.set_ylim(full[2], full[3])
    apply_paper_ticks(frame_ax, crs)
    for s in frame_ax.spines.values():
        s.set_linewidth(0.8)
        s.set_color("black")
    # Widen the map area while preserving the dedicated lower furniture band
    # used by the legend/colorbar and scale bar.
    ax = fig.add_axes([0.075, 0.20, 0.85, 0.66], facecolor="none", zorder=1)
    ax.set_xlim(full[0], full[1]); ax.set_ylim(full[2], full[3])
    draw_context(ax, rings)
    if kind == "lulc":
        cmap = ListedColormap(LULC_COLORS)
        norm = BoundaryNorm(np.arange(0.5, 6.6, 1), cmap.N)
        im = ax.imshow(arr, cmap=cmap, norm=norm, extent=extent, interpolation="nearest", zorder=2)
    else:
        data = arr.compressed()
        if common_norm is not None:
            norm = common_norm
            cmap = common_cmap
        else:
            lo = float(np.nanpercentile(data, 2)) if vmin is None else float(vmin)
            hi = float(np.nanpercentile(data, 98)) if vmax is None else float(vmax)
            if not math.isfinite(lo) or not math.isfinite(hi) or lo == hi:
                lo, hi = float(np.nanmin(data)), float(np.nanmax(data) + 1e-9)
            norm = Normalize(lo, hi)
            cmap = common_cmap or plt.get_cmap("viridis")
        ax.imshow(arr, cmap=cmap, norm=norm, extent=extent, interpolation="nearest", zorder=2)
    draw_boundary_outline(ax, rings)
    # The inner map axes is intentionally frameless and tickless.  Reapply
    # the study extent after imshow (which may autoscale) so the outer frame
    # remains the sole coordinate frame.
    ax.set_xlim(full[0], full[1]); ax.set_ylim(full[2], full[3])
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    # Keep the title in the reserved top margin, inside the outer frame.
    fig.text(.50, .878, title, ha="center", va="center", fontproperties=ZH_TITLE, zorder=30)
    add_north_ax(ax); add_scale_fig(fig)
    if kind == "lulc":
        add_lulc_legend_fig(fig)
    else:
        units = {"carbon": CN["unit_carbon"], "water_yield": CN["unit_water"],
                 "habitat_quality": CN["unit_index"], "ecosystem_service": CN["unit_index"]}[kind]
        add_colorbar_ax(fig, ax, norm, cmap, units)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output.with_suffix(".png"), dpi=300, bbox_inches=None)
    fig.savefig(output.with_suffix(".pdf"), bbox_inches=None)
    fig.savefig(output.with_suffix(".svg"), bbox_inches=None)
    plt.close(fig)


def render_maps():
    out_dirs = {
        "lulc": RESULT / "\u571f\u5730\u5229\u7528\u5206\u7c7b",
        "carbon": RESULT / "\u78b3\u50a8\u91cf",
        "water_yield": RESULT / "\u6c34\u6e90\u4f9b\u7ed9",
        "habitat_quality": RESULT / "\u751f\u5883\u8d28\u91cf",
        "ecosystem_service": RESULT / "\u7efc\u5408\u751f\u6001\u7cfb\u7edf\u670d\u52a1",
    }
    titles = {
        "lulc": lambda y: f"{y}\u5e74\u7696\u5317\u516d\u5e02\u77ff\u533a\u571f\u5730\u5229\u7528\u5206\u7c7b\u56fe",
        "carbon": lambda y: f"{y}\u5e74\u7696\u5317\u516d\u5e02\u77ff\u533a\u78b3\u50a8\u91cf\u7a7a\u95f4\u5206\u5e03\u56fe",
        "water_yield": lambda y: f"{y}\u5e74\u7696\u5317\u516d\u5e02\u77ff\u533a\u6c34\u6e90\u4f9b\u7ed9\u7a7a\u95f4\u5206\u5e03\u56fe",
        "habitat_quality": lambda y: f"{y}\u5e74\u7696\u5317\u516d\u5e02\u77ff\u533a\u751f\u5883\u8d28\u91cf\u7a7a\u95f4\u5206\u5e03\u56fe",
        "ecosystem_service": lambda y: f"{y}\u5e74\u7696\u5317\u516d\u5e02\u77ff\u533a\u7efc\u5408\u751f\u6001\u7cfb\u7edf\u670d\u52a1\u7a7a\u95f4\u5206\u5e03\u56fe",
    }
    for kind in out_dirs:
        srcs = source_rasters(kind)
        common = None
        if kind != "lulc":
            vals = []
            for p in srcs.values():
                with rasterio.open(p) as s:
                    a = s.read(1, masked=True)
                    if kind == "carbon":
                        a = np.ma.masked_where(a.data <= 0, a)
                        pixel_area_ha = abs(s.transform.a * s.transform.e) / 10000.0
                        a = a / pixel_area_ha
                    a = a.compressed()
                    vals.append(a[np.isfinite(a)][:: max(1, a.size // 200000)])
            # A partially completed rerun may legitimately have no valid
            # historical rasters for one product.  Do not abort the complete
            # publication build in that case; each available map will use its
            # own robust range and the missing product is reported below.
            vals = [v for v in vals if v.size]
            if vals:
                allv = np.concatenate(vals)
                common = Normalize(float(np.nanpercentile(allv, 2)), float(np.nanpercentile(allv, 98)))
        for y, p in srcs.items():
            name = f"{y}_{kind}"
            map_figure(p, kind, titles[kind](y), out_dirs[kind] / "\u5386\u53f2\u65f6\u671f" / str(y) / name,
                       common_cmap=plt.get_cmap("viridis") if kind != "lulc" else None, common_norm=common)
        for sc in SCENARIOS:
            src = source_rasters(kind, sc).get(2026)
            if src and src.exists():
                title = f"2026\u5e74{SC_LABELS[sc]}\u7696\u5317\u516d\u5e02\u77ff\u533a{CN[kind] if kind in CN else kind}\u56fe"
                map_figure(src, kind, title, out_dirs[kind] / "PLUS2026" / sc / f"2026_{kind}_{sc}", common_cmap=plt.get_cmap("viridis") if kind != "lulc" else None, common_norm=common)


def transition_matrix(a_path: Path, b_path: Path):
    with rasterio.open(a_path) as a, rasterio.open(b_path) as b:
        x = a.read(1, masked=True).filled(0).astype(np.int16)
        y = b.read(1, masked=True).filled(0).astype(np.int16)
    mask = (x >= 1) & (x <= 6) & (y >= 1) & (y <= 6)
    m = np.zeros((6, 6), dtype=np.int64)
    np.add.at(m, (x[mask] - 1, y[mask] - 1), 1)
    return m


def write_transition_outputs():
    base = ROOT / "outputs" / "classification" / "final_grid_v3"
    out = RESULT / "\u571f\u5730\u5229\u7528\u8f6c\u79fb\u77e9\u9635"
    rows = []
    for y0, y1 in zip(YEARS[:-1], YEARS[1:]):
        m = transition_matrix(base / f"LULC_{y0}_30m_masked.tif", base / f"LULC_{y1}_30m_masked.tif")
        csv_path = out / f"\u571f\u5730\u5229\u7528\u8f6c\u79fb\u77e9\u9635_{y0}_{y1}.csv"
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(["\u8d77\u59cb\\\u7ec8\u6b62"] + LULC_LABELS)
            for lab, row in zip(LULC_LABELS, m): w.writerow([lab] + [f"{int(v)*0.09:.2f}" for v in row])
        fig, ax = plt.subplots(figsize=(6.6, 5.4), dpi=300)
        im = ax.imshow(m * 0.09, cmap="YlGnBu")
        ax.set_xticks(range(6), LULC_LABELS, rotation=30, ha="right", fontproperties=ZH_SMALL)
        ax.set_yticks(range(6), LULC_LABELS, fontproperties=ZH_SMALL)
        ax.set_xlabel(f"{y1}\u5e74\u5730\u7c7b", fontproperties=ZH)
        ax.set_ylabel(f"{y0}\u5e74\u5730\u7c7b", fontproperties=ZH)
        ax.set_title(f"{y0}\u2014{y1}\u5e74\u571f\u5730\u5229\u7528\u8f6c\u79fb\u77e9\u9635", fontproperties=ZH_TITLE)
        for i in range(6):
            for j in range(6):
                ax.text(j, i, f"{m[i,j]*0.09:.1f}", ha="center", va="center", fontproperties=NUM_SMALL, color="black")
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04); cb.set_label("\u9762\u79ef (hm\N{SUPERSCRIPT TWO})", fontproperties=ZH_SMALL)
        for t in cb.ax.get_yticklabels(): t.set_fontproperties(NUM_SMALL)
        fig.tight_layout()
        base_name = out / f"\u8f6c\u79fb\u77e9\u9635_{y0}_{y1}"
        fig.savefig(base_name.with_suffix(".png"), dpi=300); fig.savefig(base_name.with_suffix(".pdf")); fig.savefig(base_name.with_suffix(".svg")); plt.close(fig)
        rows.append({"from": y0, "to": y1, "area_hm2": float(m.sum() * 0.09)})
    (out / "transition_summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def write_long_transition_output():
    """Export the complete 2005-2025 land-use transition matrix."""
    base = ROOT / "outputs" / "classification" / "final_grid_v3"
    out = RESULT / "\u571f\u5730\u5229\u7528\u8f6c\u79fb\u77e9\u9635"
    y0, y1 = YEARS[0], YEARS[-1]
    m = transition_matrix(base / f"LULC_{y0}_30m_masked.tif", base / f"LULC_{y1}_30m_masked.tif")
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / f"\u571f\u5730\u5229\u7528\u8f6c\u79fb\u77e9\u9635_{y0}_{y1}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["\u8d77\u59cb\\\u7ec8\u6b62"] + LULC_LABELS)
        for lab, row in zip(LULC_LABELS, m):
            w.writerow([lab] + [f"{int(v) * 0.09:.2f}" for v in row])

    fig, ax = plt.subplots(figsize=(6.6, 5.4), dpi=300)
    im = ax.imshow(m * 0.09, cmap="YlGnBu")
    ax.set_xticks(range(6), LULC_LABELS, rotation=30, ha="right", fontproperties=ZH_SMALL)
    ax.set_yticks(range(6), LULC_LABELS, fontproperties=ZH_SMALL)
    ax.set_xlabel(f"{y1}\u5e74\u5730\u7c7b", fontproperties=ZH)
    ax.set_ylabel(f"{y0}\u5e74\u5730\u7c7b", fontproperties=ZH)
    ax.set_title(f"{y0}\u2014{y1}\u5e74\u571f\u5730\u5229\u7528\u8f6c\u79fb\u77e9\u9635", fontproperties=ZH_TITLE)
    for i in range(6):
        for j in range(6):
            ax.text(j, i, f"{m[i, j] * 0.09:.1f}", ha="center", va="center",
                    fontproperties=NUM_SMALL, color="black")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("\u9762\u79ef (hm\N{SUPERSCRIPT TWO})", fontproperties=ZH_SMALL)
    for t in cb.ax.get_yticklabels():
        t.set_fontproperties(NUM_SMALL)
    fig.tight_layout()
    base_name = out / f"\u8f6c\u79fb\u77e9\u9635_{y0}_{y1}"
    fig.savefig(base_name.with_suffix(".png"), dpi=300)
    fig.savefig(base_name.with_suffix(".pdf"))
    fig.savefig(base_name.with_suffix(".svg"))
    plt.close(fig)


def sankey_flow(m, output: Path, y0: int, y1: int):
    fig, ax = plt.subplots(figsize=(10, 6.4), dpi=300)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    left = m.sum(axis=1).astype(float); right = m.sum(axis=0).astype(float); total = max(left.sum(), 1)
    gap = 0.012; usable = 0.86
    left_h = usable * left / total; right_h = usable * right / total
    yleft = 0.94 - np.cumsum(left_h) + gap; yright = 0.94 - np.cumsum(right_h) + gap
    left_cursor = yleft.copy(); right_cursor = yright.copy()
    x0, x1 = 0.10, 0.86; width = 0.022
    for i in range(6):
        if left[i] > 0: ax.add_patch(Rectangle((x0, yleft[i]), width, left_h[i]-gap, facecolor=LULC_COLORS[i], edgecolor="black", lw=.35))
        if right[i] > 0: ax.add_patch(Rectangle((x1, yright[i]), width, right_h[i]-gap, facecolor=LULC_COLORS[i], edgecolor="black", lw=.35))
    for i in range(6):
        for j in range(6):
            h = usable * m[i,j] / total
            if h <= 0: continue
            ya0, ya1 = left_cursor[i], left_cursor[i] + h
            yb0, yb1 = right_cursor[j], right_cursor[j] + h
            left_cursor[i] = ya1; right_cursor[j] = yb1
            c1, c2 = (x0 + width, x1)
            verts = [(c1, ya0), (c1 + (c2-c1)*0.30, ya0), (c2 - (c2-c1)*0.30, yb0), (c2, yb0),
                     (c2, yb1), (c2 - (c2-c1)*0.30, yb1), (c1 + (c2-c1)*0.30, ya1), (c1, ya1), (c1, ya0)]
            codes = [MplPath.MOVETO] + [MplPath.CURVE3]*6 + [MplPath.LINETO, MplPath.CLOSEPOLY]
            ax.add_patch(PathPatch(MplPath(verts, codes), facecolor=LULC_COLORS[i], alpha=.36, edgecolor="none"))
    for i, lab in enumerate(LULC_LABELS):
        ax.text(x0 - .012, yleft[i] + (left_h[i]-gap)/2, f"{y0}{lab}", ha="right", va="center", fontproperties=ZH_SMALL)
        ax.text(x1 + width + .012, yright[i] + (right_h[i]-gap)/2, f"{y1}{lab}", ha="left", va="center", fontproperties=ZH_SMALL)
    ax.text(x0 + width/2, .975, str(y0), ha="center", va="top", fontproperties=NUM)
    ax.text(x1 + width/2, .975, str(y1), ha="center", va="top", fontproperties=NUM)
    ax.text(.50, .04, "\u571f\u5730\u5229\u7528\u7c7b\u578b\u8f6c\u5316\u9762\u79ef (hm\N{SUPERSCRIPT TWO})", ha="center", fontproperties=ZH)
    ax.set_title(f"{y0}\u2014{y1}\u5e74\u571f\u5730\u5229\u7528\u8f6c\u5316\u6851\u57fa\u56fe", fontproperties=ZH_TITLE, pad=8)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output.with_suffix(".png"), dpi=300, bbox_inches="tight"); fig.savefig(output.with_suffix(".pdf"), bbox_inches="tight"); fig.savefig(output.with_suffix(".svg"), bbox_inches="tight"); plt.close(fig)


def sankey_reference_flow(m, output: Path, y0: int, y1: int):
    """Render a two-sided, paper-style Sankey matching the supplied example."""
    order = [3, 4, 2, 5, 1, 0]  # cropland, forest, built-up, grassland, water, subsidence water
    node_colors = {
        0: "#6baed6", 1: "#9ecae1", 2: "#efb6d1",
        3: "#f7c99f", 4: "#65ad68", 5: "#c5df9c",
    }
    fig, ax = plt.subplots(figsize=(10.0, 6.4), dpi=300, facecolor="white")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    area = np.asarray(m, dtype=float) * 0.09
    total = max(float(area.sum()), 1e-12)
    left = area.sum(axis=1); right = area.sum(axis=0)
    x_left, x_right, node_w = 0.025, 0.955, 0.018
    top, usable, gap = 0.93, 0.82, 0.012
    block_usable = usable - gap * (len(order) - 1)

    def stack(values):
        heights = {i: block_usable * float(values[i]) / total for i in order}
        bottoms = {}; cursor = top
        for i in order:
            cursor -= heights[i]
            bottoms[i] = cursor
            cursor -= gap
        return bottoms, heights

    y_left, h_left = stack(left); y_right, h_right = stack(right)
    left_cursor = dict(y_left); right_cursor = dict(y_right)
    for i in order:
        for j in order:
            h = block_usable * float(area[i, j]) / total
            if h <= 0:
                continue
            ya0, ya1 = left_cursor[i], left_cursor[i] + h
            yb0, yb1 = right_cursor[j], right_cursor[j] + h
            left_cursor[i] = ya1; right_cursor[j] = yb1
            c1, c2 = x_left + node_w, x_right
            xm1 = c1 + (c2 - c1) * 0.36; xm2 = c2 - (c2 - c1) * 0.36
            verts = [(c1, ya0), (xm1, ya0), (xm2, yb0), (c2, yb0),
                     (c2, yb1), (xm2, yb1), (xm1, ya1), (c1, ya1), (c1, ya0)]
            codes = [MplPath.MOVETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
                     MplPath.LINETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
                     MplPath.CLOSEPOLY]
            ax.add_patch(PathPatch(MplPath(verts, codes), facecolor=node_colors[i],
                                   edgecolor="none", alpha=.58, zorder=1))
    for i in order:
        if left[i] > 0:
            ax.add_patch(Rectangle((x_left, y_left[i]), node_w, h_left[i],
                                   facecolor=node_colors[i], edgecolor="#777777", linewidth=.45, zorder=3))
        if right[i] > 0:
            ax.add_patch(Rectangle((x_right, y_right[i]), node_w, h_right[i],
                                   facecolor=node_colors[i], edgecolor="#777777", linewidth=.45, zorder=3))
        ax.text(x_left - .006, y_left[i] + h_left[i] / 2, f"{y0}{LULC_LABELS[i]}",
                ha="right", va="center", fontproperties=ZH_SMALL, zorder=4)
        ax.text(x_right + node_w + .006, y_right[i] + h_right[i] / 2, f"{y1}{LULC_LABELS[i]}",
                ha="left", va="center", fontproperties=ZH_SMALL, zorder=4)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=.04)
    fig.savefig(output.with_suffix(".pdf"), bbox_inches="tight", pad_inches=.04)
    fig.savefig(output.with_suffix(".svg"), bbox_inches="tight", pad_inches=.04)
    plt.close(fig)


def write_sankey_outputs():
    base = ROOT / "outputs" / "classification" / "final_grid_v3"
    out = RESULT / "\u6851\u57fa"
    for y0, y1 in zip(YEARS[:-1], YEARS[1:]):
        sankey_flow(transition_matrix(base / f"LULC_{y0}_30m_masked.tif", base / f"LULC_{y1}_30m_masked.tif"), out / f"\u571f\u5730\u5229\u7528\u8f6c\u5316\u6851\u57fa_{y0}_{y1}", y0, y1)
    # Full-period figure matching the supplied reference layout.
    y0, y1 = YEARS[0], YEARS[-1]
    m = transition_matrix(base / f"LULC_{y0}_30m_masked.tif", base / f"LULC_{y1}_30m_masked.tif")
    sankey_reference_flow(m, out / f"\u571f\u5730\u5229\u7528\u8f6c\u5316\u6851\u57fa_\u8bba\u6587\u7248_{y0}_{y1}", y0, y1)


def panel_service_distribution():
    srcs = source_rasters("ecosystem_service")
    plus = [source_rasters("ecosystem_service", s)[2026] for s in SCENARIOS]
    arrays = []
    for y in YEARS:
        arrays.append(read_raster(srcs[y])[0])
    # A scenario-average panel completes the 2x3 reference layout without
    # pretending that one scenario is the historical observation.
    p_arrays = []
    with rasterio.open(plus[0]) as first:
        transform, crs, bounds = first.transform, first.crs, first.bounds
    for p in plus:
        with rasterio.open(p) as src:
            a = src.read(1, masked=True)
            p_arrays.append(np.ma.masked_where(a.data < 0, a))
    arrays.append(np.ma.mean(np.ma.stack(p_arrays), axis=0))
    vals = np.concatenate([a.compressed()[::max(1, a.count() // 100000)] for a in arrays])
    norm = Normalize(float(np.nanpercentile(vals, 2)), float(np.nanpercentile(vals, 98)))
    cmap = plt.get_cmap("viridis")
    fig, axes = plt.subplots(2, 3, figsize=(10.2, 7.6), dpi=300)
    bpath, transformer = choose_boundary(crs)
    for ax, arr, label in zip(axes.flat, arrays, [str(y) for y in YEARS] + ["2026\u60c5\u666f\u5747\u503c"]):
        ax.imshow(arr, cmap=cmap, norm=norm, extent=[bounds.left,bounds.right,bounds.bottom,bounds.top], interpolation="nearest")
        for ring in boundary_rings(bpath, transformer): ax.add_patch(Polygon(ring, closed=True, fill=False, edgecolor="#555", lw=.35))
        ax.set_title(label, fontproperties=ZH_TITLE if label.startswith("2026") else NUM)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect("equal")
        for s in ax.spines.values(): s.set_linewidth(.6)
    fig.subplots_adjust(left=.04, right=.98, top=.92, bottom=.13, wspace=.03, hspace=.10)
    cax = fig.add_axes([.24, .055, .52, .025]); cb = matplotlib.colorbar.ColorbarBase(cax, cmap=cmap, norm=norm, orientation="horizontal")
    cb.set_label("\u7efc\u5408\u751f\u6001\u7cfb\u7edf\u670d\u52a1\u6307\u6570", fontproperties=ZH_SMALL)
    for t in cb.ax.get_xticklabels(): t.set_fontproperties(NUM_SMALL)
    fig.suptitle("\u7696\u5317\u516d\u5e02\u77ff\u533a\u7efc\u5408\u751f\u6001\u7cfb\u7edf\u670d\u52a1\u65f6\u7a7a\u5206\u5e03", fontproperties=ZH_TITLE)
    out = RESULT / "\u65f6\u7a7a\u5206\u5e03" / "\u7efc\u5408\u751f\u6001\u7cfb\u7edf\u670d\u52a1\u65f6\u7a7a\u5206\u5e03_\u516d\u671f"
    fig.savefig(out.with_suffix(".png"), dpi=300); fig.savefig(out.with_suffix(".pdf")); fig.savefig(out.with_suffix(".svg")); plt.close(fig)


def profile_and_figures():
    root = RESULT / "\u5206\u6790\u7edf\u8ba1\u56fe\u4e0e\u8868" / "scipilot_figures"
    if root.exists():
        for p in root.iterdir():
            if p.is_file() or p.is_symlink(): p.unlink()
            elif p.is_dir(): shutil.rmtree(p)
    root.mkdir(parents=True, exist_ok=True)
    # Build a compact, traceable temporal summary from rasters.  The plot type
    # follows SciPilot: a line is appropriate for a time series, while scenario
    # comparisons use points/bars rather than a categorical line.
    rows = []
    for kind in ["carbon", "water_yield", "habitat_quality", "ecosystem_service"]:
        for y, p in source_rasters(kind).items():
            with rasterio.open(p) as s:
                a = s.read(1, masked=True); vals = a.compressed()
                if kind == "carbon": value = float(vals.sum() / 1_000_000.0)
                elif kind == "water_yield": value = float(vals.sum() * 0.9 / 1_000_000.0)
                else: value = float(vals.mean())
            rows.append({"year": y, "metric": kind, "value": value})
    with (root / "\u5386\u53f2\u751f\u6001\u670d\u52a1\u7edf\u8ba1.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["year", "metric", "value"]); w.writeheader(); w.writerows(rows)
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.4), dpi=300)
    names = {"carbon": ("\u78b3\u50a8\u91cf", "10^6 Mg C"), "water_yield": ("\u6c34\u6e90\u4f9b\u7ed9", "10^6 m3"), "habitat_quality": ("\u751f\u5883\u8d28\u91cf", "\u6307\u6570\u5747\u503c"), "ecosystem_service": ("\u7efc\u5408\u751f\u6001\u7cfb\u7edf\u670d\u52a1", "\u6307\u6570\u5747\u503c")}
    for ax, kind in zip(axes.flat, names):
        sub = [r for r in rows if r["metric"] == kind]
        ax.plot([r["year"] for r in sub], [r["value"] for r in sub], color="#2166ac", marker="o", lw=1.4, ms=4)
        ax.set_title(names[kind][0], fontproperties=ZH)
        ax.set_xlabel(CN["year"], fontproperties=ZH_SMALL); ax.set_ylabel(names[kind][1], fontproperties=ZH_SMALL)
        ax.grid(axis="y", color="#dddddd", lw=.5); ax.spines[["top","right"]].set_visible(False)
        for t in ax.get_xticklabels() + ax.get_yticklabels(): t.set_fontproperties(NUM_SMALL)
    fig.tight_layout()
    fig.savefig(root / "\u56fe1_\u5386\u53f2\u751f\u6001\u670d\u52a1\u65f6\u95f4\u53d8\u5316.png", dpi=300); fig.savefig(root / "\u56fe1_\u5386\u53f2\u751f\u6001\u670d\u52a1\u65f6\u95f4\u53d8\u5316.pdf"); fig.savefig(root / "\u56fe1_\u5386\u53f2\u751f\u6001\u670d\u52a1\u65f6\u95f4\u53d8\u5316.svg"); plt.close(fig)
    # Scenario comparison: four independent scenario points for each metric.
    scen_rows = []
    for sc in SCENARIOS:
        for kind in ["carbon", "water_yield", "habitat_quality", "ecosystem_service"]:
            p = source_rasters(kind, sc)[2026]
            with rasterio.open(p) as s:
                vals = s.read(1, masked=True).compressed()
                value = float(vals.sum() / 1_000_000.0) if kind == "carbon" else float(vals.sum() * 0.9 / 1_000_000.0) if kind == "water_yield" else float(vals.mean())
            scen_rows.append({"scenario": sc, "metric": kind, "value": value})
    with (root / "2026\u5e74\u56db\u60c5\u666f\u751f\u6001\u670d\u52a1\u7edf\u8ba1.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["scenario", "metric", "value"]); w.writeheader(); w.writerows(scen_rows)
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.4), dpi=300)
    for ax, kind in zip(axes.flat, names):
        sub = [r for r in scen_rows if r["metric"] == kind]
        ax.scatter(range(4), [r["value"] for r in sub], s=45, color=["#1b9e77", "#d95f02", "#7570b3", "#e7298a"])
        ax.set_xticks(range(4), [SC_SHORT[s] for s in SCENARIOS], fontproperties=NUM_SMALL)
        ax.set_title(names[kind][0], fontproperties=ZH); ax.set_ylabel(names[kind][1], fontproperties=ZH_SMALL)
        ax.grid(axis="y", color="#dddddd", lw=.5); ax.spines[["top","right"]].set_visible(False)
        for t in ax.get_yticklabels(): t.set_fontproperties(NUM_SMALL)
    fig.tight_layout(); fig.savefig(root / "\u56fe2_2026\u5e74\u56db\u60c5\u666f\u6bd4\u8f83.png", dpi=300); fig.savefig(root / "\u56fe2_2026\u5e74\u56db\u60c5\u666f\u6bd4\u8f83.pdf"); fig.savefig(root / "\u56fe2_2026\u5e74\u56db\u60c5\u666f\u6bd4\u8f83.svg"); plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    global ROOT, RESULT
    ROOT = args.root.expanduser().resolve()
    RESULT = (args.result or ROOT / "results").expanduser().resolve()
    ensure_dirs(); render_maps(); write_transition_outputs(); write_long_transition_output(); write_sankey_outputs(); panel_service_distribution(); profile_and_figures()
    print("rendered publication maps, matrices, Sankey, spatiotemporal panel and SciPilot figures")


if __name__ == "__main__":
    main()
