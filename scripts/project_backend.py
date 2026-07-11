#!/usr/bin/env python3
"""Local command backend for local-project validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_validator import validate  # noqa: E402
from project_workflow import compile_workflow  # noqa: E402
from analysis_validation import validate_results  # noqa: E402
from lulc_accuracy import evaluate as evaluate_lulc  # noqa: E402
from workflow_agent import JobRunner  # noqa: E402


def main() -> int:
    envelope = json.load(sys.stdin)
    if envelope.get("operation") == "system.capabilities":
        result = {"status": "completed", "result": {"backend": "project", "mode": "local-command", "operations": [
            "system.capabilities", "project.validate", "project.compile_workflow", "project.run_workflow",
            "analysis.validate_results", "analysis.lulc_accuracy", "analysis.plus_validation", "analysis.invest_consistency",
        ]}}
    elif envelope.get("operation") == "project.validate":
        report = validate(Path(envelope["parameters"]["project_file"]).expanduser().resolve())
        result = {"status": "completed" if report["status"] == "valid" else "failed", "result": report,
                  "error": None if report["status"] == "valid" else "; ".join(report["errors"])}
    elif envelope.get("operation") == "project.compile_workflow":
        params = envelope["parameters"]
        output = params.get("output_job")
        report = compile_workflow(Path(params["project_file"]), Path(output) if output else None)
        result = {"status": "completed", "result": report, "outputs": [report["workflow_job"]]}
    elif envelope.get("operation") == "project.run_workflow":
        params = envelope["parameters"]
        output = params.get("output_job")
        compiled = compile_workflow(Path(params["project_file"]), Path(output) if output else None)
        runner = JobRunner(Path(compiled["workflow_job"]), bool(params.get("dry_run")), bool(params.get("continue_on_error")))
        return_code = runner.run()
        state = json.loads(runner.state_path.read_text(encoding="utf-8")) if runner.state_path.exists() else {"stages": {}}
        statuses = {item.get("status") for item in state.get("stages", {}).values()}
        status = "failed" if return_code else "pending_validation" if "pending_validation" in statuses else "prepared" if "prepared" in statuses else "waiting_interactive" if "waiting_interactive" in statuses else "completed"
        result = {"status": status, "result": {"compiled": compiled, "state": str(runner.state_path), "stage_statuses": state.get("stages", {})},
                  "outputs": [compiled["workflow_job"], str(runner.state_path)]}
    elif envelope.get("operation") == "analysis.validate_results":
        params = envelope["parameters"]
        output = params.get("output_report")
        report = validate_results(Path(params["validation_file"]), Path(output) if output else None)
        result = {"status": report["status"], "result": report, "outputs": [report["output"]]}
    elif envelope.get("operation") == "analysis.lulc_accuracy":
        params = envelope["parameters"]
        report = evaluate_lulc(Path(params["samples_file"]), params.get("reference_field", "reference"),
                               params.get("prediction_field", "prediction"), Path(params["output"]))
        result = {"status": "completed", "result": report, "outputs": [report["output"]]}
    elif envelope.get("operation") == "analysis.plus_validation":
        params = envelope["parameters"]
        from plus_validation import evaluate as evaluate_plus
        report = evaluate_plus(Path(params["reference_raster"]), Path(params["predicted_raster"]),
                               Path(params["baseline_raster"]), params.get("seed_predictions", []), Path(params["output"]))
        status = "completed" if len(report.get("seed_metrics", [])) >= 2 else "pending_validation"
        result = {"status": status, "result": report, "outputs": [report["output"]]}
    elif envelope.get("operation") == "analysis.invest_consistency":
        params = envelope["parameters"]
        from invest_consistency import compare
        report = compare(Path(params["workflow_raster"]), Path(params["independent_raster"]),
                         float(params.get("relative_tolerance", 0.001)), Path(params["output"]))
        result = {"status": report["status"], "result": report, "outputs": [report["output"]]}
    else:
        result = {"status": "failed", "error": "unsupported project operation"}
    result.update({"protocol_version": "1.0", "request_id": envelope.get("request_id")})
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
