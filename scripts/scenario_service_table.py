#!/usr/bin/env python3
"""Build a four-scenario ecosystem criteria table from InVEST carbon rasters."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def raster_total(path: Path) -> float:
    try:
        import numpy as np  # type: ignore
        import rasterio  # type: ignore
    except ModuleNotFoundError as error:
        raise RuntimeError("carbon-raster aggregation requires rasterio in the local Python environment") from error
    with rasterio.open(path) as src:
        total = 0.0
        for _, window in src.block_windows(1):
            values = src.read(1, window=window, masked=True)
            total += float(np.ma.filled(values, 0.0).sum(dtype="float64"))
    return total


def read_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def build(carbon_rasters: dict[str, Path], supplemental: Path | None, output: Path,
          scenario_field: str = "scenario", id_field: str = "unit_id") -> dict[str, Any]:
    rows = read_rows(supplemental)
    supplied = {str(row.get(scenario_field, "")).strip().upper(): dict(row) for row in rows}
    result: list[dict[str, Any]] = []
    for scenario, raster in carbon_rasters.items():
        code = scenario.strip().upper()
        if not raster.exists():
            raise FileNotFoundError(f"InVEST carbon raster is missing for {code}: {raster}")
        row: dict[str, Any] = supplied.get(code, {scenario_field: code, id_field: code})
        row.setdefault(scenario_field, code)
        row.setdefault(id_field, code)
        row["carbon_storage_t_c"] = raster_total(raster)
        result.append(row)
    fields = sorted({key for row in result for key in row})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(result)
    report = {"status": "completed", "scenarios": sorted(carbon_rasters), "output": str(output.resolve()),
              "carbon_rasters": {key: str(value.resolve()) for key, value in carbon_rasters.items()}}
    output.with_suffix(output.suffix + ".metadata.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--carbon-raster", action="append", required=True,
                        help="SCENARIO=path to an InVEST total-carbon raster; repeat for each scenario")
    parser.add_argument("--supplemental", type=Path)
    parser.add_argument("--scenario-field", default="scenario")
    parser.add_argument("--id-field", default="unit_id")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rasters: dict[str, Path] = {}
    for item in args.carbon_raster:
        scenario, separator, raw = item.partition("=")
        if not separator or not scenario or not raw:
            raise SystemExit("--carbon-raster uses SCENARIO=path")
        rasters[scenario.upper()] = Path(raw).expanduser().resolve()
    report = build(rasters, args.supplemental, args.output, args.scenario_field, args.id_field)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
