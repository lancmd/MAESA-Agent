#!/usr/bin/env python3
"""Render mine-level ecosystem-service panels from the project rasters.

The panel layout follows the supplied paper-style template: years by rows and
land-use classes by columns, with one shared continuous colour scale.  The
historical six-class products are remapped to the enhanced seven-class display
positions; the independent subsidence-water class is only used for 2025 when
the enhanced raster is available.
"""
from __future__ import annotations

import argparse
import csv
import json
import struct
from pathlib import Path
from typing import Any

import fiona
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.warp import transform_geom

YEARS = (2005, 2015, 2025)
# Unicode escapes keep this source portable on Windows consoles.
LANDUSE = (
    ("\u5929\u7136\u6c34\u57df", 2),
    ("\u6797\u5730", 5),
    ("\u5efa\u8bbe\u7528\u5730", 3),
    ("\u8015\u5730", 4),
    ("\u6c89\u9677\u79ef\u6c34", 1),
    ("\u8349\u5730", 6),
)
MINE_NAMES = (
    "\u6f58\u96c6\u7b2c\u4e09\u7164\u77ff",
    "\u4e34\u6da3\u7164\u77ff",
    "\u94b1\u8425\u5b5c\u7164\u77ff",
    "\u8c22\u6865\u7164\u77ff",
    "\u8bb8\u7583\u7164\u77ff",
)


def paths(root: Path) -> dict[str, Path]:
    return {
        "boundary": root / "boundaries" / "mine_boundary.shp",
        "lulc": root / "outputs" / "classification" / "final_grid_v3",
        "service": root / "outputs" / "ecosystem_service_paper_20260806",
        "enhanced_2025": root / "outputs" / "plus_scenario_demand_20260806" / "enhanced_lulc" / "LULC_2025_enhanced_7class_30m.tif",
    }


def _dbf_utf8_names(dbf: Path) -> list[tuple[str, str]]:
    """Read the two identifying DBF fields as UTF-8 bytes.

    The supplied shapefile has a UTF-8 CPG but some GDAL builds honour the
    legacy code page first, producing replacement characters.  Reading only
    the name/city bytes keeps geometry access through Fiona and avoids changing
    the user's source boundary files.
    """
    raw = dbf.read_bytes()
    header_len = struct.unpack_from("<H", raw, 8)[0]
    record_len = struct.unpack_from("<H", raw, 10)[0]
    count = struct.unpack_from("<I", raw, 4)[0]
    fields: list[tuple[str, int]] = []
    for offset in range(32, header_len - 1, 32):
        desc = raw[offset:offset + 32]
        name = desc[:11].split(bytes([0]), 1)[0].decode("ascii", "ignore")
        if name in {"Coalmine", "City"}:
            fields.append((name, int(desc[16])))
        if len(fields) == 2:
            break
    if len(fields) != 2:
        raise ValueError(f"DBF fields Coalmine/City not found: {dbf}")
    names: list[tuple[str, str]] = []
    for index in range(count):
        row = raw[header_len + index * record_len:header_len + (index + 1) * record_len]
        cursor = 1
        values: dict[str, str] = {}
        for field_name, width in fields:
            values[field_name] = row[cursor:cursor + width].rstrip().decode("utf-8", "replace")
            cursor += width
        names.append((values.get("Coalmine", "").strip(), values.get("City", "").strip()))
    return names


def selected_geometries(boundary: Path, names: tuple[str, ...]) -> dict[str, tuple[dict[str, Any], str]]:
    selected: dict[str, tuple[dict[str, Any], str]] = {}
    dbf_names = _dbf_utf8_names(boundary.with_suffix(".dbf"))
    with fiona.open(boundary, encoding="latin1") as source:
        for index, feature in enumerate(source):
            name, city = dbf_names[index]
            if name in names and name not in selected:
                selected[name] = (feature["geometry"], city)
    missing = [name for name in names if name not in selected]
    if missing:
        raise ValueError("Mine names not found: " + ", ".join(missing))
    return selected


