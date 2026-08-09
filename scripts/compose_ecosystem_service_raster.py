#!/usr/bin/env python3
"""Build comparable multi-period ecosystem-service rasters from InVEST outputs.

The input manifest declares one carbon, water-yield and habitat-quality raster
per period.  All three services are resampled onto the carbon raster's grid
when necessary, globally Min-Max normalised across the complete time series,
and combined with AHP-derived weights.  The script writes only new outputs and
records every input, normalisation range, and AHP consistency statistic.
"""

from __future__ import annotations

import argparse
import json
import math
from contextlib import ExitStack
from pathlib import Path
from typing import Any


# The pairwise matrix is ordered by service priority: water yield, carbon
# storage, then habitat quality.  Keep this order in both reports and sums.
CRITERIA = ("water_yield", "carbon", "habitat_quality")
RANDOM_INDEX_3 = 0.58


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("manifest root must be an object")
    return value


def ahp_weights(matrix: list[list[float]]) -> tuple[list[float], float, float]:
    if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
        raise ValueError("AHP matrix must be 3 by 3 for water_yield, carbon, habitat_quality")
    for row in matrix:
        if any(not isinstance(value, (int, float)) or value <= 0 for value in row):
            raise ValueError("AHP matrix values must be positive")
    for i in range(3):
        if not math.isclose(matrix[i][i], 1.0, rel_tol=0, abs_tol=1e-9):
            raise ValueError("AHP matrix diagonal must be 1")
        for j in range(i + 1, 3):
            if not math.isclose(matrix[i][j] * matrix[j][i], 1.0, rel_tol=0, abs_tol=1e-7):
                raise ValueError("AHP matrix must be reciprocal")
    vector = [1 / 3] * 3
    for _ in range(1000):
        updated = [sum(matrix[i][j] * vector[j] for j in range(3)) for i in range(3)]
        total = sum(updated)
        updated = [value / total for value in updated]
        if max(abs(a - b) for a, b in zip(updated, vector)) < 1e-12:
            vector = updated
            break
        vector = updated
    products = [sum(matrix[i][j] * vector[j] for j in range(3)) for i in range(3)]
    lambda_max = sum(products[i] / vector[i] for i in range(3)) / 3
    consistency_ratio = ((lambda_max - 3) / 2) / RANDOM_INDEX_3
    return vector, lambda_max, consistency_ratio


