#!/usr/bin/env python3
"""Build the enhanced high-water classification and initial 2026 demands.

The paper's PLUS settings describe relative transition controls rather than a
universal area table.  This script therefore keeps the user's local 2025
classification and derives transparent, reproducible demand *proxies* from:

* the 2020--2025 local area trend;
* the paper's ND/UD/EP/RE relative controls; and
* the supplied subsidence-depth raster plus 2025/2026 workface polygons.

The resulting demand CSV is suitable for GUI calibration and review.  It is
not a substitute for calibrating the PLUS transition matrix against local
historical data.  Enhanced rasters use seven codes so that bare/mining land is
not silently lost:

1 subsidence water, 2 natural water, 3 built-up, 4 cropland, 5 forest,
6 grassland, 7 bare/mining land.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path
from typing import Any

import fiona
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import Affine
from rasterio.warp import Resampling, reproject, transform as crs_transform


SCENARIOS = ("ND", "UD", "EP", "RE")
LABELS = {
    1: "沉陷积水",
    2: "自然水体",
    3: "建设用地",
    4: "耕地",
    5: "林地",
    6: "草地",
    7: "裸地/工矿用地",
}
BASE_TO_ENHANCED = {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7}


def read_raster(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    with rasterio.open(path) as src:
        return src.read(1), src.profile.copy()


def reproject_depth(path: Path, profile: dict[str, Any]) -> np.ndarray:
    """Put depth on the 30 m master grid without filling outside the source."""
    with rasterio.open(path) as src:
        dst = np.full((profile["height"], profile["width"]), np.nan, dtype="float32")
        src_nodata = src.nodata
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src_nodata,
            dst_transform=profile["transform"],
            dst_crs=profile["crs"],
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
    dst[~np.isfinite(dst)] = np.nan
    dst[dst < 0] = np.nan
    return dst


def transformed_shapes(path: Path, target_crs: Any) -> list[dict[str, Any]]:
    """Read polygon GeoJSON and transform every ring with GDAL's CRS bridge."""
    shapes: list[dict[str, Any]] = []
    with fiona.open(path) as source:
        source_crs = source.crs_wkt or source.crs
        for feature in source:
            geom = feature.get("geometry") or {}
            if geom.get("type") not in {"Polygon", "MultiPolygon"}:
                continue
            polygons = [geom["coordinates"]] if geom["type"] == "Polygon" else list(geom["coordinates"])
            for polygon in polygons:
                out_rings: list[list[list[float]]] = []
                for ring in polygon:
                    if len(ring) < 3:
                        continue
                    xs, ys = zip(*ring)
                    tx, ty = crs_transform(source_crs, target_crs, list(xs), list(ys))
                    out_rings.append([[float(x), float(y)] for x, y in zip(tx, ty)])
                if out_rings:
                    shapes.append({"type": "Polygon", "coordinates": out_rings})
    return shapes


def workface_mask(path: Path, profile: dict[str, Any]) -> np.ndarray:
    shapes = transformed_shapes(path, profile["crs"])
    return rasterize(
        [(shape, 1) for shape in shapes],
        out_shape=(profile["height"], profile["width"]),
        transform=profile["transform"],
        fill=0,
        dtype="uint8",
    ).astype(bool)


def enhanced_raster(base: np.ndarray, depth: np.ndarray | None, workface: np.ndarray | None,
                    threshold_m: float = 0.3) -> np.ndarray:
    out = np.zeros(base.shape, dtype="uint8")
    for source_code, target_code in BASE_TO_ENHANCED.items():
        out[base == source_code] = target_code
    if depth is not None and workface is not None:
        candidate = workface & np.isfinite(depth) & (depth >= threshold_m)
        # Do not overwrite an existing built-up pixel just because it lies in
        # a workface polygon.  This makes the evidence group conservative.
        candidate &= np.isin(base, [1, 3, 4, 5, 6])
        out[candidate] = 1
    return out


def counts(raster: np.ndarray) -> dict[int, int]:
    return {code: int(np.count_nonzero(raster == code)) for code in LABELS}


def ordinary_counts(path: Path) -> dict[int, int]:
    data, _ = read_raster(path)
    return {code: int(np.count_nonzero(data == code)) for code in range(1, 7)}


def map_ordinary_counts(source: dict[int, int]) -> dict[int, int]:
    out = {code: 0 for code in LABELS}
    for source_code, target_code in BASE_TO_ENHANCED.items():
        out[target_code] += int(source.get(source_code, 0))
    return out


