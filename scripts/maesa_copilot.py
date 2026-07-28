#!/usr/bin/env python3
"""Plan and, after explicit confirmation, run a controlled local MAESA MCP workflow."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
VALID_PROVIDERS = {"ollama", "openai_compatible"}
PLAN_SCHEMA_VERSION = 1
PROJECT_CREATION_SCHEMA_VERSION = 1
CONTROLLED_TOOLS = (
    "list_backends", "validate_local_project", "compile_project_workflow",
    "run_local_project", "validate_analysis_results",
)
PAUSE_STATUSES = {"prepared", "waiting_interactive", "pending_validation", "cancelled"}
PROJECT_TASK_TYPES = {
    "classification_only", "classification_invest", "lulc_change_analysis", "plus_only", "invest_only",
    "ecosystem_service_only", "mapping_only", "full_chain",
}
PROJECT_CREATION_ARGUMENTS = {
    "project_id", "task_type", "imagery_periods", "historical_lulc_periods", "driver_factors",
    "mine_boundary", "carbon_density", "ecosystem_criteria", "ecosystem_config", "gis_outputs",
    "w_dat", "model_package", "training_roi", "classification_sensor", "envi_method", "scheme", "w_dat_unit", "w_dat_convention",
    "workface_boundary", "w_dat_max_distance_m", "subsidence_depth_raster", "patch_size",
    "patch_stride", "patch_band_indexes", "patch_input_scale", "patch_batch_size",
    "allow_patch_grid_as_lulc", "invest_models", "accuracy_config", "ecosystem_service_config",
    "subsidence_water_config", "subsidence_water_boundary", "aquatic_vegetation_boundary",
    "bottom_sediment_boundary", "elevation_vertical_datum", "water_level_vertical_datum",
    "water_surface_elevation_m",
}
PROJECT_CREATION_TOOLS = ("build_local_project_from_inputs", "validate_local_project")


def is_loopback(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def load_provider(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("LLM provider configuration must be a JSON object")
    provider = payload.get("provider")
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(VALID_PROVIDERS)}")
    base_url, model = payload.get("base_url"), payload.get("model")
    if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url must be an http(s) URL")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a non-empty string")
    if not is_loopback(base_url) and payload.get("allow_cloud") is not True:
        raise ValueError("cloud LLM endpoints require allow_cloud: true; local endpoints are allowed by default")
    return payload


def load_project(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("project file must be a JSON object")
    return payload


def project_context(project: Path | None) -> dict[str, Any] | None:
    if project is None:
        return None
    payload = load_project(project)
    return {"project_id": payload.get("project_id"), "task_type": payload.get("task_type", "custom"),
            "classification": payload.get("classification", {}).get("enabled"),
            "plus": payload.get("plus", {}).get("enabled"), "invest": payload.get("invest", {}).get("enabled"),
            "ecosystem_service": payload.get("ecosystem_service", {}).get("enabled"),
            "gis_outputs": payload.get("gis_outputs", {}).get("enabled")}


def system_prompt(context: dict[str, Any] | None) -> str:
    return (
        "You are MAESA Copilot for mining-area ecological space analysis. "
        "Help users plan local workflows for LULC, PLUS, InVEST, subsidence-water carbon, ecosystem services and maps. "
        "Do not invent input files, numerical parameters, classification accuracy, PLUS outputs, or InVEST results. "
        "Desktop software is local-only. You cannot issue shell commands or network software-control requests. "
        f"Current project summary: {json.dumps(context or {}, ensure_ascii=False)}"
    )


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    req = request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ask(provider: dict[str, Any], message: str, context: dict[str, Any] | None) -> str:
    base_url = str(provider["base_url"]).rstrip("/")
    timeout = float(provider.get("timeout_seconds", 90))
    messages = [{"role": "system", "content": system_prompt(context)}, {"role": "user", "content": message}]
    if provider["provider"] == "ollama":
        reply = post_json(base_url + "/api/chat", {"model": provider["model"], "messages": messages, "stream": False},
                          {"Content-Type": "application/json"}, timeout)
        content = reply.get("message", {}).get("content")
    else:
        endpoint = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        key_name = provider.get("api_key_env")
        if isinstance(key_name, str) and key_name:
            key = os.getenv(key_name)
            if not key:
                raise ValueError(f"environment variable is not set: {key_name}")
            headers["Authorization"] = f"Bearer {key}"
        reply = post_json(endpoint, {"model": provider["model"], "messages": messages, "temperature": 0.2}, headers, timeout)
        choices = reply.get("choices", [])
        content = choices[0].get("message", {}).get("content") if choices else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response did not contain text")
    return content.strip()


def workspace_for(project_file: Path, project: dict[str, Any]) -> Path:
    raw = project.get("workspace")
    if not isinstance(raw, str) or not raw:
        raise ValueError("project workspace is required for an execution plan")
    value = Path(raw).expanduser()
    return value.resolve() if value.is_absolute() else (project_file.parent / value).resolve()


PATH_LEAF_KEYS = {
    "path", "imagery", "lulc_baseline", "historical_lulc", "mine_boundary", "carbon_density", "model_package",
    "training_roi", "roi", "roi_file", "subsidence_w_dat", "subsidence_depth_raster", "dem", "workface_boundary",
    "aquatic_vegetation_boundary", "bottom_sediment_boundary", "subsidence_water_boundary",
    "validation_samples", "geodetector_samples", "datastack_template", "provided_datastack",
}


def looks_like_local_path(value: str) -> bool:
    suffixes = {".tif", ".tiff", ".img", ".gpkg", ".shp", ".geojson", ".csv", ".json", ".xml", ".dat", ".txt", ".aprx", ".lyrx"}
    candidate = Path(value)
    return candidate.is_absolute() or "/" in value or "\\" in value or candidate.suffix.lower() in suffixes


def nested_input_paths(value: Any, key: str = "") -> list[str]:
    """Collect paths from dated imagery and nested driver/model definitions."""
    if isinstance(value, dict):
        return [item for child_key, child in value.items() for item in nested_input_paths(child, str(child_key))]
    if isinstance(value, list):
        return [item for child in value for item in nested_input_paths(child, key)]
    if isinstance(value, str) and value and (key in PATH_LEAF_KEYS or looks_like_local_path(value)):
        return [value]
    return []


def project_relative_path(project_file: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (project_file.parent / candidate).resolve()


def planned_inputs(project: dict[str, Any], project_file: Path | None = None) -> list[str]:
    values = nested_input_paths(project.get("inputs", {})) if isinstance(project.get("inputs"), dict) else []
    if project_file:
        return sorted({str(project_relative_path(project_file, value)) for value in values})
    return sorted(set(values))


def creation_manifest(manifest_file: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load a user-selected input inventory for natural-language project creation.

    The inventory is intentionally separate from ``project.json``.  The LLM
    can select from these declared local inputs, but it cannot invent a new
    path, overwrite target, or execution tool.
    """
    manifest_file = manifest_file.expanduser().resolve()
    payload = load_project(manifest_file)
    if payload.get("schema_version") not in {None, 1}:
        raise ValueError("input manifest schema_version must be 1 when supplied")
    if payload.get("kind") not in {None, "maesa_project_input_manifest"}:
        raise ValueError("input manifest kind must be maesa_project_input_manifest")
    available = payload.get("available_inputs")
    if not isinstance(available, dict) or not available:
        raise ValueError("input manifest requires a non-empty available_inputs object")
    return payload, available


