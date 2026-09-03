#!/usr/bin/env python3
"""Create the AHP/min-max manifest for the harmonized five-period series."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.project_root.resolve()
    years = ("2005", "2010", "2015", "2020", "2025")
    periods = []
    for year in years:
        paths = {
            "carbon": root / "outputs" / "invest" / "carbon_series_harmonized_v2" / year / "tot_c_cur.tif",
            "water_yield": root / "outputs" / "invest" / "water_yield_harmonized_v2" / year / "output" / "per_pixel" / f"wyield_wy_{year}.tif",
            "habitat_quality": root / "outputs" / "invest" / "habitat_quality_318_native_harmonized_v2c" / year / f"quality_c_hq_{year}.tif",
        }
        missing = [key for key, value in paths.items() if not value.is_file()]
        if missing:
            raise FileNotFoundError(f"{year} missing: {', '.join(missing)}")
        periods.append({"year": year, **{key: str(value) for key, value in paths.items()}})
    manifest = {
        "schema_version": 1,
        "series_id": "wanbei_mining_common_boundary_harmonized_v2",
        "common_lulc_contract": "mining_water_6class: 1沉陷积水,2自然水体,3建设用地,4耕地,5林地,6草地",
        "common_statistics_boundary": str(root / "boundaries" / "mine_boundary.shp"),
        "normalization": {"method": "global_minmax", "scope": "all_declared_periods"},
        "ahp": {
            "criteria_order": ["water_yield", "carbon", "habitat_quality"],
            "consistency_threshold": 0.1,
            "pairwise_matrix": [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]],
            "parameter_status": "user_authorized_initial_AHP_contract",
        },
        "periods": periods,
        "validation_status": "pending_independent_lulc_validation",
        "interpretation_note": "All five years use the same mine-boundary mask and six-class LULC meanings.  ROI was used only as local weak reference; it is not an independent accuracy sample.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(args.output), "periods": len(periods)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
