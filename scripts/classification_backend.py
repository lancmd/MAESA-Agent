#!/usr/bin/env python3
"""Local command bridge for classification profiles and ROI quality checks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from classification_profiles import profile, supported_sensors  # noqa: E402
from path_safety import PathSafetyError, is_unc, require_within  # noqa: E402
from roi_quality import inspect, write_report  # noqa: E402


OPERATIONS = ("system.capabilities", "classification.sensor_parameters", "classification.roi_quality")


def response(envelope: dict[str, Any], status: str, **values: Any) -> dict[str, Any]:
    return {"protocol_version": "1.0", "request_id": envelope.get("request_id"), "status": status, **values}


def _input_roots() -> list[Path]:
    raw = os.getenv("MINING_GIS_INPUT_ROOTS")
    values = raw.split(os.pathsep) if raw else [str(ROOT)]
    roots = [Path(value).expanduser().resolve() for value in values if value]
    if not roots or any(is_unc(str(item)) for item in roots):
        raise PathSafetyError("MINING_GIS_INPUT_ROOTS must contain local directories")
    return roots


def _output_root() -> Path:
    value = os.getenv("MINING_GIS_OUTPUT_ROOT", str(ROOT / "outputs"))
    if is_unc(value):
        raise PathSafetyError("MINING_GIS_OUTPUT_ROOT cannot be a UNC/network path")
    return Path(value).expanduser().resolve()


def _local_input(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    if is_unc(value) or ".." in Path(value).parts:
        raise PathSafetyError(f"{label} must be a local path without parent traversal")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return require_within(path, _input_roots(), label)


def _local_output(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    if is_unc(value) or ".." in Path(value).parts:
        raise PathSafetyError(f"{label} must be a local path without parent traversal")
    return require_within(Path(value).expanduser().resolve(), [_output_root()], label)


def main() -> int:
    envelope: dict[str, Any] = {}
    try:
        envelope = json.load(sys.stdin)
        if envelope.get("protocol_version") != "1.0":
            result = response(envelope, "failed", error="unsupported protocol version")
        else:
            operation = envelope.get("operation")
            params = envelope.get("parameters", {})
            if operation == "system.capabilities":
                result = response(envelope, "completed", result={
                    "backend": "classification", "mode": "local-command", "local_only": True,
                    "operations": list(OPERATIONS), "supported_sensors": supported_sensors(),
                    "roi_readers": ["GeoJSON", "CSV", "Fiona when installed", "ArcGIS Pro Python fallback"],
                })
            elif operation == "classification.sensor_parameters":
                result = response(envelope, "completed", result=profile(
                    str(params.get("sensor", "")), str(params.get("method", "auto")),
                    str(params.get("scheme", "high_water_coal_7class")),
                ))
            elif operation == "classification.roi_quality":
                roi = _local_input(params.get("roi_file"), "roi_file")
                output = _local_output(params.get("output"), "output")
                expected = params.get("expected_classes") or []
                if not isinstance(expected, list):
                    raise ValueError("expected_classes must be an array when supplied")
                report = inspect(
                    roi, str(params.get("class_field", "class_id")), role_field=params.get("role_field"),
                    training_value=str(params.get("training_value", "training")),
                    validation_value=str(params.get("validation_value", "validation")),
                    expected_classes=expected, minimum_rois_per_class=int(params.get("minimum_rois_per_class", 30)),
                    max_class_imbalance_ratio=float(params.get("max_class_imbalance_ratio", 10.0)),
                    sample_count_field=params.get("sample_count_field"),
                    require_training_only=bool(params.get("require_training_only", False)),
                )
                report["output"] = write_report(report, output)
                result = response(envelope, report["status"], result=report, outputs=[report["output"]],
                                  error="; ".join(report["errors"]) if report["errors"] else None)
            else:
                result = response(envelope, "failed", error=f"unsupported classification operation: {operation}")
    except Exception as error:
        result = response(envelope, "failed", error=str(error))
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