def _absolute_workspace(output_project: Path, workspace: str) -> Path:
    if not isinstance(workspace, str) or not workspace.strip():
        raise ValueError("workspace must be a non-empty string")
    value = Path(workspace).expanduser()
    return value.resolve() if value.is_absolute() else (output_project.parent / value).resolve()


def _resolved_manifest_paths(manifest_file: Path, value: Any) -> set[str]:
    return {str(project_relative_path(manifest_file, path)) for path in nested_input_paths(value)}


def _normalise_manifest_paths(manifest_file: Path, value: Any, key: str = "") -> Any:
    """Turn selected manifest-relative paths into absolute paths for MCP."""
    if isinstance(value, dict):
        return {str(child_key): _normalise_manifest_paths(manifest_file, child, str(child_key))
                for child_key, child in value.items()}
    if isinstance(value, list):
        return [_normalise_manifest_paths(manifest_file, child, key) for child in value]
    if isinstance(value, str) and value and (key in PATH_LEAF_KEYS or looks_like_local_path(value)):
        return str(project_relative_path(manifest_file, value))
    return value


def project_creation_contract(manifest_file: Path, output_project: Path, workspace: str,
                              purpose: str) -> dict[str, Any]:
    """Create the constrained shell that an LLM may fill with selected inputs."""
    manifest_file = manifest_file.expanduser().resolve()
    manifest, available = creation_manifest(manifest_file)
    output_project = output_project.expanduser().resolve()
    resolved_workspace = _absolute_workspace(output_project, workspace)
    project_id = manifest.get("project_id") if isinstance(manifest.get("project_id"), str) else output_project.stem
    return {
        "schema_version": PROJECT_CREATION_SCHEMA_VERSION,
        "kind": "maesa_project_creation_plan",
        "purpose": purpose,
        "input_manifest": str(manifest_file),
        "output_project": str(output_project),
        "workspace": str(resolved_workspace),
        "available_inputs": _normalise_manifest_paths(manifest_file, available),
        "build_arguments": {"project_id": project_id, "task_type": "full_chain"},
        "confirmation_required": True,
    }


