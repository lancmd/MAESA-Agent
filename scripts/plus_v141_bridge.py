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
import hashlib
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def executable_identity(executable: Path) -> dict[str, Any]:
    """Return a version assertion and file fingerprint; do not trust its name."""
    local = load_local_paths()
    claimed_version = str(local.get("plus_v141_version") or os.getenv("PLUS_V141_VERSION") or "").strip()
    expected_hash = str(local.get("plus_v141_sha256") or os.getenv("PLUS_V141_SHA256") or "").strip().lower()
    actual_hash = sha256(executable)
    if claimed_version and claimed_version != "PLUS V1.4.1":
        raise ValueError(f"configured PLUS version is not supported by this bridge: {claimed_version}")
    if expected_hash and actual_hash != expected_hash:
        raise ValueError("PLUS executable SHA-256 does not match the locally configured V1.4.1 fingerprint")
    if not claimed_version and not expected_hash:
        raise ValueError("configure plus_v141_version or plus_v141_sha256; executable file names are not used for version validation")
    stat = executable.stat()
    return {"configured_version": claimed_version or "PLUS V1.4.1 (hash-pinned)", "sha256": actual_hash,
            "size_bytes": stat.st_size, "modified_epoch": stat.st_mtime}


def pid_is_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


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


def write_handoff(envelope: dict[str, Any], executable: Path, identity: dict[str, Any], dry_run: bool) -> tuple[Path, Path]:
    scenario, workspace, expected, request_pack = scenario_paths(envelope)
    workspace.mkdir(parents=True, exist_ok=True)
    handoff = workspace / f"plus_v141_gui_handoff_{scenario}.json"
    state = workspace / "plus_execution_state.json"
    detail = envelope.get("parameters", {}).get("parameters", {})
    plus_settings = detail.get("plus_settings", {}) if isinstance(detail, dict) else {}
    command = [str(executable)]
    handoff.write_text(json.dumps({
        "bridge": "plus_v141_gui_handoff",
        "software": "PLUS V1.4.1",
        "scenario": scenario,
        "request_pack": str(request_pack),
        "expected_output": str(expected),
        "launch_command": command,
        "launch_arguments": [],
        "working_directory": str(executable.parent),
        "executable_identity": identity,
        "parameterfile_directory": str(executable.parent / "Parameterfile"),
        "gui_parameter_checklist": {
            "scenario": scenario,
            "historical_lulc": detail.get("historical_lulc", []),
            "driver_factors": detail.get("driver_factors", {}),
            "random_seed": plus_settings.get("random_seed"),
            "neighborhood_weights": plus_settings.get("neighborhood_weights"),
            "transition_matrix": plus_settings.get("transition_matrix"),
            "constraint_raster": plus_settings.get("constraint_raster"),
            "land_demand": plus_settings.get("land_demand", {}),
            "resource_extraction": detail.get("resource_extraction") if scenario == "RE" else None,
        },
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
        "executable": str(executable),
        "executable_identity": identity,
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
            identity = executable_identity(executable) if executable and executable.is_file() else None
            result = response(envelope, "completed", result={
                "backend": "plus", "software": "PLUS V1.4.1", "mode": "local-gui-handoff", "local_only": True,
                "executable_configured": bool(identity), "executable_identity": identity,
                "operations": ["system.capabilities", "plus.run_scenario"],
                "limitations": ["No verified vendor command-line simulation entry; GUI completion is required."],
            })
        elif envelope.get("operation") != "plus.run_scenario":
            result = response(envelope, "failed", error=f"unsupported PLUS operation: {envelope.get('operation')}")
        else:
            executable = configured_executable()
            if executable is None or not executable.is_file():
                result = response(envelope, "failed", error="PLUS V1.4.1 executable is not configured or does not exist")
            else:
                dry_run = bool(envelope.get("parameters", {}).get("dry_run", False))
                identity = executable_identity(executable)
                _, workspace, expected, _ = scenario_paths(envelope)
                state = workspace / "plus_execution_state.json"
                if not dry_run and expected.exists():
                    result = response(envelope, "completed", outputs=[str(expected)],
                                      message="contracted PLUS V1.4.1 output already exists; no GUI launch was needed")
                elif not dry_run and state.is_file():
                    prior = json.loads(state.read_text(encoding="utf-8"))
                    if prior.get("bridge") == "plus_v141_gui_handoff" and pid_is_alive(prior.get("process_id")):
                        result = response(envelope, "waiting_interactive", outputs=[str(state)],
                                          message="continuing the existing PLUS V1.4.1 GUI session", process_id=prior["process_id"])
                    else:
                        handoff, state = write_handoff(envelope, executable, identity, dry_run)
                        process = subprocess.Popen([str(executable)], cwd=str(executable.parent), shell=False)
                        state_payload = json.loads(state.read_text(encoding="utf-8"))
                        state_payload.update({"status": "waiting_interactive", "process_id": process.pid})
                        state.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                        result = response(envelope, "waiting_interactive", outputs=[str(handoff), str(state)],
                                          message="PLUS V1.4.1 GUI launched without command-line arguments; complete the scenario and export the contracted GeoTIFF",
                                          process_id=process.pid)
                else:
                    handoff, state = write_handoff(envelope, executable, identity, dry_run)
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
