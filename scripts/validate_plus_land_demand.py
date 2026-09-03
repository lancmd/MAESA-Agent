"""Record the realised class demand of a PLUS scenario raster.

PLUS CARS targets a demand vector but can leave small classes slightly short
or long when neighbourhood and conversion constraints are active.  This tool
does not rewrite the prediction; it records actual class counts beside the
requested values so a model result is never reported as an exact demand match
when it is only total-area balanced.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raster", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demand-json", type=Path,
                        help="JSON object whose keys are six integer LULC codes")
    source.add_argument("--demand-manifest", type=Path,
                        help="Scenario demand manifest written by prepare_plus_scenario_demand.py")
    parser.add_argument("--scenario", choices=("ND", "UD", "EP", "RE"),
                        help="Required with --demand-manifest")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.demand_manifest:
        if not args.scenario:
            raise ValueError("--scenario is required with --demand-manifest")
        manifest = json.loads(args.demand_manifest.read_text(encoding="utf-8"))
        demand_raw = manifest.get("demands", {}).get(args.scenario) if isinstance(manifest, dict) else None
    else:
        demand_raw = json.loads(args.demand_json.read_text(encoding="utf-8"))
    if not isinstance(demand_raw, dict):
        raise ValueError("demand JSON must be an object")
    demand = {int(key): int(value) for key, value in demand_raw.items()}
    if set(demand) != set(range(1, 7)) or any(value < 0 for value in demand.values()):
        raise ValueError("demand JSON must contain non-negative codes 1..6")
    with rasterio.open(args.raster) as dataset:
        values = dataset.read(1)
        nodata = dataset.nodata
    actual = {code: int(np.count_nonzero(values == code)) for code in range(1, 7)}
    unknown = int(np.count_nonzero((values != 0) & (values != nodata) & ~np.isin(values, list(range(1, 7)))))
    rows = [{"code": code, "requested_cells": demand[code], "actual_cells": actual[code],
             "delta_cells": actual[code] - demand[code],
             "delta_percent_of_requested": None if demand[code] == 0 else (actual[code] - demand[code]) / demand[code] * 100}
            for code in range(1, 7)]
    total_requested = sum(demand.values())
    total_actual = sum(actual.values())
    exact = all(row["delta_cells"] == 0 for row in rows) and unknown == 0
    report = {
        "status": "exact_match" if exact else "total_balanced_with_class_demand_deviation",
        "raster": str(args.raster), "demand": demand, "actual": actual,
        "total_requested_cells": total_requested, "total_actual_cells": total_actual,
        "total_delta_cells": total_actual - total_requested, "unknown_nonzero_cells": unknown,
        "max_abs_class_delta_cells": max(abs(row["delta_cells"]) for row in rows),
        "rows": rows,
        "interpretation": ("CARS output exactly matches the supplied demand vector."
                           if exact else
                           "CARS preserved total requested area but did not exactly satisfy every class target; retain this as scenario-model uncertainty."),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