def validate_project_creation_plan(plan: dict[str, Any], manifest_file: Path, output_project: Path,
                                   workspace: str) -> dict[str, Any]:
    """Validate a proposed project build against local inputs and task contracts.

    Path whitelisting by itself is not enough: an LLM can select real files
    yet propose a task that the project builder cannot make runnable.  After
    the immutable-inventory checks pass, use the builder's temporary preflight
    to apply the same construction and project-validation contracts that the
    confirmed MCP build will use.  No selected output path is written here.
    """
    manifest_file = manifest_file.expanduser().resolve()
    manifest, available = creation_manifest(manifest_file)
    output_project = output_project.expanduser().resolve()
    expected_workspace = _absolute_workspace(output_project, workspace)
    errors = json_schema_errors(plan, "maesa_project_creation_plan.schema.json")
    allowed_top_level = {"schema_version", "kind", "purpose", "input_manifest", "output_project", "workspace",
                         "build_arguments", "confirmation_required", "expected_inputs", "expected_outputs"}
    extra_top_level = sorted(set(plan) - allowed_top_level)
    if extra_top_level:
        errors.append("project creation plan contains unsupported fields: " + ", ".join(extra_top_level))
    if plan.get("schema_version") != PROJECT_CREATION_SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    if plan.get("kind") != "maesa_project_creation_plan":
        errors.append("kind must be maesa_project_creation_plan")
    for label, actual, expected in (
        ("input_manifest", plan.get("input_manifest"), manifest_file),
        ("output_project", plan.get("output_project"), output_project),
        ("workspace", plan.get("workspace"), expected_workspace),
    ):
        try:
            if Path(str(actual)).expanduser().resolve() != expected:
                errors.append(f"{label} must match the locally selected value")
        except OSError:
            errors.append(f"{label} must be a valid local path")
    if plan.get("confirmation_required") is not True:
        errors.append("confirmation_required must be true")
    arguments = plan.get("build_arguments")
    if not isinstance(arguments, dict):
        errors.append("build_arguments must be an object")
        arguments = {}
    unknown = sorted(set(arguments) - PROJECT_CREATION_ARGUMENTS)
    if unknown:
        errors.append("build_arguments contains unsupported fields: " + ", ".join(unknown))
    task_type = arguments.get("task_type", "full_chain")
    if task_type not in PROJECT_TASK_TYPES:
        errors.append("task_type must be one of " + ", ".join(sorted(PROJECT_TASK_TYPES)))
    project_id = arguments.get("project_id", manifest.get("project_id", output_project.stem))
    if not isinstance(project_id, str) or not project_id.strip():
        errors.append("build_arguments.project_id must be a non-empty string")
    allowed_paths = _resolved_manifest_paths(manifest_file, available)
    selected_paths = _resolved_manifest_paths(manifest_file, arguments)
    outside = sorted(selected_paths - allowed_paths)
    if outside:
        errors.append("build_arguments references paths not declared in input manifest: " + ", ".join(outside))
    normalized_arguments = _normalise_manifest_paths(manifest_file, arguments)
    normalized_arguments.setdefault("project_id", str(project_id).strip() if isinstance(project_id, str) else output_project.stem)
    normalized_arguments.setdefault("task_type", "full_chain")
    normalized = {
        "schema_version": PROJECT_CREATION_SCHEMA_VERSION,
        "kind": "maesa_project_creation_plan",
        "purpose": str(plan.get("purpose", "create MAESA project")).strip() or "create MAESA project",
        "input_manifest": str(manifest_file),
        "output_project": str(output_project),
        "workspace": str(expected_workspace),
        "build_arguments": normalized_arguments,
        "confirmation_required": True,
        "expected_inputs": sorted(allowed_paths),
        "expected_outputs": [str(output_project), str(expected_workspace)],
    }
    preflight: dict[str, Any] | None = None
    warnings: list[str] = []
    if not errors:
        # Keep construction rules in one place.  In particular this catches a
        # classification_invest plan without every dated accuracy contract, or
        # without carbon density for the default Carbon model, before the
        # confirmation-gated build can create an invalid project file.
        from project_builder import preflight_build_arguments  # noqa: PLC0415

        preflight_arguments = dict(normalized_arguments)
        preflight_project_id = str(preflight_arguments.pop("project_id"))
        try:
            preflight = preflight_build_arguments(preflight_project_id, str(expected_workspace), **preflight_arguments)
        except (ImportError, OSError, TypeError, ValueError, json.JSONDecodeError) as caught:
            preflight = {"status": "invalid", "errors": [f"could not run local project preflight: {caught}"],
                         "pending_inputs": []}
        if preflight["status"] != "valid":
            errors.extend("project prerequisites: " + str(item) for item in preflight.get("errors", []))
        for item in preflight.get("warnings", []):
            warnings.append("project preflight: " + str(item))
        for item in preflight.get("pending_inputs", []):
            warnings.append("project preflight unresolved input: " + str(item))
    return {"status": "valid" if not errors else "invalid", "errors": errors, "warnings": warnings,
            "preflight": preflight, "normalized_plan": normalized}


