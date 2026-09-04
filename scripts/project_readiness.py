#!/usr/bin/env python3
"""Inspect a MAESA project before starting local GIS software.

The project validator checks the configuration contract.  This command goes a
step further without running ENVI, PLUS, InVEST or ArcGIS Pro: it compiles the
workflow, inspects declared raster/vector inputs, checks dated ROI and
validation samples, inventories source files, and reports which local software
is still needed.  The resulting report is useful as a reproducible hand-off
record before a long multi-period analysis begins.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from classification_input_preflight import preflight as classification_preflight
from path_safety import resolved
from project_validator import imagery_period_accuracy, imagery_period_training_roi, validate
from project_workflow import compile_workflow
from spatial_preflight import validate as spatial_validate
from workflow_runner import probe_software


SOFTWARE_BY_ADAPTER = {
    "arcgis": "arcgis_propy",
    "envi": "idl",
    "invest": "invest",
    "plus": "plus",
}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(job: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Describe static workflow inputs without requiring planned outputs to exist."""
    outputs = {str(Path(value).resolve()) for stage in job.get("stages", [])
               for value in stage.get("outputs", []) if isinstance(value, str)}
    records: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for stage in job.get("stages", []):
        identifier = str(stage.get("id", "unknown"))
        for raw in stage.get("inputs", []):
            if not isinstance(raw, str) or not raw:
                continue
            path = Path(raw).expanduser().resolve()
            key = str(path)
            record = records.setdefault(key, {"path": key, "used_by": []})
            record["used_by"].append(identifier)
            if key in outputs and not path.exists():
                record["state"] = "generated_by_workflow"
                continue
            if not path.exists():
                record["state"] = "missing"
                errors.append(f"workflow input is missing: {path}")
                continue
            if "state" not in record:
                try:
                    record.update({"state": "present", "kind": "directory" if path.is_dir() else "file",
                                   "size_bytes": None if path.is_dir() else path.stat().st_size,
                                   "sha256": None if path.is_dir() else sha256(path)})
                except OSError as error:
                    record.update({"state": "unreadable", "error": str(error)})
                    errors.append(f"workflow input cannot be read: {path}: {error}")
    for record in records.values():
        record["used_by"] = sorted(set(record["used_by"]))
    return sorted(records.values(), key=lambda item: item["path"]), errors


