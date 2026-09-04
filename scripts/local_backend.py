#!/usr/bin/env python3
"""Optional local implementation of the mining GIS backend protocol."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from workflow_runner import probe_software  # noqa: E402
from path_safety import PathSafetyError, is_unc, require_within  # noqa: E402
from carbon_density_contract import compare_codes  # noqa: E402
from invest_datastack_builder import build_from_file, build_habitat_quality_datastack  # noqa: E402
from invest_ecosystem_contract import validate as validate_invest_ecosystem_contract  # noqa: E402


def response(envelope: dict[str, Any], status: str, **values: Any) -> dict[str, Any]:
    return {
        "protocol_version": "1.0",
        "request_id": envelope.get("request_id"),
        "status": status,
        **values,
    }


def run(command: list[str], cwd: Path) -> tuple[int, str]:
    process = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", check=False)
    return process.returncode, process.stdout or ""


def mcp_workspace(value: str) -> Path:
    if is_unc(value):
        raise PathSafetyError("MCP workspace cannot be a UNC/network path")
    workspace = Path(value).expanduser().resolve()
    root = Path(os.getenv("MINING_GIS_MCP_WORKSPACE", ROOT / "outputs" / "mcp")).expanduser().resolve()
    return require_within(workspace, [root], "MCP workspace")


def capabilities(backend: str) -> dict[str, Any]:
    probe = probe_software()["software"]
    if backend == "arcgis":
        item = probe["arcgis_propy"]
        operations = ["system.capabilities", "dataset.inspect", "arcgis.run_operations"]
    elif backend == "invest":
        item = probe["invest"]
        operations = ["system.capabilities", "invest.run_carbon", "invest.run_model",
                      "invest.build_habitat_datastack", "invest.validate_carbon_density"]
    else:
        item, operations = {"available": False, "path": None}, []
    return {"backend": backend, "available": item["available"], "operations": operations,
            "software_path": item["path"], "mode": "local-command"}


def handle_arcgis(envelope: dict[str, Any]) -> dict[str, Any]:
    params = envelope.get("parameters", {})
    operation = envelope["operation"]
    propy = probe_software()["software"]["arcgis_propy"]["path"]
    if not propy:
        return response(envelope, "failed", error="ArcGIS Pro backend is unavailable")
    if operation == "dataset.inspect":
        workspace = (ROOT / "outputs" / "mcp" / "inspect" / uuid.uuid4().hex).resolve()
        output = workspace / "dataset.json"
        spec = {"environment": {"overwriteOutput": False}, "operations": [{
            "id": "inspect", "type": "describe", "input": params["path"], "output": str(output)
        }]}
    elif operation == "arcgis.run_operations":
        workspace = mcp_workspace(params["workspace"])
        spec = params["spec"]
    else:
        return response(envelope, "failed", error=f"unsupported ArcGIS operation: {operation}")
    workspace.mkdir(parents=True, exist_ok=True)
    spec_path = workspace / f"mcp_spec_{envelope['request_id']}.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=True, indent=2), encoding="utf-8")
    command = [propy, str(ROOT / "scripts" / "arcgis_ops.py"), "--spec", str(spec_path), "--workspace", str(workspace)]
    if params.get("confirm_overwrite"):
        command.append("--confirm-overwrite")
    code, log = run(command, workspace)
    log_path = workspace / f"mcp_{envelope['request_id']}.log"
    log_path.write_text(log, encoding="utf-8")
    if code:
        return response(envelope, "failed", error=f"ArcGIS returned {code}", log=str(log_path))
    outputs = [str(output)] if operation == "dataset.inspect" else []
    return response(envelope, "completed", outputs=outputs, log=str(log_path),
                    result=json.loads(output.read_text(encoding="utf-8")) if outputs else None)


def handle_invest(envelope: dict[str, Any]) -> dict[str, Any]:
    params = envelope.get("parameters", {})
    operation = envelope.get("operation")
    if operation == "invest.validate_carbon_density":
        report = compare_codes(Path(params["lulc_path"]).expanduser().resolve(),
                               Path(params["carbon_density"]).expanduser().resolve(),
                               require_exact_codes=bool(params.get("require_exact_codes", False)))
        return response(envelope, report["status"], result=report)
    if operation == "invest.build_habitat_datastack":
        workspace = mcp_workspace(params["workspace"])
        workspace.mkdir(parents=True, exist_ok=True)
        raw_target = params.get("output_datastack")
        target = None
        if raw_target:
            target = require_within(Path(str(raw_target)).expanduser().resolve(), [workspace], "Habitat Quality datastack")
        override = params.get("lulc_override")
        if params.get("config_file"):
            report = build_from_file(Path(str(params["config_file"])).expanduser().resolve(), workspace,
                                     lulc_override=override, datastack_path=target,
                                     allow_overwrite=bool(params.get("confirm_overwrite", False)))
        else:
            config = params.get("habitat_config")
            if not isinstance(config, dict):
                return response(envelope, "failed", error="provide habitat_config or config_file")
            report = build_habitat_quality_datastack(config, workspace, source_base=ROOT,
                                                      lulc_override=override, datastack_path=target,
                                                      allow_overwrite=bool(params.get("confirm_overwrite", False)))
        return response(envelope, report["status"], result=report,
                        outputs=[report[key] for key in ("datastack", "threats_table", "sensitivity_table", "manifest") if report.get(key)])
    model = "carbon" if operation == "invest.run_carbon" else params.get("model")
    if model not in {"carbon", "annual_water_yield", "habitat_quality", "sdr", "ndr"}:
        return response(envelope, "failed", error="supported InVEST models are carbon, annual_water_yield, habitat_quality, sdr, ndr")
    datastack = Path(params["datastack"]).expanduser().resolve()
    input_contract: dict[str, Any] | None = None
    if model == "carbon":
        payload = json.loads(datastack.read_text(encoding="utf-8-sig"))
        args = payload.get("args", {})
        if not isinstance(args, dict):
            return response(envelope, "failed", error="Carbon datastack args must be an object")
        lulc_raw, pools_raw = args.get("lulc_cur_path"), args.get("carbon_pools_path")
        if not lulc_raw or not pools_raw:
            return response(envelope, "failed", error="Carbon datastack needs lulc_cur_path and carbon_pools_path")
        lulc = Path(str(lulc_raw)).expanduser()
        pools = Path(str(pools_raw)).expanduser()
        lulc = lulc.resolve() if lulc.is_absolute() else (datastack.parent / lulc).resolve()
        pools = pools.resolve() if pools.is_absolute() else (datastack.parent / pools).resolve()
        input_contract = compare_codes(lulc, pools, require_exact_codes=bool(params.get("require_exact_codes", False)))
    else:
        contract_model = {"sdr": "sediment_delivery_ratio", "ndr": "nutrient_delivery_ratio"}.get(model, model)
        input_contract = validate_invest_ecosystem_contract(contract_model, datastack)
    if input_contract["status"] != "completed":
        return response(envelope, "failed", error="; ".join(input_contract.get("errors", [])), result={"input_contract": input_contract})
    executable = probe_software()["software"]["invest"]["path"]
    if not executable:
        return response(envelope, "failed", error="InVEST backend is unavailable", result={"input_contract": input_contract})
    workspace = mcp_workspace(params["workspace"])
    workspace.mkdir(parents=True, exist_ok=True)
    code, log = run([executable, "run", model, "-l", "-d",
                     str(datastack), "-w", str(workspace)], workspace)
    log_path = workspace / f"mcp_{envelope['request_id']}.log"
    log_path.write_text(log, encoding="utf-8")
    if code:
        return response(envelope, "failed", error=f"InVEST returned {code}", log=str(log_path))
    outputs = [str(item) for item in workspace.iterdir() if item.is_file()]
    return response(envelope, "completed", outputs=outputs, log=str(log_path), result={"input_contract": input_contract})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, choices=("arcgis", "invest"))
    args = parser.parse_args()
    envelope: dict[str, Any] = {}
    try:
        envelope = json.load(sys.stdin)
        if envelope.get("protocol_version") != "1.0":
            result = response(envelope, "failed", error="unsupported protocol version")
        elif envelope.get("operation") == "system.capabilities":
            result = response(envelope, "completed", result=capabilities(args.backend))
        elif args.backend == "arcgis":
            result = handle_arcgis(envelope)
        else:
            result = handle_invest(envelope)
    except Exception as error:
        result = {"protocol_version": "1.0", "request_id": envelope.get("request_id"),
                  "status": "failed", "error": str(error)}
    print(json.dumps(result, ensure_ascii=True))
    # Protocol failures are valid JSON responses; reserve process failure for a broken bridge.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