def project_creation_prompt(manifest_file: Path, output_project: Path, workspace: str, message: str) -> str:
    contract = project_creation_contract(manifest_file, output_project, workspace, message)
    inventory = contract.pop("available_inputs")
    return (
        "Return only one JSON project-creation plan. Select only suitable entries from available_inputs. "
        "Do not create paths, commands, values for missing inputs, or any field outside build_arguments. "
        "Keep input_manifest, output_project, workspace, and confirmation_required unchanged. "
        "If the stated goal cannot be fully configured from the inventory, choose the narrowest valid task_type and state the gap concisely in purpose.\n"
        "Input inventory (reference only; do not echo this key in the returned plan):\n"
        + json.dumps(inventory, ensure_ascii=False, indent=2)
        + "\nRequired returned-plan shape:\n"
        + json.dumps(contract, ensure_ascii=False, indent=2)
    )


def controlled_plan(project_file: Path, purpose: str) -> dict[str, Any]:
    project_file = project_file.expanduser().resolve()
    project = load_project(project_file)
    workspace = workspace_for(project_file, project)
    steps: list[dict[str, Any]] = [
        {"id": "capabilities", "tool": "list_backends", "arguments": {}},
        {"id": "validate_project", "tool": "validate_local_project", "arguments": {"project_file": str(project_file)}},
        {"id": "compile_workflow", "tool": "compile_project_workflow", "arguments": {
            "project_file": str(project_file), "output_job": str(workspace / "generated" / "workflow_job.json")}},
        {"id": "run_workflow", "tool": "run_local_project", "arguments": {
            "project_file": str(project_file), "output_job": str(workspace / "generated" / "workflow_job.json"),
            "dry_run": False, "continue_on_error": False, "confirm_overwrite": False}},
    ]
    validation = project.get("validation", {})
    if isinstance(validation, dict) and validation.get("enabled"):
        evidence_value = validation.get("evidence_file")
        evidence = (project_relative_path(project_file, str(evidence_value)) if evidence_value
                    else workspace / "validation" / "analysis_evidence.json")
        report_value = str(validation.get("output_report", "validation/analysis_validation_report.json"))
        report = project_relative_path(workspace / "project.json", report_value)
        steps.append({"id": "validate_results", "tool": "validate_analysis_results", "arguments": {
            "validation_file": str(evidence), "output_report": str(report)}})
    return {"schema_version": PLAN_SCHEMA_VERSION, "kind": "maesa_controlled_execution_plan",
            "project_file": str(project_file), "purpose": purpose, "task_type": project.get("task_type", "custom"),
            "expected_inputs": planned_inputs(project, project_file),
            "expected_outputs": [str(workspace / name) for name in ("outputs_manifest.json", "provenance.json", "validation_summary.json")],
            "steps": steps, "confirmation_required": True}


