"""Create audited 2026 InVEST inputs after a PLUS scenario output is accepted.

Climate and soil inputs are held at the user-authorised 2025 state for the
2026 scenario year.  The habitat threat table is copied into the scenario
folder and its mining-workface source is explicitly replaced by the supplied
2026 threat raster, so outputs never silently keep a legacy scenario's path.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("args"), dict):
        raise ValueError(f"Invalid InVEST datastack template: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_lulc(path: Path) -> list[int]:
    import numpy as np
    import rasterio

    with rasterio.open(path) as dataset:
        if not dataset.crs or not dataset.crs.is_projected:
            raise ValueError(f"PLUS LULC must have a projected CRS: {path}")
        if "int" not in dataset.dtypes[0] and "uint" not in dataset.dtypes[0]:
            raise ValueError(f"PLUS LULC must be integer-coded: {path}")
        values: set[int] = set()
        for _, window in dataset.block_windows(1):
            block = dataset.read(1, window=window)
            valid = block != dataset.nodata if dataset.nodata is not None else np.isfinite(block)
            values.update(int(value) for value in np.unique(block[valid]))
    invalid = sorted(values - set(range(1, 7)))
    if invalid:
        raise ValueError(f"PLUS LULC violates the six-class contract: {invalid}")
    return sorted(values)


def copied_threat_table(source: Path, destination: Path, mining_threat: Path) -> Path:
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    required = {"threat", "cur_path"}
    if not required.issubset(fields):
        raise ValueError(f"Habitat threat table is missing columns: {sorted(required - set(fields))}")
    found_mining = False
    for row in rows:
        if row.get("threat") == "mining_workface":
            row["cur_path"] = str(mining_threat)
            if "fut_path" in fields:
                row["fut_path"] = ""
            found_mining = True
    if not found_mining:
        raise ValueError("Habitat threat table has no mining_workface row")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return destination


def copied_sensitivity_table(source: Path, destination: Path) -> Path:
    """Copy the six-class sensitivity table using the InVEST 3.18 schema.

    Earlier project templates labelled the first field ``lulc``.  InVEST
    3.18 requires the canonical ``lucode`` header.  Normalise the header at
    the scenario boundary rather than relying on an older Workbench alias.
    """
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if "lucode" not in fields and "lulc" not in fields:
        raise ValueError("Habitat sensitivity table needs a 'lucode' or legacy 'lulc' column")
    if "lucode" not in fields:
        fields = ["lucode" if field == "lulc" else field for field in fields]
        for row in rows:
            row["lucode"] = row.pop("lulc", "")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("ND", "UD", "EP", "RE"), required=True)
    parser.add_argument("--lulc", type=Path, required=True)
    parser.add_argument("--water-template", type=Path, required=True)
    parser.add_argument("--habitat-template", type=Path, required=True)
    parser.add_argument("--habitat-threats", type=Path, required=True)
    parser.add_argument("--habitat-sensitivity", type=Path, required=True)
    parser.add_argument("--mining-threat-2026", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    scenario = args.scenario
    lulc = args.lulc.expanduser().resolve()
    mining_threat = args.mining_threat_2026.expanduser().resolve()
    required_files = [lulc, args.water_template.expanduser().resolve(), args.habitat_template.expanduser().resolve(),
                      args.habitat_threats.expanduser().resolve(), args.habitat_sensitivity.expanduser().resolve(),
                      mining_threat]
    if any(not path.is_file() for path in required_files):
        raise ValueError("One or more scenario InVEST inputs do not exist")
    codes = validate_lulc(lulc)
    root = args.output_root.expanduser().resolve()
    datastacks = root / "datastacks"

    water = read_json(args.water_template.expanduser().resolve())
    water_args = dict(water["args"])
    water_args["lulc_path"] = str(lulc)
    water_args["results_suffix"] = f"wy_2026_{scenario}"
    water["args"] = water_args
    water["scenario_input_assumption"] = "2026 uses 2025 climate and soil inputs"
    water_path = datastacks / "annual_water_yield_2026.json"
    write_json(water_path, water)

    threats_path = copied_threat_table(args.habitat_threats.expanduser().resolve(),
                                       datastacks / "habitat_threats_2026.csv", mining_threat)
    sensitivity_path = copied_sensitivity_table(args.habitat_sensitivity.expanduser().resolve(),
                                                 datastacks / "habitat_sensitivity_6class.csv")
    habitat = read_json(args.habitat_template.expanduser().resolve())
    habitat_args = dict(habitat["args"])
    habitat_args["lulc_cur_path"] = str(lulc)
    habitat_args["threats_table_path"] = str(threats_path)
    habitat_args["sensitivity_table_path"] = str(sensitivity_path)
    habitat_args["results_suffix"] = f"hq_2026_{scenario}"
    habitat["args"] = habitat_args
    habitat["scenario_input_assumption"] = "2026 uses 2025 road/railway threats and 2026 mining-workface threat"
    habitat_path = datastacks / "habitat_quality_2026.json"
    write_json(habitat_path, habitat)

    manifest = {
        "status": "prepared", "scenario": scenario, "lulc": str(lulc), "lulc_codes": codes,
        "water_yield_datastack": str(water_path), "habitat_datastack": str(habitat_path),
        "mining_threat_2026": str(mining_threat),
        "assumptions": ["2025 climate and soil forcings are reused for 2026", "2026 mining-workface threat replaces legacy threat paths"],
    }
    write_json(root / "scenario_invest_input_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