def normalize_counts(values: dict[int, float], total: int) -> dict[int, int]:
    """Largest-remainder integer allocation that preserves the valid-cell total."""
    clipped = {code: max(0.0, float(values.get(code, 0.0))) for code in LABELS}
    raw_total = sum(clipped.values())
    if raw_total <= 0:
        return {code: 0 for code in LABELS}
    scaled = {code: clipped[code] * total / raw_total for code in LABELS}
    result = {code: int(math.floor(scaled[code])) for code in LABELS}
    remaining = int(total - sum(result.values()))
    order = sorted(LABELS, key=lambda code: (scaled[code] - result[code], code), reverse=True)
    for code in order[:remaining]:
        result[code] += 1
    return result


def write_raster(path: Path, data: np.ndarray, profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output_profile = profile.copy()
    output_profile.update(driver="GTiff", dtype="uint8", count=1, nodata=0,
                          compress="lzw", BIGTIFF="IF_SAFER")
    with rasterio.open(path, "w", **output_profile) as dst:
        dst.write(data.astype("uint8"), 1)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_demand(path: Path) -> dict[str, dict[str, int]]:
    data: dict[str, dict[str, int]] = {scenario: {} for scenario in SCENARIOS}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            scenario = row["scenario"]
            data.setdefault(scenario, {})[str(row["lucode"])] = int(row["target_pixels"])
    return data


def maybe_update_project(project: Path, demand: dict[str, dict[str, int]], output_path: Path) -> None:
    payload = json.loads(project.read_text(encoding="utf-8"))
    payload.setdefault("plus", {})["land_demand"] = demand
    payload["plus"]["land_demand_source"] = str(output_path)
    payload["plus"]["demand_status"] = "pending_validation"
    payload["plus"]["demand_note"] = (
        "Initial local proxy derived from 2020-2025 trend and paper relative controls; "
        "calibrate PLUS transition matrix and validate against local history before publication."
    )
    out = project.with_name(project.stem + "_calibrated_demand.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="wanbei_six_cities data root")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--update-project", type=Path, default=None)
    parser.add_argument("--threshold-m", type=float, default=0.3)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    out_dir = (args.out_dir or root / "outputs" / "plus_scenario_demand_20260806").expanduser().resolve()
    base_profile_path = root / "outputs" / "classification" / "final_grid_v3" / "LULC_2025_30m_masked.tif"
    base, profile = read_raster(base_profile_path)
    if profile["width"] != 3570 or profile["height"] != 6460 or str(profile["crs"]) != "EPSG:32650":
        raise ValueError("the supplied 2025 LULC is not the expected EPSG:32650 30 m master grid")

    depth_2025 = reproject_depth(root / "subsidence" / "aligned" / "subsidence_depth_2025_positive_down_30m_utm50n.tif", profile)
    depth_2026 = reproject_depth(root / "subsidence" / "aligned" / "subsidence_depth_2026_positive_down_30m_utm50n.tif", profile)
    wf_2025 = workface_mask(root / "boundaries" / "workface_2025.shp", profile)
    wf_2026 = workface_mask(root / "boundaries" / "workface_2026.shp", profile)
    enhanced_2025 = enhanced_raster(base, depth_2025, wf_2025, args.threshold_m)
    enhanced_2026_evidence = enhanced_raster(base, depth_2026, wf_2026, args.threshold_m)
    enhanced_dir = out_dir / "enhanced_lulc"
    write_raster(enhanced_dir / "LULC_2025_enhanced_7class_30m.tif", enhanced_2025, profile)
    write_raster(enhanced_dir / "LULC_2026_RE_evidence_enhanced_7class_30m.tif", enhanced_2026_evidence, profile)

    scenario_dir = enhanced_dir / "PLUS2026"
    for scenario in SCENARIOS:
        source = root / "runtime_plus_2026" / "outputs" / "plus" / scenario / f"PLUS_{scenario}.tif"
        if source.is_file():
            ordinary, _ = read_raster(source)
            evidence_depth = depth_2026 if scenario == "RE" else None
            evidence_workface = wf_2026 if scenario == "RE" else None
            write_raster(scenario_dir / f"PLUS_{scenario}_enhanced_7class_30m.tif",
                         enhanced_raster(ordinary, evidence_depth, evidence_workface, args.threshold_m), profile)

    # Baseline demand starts with the enhanced 2025 areas.  ND receives the
    # observed 2020->2025 trend for ordinary classes; water is kept split by
    # the evidence overlay and its total trend is applied to natural water.
    c25 = counts(enhanced_2025)
    c20 = map_ordinary_counts(ordinary_counts(root / "outputs" / "classification" / "final_grid_v3" / "LULC_2020_30m_masked.tif"))
    ordinary25 = map_ordinary_counts(ordinary_counts(base_profile_path))
    nd_float = {code: float(c25[code]) for code in LABELS}
    nd_float[2] += ordinary25[2] - c20[2]
    for code in (3, 4, 5, 6, 7):
        nd_float[code] += ordinary25[code] - c20[code]
    # A single five-year interval can contain classification noise or a
    # restoration project.  Keep a small local floor so extrapolation does not
    # manufacture an all-zero class demand; the detailed transition matrix
    # still decides pixel-level allocations inside PLUS.
    for code in LABELS:
        nd_float[code] = max(nd_float[code], 0.05 * c25[code])
    total_cells = int(sum(c25.values()))
    demands: dict[str, dict[int, int]] = {"ND": normalize_counts(nd_float, total_cells)}

    # Paper controls are relative probability controls.  These factors are a
    # documented, reproducible first demand proxy, not a claim that +20% means
    # 20% of every pixel changes class.
    factors = {
        "UD": {3: 1.20, 4: 0.95, 5: 0.95, 6: 0.95},
        "EP": {3: 0.70, 4: 0.85, 5: 1.10, 6: 1.10},
        "RE": {1: 1.30, 3: 1.20, 4: 0.95, 5: 0.95, 6: 0.95},
    }
    for scenario, scenario_factors in factors.items():
        candidate_water = int(np.count_nonzero(wf_2026 & np.isfinite(depth_2026) & (depth_2026 >= args.threshold_m)))
        values = {code: float(demands["ND"][code]) for code in LABELS}
        if scenario == "RE":
            values[1] = max(values[1], float(candidate_water))
        for code, factor in scenario_factors.items():
            values[code] *= factor
        demands[scenario] = normalize_counts(values, total_cells)

    rows: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        for code in LABELS:
            rule = {
                "ND": "2020-2025 local trend extrapolation; no additional policy constraint",
                "UD": "built-up demand proxy ×1.20; cropland/forest/grassland demand ×0.95",
                "EP": "built-up ×0.70; cropland ×0.85; forest/grassland ×1.10",
                "RE": "PIM/workface evidence; subsidence-water ×1.30; built-up ×1.20; vegetation ×0.95",
            }[scenario]
            rows.append({"scenario": scenario, "lucode": code, "landuse": LABELS[code],
                         "target_pixels": demands[scenario][code],
                         "target_area_ha": f"{demands[scenario][code] * 0.09:.4f}",
                         "rule": rule, "source": "local_2020_2025_trend+paper_relative_controls",
                         "status": "pending_validation"})
    write_csv(out_dir / "2026四情景土地利用需求_hm2.csv", rows)
    write_csv(out_dir / "enhanced_class_mapping.csv", [
        {"source_code": code, "source_name": {1: "水体", 2: "建设用地", 3: "耕地", 4: "林地", 5: "草地", 6: "裸地/工矿用地"}[code],
         "enhanced_code": BASE_TO_ENHANCED[code], "enhanced_name": LABELS[BASE_TO_ENHANCED[code]]}
        for code in range(1, 7)
    ] + [{"source_code": "evidence", "source_name": "沉陷深度≥阈值且位于工作面", "enhanced_code": 1, "enhanced_name": LABELS[1]}])
    manifest = {
        "status": "pending_validation",
        "master_grid": {"crs": str(profile["crs"]), "width": profile["width"], "height": profile["height"], "cell_area_ha": 0.09},
        "subsidence_threshold_m": args.threshold_m,
        "evidence": {"depth_2025": str(root / "subsidence" / "aligned" / "subsidence_depth_2025_positive_down_30m_utm50n.tif"),
                     "depth_2026": str(root / "subsidence" / "aligned" / "subsidence_depth_2026_positive_down_30m_utm50n.tif"),
                     "workface_2025": str(root / "boundaries" / "workface_2025.shp"),
                     "workface_2026": str(root / "boundaries" / "workface_2026.shp"),
                     "candidate_water_cells_2026": int(np.count_nonzero(wf_2026 & np.isfinite(depth_2026) & (depth_2026 >= args.threshold_m)))},
        "class_labels": LABELS,
        "demands": {scenario: {str(code): count for code, count in values.items()} for scenario, values in demands.items()},
        "note": "Relative controls were converted to an explicit initial demand proxy for GUI review; local PLUS matrix calibration remains required.",
    }
    (out_dir / "scenario_demand_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.update_project:
        maybe_update_project(args.update_project.expanduser().resolve(), load_demand(out_dir / "2026四情景土地利用需求_hm2.csv"), out_dir / "2026四情景土地利用需求_hm2.csv")
    print(json.dumps({"out_dir": str(out_dir), "status": manifest["status"], "demands": manifest["demands"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