def standard_to_enhanced(data: np.ndarray) -> np.ndarray:
    mapping = {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7}
    out = np.zeros(data.shape, dtype=np.uint8)
    for old, new in mapping.items():
        out[data == old] = new
    return out


def crop(path: Path, geometry: dict[str, Any]) -> tuple[np.ma.MaskedArray, Any, Any]:
    with rasterio.open(path) as source:
        geom = transform_geom("EPSG:4527", source.crs, geometry, precision=6)
        data, transform = mask(source, [geom], crop=True, filled=False)
        return data[0], transform, source.crs


def extent(transform: Any, height: int, width: int) -> tuple[float, float, float, float]:
    left, top = transform.c, transform.f
    right, bottom = left + transform.a * width, top + transform.e * height
    return min(left, right), max(left, right), min(bottom, top), max(bottom, top)


def plot_boundary(ax: Any, geometry: dict[str, Any], crs: Any) -> None:
    transformed = transform_geom("EPSG:4527", crs, geometry, precision=6)
    polygons = transformed.get("coordinates", [])
    if transformed.get("type") == "Polygon":
        polygons = [polygons]
    for polygon in polygons:
        for ring in polygon:
            if len(ring) > 1:
                xs, ys = zip(*ring)
                ax.plot(xs, ys, color="#414141", linewidth=0.55, zorder=5)


def valid_values(service: np.ma.MaskedArray) -> np.ndarray:
    data = np.asarray(service.filled(np.nan), dtype="float32")
    data[~np.isfinite(data)] = np.nan
    data[data <= 0] = np.nan
    return data


