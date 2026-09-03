#!/usr/bin/env python3
"""Create a fixed common-validity support for five-period service statistics.

Cartographic LULC outputs retain the complete mine boundary.  The parallel
statistics rasters produced here are masked to cells valid in every annual
carbon, water-yield and habitat-quality result, so area, transitions and all
service totals use one explicit support rather than silently mixing extents.
"""

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
CLASSES = {1: "沉陷积水", 2: "自然水体", 3: "建设用地", 4: "耕地", 5: "林地", 6: "草地"}


def valid_mask(path: Path, reference: dict) -> np.ndarray:
    with rasterio.open(path) as dataset:
        same_grid = (
            dataset.width == reference["width"] and dataset.height == reference["height"]
            and dataset.crs == reference["crs"] and dataset.transform.almost_equals(reference["transform"])
        )
        if same_grid:
            values = dataset.read(1)
            nodata = dataset.nodata
        else:
            # Annual Water Yield has a one-pixel western offset in the local
            # InVEST output.  Align validity to the canonical LULC grid rather
            # than treating the offset as a distinct analysis extent.
            with WarpedVRT(dataset, crs=reference["crs"], transform=reference["transform"],
                           width=reference["width"], height=reference["height"],
                           resampling=Resampling.nearest, nodata=dataset.nodata) as aligned:
                values = aligned.read(1)
                nodata = aligned.nodata
        valid = np.isfinite(values)
        if nodata is not None:
            valid &= values != nodata
        return valid


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--classification-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    source_dir = args.classification_dir.resolve()
    target = args.output_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    all_support: np.ndarray | None = None
    reference_profile: dict | None = None
    for year in YEARS:
        lulc_path = source_dir / f"LULC_{year}_30m_masked.tif"
        with rasterio.open(lulc_path) as lulc:
            source_values = lulc.read(1)
            valid_lulc = np.isin(source_values, list(CLASSES))
            if reference_profile is None:
                reference_profile = lulc.profile.copy()
            elif (lulc.width, lulc.height) != (reference_profile["width"], reference_profile["height"]) or not lulc.transform.almost_equals(reference_profile["transform"]):
                raise ValueError(f"LULC grid differs in {year}")
        paths = [
            root / "outputs" / "invest" / "carbon_series_harmonized_v2" / str(year) / "tot_c_cur.tif",
            root / "outputs" / "invest" / "water_yield_harmonized_v2" / str(year) / "output" / "per_pixel" / f"wyield_wy_{year}.tif",
            root / "outputs" / "invest" / "habitat_quality_318_native_harmonized_v2c" / str(year) / f"quality_c_hq_{year}.tif",
        ]
        annual = valid_lulc.copy()
        for path in paths:
            annual &= valid_mask(path, reference_profile)
        all_support = annual if all_support is None else (all_support & annual)
    assert all_support is not None and reference_profile is not None
    profile = reference_profile.copy()
    profile.update(dtype="uint8", count=1, nodata=0, compress="lzw")
    support_path = target / "共同生态服务统计支撑区_30m.tif"
    with rasterio.open(support_path, "w", **profile) as output:
        output.write(all_support.astype("uint8"), 1)

    stats = []
    for year in YEARS:
        source_path = source_dir / f"LULC_{year}_30m_masked.tif"
        with rasterio.open(source_path) as source:
            values = source.read(1)
        output = np.where(all_support, values, 0).astype("uint8")
        target_path = target / f"LULC_{year}_30m_masked.tif"
        with rasterio.open(target_path, "w", **profile) as destination:
            destination.write(output, 1)
        for code, label in CLASSES.items():
            stats.append({"year": year, "code": code, "class": label,
                          "area_ha": round(float(np.count_nonzero(output == code)) * 0.09, 4)})
    with (target / "共同支撑区土地利用面积统计.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(stats[0]))
        writer.writeheader()
        writer.writerows(stats)
    manifest = {
        "status": "complete_pending_independent_lulc_validation",
        "purpose": "common support for area, transition, carbon and ecosystem-service statistics; not for cartographic clipping",
        "common_lulc_contract": "mining_water_6class: 1沉陷积水,2自然水体,3建设用地,4耕地,5林地,6草地",
        "support_raster": str(support_path),
        "valid_cells": int(all_support.sum()),
        "area_ha": round(float(all_support.sum()) * 0.09, 4),
        "source_lulc_directory": str(source_dir),
        "years": list(YEARS),
    }
    (target / "共同统计边界说明.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
