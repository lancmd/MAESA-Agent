#!/usr/bin/env python3
"""Build one validated Annual Water Yield datastack per dated LULC raster."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _dated(values: list[str], label: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw in values:
        year, separator, value = raw.partition("=")
        path = Path(value).expanduser().resolve()
        if not separator or not year.isdigit() or not path.is_file():
            raise ValueError(f"{label} requires YEAR=EXISTING_PATH: {raw}")
        if year in result:
            raise ValueError(f"duplicate {label} year: {year}")
        result[year] = path
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lulc", action="append", required=True, metavar="YEAR=PATH")
    parser.add_argument("--precipitation", action="append", required=True, metavar="YEAR=PATH")
    parser.add_argument("--eto", action="append", required=True, metavar="YEAR=PATH")
    parser.add_argument("--depth", required=True, type=Path)
    parser.add_argument("--pawc", required=True, type=Path)
    parser.add_argument("--watersheds", required=True, type=Path)
    parser.add_argument("--biophysical", required=True, type=Path)
    parser.add_argument("--z", required=True, type=float)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--workspace-root", type=Path,
                        help="Optional root for model workspaces; defaults to the datastack output directory.")
    args = parser.parse_args()
    lulc, precip, eto = (_dated(args.lulc, "--lulc"), _dated(args.precipitation, "--precipitation"),
                          _dated(args.eto, "--eto"))
    years = sorted(lulc)
    if set(years) != set(precip) or set(years) != set(eto):
        raise SystemExit("LULC, precipitation, and ET0 year sets must be identical")
    fixed = {name: path.resolve() for name, path in {
        "depth": args.depth, "pawc": args.pawc, "watersheds": args.watersheds, "biophysical": args.biophysical,
    }.items()}
    missing = [f"{name}: {path}" for name, path in fixed.items() if not path.is_file()]
    if missing:
        raise SystemExit("missing fixed inputs: " + "; ".join(missing))
    output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=True)
    workspace_root = args.workspace_root.resolve() if args.workspace_root else output
    workspace_root.mkdir(parents=True, exist_ok=True)
    records = []
    for year in years:
        workspace = workspace_root / year
        workspace.mkdir(parents=True, exist_ok=True)
        datastack = output / f"annual_water_yield_{year}.json"
        payload = {"model_name": "natcap.invest.annual_water_yield", "invest_version": "3.12.1", "args": {
            "lulc_path": str(lulc[year]),
            "precipitation_path": str(precip[year]), "eto_path": str(eto[year]),
            "depth_to_root_rest_layer_path": str(fixed["depth"]), "pawc_path": str(fixed["pawc"]),
            "watersheds_path": str(fixed["watersheds"]), "biophysical_table_path": str(fixed["biophysical"]),
            # A letter prefix avoids an InVEST 3.12.1 Windows CLI parsing bug
            # observed when a suffix is composed of digits only.
            "seasonality_constant": args.z, "n_workers": -1, "results_suffix": f"wy_{year}",
        }}
        datastack.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records.append({"year": year, "datastack": str(datastack), "workspace": str(workspace)})
    manifest = {"status": "completed", "model": "annual_water_yield", "years": records,
                "seasonality_constant": args.z}
    (output / "annual_water_yield_datastacks_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
