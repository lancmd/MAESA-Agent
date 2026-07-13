#!/usr/bin/env python3
"""Build scenario-service tables at scenario-total or regular-grid scale."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def raster_total(path: Path) -> float:
    import numpy as np  # type: ignore
    import rasterio  # type: ignore
    with rasterio.open(path) as src:
        total = 0.0
        for _, window in src.block_windows(1):
            values = src.read(1, window=window, masked=True)
            total += float(np.ma.filled(values, 0.0).sum(dtype="float64"))
    return total


def grid_totals(path: Path, cell_pixels: int) -> dict[str, float]:
    """Aggregate a raster into deterministic regular-grid units without vector dependencies."""
    if cell_pixels < 1:
        raise ValueError("grid_cell_pixels must be a positive integer")
    import numpy as np  # type: ignore
    import rasterio  # type: ignore
    from rasterio.windows import Window  # type: ignore
    result: dict[str, float] = {}
    with rasterio.open(path) as src:
        for row in range(0, src.height, cell_pixels):
            for col in range(0, src.width, cell_pixels):
                height, width = min(cell_pixels, src.height - row), min(cell_pixels, src.width - col)
                values = src.read(1, window=Window(col, row, width, height), masked=True)
                result[f"r{row // cell_pixels:05d}_c{col // cell_pixels:05d}"] = float(
                    np.ma.filled(values, 0.0).sum(dtype="float64"))
    return result


def read_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def build(service_rasters: dict[str, dict[str, Path]], supplemental: Path | None, output: Path,
          scenario_field: str = "scenario", id_field: str = "unit_id", grid_cell_pixels: int | None = None) -> dict[str, Any]:
    if not service_rasters:
        raise ValueError("at least one scenario service raster is required")
    supplied = read_rows(supplemental)
    supplied_by_key = {(str(row.get(scenario_field, "")).strip().upper(), str(row.get(id_field, "")).strip()): dict(row)
                       for row in supplied}
    result: list[dict[str, Any]] = []
    scale = "regular_grid" if grid_cell_pixels else "scenario_total"
    for scenario, services in sorted(service_rasters.items()):
        code = scenario.strip().upper()
        if not services:
            continue
        for field, raster in services.items():
            if not raster.exists():
                raise FileNotFoundError(f"InVEST service raster is missing for {code}/{field}: {raster}")
        if grid_cell_pixels:
            by_field = {field: grid_totals(raster, grid_cell_pixels) for field, raster in services.items()}
            unit_ids = set().union(*[set(values) for values in by_field.values()])
            for unit_id in sorted(unit_ids):
                row: dict[str, Any] = supplied_by_key.get((code, unit_id), {scenario_field: code, id_field: unit_id})
                row.setdefault(scenario_field, code); row.setdefault(id_field, unit_id)
                for field, values in by_field.items():
                    row[field] = values.get(unit_id, 0.0)
                result.append(row)
        else:
            row = supplied_by_key.get((code, code), {scenario_field: code, id_field: code})
            row.setdefault(scenario_field, code); row.setdefault(id_field, code)
            for field, raster in services.items():
                row[field] = raster_total(raster)
            result.append(row)
    fields = sorted({key for row in result for key in row})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(result)
    report = {"status": "completed", "spatial_scale": scale, "grid_cell_pixels": grid_cell_pixels,
              "record_count": len(result), "scenarios": sorted(service_rasters), "output": str(output.resolve()),
              "service_rasters": {scenario: {field: str(path.resolve()) for field, path in values.items()}
                                  for scenario, values in service_rasters.items()}}
    output.with_suffix(output.suffix + ".metadata.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-raster", action="append", default=[],
                        help="SCENARIO=FIELD=path; repeat for every scenario/service output")
    parser.add_argument("--carbon-raster", action="append", default=[],
                        help="Backward-compatible SCENARIO=path alias for carbon_storage_t_c")
    parser.add_argument("--supplemental", type=Path)
    parser.add_argument("--scenario-field", default="scenario")
    parser.add_argument("--id-field", default="unit_id")
    parser.add_argument("--grid-cell-pixels", type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rasters: dict[str, dict[str, Path]] = {}
    for item in args.service_raster:
        scenario, separator, rest = item.partition("=")
        field, separator2, raw = rest.partition("=")
        if not separator or not separator2 or not scenario or not field or not raw:
            raise SystemExit("--service-raster uses SCENARIO=FIELD=path")
        rasters.setdefault(scenario.upper(), {})[field] = Path(raw).expanduser().resolve()
    for item in args.carbon_raster:
        scenario, separator, raw = item.partition("=")
        if not separator or not scenario or not raw:
            raise SystemExit("--carbon-raster uses SCENARIO=path")
        rasters.setdefault(scenario.upper(), {})["carbon_storage_t_c"] = Path(raw).expanduser().resolve()
    report = build(rasters, args.supplemental, args.output, args.scenario_field, args.id_field, args.grid_cell_pixels)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
