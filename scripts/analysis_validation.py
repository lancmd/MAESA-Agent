#!/usr/bin/env python3
"""Validate evidence for analysis outputs, not merely whether a tool returned successfully."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import pstdev
from typing import Any


METRICS = ("oa", "precision", "recall", "f1", "iou")
KNOWN_SECTIONS = ("lulc", "plus", "invest", "ecosystem", "map")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def finite_unit(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and 0 <= float(value) <= 1


def section(status: str, checks: list[str], errors: list[str]) -> dict[str, Any]:
    return {"status": status, "checks": checks, "errors": errors}


def validate_lulc(source: dict[str, Any]) -> dict[str, Any]:
    metrics = source.get("metrics")
    if not isinstance(metrics, dict):
        return section("pending_validation", [], ["independent classification metrics are absent"])
    errors: list[str] = []
    checks: list[str] = []
    for name in ("oa", "f1", "iou"):
        if not finite_unit(metrics.get(name)):
            errors.append(f"{name} must be a finite value in [0, 1]")
        else:
            checks.append(name)
    class_metrics = metrics.get("classes")
    if not isinstance(class_metrics, dict) or not class_metrics:
        errors.append("per-class metrics are required")
    else:
        for class_id, values in class_metrics.items():
            if not isinstance(values, dict):
                errors.append(f"class {class_id} metrics must be an object")
                continue
            for name in ("precision", "recall", "f1", "iou"):
                if not finite_unit(values.get(name)):
                    errors.append(f"class {class_id} {name} must be a finite value in [0, 1]")
        checks.append("per-class precision, recall, F1 and IoU")
    return section("failed" if errors else "completed", checks, errors)


def validate_plus(source: dict[str, Any]) -> dict[str, Any]:
    if not source:
        return section("pending_validation", [], ["PLUS validation evidence is absent"])
    errors: list[str] = []
    checks: list[str] = []
    if not finite_unit(source.get("fom")):
        errors.append("FoM must be a finite value in [0, 1]")
    else:
        checks.append("FoM")
    class_metrics = source.get("classes")
    if not isinstance(class_metrics, dict) or not class_metrics:
        errors.append("PLUS key land-class metrics are required")
    else:
        for class_id, values in class_metrics.items():
            if not isinstance(values, dict) or not finite_unit(values.get("f1")) or not finite_unit(values.get("iou")):
                errors.append(f"PLUS class {class_id} requires F1 and IoU in [0, 1]")
        checks.append("key land-class accuracy")
    seeds = source.get("seed_metrics")
    if not isinstance(seeds, list) or len(seeds) < 2:
        return section("pending_validation" if not errors else "failed", checks, errors + ["at least two random-seed results are required"])
    values = []
    for item in seeds:
        if not isinstance(item, dict) or not finite_unit(item.get("fom")):
            errors.append("each seed result requires FoM in [0, 1]")
        else:
            values.append(float(item["fom"]))
    if values:
        checks.append(f"seed FoM population standard deviation={pstdev(values):.6f}")
    return section("failed" if errors else "completed", checks, errors)


def validate_invest(source: dict[str, Any]) -> dict[str, Any]:
    if not source:
        return section("pending_validation", [], ["independent InVEST comparison is absent"])
    reported = source.get("workflow_total_t_c")
    independent = source.get("independent_total_t_c")
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (reported, independent)):
        return section("pending_validation", [], ["workflow and independent InVEST totals are required"])
    tolerance = source.get("relative_tolerance", 0.001)
    if not isinstance(tolerance, (int, float)) or tolerance < 0:
        return section("failed", [], ["relative_tolerance must be non-negative"])
    denominator = max(abs(float(independent)), 1e-12)
    relative_difference = abs(float(reported) - float(independent)) / denominator
    errors = [] if relative_difference <= float(tolerance) else [
        f"relative carbon difference {relative_difference:.6g} exceeds tolerance {float(tolerance):.6g}"
    ]
    return section("failed" if errors else "completed", [f"relative difference={relative_difference:.6g}"], errors)


def validate_ecosystem(source: dict[str, Any]) -> dict[str, Any]:
    if not source:
        return section("pending_validation", [], ["ecosystem-service validation evidence is absent"])
    errors: list[str] = []
    checks: list[str] = []
    ranges = source.get("normalised_ranges")
    if not isinstance(ranges, dict) or not ranges:
        errors.append("normalised_ranges are required")
    else:
        for name, bounds in ranges.items():
            if not isinstance(bounds, list) or len(bounds) != 2 or not all(finite_unit(value) for value in bounds):
                errors.append(f"normalised range for {name} must be [min, max] within [0, 1]")
            elif bounds[0] > bounds[1]:
                errors.append(f"normalised range for {name} has min greater than max")
        checks.append("normalisation ranges")
    if source.get("method") == "ahp":
        ratio = source.get("ahp_consistency_ratio")
        if not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or ratio > 0.1:
            errors.append("AHP consistency ratio must be finite and no greater than 0.1")
        else:
            checks.append("AHP consistency ratio")
    sensitivity = source.get("sensitivity")
    if not isinstance(sensitivity, dict) or not sensitivity:
        errors.append("sensitivity analysis summary is required")
    else:
        checks.append("sensitivity analysis")
    return section("failed" if errors else "completed", checks, errors)


def validate_map(source: dict[str, Any]) -> dict[str, Any]:
    if not source:
        return section("pending_validation", [], ["map-layout validation evidence is absent"])
    errors: list[str] = []
    checks: list[str] = []
    expected = set(source.get("expected_layers", []))
    actual = set(source.get("actual_layers", []))
    if not expected:
        errors.append("expected_layers are required")
    elif not expected.issubset(actual):
        errors.append("one or more expected map layers are absent")
    else:
        checks.append("layer completeness")
    if source.get("legend_accuracy") != 1:
        errors.append("legend_accuracy must equal 1 after visual/symbol inspection")
    else:
        checks.append("legend accuracy")
    extent = source.get("extent")
    if not isinstance(extent, list) or len(extent) != 4 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in extent):
        errors.append("extent must contain four finite coordinates")
    else:
        checks.append("spatial extent")
    resolution = source.get("resolution")
    if not isinstance(resolution, (int, float)) or resolution <= 0:
        errors.append("resolution must be positive")
    else:
        checks.append("export resolution")
    return section("failed" if errors else "completed", checks, errors)


def validate_results(validation_file: Path, output_report: Path | None = None) -> dict[str, Any]:
    payload = load_json(validation_file.expanduser().resolve())
    if payload.get("schema_version") != 1:
        raise ValueError("analysis validation schema_version must be 1")
    reports = payload.get("reports")
    if not isinstance(reports, dict):
        raise ValueError("analysis validation reports must be an object")
    required_sections = payload.get("required_sections", list(KNOWN_SECTIONS))
    if not isinstance(required_sections, list) or not required_sections or any(item not in KNOWN_SECTIONS for item in required_sections):
        raise ValueError("required_sections must be a non-empty subset of " + ", ".join(KNOWN_SECTIONS))
    all_sections = {
        "lulc": validate_lulc(reports.get("lulc", {})),
        "plus": validate_plus(reports.get("plus", {})),
        "invest": validate_invest(reports.get("invest", {})),
        "ecosystem": validate_ecosystem(reports.get("ecosystem", {})),
        "map": validate_map(reports.get("map", {})),
    }
    sections = {name: all_sections[name] for name in required_sections}
    states = {item["status"] for item in sections.values()}
    status = "failed" if "failed" in states else "pending_validation" if "pending_validation" in states else "completed"
    result = {"status": status, "required_sections": required_sections, "sections": sections,
              "source": str(validation_file.expanduser().resolve())}
    output = output_report or validation_file.with_name("analysis_validation_report.json")
    result["output"] = str(output.expanduser().resolve())
    write_json(Path(result["output"]), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation-file", required=True, type=Path)
    parser.add_argument("--output-report", type=Path)
    args = parser.parse_args()
    result = validate_results(args.validation_file, args.output_report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
