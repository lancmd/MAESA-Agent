#!/usr/bin/env python3
"""Local command backend for PyTorch LULC model validation and inference."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pytorch_lulc import infer, validate_package  # noqa: E402


def response(envelope: dict[str, Any], status: str, **values: Any) -> dict[str, Any]:
    return {"protocol_version": "1.0", "request_id": envelope.get("request_id"),
            "status": status, **values}


def main() -> int:
    envelope: dict[str, Any] = {}
    try:
        envelope = json.load(sys.stdin)
        operation = envelope.get("operation")
        params = envelope.get("parameters", {})
        if envelope.get("protocol_version") != "1.0":
            result = response(envelope, "failed", error="unsupported protocol version")
        elif operation == "system.capabilities":
            dependencies = {name: bool(importlib.util.find_spec(name)) for name in ("torch", "numpy", "rasterio")}
            result = response(envelope, "completed", result={
                "backend": "pytorch", "operations": ["system.capabilities", "pytorch.validate_model",
                                                        "pytorch.run_lulc_inference"],
                "dependencies": dependencies, "inference_available": all(dependencies.values())
            })
        elif operation == "pytorch.validate_model":
            validation = validate_package(Path(params["model_package"]).expanduser().resolve())
            result = response(envelope, "completed" if validation["status"] == "valid" else "failed",
                              result=validation, error=None if validation["status"] == "valid" else "; ".join(validation["errors"]))
        elif operation == "pytorch.run_lulc_inference":
            report = infer(Path(params["model_package"]).expanduser().resolve(),
                           Path(params["input_raster"]).expanduser().resolve(),
                           Path(params["class_output"]).expanduser().resolve(),
                           Path(params["confidence_output"]).expanduser().resolve(),
                           str(params.get("device", "auto")),
                           Path(params["low_confidence_output"]).expanduser().resolve() if params.get("low_confidence_output") else None,
                           params.get("low_confidence_threshold"))
            result = response(envelope, "completed", result=report,
                              outputs=[item for item in [report["class_output"], report["confidence_output"], report.get("low_confidence_output")] if item])
        else:
            result = response(envelope, "failed", error=f"unsupported PyTorch operation: {operation}")
    except Exception as error:
        result = response(envelope, "failed", error=str(error))
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
