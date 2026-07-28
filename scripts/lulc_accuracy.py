#!/usr/bin/env python3
"""Calculate OA and per-class precision, recall, F1, and IoU from independent validation samples."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


def metrics(reference: list[str], prediction: list[str]) -> dict[str, Any]:
    if not reference or len(reference) != len(prediction):
        raise ValueError("reference and prediction samples must have the same non-zero length")
    labels = sorted(set(reference) | set(prediction))
    rows: dict[str, dict[str, float]] = {}
    correct = sum(left == right for left, right in zip(reference, prediction))
    for label in labels:
        true_positive = sum(left == label and right == label for left, right in zip(reference, prediction))
        false_positive = sum(left != label and right == label for left, right in zip(reference, prediction))
        false_negative = sum(left == label and right != label for left, right in zip(reference, prediction))
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        iou = true_positive / (true_positive + false_positive + false_negative) if true_positive + false_positive + false_negative else 0.0
        rows[label] = {"sample_count": sum(left == label for left in reference), "precision": precision,
                       "recall": recall, "f1": f1, "iou": iou}
    return {"sample_count": len(reference), "oa": correct / len(reference),
            "f1": sum(row["f1"] for row in rows.values()) / len(rows),
            "iou": sum(row["iou"] for row in rows.values()) / len(rows), "classes": rows}


def prepared_rows(samples_file: Path, reference_field: str, prediction_field: str,
                  classification_raster: Path | None = None, x_field: str | None = None,
                  y_field: str | None = None, samples_crs: str | None = None,
                  require_raster_sampling: bool = False) -> list[dict[str, str]]:
    with samples_file.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or reference_field not in rows[0]:
        raise ValueError("sample table must contain the reference field")
    if require_raster_sampling and classification_raster is None:
        raise ValueError("independent accuracy requires predictions sampled from --classification-raster")
    if require_raster_sampling and not samples_crs:
        raise ValueError("independent raster-sampled accuracy requires --samples-crs")
    if classification_raster is None and prediction_field not in rows[0]:
        raise ValueError("sample table must contain the prediction field when classification_raster is not supplied")
    if classification_raster is not None:
        if not x_field or not y_field or x_field not in rows[0] or y_field not in rows[0]:
            raise ValueError("raster sampling requires x_field and y_field in the validation sample table")
        try:
            import rasterio  # type: ignore
            from rasterio.warp import transform  # type: ignore
        except ModuleNotFoundError as error:
            raise RuntimeError("raster-sampled accuracy evaluation requires rasterio") from error
        with rasterio.open(classification_raster) as src:
            try:
                coordinates = [(float(row[x_field]), float(row[y_field])) for row in rows]
            except (TypeError, ValueError, KeyError) as error:
                raise ValueError("validation sample coordinates must be numeric values") from error
            if any(not math.isfinite(x) or not math.isfinite(y) for x, y in coordinates):
                raise ValueError("validation sample coordinates must be finite values")
            if samples_crs and str(src.crs) != samples_crs:
                if not src.crs:
                    raise ValueError("classification raster has no CRS for coordinate transformation")
                x_values, y_values = transform(samples_crs, str(src.crs), [item[0] for item in coordinates],
                                                [item[1] for item in coordinates])
                coordinates = list(zip(x_values, y_values))
            outside = [index + 1 for index, (x_value, y_value) in enumerate(coordinates)
                       if not (src.bounds.left <= x_value < src.bounds.right and
                               src.bounds.bottom < y_value <= src.bounds.top)]
            if outside:
                preview = ", ".join(str(item) for item in outside[:10])
                suffix = "..." if len(outside) > 10 else ""
                raise ValueError(f"{len(outside)} validation samples fall outside the classification raster (rows {preview}{suffix})")
            nodata = src.nodata
            for row, value in zip(rows, src.sample(coordinates)):
                predicted = value[0]
                is_nodata = nodata is not None and predicted == nodata
                try:
                    is_nan = math.isnan(float(predicted))
                except (TypeError, ValueError):
                    is_nan = False
                if is_nan:
                    is_nodata = True
                row[prediction_field] = "" if is_nodata else str(int(predicted))
    return rows


def evaluate(samples_file: Path, reference_field: str, prediction_field: str, output: Path,
             classification_raster: Path | None = None, x_field: str | None = None,
             y_field: str | None = None, samples_crs: str | None = None,
             require_raster_sampling: bool = False) -> dict[str, Any]:
    with samples_file.open("r", encoding="utf-8-sig", newline="") as stream:
        source_columns = set((csv.DictReader(stream).fieldnames or []))
    rows = prepared_rows(samples_file, reference_field, prediction_field, classification_raster, x_field, y_field,
                         samples_crs, require_raster_sampling)
    valid = [row for row in rows if row.get(reference_field, "") != "" and row.get(prediction_field, "") != ""]
    report = metrics([row[reference_field] for row in valid], [row[prediction_field] for row in valid])
    report.update({"status": "completed", "samples_file": str(samples_file.resolve()),
                   "reference_field": reference_field, "prediction_field": prediction_field,
                   "prediction_source": "classification_raster_sample" if classification_raster else "validation_table",
                   "classification_raster": str(classification_raster.resolve()) if classification_raster else None,
                   "x_field": x_field if classification_raster else None,
                   "y_field": y_field if classification_raster else None,
                   "samples_crs": samples_crs if classification_raster else None,
                   "preexisting_prediction_field_ignored": bool(classification_raster and prediction_field in source_columns)})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["output"] = str(output.resolve())
    return report


def write_confusion_matrix(samples_file: Path, reference_field: str, prediction_field: str, output: Path,
                           classification_raster: Path | None = None, x_field: str | None = None,
                           y_field: str | None = None, samples_crs: str | None = None,
                           require_raster_sampling: bool = False) -> str:
    rows = prepared_rows(samples_file, reference_field, prediction_field, classification_raster, x_field, y_field,
                         samples_crs, require_raster_sampling)
    valid = [row for row in rows if row.get(reference_field, "") and row.get(prediction_field, "")]
    labels = sorted({row[reference_field] for row in valid} | {row[prediction_field] for row in valid})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["reference\\prediction", *labels])
        for reference in labels:
            writer.writerow([reference, *[sum(row[reference_field] == reference and row[prediction_field] == prediction
                                           for row in valid) for prediction in labels]])
    return str(output.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, type=Path)
    parser.add_argument("--reference-field", default="reference")
    parser.add_argument("--prediction-field", default="prediction")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confusion-matrix", type=Path)
    parser.add_argument("--classification-raster", type=Path)
    parser.add_argument("--x-field")
    parser.add_argument("--y-field")
    parser.add_argument("--samples-crs")
    parser.add_argument("--require-raster-sampling", action="store_true",
                        help="reject table-supplied predictions; sample the generated classification raster instead")
    args = parser.parse_args()
    report = evaluate(args.samples, args.reference_field, args.prediction_field, args.output,
                      args.classification_raster, args.x_field, args.y_field, args.samples_crs,
                      args.require_raster_sampling)
    if args.confusion_matrix:
        report["confusion_matrix"] = write_confusion_matrix(args.samples, args.reference_field,
            args.prediction_field, args.confusion_matrix, args.classification_raster, args.x_field, args.y_field,
            args.samples_crs, args.require_raster_sampling)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
