#!/usr/bin/env python3
"""Evaluate PLUS backcasts with FoM, class metrics, and multiple random seeds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import pstdev
from typing import Any

import numpy as np
import rasterio

from lulc_accuracy import metrics


def read_raster(path: Path) -> tuple[np.ndarray, dict[str, Any], np.ndarray]:
    with rasterio.open(path) as source:
        data = source.read(1)
        valid = source.dataset_mask() > 0
        profile = {"width": source.width, "height": source.height, "crs": str(source.crs), "transform": tuple(source.transform)}
    return data, profile, valid


def require_aligned(reference: dict[str, Any], candidate: dict[str, Any], label: str) -> None:
    if reference != candidate:
        raise ValueError(f"{label} is not aligned to the reference raster")


def evaluate(reference_path: Path, predicted_path: Path, baseline_path: Path,
             seed_predictions: list[dict[str, Any]] | None, output: Path) -> dict[str, Any]:
    observed, profile, observed_valid = read_raster(reference_path)
    predicted, predicted_profile, predicted_valid = read_raster(predicted_path)
    baseline, baseline_profile, baseline_valid = read_raster(baseline_path)
    require_aligned(profile, predicted_profile, "predicted raster")
    require_aligned(profile, baseline_profile, "baseline raster")
    valid = observed_valid & predicted_valid & baseline_valid
    if not valid.any():
        raise ValueError("no common valid pixels")
    observed_values = observed[valid].astype(str).tolist()
    predicted_values = predicted[valid].astype(str).tolist()
    actual_change = observed[valid] != baseline[valid]
    predicted_change = predicted[valid] != baseline[valid]
    correct_change = actual_change & predicted_change & (observed[valid] == predicted[valid])
    union = actual_change | predicted_change
    fom = float(correct_change.sum() / union.sum()) if union.any() else 1.0
    report: dict[str, Any] = {"status": "completed", "fom": fom,
                              **metrics(observed_values, predicted_values),
                              "reference": str(reference_path.resolve()), "predicted": str(predicted_path.resolve()),
                              "baseline": str(baseline_path.resolve()), "valid_pixel_count": int(valid.sum())}
    seed_rows: list[dict[str, Any]] = []
    for item in seed_predictions or []:
        path = Path(item["path"]).expanduser().resolve()
        data, seed_profile, seed_valid = read_raster(path)
        require_aligned(profile, seed_profile, f"seed raster {path.name}")
        seed_mask = valid & seed_valid
        change = data[seed_mask] != baseline[seed_mask]
        actual = observed[seed_mask] != baseline[seed_mask]
        correct = change & actual & (data[seed_mask] == observed[seed_mask])
        seed_union = change | actual
        seed_rows.append({"seed": item.get("seed", path.stem), "fom": float(correct.sum() / seed_union.sum()) if seed_union.any() else 1.0,
                          "path": str(path)})
    report["seed_metrics"] = seed_rows
    if len(seed_rows) >= 2:
        report["seed_fom_population_stddev"] = pstdev([row["fom"] for row in seed_rows])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["output"] = str(output.resolve())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--predicted", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--seed-predictions", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    seeds = json.loads(args.seed_predictions.read_text(encoding="utf-8")) if args.seed_predictions else []
    print(json.dumps(evaluate(args.reference, args.predicted, args.baseline, seeds, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
