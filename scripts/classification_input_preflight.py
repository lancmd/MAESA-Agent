#!/usr/bin/env python3
"""Check supervised-classification inputs before ENVI or PyTorch starts.

The project schema can confirm that files are present, but this preflight
looks inside the training ROI and independent validation table.  It stops a
classification run before a local software backend is opened when a class
field, geometry/CRS, reference field, or required sampling coordinates are
missing.  It records per-class validation counts so small classes are visible
before accuracy metrics are interpreted.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from roi_quality import inspect as inspect_roi


def inspect_validation_samples(path: Path, reference_field: str, *,
                               prediction_field: str = "prediction",
                               x_field: str | None = None, y_field: str | None = None,
                               samples_crs: str | None = None,
                               require_raster_sampling: bool = False,
                               minimum_samples_per_class: int = 1) -> dict[str, Any]:
    """Read the same CSV form consumed by ``lulc_accuracy.py``.

    A prediction column is deliberately optional when the generated LULC will
    be sampled.  In that mode coordinates and their CRS are evidence, not
    optional metadata.
    """
    errors: list[str] = []
    warnings: list[str] = []
    fieldnames: list[str] = []
    records: list[dict[str, str]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fieldnames = list(reader.fieldnames or [])
            records = list(reader)
    except (OSError, csv.Error) as error:
        errors.append(f"cannot read validation sample table: {error}")
    if not records:
        errors.append("validation sample table contains no records")
    if reference_field not in fieldnames:
        errors.append(f"validation sample table is missing reference field: {reference_field}")
    if require_raster_sampling:
        for field, label in ((x_field, "x_field"), (y_field, "y_field")):
            if not field or field not in fieldnames:
                errors.append(f"raster-sampled validation needs {label} in the sample table")
        if not samples_crs:
            errors.append("raster-sampled validation needs samples_crs")
    elif prediction_field not in fieldnames:
        warnings.append(f"prediction field {prediction_field!r} is absent; it must be sampled from a generated raster")

    labels: Counter[str] = Counter()
    invalid_coordinates = 0
    if reference_field in fieldnames:
        for row in records:
            label = str(row.get(reference_field, "")).strip()
            if label:
                labels[label] += 1
        if not labels:
            errors.append("validation sample table has no non-empty reference labels")
        elif len(labels) < 2:
            errors.append("validation sample table needs at least two reference classes")
    if x_field and y_field and x_field in fieldnames and y_field in fieldnames:
        for row in records:
            try:
                if not (math.isfinite(float(row[x_field])) and math.isfinite(float(row[y_field]))):
                    invalid_coordinates += 1
            except (TypeError, ValueError):
                invalid_coordinates += 1
        if invalid_coordinates:
            errors.append(f"{invalid_coordinates} validation records have invalid coordinate values")
    small = sorted(label for label, count in labels.items() if count < minimum_samples_per_class)
    if small:
        warnings.append("classes below requested validation sample guidance: " + ", ".join(small))
    return {
        "status": "failed" if errors else "completed",
        "validation_samples": str(path.resolve()),
        "reference_field": reference_field,
        "prediction_field": prediction_field,
        "x_field": x_field,
        "y_field": y_field,
        "samples_crs": samples_crs,
        "require_raster_sampling": require_raster_sampling,
        "record_count": len(records),
        "class_counts": dict(sorted(labels.items())),
        "minimum_samples_per_class": minimum_samples_per_class,
        "errors": errors,
        "warnings": warnings,
    }


def preflight(*, roi: Path | None, class_field: str, role_field: str | None,
              training_value: str, validation_value: str, expected_classes: list[str],
              minimum_rois_per_class: int, max_class_imbalance_ratio: float,
              sample_count_field: str | None, require_training_only: bool,
              validation_samples: Path | None, reference_field: str,
              prediction_field: str, x_field: str | None, y_field: str | None,
              samples_crs: str | None, require_raster_sampling: bool,
              minimum_validation_samples_per_class: int) -> dict[str, Any]:
    """Combine ROI and accuracy-sample checks into one pre-backend verdict."""
    sections: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []
    if roi is not None:
        roi_report = inspect_roi(roi, class_field, role_field=role_field,
                                 training_value=training_value, validation_value=validation_value,
                                 expected_classes=expected_classes,
                                 minimum_rois_per_class=minimum_rois_per_class,
                                 max_class_imbalance_ratio=max_class_imbalance_ratio,
                                 sample_count_field=sample_count_field,
                                 require_training_only=require_training_only)
        sections["roi"] = roi_report
        errors.extend(roi_report["errors"])
        warnings.extend(roi_report["warnings"])
    if validation_samples is not None:
        validation_report = inspect_validation_samples(
            validation_samples, reference_field, prediction_field=prediction_field,
            x_field=x_field, y_field=y_field, samples_crs=samples_crs,
            require_raster_sampling=require_raster_sampling,
            minimum_samples_per_class=minimum_validation_samples_per_class,
        )
        sections["validation_samples"] = validation_report
        errors.extend(validation_report["errors"])
        warnings.extend(validation_report["warnings"])
    elif require_raster_sampling:
        errors.append("independent raster-sampled validation is required but no validation sample table was supplied")
    return {"status": "failed" if errors else "completed", "roi": sections.get("roi"),
            "validation_samples": sections.get("validation_samples"), "errors": errors,
            "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roi", type=Path)
    parser.add_argument("--class-field", default="class_id")
    parser.add_argument("--role-field")
    parser.add_argument("--training-value", default="training")
    parser.add_argument("--validation-value", default="validation")
    parser.add_argument("--expected-class", action="append", default=[])
    parser.add_argument("--minimum-rois-per-class", type=int, default=30)
    parser.add_argument("--max-class-imbalance-ratio", type=float, default=10.0)
    parser.add_argument("--sample-count-field")
    parser.add_argument("--require-training-only", action="store_true")
    parser.add_argument("--validation-samples", type=Path)
    parser.add_argument("--reference-field", default="reference")
    parser.add_argument("--prediction-field", default="prediction")
    parser.add_argument("--x-field")
    parser.add_argument("--y-field")
    parser.add_argument("--samples-crs")
    parser.add_argument("--require-raster-sampling", action="store_true")
    parser.add_argument("--minimum-validation-samples-per-class", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.minimum_validation_samples_per_class < 1:
        raise SystemExit("minimum_validation_samples_per_class must be at least 1")
    report = preflight(
        roi=args.roi.resolve() if args.roi else None, class_field=args.class_field, role_field=args.role_field,
        training_value=args.training_value, validation_value=args.validation_value,
        expected_classes=args.expected_class, minimum_rois_per_class=args.minimum_rois_per_class,
        max_class_imbalance_ratio=args.max_class_imbalance_ratio, sample_count_field=args.sample_count_field,
        require_training_only=args.require_training_only,
        validation_samples=args.validation_samples.resolve() if args.validation_samples else None,
        reference_field=args.reference_field, prediction_field=args.prediction_field,
        x_field=args.x_field, y_field=args.y_field, samples_crs=args.samples_crs,
        require_raster_sampling=args.require_raster_sampling,
        minimum_validation_samples_per_class=args.minimum_validation_samples_per_class,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