def _normalise_periods(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    raw_periods = manifest.get("periods")
    if not isinstance(raw_periods, list) or not raw_periods:
        raise ValueError("manifest.periods must be a non-empty list")
    periods = []
    seen = set()
    for item in raw_periods:
        if not isinstance(item, dict):
            raise ValueError("every period must be an object")
        year = str(item.get("year", "")).strip()
        if not year or year in seen:
            raise ValueError("every period needs a unique year")
        seen.add(year)
        paths = {criterion: Path(str(item.get(criterion, ""))).expanduser().resolve() for criterion in CRITERIA}
        missing = [criterion for criterion, path in paths.items() if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"period {year} has missing raster(s): {', '.join(missing)}")
        periods.append({"year": year, **paths})
    return periods


def _as_aligned_reader(stack: ExitStack, source, master):
    import rasterio
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling

    same_grid = (source.crs == master.crs and source.width == master.width and source.height == master.height
                 and source.transform.almost_equals(master.transform))
    if same_grid:
        return source
    if not source.crs or not master.crs:
        raise ValueError("all service rasters need valid CRS definitions")
    return stack.enter_context(WarpedVRT(source, crs=master.crs, transform=master.transform,
                                         width=master.width, height=master.height,
                                         resampling=Resampling.bilinear, nodata=source.nodata))


def _valid(values, nodata):
    import numpy as np

    result = np.isfinite(values)
    if nodata is not None:
        result &= values != nodata
    return result


def _scan_bounds(periods: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    import rasterio

    bounds = {criterion: {"min": math.inf, "max": -math.inf, "count": 0} for criterion in CRITERIA}
    for period in periods:
        with ExitStack() as stack:
            master = stack.enter_context(rasterio.open(period["carbon"]))
            readers = {criterion: _as_aligned_reader(stack, stack.enter_context(rasterio.open(period[criterion])), master)
                       for criterion in CRITERIA}
            for _, window in master.block_windows(1):
                for criterion, source in readers.items():
                    values = source.read(1, window=window).astype("float64", copy=False)
                    valid = _valid(values, source.nodata)
                    if valid.any():
                        current = bounds[criterion]
                        current["min"] = min(current["min"], float(values[valid].min()))
                        current["max"] = max(current["max"], float(values[valid].max()))
                        current["count"] += int(valid.sum())
    for criterion, current in bounds.items():
        if not current["count"] or not math.isfinite(current["min"]) or not math.isfinite(current["max"]):
            raise ValueError(f"no valid cells found for {criterion}")
        if math.isclose(current["min"], current["max"], rel_tol=0, abs_tol=1e-12):
            # A spatially constant criterion contains no ranking information;
            # set it to 0.5 rather than divide by zero.
            current["constant"] = True
        else:
            current["constant"] = False
    return bounds


def compose(manifest_path: Path, output_dir: Path, *, overwrite: bool = False) -> dict[str, Any]:
    import numpy as np
    import rasterio

    manifest = read_json(manifest_path)
    if int(manifest.get("schema_version", 0)) != 1:
        raise ValueError("manifest.schema_version must be 1")
    periods = _normalise_periods(manifest)
    ahp = manifest.get("ahp", {})
    if not isinstance(ahp, dict) or not isinstance(ahp.get("pairwise_matrix"), list):
        raise ValueError("manifest.ahp.pairwise_matrix is required")
    matrix = ahp["pairwise_matrix"]
    weights, lambda_max, consistency_ratio = ahp_weights(matrix)
    threshold = float(ahp.get("consistency_threshold", 0.1))
    if consistency_ratio > threshold:
        raise ValueError(f"AHP consistency ratio {consistency_ratio:.6f} exceeds threshold {threshold:.6f}")
    bounds = _scan_bounds(periods)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for period in periods:
        output = output_dir / f"ecosystem_service_{period['year']}.tif"
        if output.exists() and not overwrite:
            raise FileExistsError(f"output exists: {output}; use --overwrite after reviewing it")
        with ExitStack() as stack:
            master = stack.enter_context(rasterio.open(period["carbon"]))
            readers = {criterion: _as_aligned_reader(stack, stack.enter_context(rasterio.open(period[criterion])), master)
                       for criterion in CRITERIA}
            profile = master.profile.copy()
            profile.update(count=1, dtype="float32", nodata=-1.0, compress="lzw")
            with rasterio.open(output, "w", **profile) as destination:
                count_valid = 0
                for _, window in master.block_windows(1):
                    values = {criterion: source.read(1, window=window).astype("float64", copy=False)
                              for criterion, source in readers.items()}
                    valid = np.ones(values["carbon"].shape, dtype=bool)
                    for criterion, source in readers.items():
                        valid &= _valid(values[criterion], source.nodata)
                    result = np.full(values["carbon"].shape, -1.0, dtype="float32")
                    if valid.any():
                        score = np.zeros(int(valid.sum()), dtype="float64")
                        for criterion, weight in zip(CRITERIA, weights):
                            current = bounds[criterion]
                            if current["constant"]:
                                normalised = np.full(int(valid.sum()), 0.5, dtype="float64")
                            else:
                                normalised = (values[criterion][valid] - current["min"]) / (current["max"] - current["min"])
                                normalised = np.clip(normalised, 0.0, 1.0)
                            score += weight * normalised
                        result[valid] = score.astype("float32")
                        count_valid += int(valid.sum())
                    destination.write(result, 1, window=window)
        outputs.append({"year": period["year"], "output": str(output), "valid_cell_count": count_valid})
    report = {
        "status": "completed",
        "method": "global_minmax_then_AHP_weighted_sum",
        "criteria_order": list(CRITERIA),
        "weights": dict(zip(CRITERIA, weights)),
        "pairwise_matrix": matrix,
        "lambda_max": lambda_max,
        "consistency_ratio": consistency_ratio,
        "consistency_threshold": threshold,
        "normalization_bounds": bounds,
        "outputs": outputs,
        "manifest": str(manifest_path.resolve()),
    }
    (output_dir / "ecosystem_service_series_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    print(json.dumps(compose(args.manifest.resolve(), args.output_dir.resolve(), overwrite=args.overwrite), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
