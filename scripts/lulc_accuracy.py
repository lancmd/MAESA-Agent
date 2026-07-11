#!/usr/bin/env python3
"""Calculate OA and per-class precision, recall, F1, and IoU from independent validation samples."""

from __future__ import annotations

import argparse
import csv
import json
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


def evaluate(samples_file: Path, reference_field: str, prediction_field: str, output: Path) -> dict[str, Any]:
    with samples_file.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or reference_field not in rows[0] or prediction_field not in rows[0]:
        raise ValueError("sample table must contain the reference and prediction fields")
    valid = [row for row in rows if row.get(reference_field, "") != "" and row.get(prediction_field, "") != ""]
    report = metrics([row[reference_field] for row in valid], [row[prediction_field] for row in valid])
    report.update({"status": "completed", "samples_file": str(samples_file.resolve()),
                   "reference_field": reference_field, "prediction_field": prediction_field})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["output"] = str(output.resolve())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, type=Path)
    parser.add_argument("--reference-field", default="reference")
    parser.add_argument("--prediction-field", default="prediction")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.samples, args.reference_field, args.prediction_field, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