def extract_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if match:
        candidate = match.group(1)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as caught:
        raise ValueError("LLM did not return a JSON execution plan") from caught
    if not isinstance(payload, dict):
        raise ValueError("LLM execution plan must be a JSON object")
    return payload


def json_schema_errors(plan: dict[str, Any], schema_name: str = "maesa_execution_plan.schema.json") -> list[str]:
    """Run the shipped Draft 2020-12 schema when the MAESA validation extra is installed."""
    schema_path = ROOT / "schemas" / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        from jsonschema import Draft202012Validator  # type: ignore
    except ImportError:
        # The fixed-contract checks below remain deliberately conservative for
        # a minimal standalone installation. The normal MAESA validation extra
        # installs jsonschema and exercises the complete document schema.
        required = schema.get("required", [])
        return [f"schema requires {name}" for name in required if name not in plan]
    return sorted(error.message for error in Draft202012Validator(schema).iter_errors(plan))


def validate_execution_plan(plan: dict[str, Any], project_file: Path) -> dict[str, Any]:
    """Validate schema and make the LLM plan match the fixed local tool contract."""
    expected = controlled_plan(project_file, str(plan.get("purpose", "execute MAESA project")))
    errors: list[str] = json_schema_errors(plan)
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    if plan.get("kind") != "maesa_controlled_execution_plan":
        errors.append("kind must be maesa_controlled_execution_plan")
    try:
        same_project = Path(str(plan.get("project_file", ""))).expanduser().resolve() == project_file.expanduser().resolve()
    except OSError:
        same_project = False
    if not same_project:
        errors.append("project_file must match the locally selected project")
    steps = plan.get("steps")
    if not isinstance(steps, list):
        errors.append("steps must be an array")
    else:
        expected_steps = expected["steps"]
        if [item.get("tool") for item in steps if isinstance(item, dict)] != [item["tool"] for item in expected_steps]:
            errors.append("steps must use the controlled capability-validate-compile-run-validate order")
        elif len(steps) == len(expected_steps):
            for actual, allowed in zip(steps, expected_steps):
                if not isinstance(actual, dict) or actual.get("arguments") != allowed["arguments"]:
                    errors.append(f"step {allowed['id']} arguments differ from the controlled local contract")
                    break
    if plan.get("confirmation_required") is not True:
        errors.append("confirmation_required must be true")
    return {"status": "valid" if not errors else "invalid", "errors": errors, "normalized_plan": expected}


def execution_prompt(project_file: Path, message: str) -> str:
    template = controlled_plan(project_file, message)
    return (
        "Return only one JSON execution plan. Do not add commands, URLs, or tools. "
        "The exact tool sequence and arguments must remain unchanged; you may only write a concise purpose.\n"
        + json.dumps(template, ensure_ascii=False, indent=2)
    )


