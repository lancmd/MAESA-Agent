#!/usr/bin/env python3
"""Write comparable five-period statistics for harmonized MAESA services."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT


YEARS = (2005, 2010, 2015, 2020, 2025)


def stats(path: Path, support_path: Path) -> dict[str, float | int]:
    count = 0
    total = 0.0
    low = float("inf")
    high = float("-inf")
    cell_area_m2 = 0.0
    with rasterio.open(support_path) as support, rasterio.open(path) as source:
        cell_area_m2 = abs(float(support.transform.a * support.transform.e))
        same_grid = (source.crs == support.crs and source.width == support.width and source.height == support.height
                     and source.transform.almost_equals(support.transform))
        reader = source if same_grid else WarpedVRT(
            source, crs=support.crs, transform=support.transform, width=support.width, height=support.height,
            resampling=Resampling.bilinear, nodata=source.nodata
        )
        nodata = reader.nodata
        for _, window in support.block_windows(1):
            values = reader.read(1, window=window).astype("float64", copy=False)
            support_values = support.read(1, window=window)
            valid = np.isfinite(values)
            if nodata is not None:
                valid &= values != nodata
            valid &= support_values == 1
            if not valid.any():
                continue
            current = values[valid]
            count += int(current.size)
            total += float(current.sum(dtype="float64"))
            low = min(low, float(current.min()))
            high = max(high, float(current.max()))
        if reader is not source:
            reader.close()
    if not count:
        raise ValueError(f"No valid values: {path}")
    return {"count": count, "sum": total, "mean": total / count, "min": low, "max": high, "cell_area_m2": cell_area_m2}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    records = []
    support = root / "outputs" / "statistics_harmonized_v2_common_support" / "lulc" / "共同生态服务统计支撑区_30m.tif"
    if not support.is_file():
        raise FileNotFoundError(f"Missing common service support: {support}")
    for year in YEARS:
        carbon = stats(root / "outputs" / "invest" / "carbon_series_harmonized_v2" / str(year) / "tot_c_cur.tif", support)
        water = stats(root / "outputs" / "invest" / "water_yield_harmonized_v2" / str(year) / "output" / "per_pixel" / f"wyield_wy_{year}.tif", support)
        habitat = stats(root / "outputs" / "invest" / "habitat_quality_318_native_harmonized_v2c" / str(year) / f"quality_c_hq_{year}.tif", support)
        composite = stats(root / "outputs" / "ecosystem_service_harmonized_v2_native_habitat" / f"ecosystem_service_{year}.tif", support)
        # InVEST Carbon stores Mg C per pixel.  Annual Water Yield is depth (mm);
        # its volume is sum(mm / 1000 * cell_area_m2) on valid cells.
        records.append({
            "year": year,
            "carbon_storage_MgC": round(float(carbon["sum"]), 3),
            "carbon_storage_10ktC": round(float(carbon["sum"]) / 10000.0, 4),
            "mean_carbon_MgC_per_pixel": round(float(carbon["mean"]), 6),
            "mean_water_yield_mm": round(float(water["mean"]), 6),
            "water_yield_volume_m3": round(float(water["sum"]) / 1000.0 * float(water["cell_area_m2"]), 3),
            "mean_habitat_quality_index": round(float(habitat["mean"]), 6),
            "mean_composite_ecosystem_service_index": round(float(composite["mean"]), 6),
            "common_boundary_area_ha": round(float(composite["count"]) * float(composite["cell_area_m2"]) / 10000.0, 4),
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    provenance = {
        "status": "complete_pending_independent_lulc_validation",
        "common_lulc_contract": "mining_water_6class: 1沉陷积水,2自然水体,3建设用地,4耕地,5林地,6草地",
        "common_statistics_boundary": str(support),
        "carbon_unit": "Mg C per pixel; total reported as Mg C and 10^4 t C",
        "water_yield_unit": "mm per pixel; total volume derived using 30 m x 30 m valid cells",
        "habitat_note": "native InVEST Habitat Quality 3.18.0; supplied road, railway and dated mining-workface threat/sensitivity contract",
        "records": records,
    }
    args.output.with_suffix(".json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "records": len(records)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