def render_one(root: Path, output_root: Path, mine: str, city: str, geometry: dict[str, Any]) -> None:
    source = paths(root)
    records: list[dict[str, Any]] = []
    panels: dict[tuple[int, str], tuple[np.ma.MaskedArray, Any, Any]] = {}
    all_values: list[np.ndarray] = []
    for year in YEARS:
        lulc_path = source["lulc"] / f"LULC_{year}_30m_masked.tif"
        service_path = source["service"] / f"ecosystem_service_{year}.tif"
        if not lulc_path.is_file():
            raise FileNotFoundError(lulc_path)
        if not service_path.is_file():
            raise FileNotFoundError(service_path)
        lulc, _, _ = crop(lulc_path, geometry)
        service, service_transform, service_crs = crop(service_path, geometry)
        if year == 2025 and source["enhanced_2025"].is_file():
            lulc_enhanced, _, _ = crop(source["enhanced_2025"], geometry)
        else:
            lulc_enhanced = np.ma.array(standard_to_enhanced(lulc.filled(0)), mask=lulc.mask)
        if lulc_enhanced.shape != service.shape:
            raise ValueError(f"{mine} {year}: LULC/service crop shapes differ")
        values = valid_values(service)
        for label, code in LANDUSE:
            class_mask = (~np.ma.getmaskarray(lulc_enhanced)) & (lulc_enhanced.data == code)
            masked = values.copy()
            masked[~class_mask] = np.nan
            panel = np.ma.masked_invalid(masked)
            panels[(year, label)] = (panel, service_transform, service_crs)
            flat = masked[np.isfinite(masked)]
            all_values.append(flat)
            records.append({
                "mine": mine, "city": city, "year": year, "landuse": label, "code": code,
                "valid_pixels": int(flat.size), "area_ha": round(float(flat.size * 0.09), 4),
                "service_mean": round(float(np.mean(flat)), 6) if flat.size else "",
                "service_median": round(float(np.median(flat)), 6) if flat.size else "",
                "service_min": round(float(np.min(flat)), 6) if flat.size else "",
                "service_max": round(float(np.max(flat)), 6) if flat.size else "",
                "classification_note": "2025 enhanced 7-class raster" if year == 2025 else "historical standard 6-class raster; subsidence water not separately observed",
            })
    nonempty = [item for item in all_values if item.size]
    if not nonempty:
        raise ValueError(f"{mine}: no valid ecosystem-service pixels")
    joined = np.concatenate(nonempty)
    vmin, vmax = float(np.nanpercentile(joined, 2)), float(np.nanpercentile(joined, 98))
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
        vmin, vmax = float(np.nanmin(joined)), float(np.nanmax(joined))
    output_root.mkdir(parents=True, exist_ok=True)
    safe = mine.replace("/", "_").replace("\\", "_")
    stem = output_root / f"{safe}_\u751f\u6001\u670d\u52a1\u5206\u5730\u7c7b\u65f6\u7a7a\u5206\u5e03\u56fe"
    plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"], "axes.unicode_minus": False})
    fig, axes = plt.subplots(len(YEARS), len(LANDUSE), figsize=(13.0, 7.8), squeeze=False)
    cmap = plt.get_cmap("viridis").copy(); cmap.set_bad((1, 1, 1, 0))
    for col, (label, _) in enumerate(LANDUSE):
        axes[0, col].set_title(label, fontsize=11, pad=7)
    for row, year in enumerate(YEARS):
        for col, (label, _) in enumerate(LANDUSE):
            ax = axes[row, col]; panel, transform, crs = panels[(year, label)]
            h, w = panel.shape
            ax.imshow(panel, cmap=cmap, vmin=vmin, vmax=vmax, extent=extent(transform, h, w), origin="upper", interpolation="nearest")
            plot_boundary(ax, geometry, crs)
            ax.set_xticks([]); ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_linewidth(0.45); spine.set_color("#9ca3af")
            if col == 0:
                ax.text(-0.16, 0.5, str(year), transform=ax.transAxes, rotation=90, ha="center", va="center", fontsize=12, fontname="Times New Roman")
    fig.suptitle(f"{city}{mine}\u751f\u6001\u670d\u52a1\u5206\u5730\u7c7b\u65f6\u7a7a\u5206\u5e03", fontsize=15, y=0.995)
    fig.text(0.5, 0.015, "\u6ce8\uff1a\u6c89\u9677\u79ef\u6c34\u4ec5\u57282025\u5e74\u589e\u5f3a\u5206\u7c7b\u4e2d\u72ec\u7acb\u8bc6\u522b\uff1b\u65e9\u671f\u5e74\u4efd\u6309\u6807\u51c6\u516d\u7c7b\u4f53\u7cfb\u5904\u7406\u3002", ha="center", fontsize=8.5)
    cbar = fig.colorbar(plt.cm.ScalarMappable(norm=plt.Normalize(vmin=vmin, vmax=vmax), cmap=cmap), ax=axes.ravel().tolist(), orientation="horizontal", fraction=0.035, pad=0.06, aspect=45)
    cbar.set_label("\u7efc\u5408\u751f\u6001\u7cfb\u7edf\u670d\u52a1\u6307\u6570", fontsize=10); cbar.ax.tick_params(labelsize=8)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.94, bottom=0.10, wspace=0.08, hspace=0.25)
    fig.savefig(stem.with_suffix(".png"), dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight", facecolor="white"); plt.close(fig)
    csv_path = output_root / f"{safe}_\u751f\u6001\u670d\u52a1\u5206\u5730\u7c7b\u7edf\u8ba1.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
    meta = {"mine": mine, "city": city, "years": list(YEARS), "landuse": [{"name": n, "code": c} for n, c in LANDUSE], "value_raster": "ecosystem_service_YYYY.tif", "vmin": vmin, "vmax": vmax, "note": "Historical six-class LULC is remapped to enhanced display positions; 2025 uses the available enhanced seven-class raster."}
    (output_root / f"{safe}_\u5143\u6570\u636e.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--project-root", type=Path, required=True); parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(); root = args.project_root.expanduser().resolve()
    output = (args.output or (root / "结果" / "分析统计图与表" / "矿区专题分析")).expanduser().resolve()
    selected = selected_geometries(paths(root)["boundary"], MINE_NAMES)
    for mine, (geometry, city) in selected.items():
        render_one(root, output / mine, mine, city, geometry)
    print(json.dumps({"status": "completed", "mines": list(selected), "output": str(output)}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