async def execute_with_mcp(plan: dict[str, Any]) -> dict[str, Any]:
    """Invoke only the allowlisted local stdio MCP server tools."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as caught:
        raise RuntimeError("MCP Python client is unavailable; install the MAESA runtime before executing a plan") from caught
    parameters = StdioServerParameters(command=sys.executable,
                                       args=[str(ROOT / "mcp_server" / "mining_mcp_server.py"), "--transport", "stdio"],
                                       env=dict(os.environ))
    records: list[dict[str, Any]] = []
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            available = {item.name for item in (await session.list_tools()).tools}
            for step in plan["steps"]:
                tool = step["tool"]
                if tool not in CONTROLLED_TOOLS or tool not in available:
                    return {"status": "failed", "records": records, "error": f"controlled MCP tool is unavailable: {tool}"}
                response = await session.call_tool(tool, step["arguments"])
                try:
                    payload = json.loads(response.content[0].text)
                except (IndexError, AttributeError, json.JSONDecodeError) as caught:
                    return {"status": "failed", "records": records, "error": f"invalid MCP response from {tool}: {caught}"}
                records.append({"id": step["id"], "tool": tool, "result": payload})
                status = payload.get("status")
                if status == "failed":
                    return {"status": "failed", "records": records, "error": payload.get("error", f"{tool} failed"),
                            "repair": "Correct the reported local project/input issue, then execute the same confirmed plan again."}
                if status in PAUSE_STATUSES:
                    return {"status": status, "records": records,
                            "resume": "Complete the indicated local handoff or validation, then re-run this same confirmed plan."}
    return {"status": "completed", "records": records}


async def execute_project_creation_with_mcp(plan: dict[str, Any]) -> dict[str, Any]:
    """Build and validate a project through only the fixed local MCP tools."""
    # This function is public and can be called without the CLI wrapper.  Run
    # the same no-write preflight here so a programmatic caller cannot bypass
    # task prerequisites and leave an invalid project at its selected target.
    try:
        checked = validate_project_creation_plan(
            plan,
            Path(str(plan.get("input_manifest", ""))),
            Path(str(plan.get("output_project", ""))),
            str(plan.get("workspace", "")),
        )
    except (OSError, ValueError, json.JSONDecodeError) as caught:
        return {"status": "failed", "records": [], "error": f"project creation plan preflight failed: {caught}"}
    if checked["status"] != "valid":
        return {"status": "failed", "records": [],
                "error": "project creation plan validation failed: " + "; ".join(checked["errors"]),
                "preflight": checked.get("preflight")}
    plan = checked["normalized_plan"]
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as caught:
        raise RuntimeError("MCP Python client is unavailable; install the MAESA runtime before creating a project") from caught
    build_arguments = {
        "output_project": plan["output_project"], "workspace": plan["workspace"],
        **plan["build_arguments"],
    }
    parameters = StdioServerParameters(command=sys.executable,
                                       args=[str(ROOT / "mcp_server" / "mining_mcp_server.py"), "--transport", "stdio"],
                                       env=dict(os.environ))
    records: list[dict[str, Any]] = []
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            available = {item.name for item in (await session.list_tools()).tools}
            missing = set(PROJECT_CREATION_TOOLS) - available
            if missing:
                return {"status": "failed", "records": records,
                        "error": "controlled MCP tool is unavailable: " + ", ".join(sorted(missing))}
            build_response = await session.call_tool("build_local_project_from_inputs", build_arguments)
            try:
                build = json.loads(build_response.content[0].text)
            except (IndexError, AttributeError, json.JSONDecodeError) as caught:
                return {"status": "failed", "records": records, "error": f"invalid MCP response from project builder: {caught}"}
            records.append({"id": "build_project", "tool": "build_local_project_from_inputs", "result": build})
            if build.get("status") == "failed":
                return {"status": "failed", "records": records, "error": build.get("error", "project build failed")}
            project_file = build.get("result", {}).get("project_file")
            if not isinstance(project_file, str):
                return {"status": "failed", "records": records, "error": "project builder did not return project_file"}
            validation_response = await session.call_tool("validate_local_project", {"project_file": project_file})
            try:
                validation = json.loads(validation_response.content[0].text)
            except (IndexError, AttributeError, json.JSONDecodeError) as caught:
                return {"status": "failed", "records": records, "error": f"invalid MCP response from project validation: {caught}"}
            records.append({"id": "validate_project", "tool": "validate_local_project", "result": validation})
            if validation.get("status") == "failed":
                return {"status": "failed", "records": records, "error": validation.get("error", "project validation failed")}
            return {"status": build.get("status", "completed"), "records": records, "project_file": project_file,
                    "next": "Review the generated project and create a separate execution plan before running analysis."}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", type=Path, default=ROOT / "config" / "llm_provider.json")
    parser.add_argument("--message")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--input-manifest", type=Path,
                        help="Local input inventory for controlled natural-language project creation")
    parser.add_argument("--output-project", type=Path,
                        help="Fixed local project.json target for --write-project-plan")
    parser.add_argument("--workspace", help="Fixed local workspace target for --write-project-plan")
    parser.add_argument("--dry-run", action="store_true", help="Validate provider and preview a confirmation-gated plan without contacting a model")
    parser.add_argument("--write-execution-plan", type=Path, help="Ask the configured LLM for a constrained JSON plan and save it")
    parser.add_argument("--execute-plan", type=Path, help="Execute a previously validated local plan through stdio MCP")
    parser.add_argument("--write-project-plan", type=Path,
                        help="Ask the configured LLM for a constrained project-creation plan and save it")
    parser.add_argument("--execute-project-plan", type=Path,
                        help="Build a project from a previously validated project-creation plan through stdio MCP")
    parser.add_argument("--confirm", action="store_true", help="Required acknowledgement before local MCP execution")
    args = parser.parse_args()
    try:
        if args.execute_project_plan:
            if not args.confirm:
                raise ValueError("--execute-project-plan requires --confirm; review the declared inputs and target paths first")
            plan = load_project(args.execute_project_plan.expanduser().resolve())
            manifest_file = Path(str(plan.get("input_manifest", ""))).expanduser().resolve()
            output_project = Path(str(plan.get("output_project", ""))).expanduser().resolve()
            checked = validate_project_creation_plan(plan, manifest_file, output_project, str(plan.get("workspace", "")))
            if checked["status"] != "valid":
                raise ValueError("project creation plan validation failed: " + "; ".join(checked["errors"]))
            result = asyncio.run(execute_project_creation_with_mcp(checked["normalized_plan"]))
        elif args.execute_plan:
            if not args.confirm:
                raise ValueError("--execute-plan requires --confirm; review the plan's inputs, steps, and outputs first")
            plan = load_project(args.execute_plan.expanduser().resolve())
            project_file = Path(str(plan.get("project_file", ""))).expanduser().resolve()
            checked = validate_execution_plan(plan, project_file)
            if checked["status"] != "valid":
                raise ValueError("execution plan validation failed: " + "; ".join(checked["errors"]))
            result = asyncio.run(execute_with_mcp(checked["normalized_plan"]))
        else:
            provider = load_provider(args.provider.expanduser().resolve())
            context = project_context(args.project)
            if args.dry_run:
                result = {"status": "pending_confirmation" if args.project else "prepared", "provider": provider["provider"],
                          "model": provider["model"], "endpoint_is_local": is_loopback(str(provider["base_url"])), "project": context}
                if args.project:
                    result["execution_plan"] = controlled_plan(args.project.expanduser().resolve(), args.message or "review project")
                if args.input_manifest or args.output_project or args.workspace:
                    if not (args.input_manifest and args.output_project and args.workspace):
                        raise ValueError("--input-manifest, --output-project, and --workspace are required together")
                    result["project_creation_contract"] = project_creation_contract(
                        args.input_manifest, args.output_project, args.workspace, args.message or "create local project")
            else:
                if not args.message:
                    raise ValueError("--message is required unless an execute-plan option is used")
                if args.write_project_plan:
                    if not (args.input_manifest and args.output_project and args.workspace):
                        raise ValueError("--write-project-plan requires --input-manifest, --output-project, and --workspace")
                    proposed = extract_json(ask(provider, project_creation_prompt(
                        args.input_manifest, args.output_project, args.workspace, args.message), None))
                    checked = validate_project_creation_plan(proposed, args.input_manifest, args.output_project, args.workspace)
                    if checked["status"] != "valid":
                        result = {"status": "failed", "errors": checked["errors"], "warnings": checked.get("warnings", []),
                                  "preflight": checked.get("preflight"), "reply": proposed}
                    else:
                        destination = args.write_project_plan.expanduser().resolve()
                        write_json(destination, checked["normalized_plan"])
                        result = {"status": "pending_confirmation", "provider": provider["provider"], "model": provider["model"],
                                  "project_creation_plan": str(destination), "plan": checked["normalized_plan"],
                                  "warnings": checked.get("warnings", []), "preflight": checked.get("preflight")}
                elif args.write_execution_plan:
                    if not args.project:
                        raise ValueError("--write-execution-plan requires --project")
                    proposed = extract_json(ask(provider, execution_prompt(args.project.expanduser().resolve(), args.message), context))
                    checked = validate_execution_plan(proposed, args.project.expanduser().resolve())
                    if checked["status"] != "valid":
                        result = {"status": "failed", "errors": checked["errors"], "reply": proposed}
                    else:
                        destination = args.write_execution_plan.expanduser().resolve()
                        write_json(destination, checked["normalized_plan"])
                        result = {"status": "pending_confirmation", "provider": provider["provider"], "model": provider["model"],
                                  "execution_plan": str(destination), "plan": checked["normalized_plan"]}
                else:
                    result = {"status": "completed", "provider": provider["provider"], "model": provider["model"],
                              "reply": ask(provider, args.message, context)}
    except (OSError, ValueError, error.URLError, json.JSONDecodeError, RuntimeError) as caught:
        result = {"status": "failed", "error": str(caught)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"prepared", "pending_confirmation", "completed", *PAUSE_STATUSES} else 1


if __name__ == "__main__":
    raise SystemExit(main())
