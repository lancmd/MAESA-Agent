#!/usr/bin/env python3
"""Local GUI hand-off bridge for PLUS V1.4.1.

The packaged ``PLUS v1.4.1_boxed.exe`` documents a desktop interface and
Parameterfile persistence, but no supported batch or command-line simulation
entry.  This bridge deliberately starts the executable without invented
arguments, writes a per-scenario hand-off manifest, and lets the workflow adopt
the contracted raster on its next run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from path_safety import PathSafetyError, is_unc, require_within
from plus_contract import expected_plus_raster


ROOT = Path(__file__).resolve().parents[1]


def response(envelope: dict[str, Any], status: str, **values: Any) -> dict[str, Any]:
    return {"protocol_version": "1.0", "request_id": envelope.get("request_id"), "status": status, **values}


def load_local_paths() -> dict[str, Any]:
    configured = Path(os.getenv("MINING_GIS_LOCAL_PATHS", ROOT / "config" / "local_paths.json")).expanduser()
    if not configured.is_file():
        return {}
    payload = json.loads(configured.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def configured_executable() -> Path | None:
    local = load_local_paths()
    raw = os.getenv("PLUS_V141_EXECUTABLE") or local.get("plus_v141_executable") or local.get("plus") or os.getenv("PLUS_EXE")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(os.path.expandvars(raw)).expanduser().resolve()


def scenario_paths(envelope: dict[str, Any]) -> tuple[str, Path, Path, Path]:
    parameters = envelope.get("parameters", {})
    detail = parameters.get("parameters", {}) if isinstance(parameters.get("parameters"), dict) else {}
    scenario = str(parameters.get("scenario", "scenario")).strip().upper()
    raw_workspace = detail.get("output_directory") or parameters.get("workspace")
    if not isinstance(raw_workspace, str) or not raw_workspace:
        raise ValueError("PLUS V1.4.1 bridge needs a scenario output_directory")
    if is_unc(raw_workspace):
        raise PathSafetyError("PLUS workspace cannot be a UNC/network path")
    workspace = Path(raw_workspace).expanduser().resolve()
    project_file = parameters.get("project")
    if isinstance(project_file, str) and Path(project_file).expanduser().is_file():
        from project_validator import validate
        report = validate(Path(project_file).expanduser().resolve())
        if report.get("status") != "valid":
            raise ValueError("PLUS project is no longer valid: " + "; ".join(report.get("errors", [])))
        require_within(workspace, [Path(report["workspace"])], "PLUS scenario workspace")
    else:
        output_root = os.getenv("MINING_PLUS_OUTPUT_ROOT")
        if not output_root:
            raise ValueError("PLUS requires an existing project.json or MINING_PLUS_OUTPUT_ROOT")
        require_within(workspace, [Path(output_root).expanduser().resolve()], "PLUS scenario workspace")
    expected = Path(detail.get("expected_output") or expected_plus_raster(workspace, scenario)).expanduser().resolve()
    require_within(expected, [workspace], "PLUS expected output")
    request_pack = workspace / f"plus_local_request_{scenario}.json"
    return scenario, workspace, expected, request_pack


def write_handoff(envelope: dict[str, Any], executable: Path | None, dry_run: bool) -> tuple[Path, Path]:
    scenario, workspace, expected, request_pack = scenario_paths(envelope)
    workspace.mkdir(parents=True, exist_ok=True)
    handoff = workspace / f"plus_v141_gui_handoff_{scenario}.json"
    state = workspace / "plus_execution_state.json"
    command = [str(executable)] if executable else []
    handoff.write_text(json.dumps({
        "bridge": "plus_v141_gui_handoff",
        "software": "PLUS V1.4.1",
        "scenario": scenario,
        "request_pack": str(request_pack),
        "expected_output": str(expected),
        "launch_command": command,
        "launch_arguments": [],
        "working_directory": str(executable.parent) if executable else None,
        "automation": "interactive_gui",
        "notes": [
            "This PLUS distribution has no verified batch or command-line simulation command.",
            "Open the request pack to identify the scenario inputs, enter them in PLUS, and export the result to expected_output.",
            "Rerun the same project after the GeoTIFF exists; the local workflow will validate and adopt it."
        ]
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state.write_text(json.dumps({
        "scenario": scenario,
        "status": "prepared",
        "bridge": "plus_v141_gui_handoff",
        "request": str(request_pack),
        "handoff": str(handoff),
        "expected_output": str(expected),
        "executable": str(executable) if executable else None,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return handoff, state


def main() -> int:
    envelope: dict[str, Any] = {}
    try:
        envelope = json.load(sys.stdin)
        if envelope.get("protocol_version") != "1.0":
            result = response(envelope, "failed", error="unsupported protocol version")
        elif envelope.get("operation") == "system.capabilities":
            executable = configured_executable()
            result = response(envelope, "completed", result={
                "backend": "plus", "software": "PLUS V1.4.1", "mode": "local-gui-handoff", "local_only": True,
                "executable_configured": bool(executable and executable.is_file()),
                "operations": ["system.capabilities", "plus.run_scenario"],
                "limitations": ["No verified vendor command-line simulation entry; GUI completion is required."],
            })
        elif envelope.get("operation") != "plus.run_scenario":
            result = response(envelope, "failed", error=f"unsupported PLUS operation: {envelope.get('operation')}")
        else:
            executable = configured_executable()
            if executable is None or not executable.is_file():
                result = response(envelope, "failed", error="PLUS V1.4.1 executable is not configured or does not exist")
            elif executable.name.lower() != "plus v1.4.1_boxed.exe":
                result = response(envelope, "failed", error="configured executable is not the expected PLUS V1.4.1 boxed application")
            else:
                dry_run = bool(envelope.get("parameters", {}).get("dry_run", False))
                handoff, state = write_handoff(envelope, executable, dry_run)
                if dry_run:
                    result = response(envelope, "prepared", outputs=[str(handoff), str(state)],
                                      message="PLUS V1.4.1 GUI hand-off prepared (dry run)")
                else:
                    process = subprocess.Popen([str(executable)], cwd=str(executable.parent), shell=False)
                    state_payload = json.loads(state.read_text(encoding="utf-8"))
                    state_payload.update({"status": "waiting_interactive", "process_id": process.pid})
                    state.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    result = response(envelope, "waiting_interactive", outputs=[str(handoff), str(state)],
                                      message="PLUS V1.4.1 GUI launched without command-line arguments; complete the scenario and export the contracted GeoTIFF",
                                      process_id=process.pid)
    except Exception as error:
        result = response(envelope, "failed", error=str(error))
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
