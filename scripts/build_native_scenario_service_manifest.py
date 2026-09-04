#!/usr/bin/env python3
"""Build a strict manifest for native 2026 scenario ecosystem-service maps.

Only scenario folders that contain real InVEST Carbon, Annual Water Yield and
Habitat Quality outputs are admitted.  This prevents preliminary maps, model
contracts or formula substitutes from entering the AHP comparison.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


SCENARIOS = ("ND", "UD", "EP", "RE")


def one(path: Path, pattern: str, description: str) -> Path:
    matches = sorted(path.glob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(f"{description}: expected exactly one {pattern} below {path}, found {matches}")
    return matches[0].resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--series-id", default="mining_area_native_invest_scenarios")
    parser.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=SCENARIOS)
    args = parser.parse_args()
    root = args.scenario_root.expanduser().resolve()
    periods = []
    for scenario in args.scenarios:
        run = root / scenario
        carbon = one(run / "carbon" / "2026", "tot_c_cur.tif", f"{scenario} carbon")
        water = one(run / "water" / "2026" / "output" / "per_pixel", "wyield_wy_2026_*.tif", f"{scenario} water yield")
        habitat = one(run / "habitat_318_native" / "2026", "quality_c_hq_2026_*.tif", f"{scenario} habitat quality")
        periods.append({"year": f"2026_{scenario}", "scenario": scenario, "carbon": str(carbon),
                        "water_yield": str(water), "habitat_quality": str(habitat)})
    manifest = {
        "schema_version": 1,
        "series_id": args.series_id,
        "common_lulc_contract": "mining_water_6class: 1沉陷积水,2自然水体,3建设用地,4耕地,5林地,6草地",
        "normalization": {"method": "global_minmax", "scope": "all_declared_2026_scenarios"},
        "ahp": {"criteria_order": ["water_yield", "carbon", "habitat_quality"],
                "consistency_threshold": 0.1,
                "pairwise_matrix": [[1, 3, 5], [1 / 3, 1, 3], [1 / 5, 1 / 3, 1]],
                "parameter_status": "user_authorized_initial_AHP_contract"},
        "climate_soil_assumption": "All 2026 scenarios reuse the user-authorised 2025 climate and soil inputs.",
        "validation_status": "pending_independent_lulc_validation",
        "periods": periods,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