def required_software(job: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    required = sorted({SOFTWARE_BY_ADAPTER[stage.get("adapter")] for stage in job.get("stages", [])
                       if stage.get("enabled") and stage.get("adapter") in SOFTWARE_BY_ADAPTER})
    available = probe.get("software", {}) if isinstance(probe.get("software"), dict) else {}
    entries = [{"name": name, "available": bool(available.get(name, {}).get("available")),
                "path": available.get(name, {}).get("path"), "version": available.get(name, {}).get("version")}
               for name in required]
    return {"required": entries, "missing": [item["name"] for item in entries if not item["available"]]}


def dated_classification_checks(project: dict[str, Any], base: Path) -> tuple[list[dict[str, Any]], list[str], list[str], bool]:
    """Run the same ROI/reference checks used immediately before classification."""
    classification = project.get("classification", {})
    inputs = project.get("inputs", {})
    if not isinstance(classification, dict) or not classification.get("enabled"):
        return [], [], [], False
    engine = classification.get("engine")
    periods = inputs.get("imagery_periods") if isinstance(inputs, dict) else None
    periods = periods if isinstance(periods, list) and periods else [{}]
    task_type = project.get("task_type")
    global_quality = classification.get("roi_quality", {})
    global_accuracy = classification.get("accuracy", {})
    reports: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    independent_accuracy = False
    for index, raw_period in enumerate(periods):
        period = raw_period if isinstance(raw_period, dict) else {}
        year = period.get("year", index + 1)
        try:
            accuracy = imagery_period_accuracy(period, int(year)) if period else dict(global_accuracy)
        except (TypeError, ValueError) as error:
            reports.append({"year": year, "status": "failed", "errors": [str(error)]})
            errors.append(f"classification period {year}: {error}")
            continue
        if accuracy.get("enabled"):
            independent_accuracy = True
        quality: dict[str, Any] = {}
        if isinstance(global_quality, dict):
            quality.update(global_quality)
        if isinstance(period.get("roi_quality"), dict):
            quality.update(period["roi_quality"])
        roi_value = None
        if engine == "envi":
            try:
                roi_value = imagery_period_training_roi(period) or inputs.get("training_roi")
            except ValueError as error:
                errors.append(f"classification period {year}: {error}")
        samples_value = accuracy.get("validation_samples") if isinstance(accuracy, dict) and accuracy.get("enabled") else None
        try:
            roi = Path(resolved(str(roi_value), base)) if roi_value else None
            samples = Path(resolved(str(samples_value), base)) if samples_value else None
            report = classification_preflight(
                roi=roi, class_field=str(quality.get("class_field", "class_id")),
                role_field=quality.get("role_field"), training_value=str(quality.get("training_value", "training")),
                validation_value=str(quality.get("validation_value", "validation")),
                expected_classes=[str(item) for item in quality.get("expected_classes", [])],
                minimum_rois_per_class=int(quality.get("minimum_rois_per_class", 30)),
                max_class_imbalance_ratio=float(quality.get("max_class_imbalance_ratio", 10.0)),
                sample_count_field=quality.get("sample_count_field"),
                require_training_only=task_type == "classification_invest",
                validation_samples=samples,
                reference_field=str(accuracy.get("reference_field", "reference")),
                prediction_field=str(accuracy.get("prediction_field", "prediction")),
                x_field=accuracy.get("x_field"), y_field=accuracy.get("y_field"),
                samples_crs=accuracy.get("samples_crs"),
                require_raster_sampling=task_type == "classification_invest",
                minimum_validation_samples_per_class=int(accuracy.get("minimum_samples_per_class", 1)),
            )
        except (OSError, TypeError, ValueError) as error:
            report = {"status": "failed", "errors": [str(error)], "warnings": []}
        report["year"] = year
        reports.append(report)
        errors.extend(f"classification period {year}: {item}" for item in report.get("errors", []))
        warnings.extend(f"classification period {year}: {item}" for item in report.get("warnings", []))
    return reports, errors, warnings, independent_accuracy


def inspect_project(project_path: Path, output: Path | None = None) -> dict[str, Any]:
    """Return a non-destructive readiness report for one project file."""
    project_path = project_path.expanduser().resolve()
    validation = validate(project_path)
    workspace = Path(validation.get("workspace", project_path.parent / "runtime")).resolve()
    report_path = output.expanduser().resolve() if output else workspace / "validation" / "project_readiness.json"
    result: dict[str, Any] = {
        "project_file": str(project_path), "project_validation": validation,
        "output": str(report_path), "status": "failed", "readiness": "not_ready",
        "errors": list(validation.get("errors", [])), "warnings": list(validation.get("warnings", [])),
    }
    if validation.get("status") != "valid":
        write_json(report_path, result)
        return result

    project, base = read_json(project_path), project_path.parent
    try:
        compiled = compile_workflow(project_path)
        job_path = Path(compiled["workflow_job"])
        job = read_json(job_path)
    except Exception as error:
        result["errors"].append(f"workflow compilation failed: {error}")
        write_json(report_path, result)
        return result

    items, inventory_errors = inventory(job)
    result["workflow"] = {"job": str(job_path), "stage_count": len(job.get("stages", [])),
                          "stages_by_adapter": dict(sorted(Counter(str(stage.get("adapter", "unknown"))
                                                                      for stage in job.get("stages", [])).items())),
                          "stage_ids": [str(stage.get("id")) for stage in job.get("stages", [])]}
    result["input_inventory"] = items
    result["errors"].extend(inventory_errors)

    spatial_path = workspace / "generated" / "spatial_preflight.json"
    if spatial_path.exists():
        try:
            spatial = spatial_validate(read_json(spatial_path))
        except Exception as error:
            spatial = {"status": "failed", "errors": [str(error)], "warnings": []}
        result["spatial_preflight"] = spatial
        result["errors"].extend(f"spatial preflight: {item}" for item in spatial.get("errors", []))
        result["warnings"].extend(f"spatial preflight: {item}" for item in spatial.get("warnings", []))
    else:
        result["spatial_preflight"] = {"state": "not_applicable", "reason": "no static raster/vector preflight is required by this task"}

    checks, check_errors, check_warnings, independent_accuracy = dated_classification_checks(project, base)
    result["classification_input_checks"] = checks
    result["errors"].extend(check_errors)
    result["warnings"].extend(check_warnings)
    result["software_probe"] = probe_software(project.get("software", {}))
    result["software_readiness"] = required_software(job, result["software_probe"])

    if result["errors"]:
        result.update({"status": "failed", "readiness": "not_ready"})
    elif result["software_readiness"]["missing"]:
        result.update({"status": "prepared", "readiness": "software_required"})
    elif project.get("classification", {}).get("enabled") and not independent_accuracy:
        result["warnings"].append("classification can run, but final accuracy evidence remains pending_validation until independent samples are supplied")
        result.update({"status": "pending_validation", "readiness": "runnable_with_pending_validation"})
    else:
        result.update({"status": "completed", "readiness": "ready_to_run"})
    write_json(report_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = inspect_project(args.project, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"completed", "prepared", "pending_validation"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
