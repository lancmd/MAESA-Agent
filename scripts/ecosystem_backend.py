#!/usr/bin/env python3
"""Local command backend for ecosystem-service scoring."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ecosystem_service import (  # noqa: E402
    calibrate_water_yield,
    evaluate,
    geodetector_factor_analysis,
    scenario_compare,
    tradeoff_analysis,
)


def main() -> int:
    envelope = json.load(sys.stdin)
    if envelope.get("operation") == "system.capabilities":
        result = {"status": "completed", "result": {"backend": "ecosystem", "operations": [
            "system.capabilities", "ecosystem.evaluate", "ecosystem.tradeoff_analysis",
            "ecosystem.scenario_compare", "ecosystem.water_yield_calibration", "ecosystem.geodetector_factor_analysis",
        ]}}
    elif envelope.get("operation") == "ecosystem.evaluate":
        params = envelope["parameters"]
        report = evaluate(Path(params["criteria_table"]).expanduser().resolve(),
                          Path(params["config"]).expanduser().resolve(), Path(params["output"]).expanduser().resolve())
        result = {"status": "completed", "result": report, "outputs": [report["output"]]}
    elif envelope.get("operation") == "ecosystem.tradeoff_analysis":
        params = envelope["parameters"]
        report = tradeoff_analysis(Path(params["criteria_table"]).expanduser().resolve(), params["fields"],
                                   Path(params["output"]).expanduser().resolve())
        result = {"status": "completed", "result": report, "outputs": [report["output"]]}
    elif envelope.get("operation") == "ecosystem.scenario_compare":
        params = envelope["parameters"]
        report = scenario_compare(Path(params["scores_table"]).expanduser().resolve(), params.get("scenario_field", "scenario"),
                                  params["reference_scenario"], params.get("value_fields", ["ecosystem_service_score"]),
                                  Path(params["output"]).expanduser().resolve())
        result = {"status": "completed", "result": report, "outputs": [report["output"]]}
    elif envelope.get("operation") == "ecosystem.water_yield_calibration":
        params = envelope["parameters"]
        report = calibrate_water_yield(Path(params["candidates_table"]).expanduser().resolve(),
                                       params.get("parameter_field", "seasonality_constant_z"),
                                       params.get("modeled_volume_field", "modeled_water_yield_m3"),
                                       params["observed_volume_m3"], Path(params["output"]).expanduser().resolve())
        result = {"status": "completed", "result": report, "outputs": [report["output"]]}
    elif envelope.get("operation") == "ecosystem.geodetector_factor_analysis":
        params = envelope["parameters"]
        report = geodetector_factor_analysis(Path(params["samples_table"]).expanduser().resolve(), params["target_field"],
                                             params["factor_fields"], Path(params["output"]).expanduser().resolve())
        result = {"status": "completed", "result": report, "outputs": [report["output"]]}
    else:
        result = {"status": "failed", "error": "unsupported ecosystem operation"}
    result.update({"protocol_version": "1.0", "request_id": envelope.get("request_id")})
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
