#!/usr/bin/env python3
"""Local GUI bridge pinned to one official HPSCIL PLUS repository snapshot.

The selected official repository snapshot contains an executable named
``PLUS V1.4.2.exe`` but its live Qt window identifies itself as V1.4.1 and the
repository has no tagged release.  The bridge records this evidence instead of
asserting a vendor version from the file name.  It automates the local window
with an explicitly calibrated profile and never invents menu names, dialog
controls, or command-line arguments.  UI Automation through :mod:`pywinauto`
is preferred; a screenshot template is only a local fallback.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from path_safety import PathSafetyError, is_unc, require_within
from plus_contract import expected_plus_raster


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_NAME = "plus_v142_gui_automation"
SOFTWARE_NAME = "HPSCIL official PLUS snapshot"
EXE_FILE_LABEL = "PLUS V1.4.2.exe"
OBSERVED_UI_TITLE = "Patch-generating Land Use Simulation (PLUS) Model V1.4.1"
OFFICIAL_REMOTE = "https://github.com/HPSCIL/Patch-generating_Land_Use_Simulation_Model.git"
PINNED_COMMIT = "de7ba6efd35b530da6c37e81103276a17716602c"
PINNED_EXECUTABLE = "PLUS V1.4.2.exe"
PINNED_SHA256 = "2f49f4f01c0a209d0d67fabef9013d41fca30b1632e334898abadad5c2eb25d4"
VALID_SCENARIOS = {"ND", "UD", "EP", "RE"}
GUI_LIFECYCLE_STATES = {
    "prepared", "calibration_required", "waiting_uac", "running_gui", "waiting_export",
    "output_detected", "validated", "completed",
}


class GuiAutomationError(RuntimeError):
    """A profile cannot safely operate the current local PLUS window."""


def response(envelope: dict[str, Any], status: str, **values: Any) -> dict[str, Any]:
    return {"protocol_version": "1.0", "request_id": envelope.get("request_id"), "status": status, **values}


def read_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def transition(state: dict[str, Any], lifecycle_status: str, **values: Any) -> None:
    """Persist a compact lifecycle audit trail beside the resumable GUI state."""
    if lifecycle_status not in GUI_LIFECYCLE_STATES:
        raise ValueError(f"unsupported PLUS GUI lifecycle state: {lifecycle_status}")
    history = state.setdefault("lifecycle_history", [])
    if not history or history[-1].get("state") != lifecycle_status:
        history.append({"state": lifecycle_status, "at": time.time()})
    state.update({"lifecycle_status": lifecycle_status, **values})


def load_local_paths() -> dict[str, Any]:
    configured = Path(os.getenv("MINING_GIS_LOCAL_PATHS", ROOT / "config" / "local_paths.json")).expanduser()
    payload = read_json(configured, {})
    return payload if isinstance(payload, dict) else {}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_remote(value: str) -> str:
    return value.strip().replace("\\", "/").rstrip("/").removesuffix(".git").lower()


def git_identity(repository: Path) -> tuple[str, str]:
    """Read the origin URL and checked-out SHA without relying on a Git binary."""
    dot_git = repository / ".git"
    if not dot_git.is_dir():
        raise ValueError("official PLUS snapshot does not contain .git metadata")
    config = (dot_git / "config").read_text(encoding="utf-8", errors="replace")
    origin = re.search(r'\[remote "origin"\][^\[]*?^\s*url\s*=\s*(.+?)\s*$', config, flags=re.MULTILINE | re.DOTALL)
    if not origin:
        raise ValueError("official PLUS snapshot has no origin remote")
    head = (dot_git / "HEAD").read_text(encoding="ascii", errors="replace").strip()
    if head.startswith("ref: "):
        ref = head[5:].strip()
        reference = dot_git / ref
        if reference.is_file():
            commit = reference.read_text(encoding="ascii", errors="replace").strip()
        else:
            packed = dot_git / "packed-refs"
            lines = packed.read_text(encoding="ascii", errors="replace").splitlines() if packed.is_file() else []
            commit = next((line.split(" ", 1)[0] for line in lines if line.endswith(" " + ref)), "")
    else:
        commit = head
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ValueError("cannot resolve the checked-out official PLUS snapshot commit")
    return origin.group(1).strip(), commit.lower()


def configured_installation() -> tuple[Path, Path, dict[str, Any]]:
    """Return the one approved local official release, or raise a useful error."""
    local = load_local_paths()
    repo_raw = os.getenv("PLUS_V142_REPOSITORY") or local.get("plus_v142_repository")
    executable_raw = os.getenv("PLUS_V142_EXECUTABLE") or local.get("plus_v142_executable") or local.get("plus")
    if not isinstance(repo_raw, str) or not repo_raw.strip() or not isinstance(executable_raw, str) or not executable_raw.strip():
        raise ValueError("configure plus_v142_repository and plus_v142_executable in config/local_paths.json")
    if is_unc(repo_raw) or is_unc(executable_raw):
        raise PathSafetyError("official PLUS snapshot must be installed on a local drive, not a UNC/network path")
    repository = Path(os.path.expandvars(repo_raw)).expanduser().resolve()
    executable = Path(os.path.expandvars(executable_raw)).expanduser().resolve()
    if not repository.is_dir() or not executable.is_file():
        raise ValueError("configured official PLUS snapshot repository or executable does not exist")
    if executable.name != PINNED_EXECUTABLE:
        raise ValueError(f"official snapshot bridge only accepts the repository executable named {PINNED_EXECUTABLE}")
    require_within(executable, [repository], "official PLUS snapshot executable")
    origin, commit = git_identity(repository)
    if normalize_remote(origin) != normalize_remote(OFFICIAL_REMOTE):
        raise ValueError("PLUS snapshot origin is not the approved HPSCIL official repository")
    if commit != PINNED_COMMIT:
        raise ValueError(f"official PLUS snapshot checkout is {commit}, expected pinned commit {PINNED_COMMIT}")
    claimed_version = str(local.get("plus_v142_version") or "unverified").strip()
    claimed_hash = str(local.get("plus_v142_sha256") or PINNED_SHA256).strip().lower()
    claimed_commit = str(local.get("plus_v142_commit") or PINNED_COMMIT).strip().lower()
    actual_hash = sha256(executable)
    if claimed_commit != PINNED_COMMIT or claimed_hash != PINNED_SHA256:
        raise ValueError("local PLUS snapshot identity fields do not match the pinned official binary")
    if actual_hash != PINNED_SHA256:
        raise ValueError("official PLUS snapshot executable SHA-256 differs from the pinned binary")
    identity = {
        "software": SOFTWARE_NAME,
        "version_evidence": {
            "repository_executable_filename": EXE_FILE_LABEL,
            "configured_label": claimed_version,
            "observed_ui_title": OBSERVED_UI_TITLE,
            "vendor_release_status": "unverified: no repository tag or GitHub release",
        },
        "repository": str(repository),
        "origin": origin,
        "commit": commit,
        "executable": str(executable),
        "sha256": actual_hash,
        "size_bytes": executable.stat().st_size,
    }
    return repository, executable, identity


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


def scenario_paths(envelope: dict[str, Any]) -> tuple[str, Path, Path, Path, Path]:
    parameters = envelope.get("parameters", {})
    detail = parameters.get("parameters", {}) if isinstance(parameters.get("parameters"), dict) else {}
    scenario = str(parameters.get("scenario", "")).strip().upper()
    if scenario not in VALID_SCENARIOS:
        raise ValueError("official HPSCIL PLUS snapshot supports only ND, UD, EP, or RE scenarios")
    raw_workspace = detail.get("output_directory") or parameters.get("workspace")
    if not isinstance(raw_workspace, str) or not raw_workspace:
        raise ValueError("official HPSCIL PLUS bridge needs a per-scenario output_directory")
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
    request = workspace / f"plus_v142_gui_request_{scenario}.json"
    state = workspace / "plus_execution_state.json"
    return scenario, workspace, expected, request, state


def render_value(value: Any, context: dict[str, Any]) -> Any:
    """Render ${field} placeholders from a flat, local request context."""
    if not isinstance(value, str):
        return value
    def replacement(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            raise GuiAutomationError(f"PLUS GUI profile references unavailable context field: {key}")
        return str(context[key])
    return re.sub(r"\$\{([A-Za-z0-9_.-]+)\}", replacement, value)


def request_context(envelope: dict[str, Any], scenario: str, workspace: Path, expected: Path) -> dict[str, Any]:
    detail = envelope.get("parameters", {}).get("parameters", {})
    detail = detail if isinstance(detail, dict) else {}
    history = [str(item) for item in detail.get("historical_lulc", []) if isinstance(item, str)]
    drivers = detail.get("driver_factors", {}) if isinstance(detail.get("driver_factors"), dict) else {}
    context: dict[str, Any] = {"scenario": scenario, "workspace": str(workspace), "expected_output": str(expected),
                               "historical_lulc_count": len(history)}
    # LEAS receives a directory rather than one driver path.  The compiler
    # passes all aligned driver paths in ``driver_factors``; derive the common
    # parent so the GUI and the generated LEAS parameter file use the same
    # contract.  An explicit value in plus_settings wins for projects that
    # keep a curated feature stack separate from other drivers.
    driver_paths = [Path(value) for value in drivers.values() if isinstance(value, str) and value]
    if driver_paths:
        parents = {str(path.expanduser().resolve().parent) for path in driver_paths}
        if len(parents) == 1:
            context["leas_driver_folder"] = next(iter(parents))
        else:
            context["leas_driver_folder"] = str(driver_paths[0].expanduser().resolve().parent)
    else:
        context["leas_driver_folder"] = ""
    for index, item in enumerate(history):
        context[f"historical_lulc_{index}"] = item
    for key, value in drivers.items():
        if isinstance(value, str):
            context[f"driver_{key}"] = value
    settings = detail.get("plus_settings", {}) if isinstance(detail.get("plus_settings"), dict) else {}
    for key, value in settings.items():
        if isinstance(value, (str, int, float)) or value is None:
            context[f"plus_{key}"] = "" if value is None else value
    explicit_feature_folder = settings.get("leas_driver_folder")
    if isinstance(explicit_feature_folder, str) and explicit_feature_folder:
        context["leas_driver_folder"] = explicit_feature_folder
    explicit_expansion = settings.get("leas_expansion_input")
    if isinstance(explicit_expansion, str) and explicit_expansion:
        context["leas_expansion_input"] = explicit_expansion
    elif len(history) >= 2:
        # Keep the fallback deterministic for older project requests.  The
        # workflow compiler normally writes this raster before creating the
        # request, so this path is also a useful contract diagnostic.
        context["leas_expansion_input"] = str(workspace.parent.parent / "intermediate" / "plus_inputs" /
                                              f"land_expansion_{settings.get('baseline_year', 2025)}_{settings.get('target_year', 2026)}.tif")
    else:
        context["leas_expansion_input"] = ""
    # Land demand is passed as a per-scenario class mapping by the project
    # compiler.  Flatten it into explicit placeholders so one calibrated GUI
    # profile can be reused for ND/UD/EP/RE without editing screen coordinates
    # or hard-coding the same demand vector into every scenario.
    land_demand = settings.get("land_demand")
    if isinstance(land_demand, dict):
        for class_code, value in land_demand.items():
            if isinstance(value, (str, int, float)):
                context[f"plus_demand_{class_code}"] = value
    resource = detail.get("resource_extraction", {}) if isinstance(detail.get("resource_extraction"), dict) else {}
    for key, value in resource.items():
        if isinstance(value, (str, int, float)) or value is None:
            context[f"re_{key}"] = "" if value is None else value
    core_input = resource.get("core_driver_input")
    if isinstance(core_input, str) and core_input:
        core_path = Path(core_input)
        zone_candidate = core_path.with_name("subsidence_zone_plus_uint8.tif")
        context["re_plus_zone_input"] = str(zone_candidate if zone_candidate.is_file() else core_path)
    return context


def profile_path() -> Path | None:
    local = load_local_paths()
    raw = os.getenv("PLUS_V142_UI_PROFILE") or local.get("plus_v142_ui_profile")
    if not isinstance(raw, str) or not raw.strip() or is_unc(raw):
        return None
    return Path(os.path.expandvars(raw)).expanduser().resolve()


def requires_elevation() -> bool:
    """The pinned official executable requests elevation on this Windows build."""
    value = load_local_paths().get("plus_v142_requires_elevation", True)
    return value is not False


def worker_workspace(envelope: dict[str, Any]) -> Path:
    params = envelope.get("parameters", {})
    if envelope.get("operation") == "plus.calibrate":
        raw = params.get("workspace")
        if not isinstance(raw, str) or not raw or is_unc(raw):
            raise ValueError("official HPSCIL PLUS calibration needs a local workspace")
        workspace = Path(raw).expanduser().resolve()
        allowed = os.getenv("MINING_GIS_MCP_WORKSPACE") or os.getenv("MINING_PLUS_OUTPUT_ROOT") or (ROOT / "outputs" / "mcp")
        return require_within(workspace, [Path(allowed).expanduser().resolve()], "PLUS calibration workspace")
    return scenario_paths(envelope)[1]


def elevated_worker(envelope: dict[str, Any]) -> dict[str, Any]:
    """Run this same local bridge at the PLUS process integrity level via UAC.

    The UAC dialog is intentional: it is the Windows-approved boundary that
    lets pywinauto access the vendor application without weakening UAC or
    exposing any control endpoint over the network.
    """
    workspace = worker_workspace(envelope)
    workspace.mkdir(parents=True, exist_ok=True)
    if envelope.get("operation") == "plus.run_scenario":
        scenario, _, expected, _, state_path = scenario_paths(envelope)
        prior = read_json(state_path, {})
        if not isinstance(prior, dict):
            prior = {"bridge": BRIDGE_NAME, "software": SOFTWARE_NAME, "scenario": scenario,
                     "expected_output": str(expected)}
        transition(prior, "waiting_uac", status="waiting_interactive", uac_requested_at=time.time())
        write_json(state_path, prior)
    request_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(envelope.get("request_id") or "plus"))
    request = workspace / f"plus_v142_elevated_request_{request_id}.json"
    reply = workspace / f"plus_v142_elevated_response_{request_id}.json"
    write_json(request, envelope)
    worker = ROOT / "scripts" / "plus_v142_elevated_worker.ps1"
    command = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(worker),
               "-Python", sys.executable, "-Bridge", str(Path(__file__).resolve()), "-Request", str(request),
               "-Response", str(reply)]
    try:
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 encoding="utf-8", errors="replace", timeout=180, check=False)
    except subprocess.TimeoutExpired:
        return response(envelope, "waiting_interactive", outputs=[str(request), str(reply)],
                        lifecycle_status="waiting_uac",
                        message="waiting for the local elevated HPSCIL PLUS worker; approve the Windows UAC prompt if it is visible")
    if reply.is_file():
        result = read_json(reply, {})
        if isinstance(result, dict):
            result.setdefault("outputs", [])
            result["outputs"] = [*result["outputs"], str(request), str(reply)]
            return result
    return response(envelope, "failed", outputs=[str(request)],
                    error=process.stderr.strip() or process.stdout.strip() or "elevated HPSCIL PLUS worker did not write a response")


def load_profile(path: Path | None) -> tuple[dict[str, Any], str | None]:
    if path is None or not path.is_file():
        return {}, None
    payload = read_json(path, {})
    if not isinstance(payload, dict):
        raise ValueError("official HPSCIL PLUS GUI profile must be a JSON object")
    if payload.get("profile_version") != "1.0" or payload.get("software") != SOFTWARE_NAME:
        raise ValueError("official HPSCIL PLUS GUI profile has an unsupported profile version or software identity")
    return payload, sha256(path)


def scenario_steps(profile: dict[str, Any], scenario: str, *, phase: str | None = None) -> list[dict[str, Any]]:
    base = profile.get("steps", [])
    overrides = profile.get("scenario_steps", {})
    extra = overrides.get(scenario, []) if isinstance(overrides, dict) else []
    if not isinstance(base, list) or not isinstance(extra, list):
        raise ValueError("official HPSCIL PLUS GUI profile steps must be lists")
    base_items = [item for item in base if isinstance(item, dict)]
    extra_items = [item for item in extra if isinstance(item, dict)]
    # Scenario-specific controls (notably the RE development-zone mask) must
    # be applied before the shared CARS Run button.  Keeping the insertion
    # point in the profile avoids a second, duplicated GUI workflow.
    if phase == "cars_only":
        # A completed LEAS run can be resumed after the elevated worker or
        # vendor GUI exits.  CARS consumes the six contracted probability
        # bands, so replaying LEAS would overwrite valid bands or repeat an
        # expensive prediction.
        base_items = [item for item in base_items
                      if str(item.get("id", "")).startswith("cars_")
                      or str(item.get("id", "")) in {"close_leas", "open_plus_menu_cars", "open_cars"}]
    if extra_items:
        run_index = next((index for index, item in enumerate(base_items)
                          if str(item.get("id", "")) == "cars_run"), len(base_items))
        steps = [*base_items[:run_index], *extra_items, *base_items[run_index:]]
    else:
        steps = base_items
    identifiers = [str(item.get("id", "")).strip() for item in steps]
    if not steps or not all(identifiers) or len(set(identifiers)) != len(identifiers):
        return []
    return steps


class PlusGui:
    """pywinauto-first controller with an OpenCV screenshot fallback."""

    def __init__(self, process_id: int, profile: dict[str, Any], profile_file: Path | None, artifact_dir: Path):
        try:
            from pywinauto import Desktop  # type: ignore
        except ImportError as error:
            raise GuiAutomationError("install the plus-gui extra: python -m pip install -e .\\mcp_server[validation,plus-gui]") from error
        window_spec = profile.get("window", {}) if isinstance(profile.get("window"), dict) else {}
        backend = str(window_spec.get("backend", "uia"))
        criteria: dict[str, Any] = {"process": process_id}
        for key in ("title", "title_re", "class_name", "control_type", "auto_id"):
            if isinstance(window_spec.get(key), str) and window_spec[key]:
                criteria[key] = window_spec[key]
        self.desktop = Desktop(backend=backend)
        self.process_id = process_id
        self.window = self.desktop.window(**criteria)
        self.window.wait("exists visible ready", timeout=float(window_spec.get("timeout_seconds", 20)))
        # The PLUS snapshot remembers the last monitor position.  In this
        # workstation that position can be on a disconnected display, which
        # leaves the Qt menu/dialog technically visible but unreachable by
        # screen automation.  Bring an off-screen main window back onto the
        # primary desktop before replaying the calibrated sequence.
        try:
            rectangle = self.window.rectangle()
            if rectangle.right <= 0 or rectangle.bottom <= 0:
                import ctypes
                user32 = ctypes.windll.user32
                user32.ShowWindow(int(self.window.handle), 9)  # SW_RESTORE
                user32.SetWindowPos(int(self.window.handle), -1, 80, 80, 0, 0, 0x0001 | 0x0004)
                time.sleep(0.4)
        except Exception:
            pass
        # Qt's screenshot fallback sees the on-screen composition.  Bring the
        # elevated PLUS window forward before collecting a template or clicking
        # a menu so an unrelated foreground app cannot hide the target.
        self.window.set_focus()
        self.profile = profile
        self.profile_file = profile_file
        self.artifact_dir = artifact_dir
        self.backend = backend

    def find_cars_window(self, timeout: float = 10.0):
        """Find the top-level CARS dialog across UIA and Win32 backends.

        The PLUS Qt child dialog is exposed as a Win32 top-level window on
        some machines and as a UIA window on others.  Restricting the search
        to the main UIA Desktop therefore makes a valid dialog look absent.
        """
        from pywinauto import Desktop  # type: ignore
        deadline = time.time() + max(0.5, float(timeout))
        backends = [self.desktop]
        if self.backend.lower() != "win32":
            try:
                backends.append(Desktop(backend="win32"))
            except Exception:
                pass
        while time.time() < deadline:
            for desktop in backends:
                try:
                    candidates = list(desktop.windows(process=self.process_id))
                except Exception:
                    candidates = []
                try:
                    candidates += [item for item in desktop.windows()
                                   if item not in candidates and item.window_text() == "CARS"]
                except Exception:
                    pass
                for item in candidates:
                    try:
                        if item.window_text() == "CARS" and item.is_visible():
                            return item
                    except Exception:
                        continue
            time.sleep(0.25)
        raise GuiAutomationError("CARS window did not become visible within the timeout")

    @staticmethod
    def _uia_criteria(target: dict[str, Any]) -> dict[str, Any]:
        values = target.get("uia", target)
        if not isinstance(values, dict):
            return {}
        allowed = ("title", "title_re", "auto_id", "class_name", "control_type", "best_match", "found_index")
        return {key: value for key, value in values.items() if key in allowed and value not in (None, "")}

    def _control(self, target: dict[str, Any]):
        criteria = self._uia_criteria(target)
        if not criteria:
            raise GuiAutomationError("profile action has no UI Automation selector")
        def direct_match(candidate: Any):
            """Find a Qt control whose UIA properties match exactly.

            Some Qt5 builds expose dotted automation IDs but do not allow
            pywinauto's ``child_window`` resolver to traverse them.  Walking
            the visible tree is slower, but keeps UIA as the primary route
            and also works for top-level LEAS/CARS dialogs.
            """
            for item in [candidate, *candidate.descendants()]:
                try:
                    if "auto_id" in criteria and item.automation_id() != criteria["auto_id"]:
                        continue
                    if "control_type" in criteria and item.element_info.control_type != criteria["control_type"]:
                        continue
                    if "title" in criteria and item.window_text() != criteria["title"]:
                        continue
                    if "title_re" in criteria and not re.search(criteria["title_re"], item.window_text()):
                        continue
                    if "class_name" in criteria and item.class_name() != criteria["class_name"]:
                        continue
                    # ``descendants`` already returns a wrapper.  Calling
                    # wrapper_object() again can fail for Qt proxy edits
                    # even though the control is present and usable.
                    return item
                except Exception:
                    continue
            return None
        try:
            return self.window.child_window(**criteria).wrapper_object()
        except Exception as first_error:
            # Qt popup menus and file dialogs can be sibling windows rather
            # than descendants of the main window.
            # Qt menu popups and modal dialogs are often exposed as top-level
            # UIA windows without the parent process filter.  Search the
            # process-scoped windows first, then visible desktop windows so a
            # menu item such as PLUS -> CARS can be addressed reliably.
            candidates = list(self.desktop.windows(process=self.process_id))
            try:
                candidates += [item for item in self.desktop.windows()
                               if item not in candidates and item.is_visible()]
            except Exception:
                pass
            for candidate in candidates:
                try:
                    found = direct_match(candidate)
                    if found is not None:
                        return found
                    try:
                        return candidate.child_window(**criteria).wrapper_object()
                    except Exception:
                        if "auto_id" in criteria:
                            return candidate.child_window(auto_id=criteria["auto_id"]).wrapper_object()
                        raise
                except Exception:
                    continue
            try:
                write_json(self.artifact_dir / "plus_control_debug.json", {
                    "criteria": criteria,
                    "windows": [candidate.window_text() for candidate in candidates],
                    "matching_candidates": [
                        {"window": candidate.window_text(), "controls": [
                            {"title": item.window_text(), "auto_id": item.automation_id(),
                             "control_type": item.element_info.control_type}
                            for item in candidate.descendants()
                            if (criteria.get("auto_id") is None or item.automation_id() == criteria.get("auto_id"))
                               or (criteria.get("control_type") is None or item.element_info.control_type == criteria.get("control_type"))
                        ]}
                        for candidate in candidates if candidate.window_text() in {"LEAS", "Patch-generating Land Use Simulation (PLUS) Model V1.4.1"}
                    ],
                    "process_id": self.process_id,
                })
            except Exception:
                pass
            raise first_error

    @staticmethod
    def click_screen(point: list[Any]) -> dict[str, Any]:
        if len(point) != 2 or not all(isinstance(value, (int, float)) for value in point):
            raise GuiAutomationError("screen point must contain two numeric coordinates")
        try:
            import ctypes
            ctypes.windll.user32.SetCursorPos(int(point[0]), int(point[1]))
            ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
            ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
            return {"route": "screen_point", "x": int(point[0]), "y": int(point[1])}
        except Exception as error:
            raise GuiAutomationError(f"screen click failed: {error}") from error

    def _image_target(self, target: dict[str, Any]) -> tuple[Path, float]:
        raw = target.get("image") if isinstance(target, dict) else None
        if isinstance(raw, str):
            raw, threshold = {"template": raw}, 0.92
        elif isinstance(raw, dict):
            threshold = float(raw.get("threshold", 0.92))
        else:
            raise GuiAutomationError("no screenshot fallback is configured for this PLUS GUI action")
        template = raw.get("template")
        if not isinstance(template, str) or not template:
            raise GuiAutomationError("screenshot fallback needs image.template")
        root = self.profile_file.parent if self.profile_file else ROOT / "config"
        candidate = (root / template).resolve() if not Path(template).is_absolute() else Path(template).resolve()
        require_within(candidate, [root], "PLUS GUI screenshot template")
        if not candidate.is_file():
            raise GuiAutomationError(f"screenshot template does not exist: {candidate}")
        return candidate, threshold

    def _template_center(self, target: dict[str, Any]) -> tuple[int, int, float]:
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except ImportError as error:
            raise GuiAutomationError("image fallback needs opencv-python-headless and numpy from the plus-gui extra") from error
        template, threshold = self._image_target(target)
        screenshot = np.asarray(self.window.capture_as_image().convert("RGB"))[:, :, ::-1]
        needle = cv2.imread(str(template), cv2.IMREAD_COLOR)
        if needle is None or needle.shape[0] > screenshot.shape[0] or needle.shape[1] > screenshot.shape[1]:
            raise GuiAutomationError(f"invalid PLUS GUI screenshot template: {template}")
        _, score, _, point = cv2.minMaxLoc(cv2.matchTemplate(screenshot, needle, cv2.TM_CCOEFF_NORMED))
        if score < threshold:
            raise GuiAutomationError(f"screenshot template did not meet threshold ({score:.3f} < {threshold:.3f}): {template.name}")
        return point[0] + needle.shape[1] // 2, point[1] + needle.shape[0] // 2, float(score)

    def click(self, target: dict[str, Any]) -> dict[str, Any]:
        window_point = target.get("window_point") if isinstance(target, dict) else None
        if (isinstance(window_point, list) and len(window_point) == 2
                and all(isinstance(value, (int, float)) for value in window_point)):
            # Calibrated menu coordinates are recorded in PLUS window space,
            # not desktop space.  This survives the window being moved or
            # restored beneath another application between runs.
            rectangle = self.window.rectangle()
            return self.click_screen([
                int(rectangle.left + window_point[0]),
                int(rectangle.top + window_point[1]),
            ])
        screen_point = target.get("screen_point") if isinstance(target, dict) else None
        if (isinstance(screen_point, list) and len(screen_point) == 2
                and all(isinstance(value, (int, float)) for value in screen_point)):
            # Screen coordinates are useful for Qt menu popups whose client
            # origin is shifted by a title bar or Windows display scaling.
            return self.click_screen(screen_point)
        point = target.get("point") if isinstance(target, dict) else None
        if (isinstance(point, list) and len(point) == 2 and
                all(isinstance(value, (int, float)) for value in point)):
            self.window.click_input(coords=(int(point[0]), int(point[1])))
            return {"route": "calibrated_point", "x": int(point[0]), "y": int(point[1])}
        try:
            control = self._control(target)
            # QAction-backed Qt menu entries respond more reliably to the UIA
            # Invoke pattern than to a synthesized mouse click.
            if getattr(getattr(control, "element_info", None), "control_type", "") == "MenuItem" \
                    and hasattr(control, "invoke"):
                control.invoke()
            elif getattr(getattr(control, "element_info", None), "control_type", "") == "SplitButton":
                # Windows' file picker exposes its primary Open/Save action as
                # a SplitButton.  The wrapper's default click lands on the
                # arrow half and only opens the drop-down, leaving the modal
                # dialog in front of the PLUS table.  Use the left/main
                # segment explicitly so the selected filename is committed.
                rectangle = control.rectangle()
                x = max(8, min(35, max(1, rectangle.width() // 3)))
                control.click_input(coords=(x, max(1, rectangle.height() // 2)))
            else:
                control.click_input()
            return {"route": "pywinauto", "control": control.window_text()}
        except Exception as selector_error:
            # Qt's native file picker can expose the primary Open action only
            # visually (the SplitButton UIA node disappears on some DPI/Qt
            # combinations).  When the request targets auto_id=1, the active
            # dialog already owns focus after the filename was entered; Enter
            # commits that filename without guessing a screen coordinate.
            uia_target = target.get("uia") if isinstance(target, dict) else None
            if (isinstance(uia_target, dict) and str(uia_target.get("auto_id")) == "1"
                    and str(uia_target.get("control_type", "")) == "SplitButton"):
                try:
                    from pywinauto.keyboard import send_keys  # type: ignore
                    send_keys("{ENTER}")
                    return {"route": "keyboard_primary_open", "selector_error": str(selector_error)}
                except Exception as keyboard_error:
                    selector_error = keyboard_error
            x, y, score = self._template_center(target)
            self.window.click_input(coords=(x, y))
            return {"route": "image", "x": x, "y": y, "score": score, "selector_error": str(selector_error)}

    def set_text(self, target: dict[str, Any], value: str, *, commit: bool = False) -> dict[str, Any]:
        try:
            control = self._control(target)
            control.set_focus()
            try:
                if hasattr(control, "set_edit_text"):
                    control.set_edit_text(value)
                else:
                    raise AttributeError("set_edit_text unavailable")
            except Exception:
                # Qt QLineEdit wrappers sometimes expose set_edit_text but
                # reject it at runtime; keyboard replacement still works.
                control.type_keys("^a{BACKSPACE}" + value, with_spaces=True, set_foreground=True)
            if commit:
                # The PLUS Qt dialogs persist their parameter file from the
                # edited widget's focus-out signal.  set_edit_text changes the
                # visible text but, on some Qt builds, does not emit that
                # signal.  A harmless Tab makes the value part of the LEAS
                # request instead of leaving <Input Feature folder> blank.
                try:
                    control.type_keys("{TAB}", set_foreground=True)
                except Exception:
                    try:
                        from pywinauto.keyboard import send_keys  # type: ignore
                        send_keys("{TAB}")
                    except Exception:
                        pass
            return {"route": "pywinauto", "control": control.window_text(), "committed": commit}
        except Exception as selector_error:
            self.click(target)
            self.window.type_keys("^a{BACKSPACE}" + value, with_spaces=True, set_foreground=True)
            if commit:
                self.window.type_keys("{TAB}", set_foreground=True)
            return {"route": "image", "selector_error": str(selector_error), "committed": commit}

    def select_files_clean(self, target: dict[str, Any], directory: str) -> dict[str, Any]:
        """Select all development-potential TIFFs without relying on Qt labels."""
        folder = Path(directory).expanduser().resolve()
        if is_unc(str(folder)) or not folder.is_dir():
            raise GuiAutomationError(f"PLUS multi-file picker directory does not exist: {folder}")
        self.click(target)
        time.sleep(0.5)
        try:
            dialog = next(item for window in self.desktop.windows(process=self.process_id)
                          for item in window.descendants()
                          if item.window_text().startswith(("Pick", "Open", "鎵撳紑")))
            edit = next(item for item in dialog.descendants()
                        if item.automation_id() == "1148" and item.element_info.control_type == "Edit")
            edit.set_edit_text(str(folder))
            edit.set_focus()
            from pywinauto.keyboard import send_keys  # type: ignore
            send_keys("{ENTER}")
            time.sleep(0.8)
            list_view = next(item for item in dialog.descendants()
                             if item.element_info.control_type in {"List", "Pane"}
                             and (item.automation_id() == "listview" or item.class_name() in {"UIItemsView", "DUIListView"}))
            rectangle = list_view.rectangle()
            self.click_screen([rectangle.left + max(20, min(120, rectangle.width() // 2)),
                               rectangle.top + max(20, min(120, rectangle.height() // 2))])
            import ctypes
            user32 = ctypes.windll.user32
            user32.keybd_event(0x11, 0, 0, 0)
            user32.keybd_event(0x41, 0, 0, 0)
            user32.keybd_event(0x41, 0, 2, 0)
            user32.keybd_event(0x11, 0, 2, 0)
            time.sleep(0.3)
            open_button = next(item for item in dialog.descendants()
                               if item.automation_id() == "1" and item.element_info.control_type == "SplitButton")
            rectangle = open_button.rectangle()
            open_button.click_input(coords=(min(30, max(8, rectangle.width() // 3)),
                                            max(1, rectangle.height() // 2)))
        except Exception as error:
            raise GuiAutomationError(f"PLUS multi-file picker failed: {error}") from error
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                if not any(item.window_text().startswith(("Pick", "Open", "鎵撳紑"))
                           for window in self.desktop.windows(process=self.process_id)
                           for item in window.descendants()):
                    break
            except Exception:
                break
            time.sleep(0.2)
        selected = sorted(folder.glob("development_potential_band_*.tif"))
        if len(selected) < 2:
            raise GuiAutomationError(f"PLUS multi-file picker found fewer than two development-potential bands in {folder}")
        try:
            import rasterio  # type: ignore
            invalid = []
            for item in selected:
                if item.stat().st_size <= 8:
                    invalid.append(f"{item.name}:empty")
                    continue
                with rasterio.open(item) as raster:
                    if raster.count != 1 or raster.width <= 0 or raster.height <= 0:
                        invalid.append(f"{item.name}:invalid-grid")
            if invalid:
                raise GuiAutomationError("PLUS CARS received invalid LEAS bands: " + ", ".join(invalid))
        except GuiAutomationError:
            raise
        except Exception as error:
            raise GuiAutomationError(f"PLUS LEAS band validation failed: {error}") from error
        return {"route": "pywinauto_file_dialog_multiselect", "directory": str(folder), "selected": len(selected)}

    def select_files(self, target: dict[str, Any], directory: str) -> dict[str, Any]:
        """Select all matching TIFFs in an isolated Windows file-picker folder.

        CARS expects one development-potential row per class.  The native
        picker accepts a multi-selection, but typing quoted absolute paths into
        the filename box does not reliably commit them.  Navigate to the
        folder, select its list items with Win32 Ctrl+A, then invoke the main
        half of the Open split button.
        """
        folder = Path(directory).expanduser().resolve()
        if is_unc(str(folder)) or not folder.is_dir():
            raise GuiAutomationError(f"PLUS multi-file picker directory does not exist: {folder}")
        self.click(target)
        time.sleep(0.5)
        try:
            process_windows = list(self.desktop.windows(process=self.process_id))
            dialog = next(item for window in process_windows for item in window.descendants()
                          if item.window_text().startswith(("Pick", "Open", "打开")))
        except StopIteration as error:
            raise GuiAutomationError("PLUS file picker did not open") from error
        try:
            edit = next(item for item in dialog.descendants()
                        if item.automation_id() == "1148" and item.element_info.control_type == "Edit")
            edit.set_edit_text(str(folder))
            edit.set_focus()
            # Qt's directory picker labels the commit button "Select
            # Folder" (or its localized equivalent); Enter only navigates
            # the text box and leaves the dialog open.
            buttons = [item for item in dialog.descendants()
                       if item.element_info.control_type == "Button"]
            accept = next((item for item in buttons
                           if item.window_text().strip().lower() in
                           {"select folder", "choose folder", "选择文件夹", "选择資料夾"}), None)
            if accept is not None:
                accept.click_input()
            else:
                from pywinauto.keyboard import send_keys  # type: ignore
                send_keys("%s")
        except Exception as error:
            raise GuiAutomationError(f"PLUS file picker navigation failed: {error}") from error
        time.sleep(0.8)
        try:
            list_view = next(item for item in dialog.descendants()
                             if item.element_info.control_type in {"List", "Pane"}
                             and (item.automation_id() == "listview" or item.class_name() in {"UIItemsView", "DUIListView"}))
            rectangle = list_view.rectangle()
            self.click_screen([rectangle.left + max(20, min(120, rectangle.width() // 2)),
                               rectangle.top + max(20, min(120, rectangle.height() // 2))])
            import ctypes
            user32 = ctypes.windll.user32
            user32.keybd_event(0x11, 0, 0, 0)  # Ctrl down
            user32.keybd_event(0x41, 0, 0, 0)  # A down
            user32.keybd_event(0x41, 0, 2, 0)  # A up
            user32.keybd_event(0x11, 0, 2, 0)  # Ctrl up
        except Exception as error:
            raise GuiAutomationError(f"PLUS file list multi-selection failed: {error}") from error
        time.sleep(0.3)
        try:
            open_button = next(item for item in dialog.descendants()
                               if item.automation_id() == "1" and item.element_info.control_type == "SplitButton")
            rectangle = open_button.rectangle()
            open_button.click_input(coords=(min(30, max(8, rectangle.width() // 3)),
                                            max(1, rectangle.height() // 2)))
        except Exception as error:
            raise GuiAutomationError(f"PLUS multi-file picker Open failed: {error}") from error
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                process_windows = list(self.desktop.windows(process=self.process_id))
                if not any(item.window_text().startswith(("Pick", "Open", "打开"))
                           for window in process_windows for item in window.descendants()):
                    break
            except Exception:
                break
            time.sleep(0.2)
        selected = sorted(folder.glob("development_potential_band_*.tif"))
        if len(selected) < 2:
            raise GuiAutomationError(f"PLUS multi-file picker found fewer than two development-potential bands in {folder}")
        return {"route": "pywinauto_file_dialog_multiselect", "directory": str(folder), "selected": len(selected)}

    def select_directory(self, target: dict[str, Any], directory: str) -> dict[str, Any]:
        """Use the vendor browse button to commit a directory value.

        LEAS writes ``<Input Featrue folder>`` from the QFileDialog result;
        editing the QLineEdit alone changes only the visible widget on some
        Qt builds.  Navigating the native dialog and pressing Open triggers
        the same signal as a human selection.
        """
        folder = Path(directory).expanduser().resolve()
        if is_unc(str(folder)) or not folder.is_dir():
            raise GuiAutomationError(f"PLUS LEAS feature directory does not exist: {folder}")
        self.click(target)
        time.sleep(0.5)
        screen_error: Exception | None = None
        try:
            from pywinauto.keyboard import send_keys  # type: ignore
            import win32clipboard  # type: ignore
            self.click_screen([900, 585])
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(str(folder))
            finally:
                win32clipboard.CloseClipboard()
            send_keys("^a^v")
            self.click_screen([1160, 615])
            time.sleep(0.8)
            return {"route": "calibrated_screen_directory_dialog", "directory": str(folder)}
        except Exception as error:
            screen_error = error
        try:
            dialog = next(item for window in self.desktop.windows(process=self.process_id)
                          for item in window.descendants()
                          if item.window_text().startswith(("Pick", "Open", "choose", "选择", "鎵撳紑")))
        except StopIteration as error:
            detail = f"; screen fallback: {screen_error!r}" if screen_error else ""
            raise GuiAutomationError("PLUS LEAS directory picker did not open" + detail) from error
        try:
            edit = next(item for item in dialog.descendants()
                        if item.automation_id() == "1148" and item.element_info.control_type == "Edit")
            edit.set_edit_text(str(folder))
            edit.set_focus()
            from pywinauto.keyboard import send_keys  # type: ignore
            send_keys("{ENTER}")
        except Exception as error:
            detail = f"; screen fallback: {screen_error!r}" if screen_error else ""
            raise GuiAutomationError(f"PLUS LEAS directory picker navigation failed: {error!r}{detail}") from error
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                if not any(item.window_text().startswith(("Pick", "Open", "choose", "选择", "鎵撳紑"))
                           for window in self.desktop.windows(process=self.process_id)
                           for item in window.descendants()):
                    break
            except Exception:
                break
            time.sleep(0.2)
        return {"route": "pywinauto_file_dialog_directory", "directory": str(folder)}

    def select(self, target: dict[str, Any], value: str) -> dict[str, Any]:
        try:
            control = self._control(target)
            control.select(value)
            return {"route": "pywinauto", "control": control.window_text()}
        except Exception as selector_error:
            self.click(target)
            self.window.type_keys(value, with_spaces=True, set_foreground=True)
            self.window.type_keys("{ENTER}")
            return {"route": "image", "selector_error": str(selector_error)}

    def menu(self, step: dict[str, Any]) -> dict[str, Any]:
        path = step.get("path")
        if isinstance(path, str) and path:
            parts = [item.strip() for item in path.replace("->", ">>").split(">>") if item.strip()]
            # The Qt QAction for CARS is not reliably exposed to UIA on the
            # pinned build.  Use the calibrated two-click route directly:
            # open PLUS, then click the CARS row in its submenu.  Coordinates
            # are client-relative and therefore remain valid after the main
            # window is restored from an off-screen monitor.
            if parts and parts[-1].upper() == "CARS":
                menu_points = self.profile.get("calibration_menu_points", {}) if isinstance(self.profile, dict) else {}
                submenu_points = self.profile.get("calibration_submenu_points", {}) if isinstance(self.profile, dict) else {}
                root_point = menu_points.get(parts[0]) if isinstance(menu_points, dict) else None
                cars_point = submenu_points.get("CA based on Multiple Random Seeds (CARS)") if isinstance(submenu_points, dict) else None
                if not (isinstance(root_point, list) and len(root_point) == 2
                        and isinstance(cars_point, list) and len(cars_point) == 2):
                    raise GuiAutomationError("PLUS GUI profile has no calibrated PLUS/CARS menu points")
                self.window.set_focus()
                # These calibration points were recorded in desktop space
                # (the PLUS window is normally maximized), not client space.
                self.click_screen(root_point)
                time.sleep(0.4)
                self.click_screen(cars_point)
                self.find_cars_window(timeout=8.0)
                return {"route": "calibrated_menu_points", "path": path,
                        "root": root_point, "submenu": cars_point}
            try:
                self.window.menu_select(path)
                return {"route": "pywinauto_menu", "path": path}
            except Exception:
                # Some Qt5 builds do not expose QMenu actions to
                # ``menu_select``.  Open the top-level menu through its
                # calibrated screen point and use the visible action's
                # mnemonic/first letter, which is stable for the English
                # PLUS interface.
                if parts:
                    if len(parts) == 1:
                        # Qt accepts the standard Alt+letter menu mnemonic
                        # even when QMenu is not exposed to UIA.
                        self.window.type_keys("%" + parts[0][0].lower(), set_foreground=True)
                        return {"route": "keyboard_menu_root", "path": path}
                    points = self.profile.get("calibration_menu_points", {}) if isinstance(self.profile, dict) else {}
                    point = points.get(parts[0]) if isinstance(points, dict) else None
                    if isinstance(point, list) and len(point) == 2:
                        self.window.click_input(coords=(int(point[0]), int(point[1])))
                    else:
                        self.window.child_window(title=parts[0], control_type="MenuItem").click_input()
                    time.sleep(0.3)
                    if len(parts) > 1:
                        self.window.type_keys(parts[-1][0], set_foreground=True)
                        self.window.type_keys("{ENTER}", set_foreground=True)
                        if parts[-1].upper() == "CARS":
                            self.find_cars_window(timeout=5.0)
                        return {"route": "keyboard_menu", "path": path}
        target = step.get("target")
        if not isinstance(target, dict):
            raise GuiAutomationError("menu action needs path or target")
        return self.click(target)

    def capture(self, name: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "window"
        output = self.artifact_dir / f"{safe}.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.window.capture_as_image().save(output)
        except Exception:
            # CARS can rename/reparent the Qt window after Run.  Keep the
            # artifact useful without converting that normal UI transition
            # into a calibration failure.
            captured = False
            try:
                for candidate in self.desktop.windows(process=self.process_id):
                    if candidate.is_visible():
                        candidate.capture_as_image().save(output)
                        captured = True
                        break
            except Exception:
                pass
            if not captured:
                try:
                    from PIL import ImageGrab  # type: ignore
                    ImageGrab.grab().save(output)
                    captured = True
                except Exception:
                    pass
            if not captured:
                raise
        return output

    @staticmethod
    def _control_records(window: Any) -> list[dict[str, Any]]:
        controls: list[dict[str, Any]] = []
        for item in window.descendants():
            try:
                rectangle = item.rectangle()
                controls.append({"title": item.window_text(), "automation_id": item.automation_id(),
                                 "control_type": item.element_info.control_type, "class_name": item.class_name(),
                                 "rectangle": [rectangle.left, rectangle.top, rectangle.right, rectangle.bottom]})
            except Exception:
                continue
        return controls

    def calibration(self, label: str = "plus_v142_calibration") -> dict[str, Any]:
        windows: list[dict[str, Any]] = []
        # Qt occasionally exposes the same dialog twice through UI Automation.
        # A calibration report is an inventory, so one record per visible title
        # is clearer than duplicate copies of the identical control tree.
        seen_titles: set[str] = set()
        candidates = list(self.desktop.windows(process=self.process_id))
        # A Qt menu or dialog can be a separate top-level UIA window. Include
        # visible titled windows while excluding unrelated desktop apps.
        try:
            for candidate in self.desktop.windows():
                if candidate in candidates or not candidate.is_visible():
                    continue
                title = candidate.window_text()
                if title and ("PLUS" in title.upper() or "LEAS" in title.upper()
                              or "CARS" in title.upper()):
                    candidates.append(candidate)
        except Exception:
            pass
        for index, candidate in enumerate(candidates):
            try:
                title = candidate.window_text()
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                safe_title = re.sub(r"[^A-Za-z0-9_.-]+", "_", title).strip("_") or f"window_{index}"
                screenshot = self.artifact_dir / f"{label}_{index}_{safe_title}.png"
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                candidate.capture_as_image().save(screenshot)
                windows.append({"title": title, "screenshot": str(screenshot),
                                "controls": self._control_records(candidate)})
            except Exception:
                continue
        main_controls = self._control_records(self.window)
        main_screenshot = self.capture(label)
        return {"backend": self.backend, "window_title": self.window.window_text(), "screenshot": str(main_screenshot),
                "controls": main_controls, "windows": windows}

    def close_auxiliary_dialogs(self) -> list[str]:
        """Close idle child dialogs before opening another calibration screen."""
        closed: list[str] = []
        main_title = self.window.window_text()
        for candidate in self.desktop.windows(process=self.process_id):
            try:
                title = candidate.window_text()
                if not title or title == main_title or title.lower() in {"progress", "running"}:
                    continue
                candidate.close()
                closed.append(title)
            except Exception:
                continue
        return closed


def execute_steps(gui: PlusGui, steps: list[dict[str, Any]], context: dict[str, Any], completed: list[str],
                  update: Callable[[list[str], str | None], None]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    done = set(completed)
    for step in steps:
        identifier = str(step["id"])
        if identifier in done:
            events.append({"id": identifier, "status": "reused"})
            continue
        action = str(step.get("action", "")).strip().lower()
        target = step.get("target") if isinstance(step.get("target"), dict) else {}
        if action == "click":
            event = gui.click(target)
        elif action == "click_if_present":
            try:
                event = {**gui.click(target), "optional": True}
            except Exception as error:
                event = {"route": "optional_not_present", "optional": True, "error": str(error)}
        elif action == "set_text":
            event = gui.set_text(target, str(render_value(step.get("value", ""), context)),
                                 commit=bool(step.get("commit", False)))
        elif action == "select_files":
            event = gui.select_files_clean(target, str(render_value(step.get("directory", step.get("value", "")), context)))
        elif action == "select_directory":
            event = gui.select_directory(target, str(render_value(step.get("directory", step.get("value", "")), context)))
        elif action == "select":
            event = gui.select(target, str(render_value(step.get("value", ""), context)))
        elif action == "menu":
            event = gui.menu({**step, "path": render_value(step.get("path"), context)})
        elif action == "hotkey":
            gui.window.type_keys(str(render_value(step.get("keys", ""), context)), set_foreground=True)
            event = {"route": "pywinauto", "keys": step.get("keys", "")}
        elif action == "close_dialogs":
            event = {"route": "pywinauto", "closed": gui.close_auxiliary_dialogs()}
        elif action == "screen_type":
            screen_point = target.get("screen_point") if isinstance(target, dict) else None
            relative_point = target.get("point") if isinstance(target, dict) else None
            point = relative_point if isinstance(relative_point, list) else screen_point
            if not (isinstance(point, list) and len(point) == 2):
                raise GuiAutomationError("screen_type needs target.point or target.screen_point")
            # The main PLUS window remains the bridge owner while CARS is a
            # separate Qt top-level dialog.  Bring CARS to the foreground so
            # keyboard input cannot leak into the host terminal or picker.
            cars_rectangle = None
            relative_used = None
            try:
                cars_window = gui.find_cars_window()
                cars_window.set_focus()
                try:
                    import ctypes
                    user32 = ctypes.windll.user32
                    user32.ShowWindow(int(cars_window.handle), 9)  # SW_RESTORE
                    user32.BringWindowToTop(int(cars_window.handle))
                    user32.SetForegroundWindow(int(cars_window.handle))
                except Exception:
                    pass
                rectangle = cars_window.rectangle()
                cars_rectangle = [rectangle.left, rectangle.top, rectangle.right, rectangle.bottom]
                # Qt's QTableWidget reports a client rectangle whose origin
                # does not match the top-level wrapper origin on this DPI
                # scaled build.  Resolve the legacy points against the
                # visible Land Demands stack and send a real screen double
                # click; wrapper-relative input lands in the log pane.
                if isinstance(relative_point, list):
                    stack = next((item for item in cars_window.descendants()
                                  if item.automation_id() == "QtGuiCARS.tabWidget.qt_tabwidget_stackedwidget"), None)
                    if stack is not None:
                        stack_rect = stack.rectangle()
                        column = max(0, min(6, round((int(point[0]) - 480) / 100)))
                        screen_x = int(stack_rect.left + 201 + column * 100)
                        screen_y = int(stack_rect.top + 93)
                    else:
                        screen_x = int(rectangle.left + int(point[0]))
                        screen_y = int(rectangle.top + int(point[1]))
                else:
                    screen_x = int(point[0])
                    screen_y = int(point[1])
                relative_used = [screen_x, screen_y]
                import ctypes
                user32 = ctypes.windll.user32
                user32.SetCursorPos(screen_x, screen_y)
                for _ in range(2):
                    user32.mouse_event(2, 0, 0, 0, 0)
                    user32.mouse_event(4, 0, 0, 0, 0)
                    time.sleep(0.08)
                time.sleep(0.15)
            except Exception:
                gui.click_screen(point)
                time.sleep(0.1)
                gui.click_screen(point)
            try:
                from pywinauto.keyboard import send_keys  # type: ignore
                send_keys("{F2}")
                send_keys("^a{BACKSPACE}", with_spaces=True)
                send_keys(str(render_value(step.get("value", ""), context)), with_spaces=True)
                send_keys("{ENTER}")
            except Exception as error:
                raise GuiAutomationError(f"screen keyboard input failed: {error}") from error
            event = {"route": "uia_cars_relative_keyboard" if isinstance(relative_point, list) else "screen_point_keyboard",
                     "x": int(point[0]), "y": int(point[1]), "cars_rectangle": cars_rectangle,
                     "relative_used": relative_used}
        elif action == "screen_type_absolute":
            point = target.get("point") if isinstance(target, dict) else None
            if not (isinstance(point, list) and len(point) == 2):
                raise GuiAutomationError("screen_type_absolute needs target.point")
            try:
                cars_window = gui.find_cars_window()
                cars_window.set_focus()
                import ctypes
                user32 = ctypes.windll.user32
                user32.ShowWindow(int(cars_window.handle), 9)
                user32.BringWindowToTop(int(cars_window.handle))
                user32.SetForegroundWindow(int(cars_window.handle))
                time.sleep(0.2)
            except Exception as error:
                raise GuiAutomationError(f"CARS window focus failed: {error}") from error
            gui.click_screen([int(point[0]), int(point[1])])
            try:
                from pywinauto.keyboard import send_keys  # type: ignore
                send_keys("{F2}")
                send_keys("^a{BACKSPACE}" + str(render_value(step.get("value", ""), context)), with_spaces=True)
                send_keys("{ENTER}")
            except Exception as error:
                raise GuiAutomationError(f"absolute screen keyboard input failed: {error}") from error
            event = {"route": "screen_point_keyboard_absolute", "x": int(point[0]), "y": int(point[1])}
        elif action == "cars_window_type":
            point = target.get("point") if isinstance(target, dict) else None
            if not (isinstance(point, list) and len(point) == 2
                    and all(isinstance(value, (int, float)) for value in point)):
                raise GuiAutomationError("cars_window_type needs target.point")
            try:
                cars_window = gui.find_cars_window()
                cars_window.set_focus()
                rectangle = cars_window.rectangle()
                screen_x = int(rectangle.left + point[0])
                screen_y = int(rectangle.top + point[1])
                import ctypes
                user32 = ctypes.windll.user32
                user32.ShowWindow(int(cars_window.handle), 9)
                user32.BringWindowToTop(int(cars_window.handle))
                user32.SetForegroundWindow(int(cars_window.handle))
                user32.SetCursorPos(screen_x, screen_y)
                for _ in range(2):
                    user32.mouse_event(2, 0, 0, 0, 0)
                    user32.mouse_event(4, 0, 0, 0, 0)
                    time.sleep(0.08)
                from pywinauto.keyboard import send_keys  # type: ignore
                send_keys("{F2}")
                send_keys("^a{BACKSPACE}", with_spaces=True)
                send_keys(str(render_value(step.get("value", ""), context)), with_spaces=True)
                send_keys("{ENTER}")
                event = {"route": "cars_window_relative_keyboard", "x": screen_x, "y": screen_y,
                         "cars_rectangle": [rectangle.left, rectangle.top, rectangle.right, rectangle.bottom]}
            except Exception as error:
                raise GuiAutomationError(f"CARS window keyboard input failed: {type(error).__name__}: {error!r}") from error
        elif action == "wait":
            # Explicit wait steps are used for an interactive vendor dialog
            # that may need a human-scale pause before a resume/inspection.
            # Keep a generous ceiling while still preventing an accidental
            # unbounded sleep from a malformed profile.
            seconds = min(float(step.get("seconds", 1)), 300.0)
            if seconds < 0:
                raise GuiAutomationError("wait seconds cannot be negative")
            time.sleep(seconds)
            event = {"seconds": seconds}
        elif action == "capture":
            event = {"screenshot": str(gui.capture(identifier))}
        else:
            raise GuiAutomationError(f"unsupported PLUS GUI profile action: {action}")
        if float(step.get("after_seconds", 0)) > 0:
            time.sleep(min(float(step["after_seconds"]), 30.0))
        completed.append(identifier)
        done.add(identifier)
        update(completed, identifier)
        events.append({"id": identifier, "status": "completed", **event})
    return events


def output_validation(expected: Path, reference: str | None) -> dict[str, Any]:
    if not expected.is_file() or expected.stat().st_size <= 8:
        raise ValueError(f"contracted PLUS output does not exist or is empty: {expected}")
    with expected.open("rb") as stream:
        if stream.read(4) not in {b"II*\x00", b"MM\x00*"}:
            raise ValueError("contracted PLUS output is not a TIFF")
    try:
        import rasterio  # type: ignore
    except ImportError as error:
        raise ValueError("GeoTIFF acceptance needs the validation extra (rasterio)") from error
    with rasterio.open(expected) as raster:
        if raster.count != 1 or not raster.crs or raster.width <= 0 or raster.height <= 0:
            raise ValueError("PLUS output lacks a valid single-band spatial raster contract")
        if not (raster.dtypes[0].startswith("int") or raster.dtypes[0].startswith("uint")):
            raise ValueError("PLUS output must use an integer LULC class raster")
        report: dict[str, Any] = {"status": "completed", "output": str(expected), "width": raster.width,
                                  "height": raster.height, "crs": str(raster.crs), "dtype": raster.dtypes[0],
                                  "transform": list(raster.transform)[:6]}
        if reference and Path(reference).is_file():
            with rasterio.open(reference) as master:
                matches = (master.crs == raster.crs and master.width == raster.width and master.height == raster.height
                           and master.transform.almost_equals(raster.transform))
                report["matches_historical_lulc_grid"] = matches
                if not matches:
                    raise ValueError("PLUS output is not aligned with the latest historical LULC grid")
    report_path = expected.with_suffix(expected.suffix + ".validation.json")
    write_json(report_path, report)
    report["report"] = str(report_path)
    return report


def stable_output(expected: Path) -> bool:
    seconds = max(0.0, float(os.getenv("MINING_PLUS_OUTPUT_STABLE_SECONDS", "5")))
    if not expected.is_file() or expected.stat().st_size <= 8:
        return False
    # See plus_backend.adopt_existing_output: Windows can round mtime forward
    # relative to the process clock, so an apparent negative age is treated as
    # zero rather than incorrectly rejecting a zero-second stability request.
    apparent_age = max(0.0, time.time() - expected.stat().st_mtime)
    return apparent_age >= seconds


def adopt_vendor_output(expected: Path, scenario: str) -> Path | None:
    """Adopt PLUS's native ``PLUS_<scenario>Simulation_N.tif`` export.

    The official GUI appends ``Simulation_1`` (and increments the suffix on
    subsequent runs) instead of honoring the bridge contract filename.  A
    successful run must still expose the stable per-scenario contract path;
    copy the newest native export beside it and retain the native file for
    provenance.
    """
    candidates = sorted(expected.parent.glob(f"PLUS_{scenario}Simulation_*.tif"),
                        key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    source = candidates[0]
    if source.resolve() == expected.resolve():
        return source
    import shutil
    shutil.copy2(source, expected)
    return source


def initial_state(scenario: str, expected: Path, identity: dict[str, Any], profile_file: Path | None,
                  profile_digest: str | None) -> dict[str, Any]:
    return {"bridge": BRIDGE_NAME, "software": SOFTWARE_NAME, "scenario": scenario, "status": "prepared",
            "lifecycle_status": "prepared", "lifecycle_states": sorted(GUI_LIFECYCLE_STATES),
            "expected_output": str(expected), "executable_identity": identity,
            "profile": str(profile_file) if profile_file else None, "profile_sha256": profile_digest,
            "completed_steps": [], "attempts": 0, "lifecycle_history": [{"state": "prepared", "at": time.time()}]}


def write_request(envelope: dict[str, Any], identity: dict[str, Any], dry_run: bool) -> tuple[str, Path, Path, Path, dict[str, Any]]:
    scenario, workspace, expected, request, state_path = scenario_paths(envelope)
    workspace.mkdir(parents=True, exist_ok=True)
    profile_file = profile_path()
    profile, digest = load_profile(profile_file)
    state = read_json(state_path, {})
    if not isinstance(state, dict) or state.get("bridge") != BRIDGE_NAME or state.get("scenario") != scenario:
        state = initial_state(scenario, expected, identity, profile_file, digest)
    # Keep the last applied profile hash intact here.  The run method compares
    # it with the requested profile before deciding whether saved GUI steps can
    # safely be reused after an interruption.
    state.update({"expected_output": str(expected), "profile": str(profile_file) if profile_file else None,
                  "requested_profile_sha256": digest, "dry_run": dry_run, "request_file": str(request),
                  "input_files": [str(item) for item in request_context(envelope, scenario, workspace, expected).values()
                                  if isinstance(item, str) and item and item != str(expected)]})
    write_json(request, {"bridge": BRIDGE_NAME, "software": SOFTWARE_NAME, "scenario": scenario,
                         "request": envelope, "expected_output": str(expected), "identity": identity,
                         "profile": str(profile_file) if profile_file else None, "profile_sha256": digest})
    write_json(state_path, state)
    return scenario, workspace, expected, state_path, state


def capabilities(envelope: dict[str, Any]) -> dict[str, Any]:
    installation: dict[str, Any]
    try:
        _, _, installation = configured_installation()
        installed, error = True, None
    except Exception as caught:
        installed, error, installation = False, str(caught), {}
    profile_file = profile_path()
    profile, _ = load_profile(profile_file) if profile_file and profile_file.is_file() else ({}, None)
    return response(envelope, "completed", result={
        "backend": "plus", "software": SOFTWARE_NAME, "mode": "local-gui-automation", "local_only": True,
        "official_remote": OFFICIAL_REMOTE, "pinned_commit": PINNED_COMMIT, "pinned_executable_sha256": PINNED_SHA256,
        "installation_verified": installed, "installation_error": error, "executable_identity": installation,
        "pywinauto_available": importlib.util.find_spec("pywinauto") is not None,
        "image_fallback_available": importlib.util.find_spec("cv2") is not None,
        "profile": str(profile_file) if profile_file else None,
        "profile_calibrated": bool(profile.get("calibrated") is True and scenario_steps(profile, "ND")),
        "operations": ["system.capabilities", "plus.calibrate", "plus.run_scenario"],
        "lifecycle_states": sorted(GUI_LIFECYCLE_STATES),
        "limitations": ["The first run needs a local, version-specific UI calibration profile.",
                        "completed is returned only after the contracted GeoTIFF is written and passes grid checks."],
    })


def calibrate(envelope: dict[str, Any]) -> dict[str, Any]:
    """Open the local window once and save selectors/screenshots without a model run."""
    _, executable, identity = configured_installation()
    params = envelope.get("parameters", {})
    raw_workspace = params.get("workspace")
    if not isinstance(raw_workspace, str) or not raw_workspace or is_unc(raw_workspace):
        raise ValueError("official HPSCIL PLUS calibration needs a local workspace")
    workspace = Path(raw_workspace).expanduser().resolve()
    allowed = os.getenv("MINING_GIS_MCP_WORKSPACE") or os.getenv("MINING_PLUS_OUTPUT_ROOT") or (ROOT / "outputs" / "mcp")
    require_within(workspace, [Path(allowed).expanduser().resolve()], "PLUS calibration workspace")
    profile_file = profile_path()
    profile, _ = load_profile(profile_file)
    open_menu = params.get("open_menu")
    if open_menu is not None and (not isinstance(open_menu, str) or not open_menu.strip()):
        raise ValueError("open_menu must be a non-empty visible PLUS menu title")
    open_menu_item = params.get("open_menu_item")
    if open_menu_item is not None and (not isinstance(open_menu_item, str) or not open_menu_item.strip()):
        raise ValueError("open_menu_item must be a non-empty PLUS command title")
    if open_menu_item is not None and open_menu is None:
        raise ValueError("open_menu_item requires open_menu")
    close_dialogs = params.get("close_auxiliary_dialogs", False)
    if not isinstance(close_dialogs, bool):
        raise ValueError("close_auxiliary_dialogs must be a boolean")
    supplied_pid = params.get("process_id")
    if pid_is_alive(supplied_pid):
        process_id, launch_mode = int(supplied_pid), "attached_existing_gui"
    else:
        process = subprocess.Popen([str(executable)], cwd=str(executable.parent), shell=False)
        process_id, launch_mode = process.pid, "launched_gui"
        time.sleep(min(float(profile.get("startup_wait_seconds", 2)) if profile else 2, 15))
    artifact_dir = workspace / "plus_v142_gui_artifacts"
    closed_dialogs: list[str] = []
    try:
        gui = PlusGui(process_id, profile, profile_file, artifact_dir)
        if close_dialogs:
            closed_dialogs = gui.close_auxiliary_dialogs()
            time.sleep(0.3)
        if isinstance(open_menu, str):
            points = profile.get("calibration_menu_points", {})
            point = points.get(open_menu) if isinstance(points, dict) else None
            target = {"point": point} if isinstance(point, list) else {"uia": {"title": open_menu, "control_type": "MenuItem"}}
            if isinstance(point, list):
                gui.click_screen(point)
            else:
                gui.click(target)
            time.sleep(0.3)
        if isinstance(open_menu_item, str):
            # Qt menu actions are not always descendants of the main window;
            # use the native menu path first, then fall back to a UIA click.
            submenu_points = profile.get("calibration_submenu_points", {}) if isinstance(profile, dict) else {}
            point = submenu_points.get(open_menu_item) if isinstance(submenu_points, dict) else None
            if isinstance(point, list):
                gui.click_screen(point)
            elif isinstance(open_menu, str):
                gui.menu({"path": f"{open_menu}->{open_menu_item}",
                          "target": {"uia": {"title": open_menu_item, "control_type": "MenuItem"}}})
            else:
                gui.click({"uia": {"title": open_menu_item, "control_type": "MenuItem"}})
            time.sleep(0.5)
        # Some PLUS child windows inherit a saved off-screen geometry (the
        # calibration report may show coordinates around -32000). Bring such
        # a window back onto the primary monitor before inventorying controls.
        try:
            for candidate in gui.desktop.windows():
                title = candidate.window_text()
                if title and ("PLUS" in title.upper() or "LEAS" in title.upper()
                              or "CARS" in title.upper()):
                    rect = candidate.rectangle()
                    if rect.right < 0 or rect.bottom < 0:
                        try:
                            candidate.restore()
                        except Exception:
                            pass
                        candidate.move_window(x=80, y=80)
                        try:
                            candidate.maximize()
                        except Exception:
                            pass
                        candidate.set_focus()
        except Exception:
            pass
        label = "plus_v142_calibration"
        if isinstance(open_menu, str):
            label = "plus_v142_menu_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", open_menu)
        if isinstance(open_menu_item, str):
            label += "_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", open_menu_item)
        report = gui.calibration(label)
    except Exception as caught:
        report = {"error": str(caught), "process_id": process_id}
    report.update({"bridge": BRIDGE_NAME, "software": SOFTWARE_NAME, "identity": identity,
                   "process_id": process_id, "launch_mode": launch_mode, "opened_menu": open_menu,
                   "opened_menu_item": open_menu_item, "closed_auxiliary_dialogs": closed_dialogs})
    suffix = "" if not isinstance(open_menu, str) else "_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", open_menu)
    if isinstance(open_menu_item, str):
        suffix += "_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", open_menu_item)
    report_path = artifact_dir / f"plus_v142_calibration{suffix}.json"
    write_json(report_path, report)
    return response(envelope, "waiting_interactive", outputs=[str(report_path)], process_id=process_id,
                    lifecycle_status="calibration_required",
                    message="official HPSCIL PLUS calibration report was written; update the local UI profile, then resume or close the window")


def run_scenario(envelope: dict[str, Any]) -> dict[str, Any]:
    _, executable, identity = configured_installation()
    dry_run = bool(envelope.get("parameters", {}).get("dry_run", False))
    scenario, workspace, expected, state_path, state = write_request(envelope, identity, dry_run)
    # A resumed run starts with a clean error field; the previous exception is
    # retained in the request/state history and must not masquerade as the
    # current attempt's result.
    state.pop("error", None)
    state.pop("reason", None)
    write_json(state_path, state)
    detail = envelope.get("parameters", {}).get("parameters", {})
    detail = detail if isinstance(detail, dict) else {}
    history = [item for item in detail.get("historical_lulc", []) if isinstance(item, str)]
    adopt_vendor_output(expected, scenario)
    if stable_output(expected):
        transition(state, "output_detected", status="running", output_detected_at=time.time())
        write_json(state_path, state)
        validation = output_validation(expected, history[-1] if history else None)
        transition(state, "validated", status="running", validation_status="validated", validation=validation,
                   validated_at=time.time())
        transition(state, "completed", status="completed", completed_at=time.time())
        write_json(state_path, state)
        return response(envelope, "completed", outputs=[str(expected), validation["report"]],
                        result={"landuse_raster": str(expected), "validation": validation},
                        lifecycle_status="completed", message="existing contracted HPSCIL PLUS output passed validation")
    if dry_run:
        return response(envelope, "prepared", outputs=[str(workspace / f"plus_v142_gui_request_{scenario}.json"), str(state_path)],
                        lifecycle_status="prepared", message="official HPSCIL PLUS request and per-scenario GUI state prepared (dry run)")
    profile_file = profile_path()
    profile, digest = load_profile(profile_file)
    previous_pid = state.get("process_id")
    same_profile = state.get("profile_sha256") == digest
    if pid_is_alive(previous_pid) and not same_profile:
        state.update({"status": "waiting_interactive", "lifecycle_status": "calibration_required", "reason": "ui_profile_changed_while_gui_running",
                      "process_id": previous_pid, "updated_at": time.time()})
        write_json(state_path, state)
        return response(envelope, "waiting_interactive", outputs=[str(state_path)], process_id=previous_pid,
                        message="the official HPSCIL PLUS GUI profile changed during a live session; close that window before resuming so the full calibrated sequence can be replayed")
    process_id: int
    if pid_is_alive(previous_pid):
        process_id = int(previous_pid)
        state["resume_mode"] = "attached_existing_gui"
    else:
        process = subprocess.Popen([str(executable)], cwd=str(executable.parent), shell=False)
        process_id = process.pid
        state.update({"process_id": process_id, "attempts": int(state.get("attempts", 0)) + 1,
                      # A restarted desktop application has no reliable UI state.
                      # Reapply the calibrated sequence instead of skipping saved
                      # steps that were completed in a now-closed window.
                      "resume_mode": "restarted_gui", "completed_steps": []})
        time.sleep(min(float(profile.get("startup_wait_seconds", 2)) if profile else 2, 15))
    artifact_dir = workspace / "plus_v142_gui_artifacts"
    transition(state, "running_gui", status="running", process_id=process_id, profile_sha256=digest,
               started_at=state.get("started_at", time.time()), updated_at=time.time())
    write_json(state_path, state)
    try:
        gui = PlusGui(process_id, profile, profile_file, artifact_dir)
        settings = detail.get("plus_settings", {}) if isinstance(detail.get("plus_settings", {}), dict) else {}
        phase = settings.get("phase") if isinstance(settings.get("phase"), str) else None
        steps = scenario_steps(profile, scenario, phase=phase) if profile.get("calibrated") is True else []
        if not steps:
            calibration = gui.calibration()
            calibration_path = artifact_dir / "plus_v142_calibration.json"
            write_json(calibration_path, calibration)
            state.update({"status": "waiting_interactive", "lifecycle_status": "calibration_required", "reason": "ui_profile_not_calibrated",
                          "calibration": str(calibration_path), "process_id": process_id})
            write_json(state_path, state)
            return response(envelope, "waiting_interactive", outputs=[str(state_path), str(calibration_path), calibration["screenshot"]],
                            process_id=process_id, message="HPSCIL PLUS window is ready; calibrate config/plus_v142_ui_profile.json from the saved local control report, then resume")
        completed = list(state.get("completed_steps", [])) if same_profile else []
        def persist(done: list[str], current: str | None) -> None:
            state.update({"status": "running", "lifecycle_status": "running_gui", "process_id": process_id, "completed_steps": done,
                          "current_step": current, "updated_at": time.time()})
            write_json(state_path, state)
        events = execute_steps(gui, steps, request_context(envelope, scenario, workspace, expected), completed, persist)
        screenshot = gui.capture("plus_v142_after_automation")
        state.update({"completed_steps": completed, "automation_events": events, "screenshot": str(screenshot)})
    except Exception as caught:
        # A late-stage Qt dialog failure (for example CARS closing after a
        # rejected demand table) is not a calibration failure.  Keep the
        # resumable handoff state explicit so the next run can attach to a
        # fresh GUI and the user can inspect the saved screenshot/request.
        late_stage = bool(str(state.get("current_step", "")).startswith("cars_") or state.get("completed_steps", []))
        state.update({"status": "waiting_interactive",
                      "lifecycle_status": "waiting_export" if late_stage else "calibration_required",
                      "reason": "gui_automation_needs_attention" if late_stage else "gui_automation_needs_calibration",
                      "error": str(caught), "process_id": process_id, "updated_at": time.time()})
        write_json(state_path, state)
        return response(envelope, "waiting_interactive", outputs=[str(state_path)], process_id=process_id,
                        message=f"HPSCIL PLUS GUI needs local calibration or attention: {caught}")
    native_output = adopt_vendor_output(expected, scenario)
    if native_output is not None:
        state["native_output"] = str(native_output)
        state["contract_output"] = str(expected)
        write_json(state_path, state)
    if stable_output(expected):
        transition(state, "output_detected", status="running", output_detected_at=time.time())
        write_json(state_path, state)
        validation = output_validation(expected, history[-1] if history else None)
        transition(state, "validated", status="running", validation_status="validated", validation=validation,
                   validated_at=time.time())
        transition(state, "completed", status="completed", completed_at=time.time())
        write_json(state_path, state)
        return response(envelope, "completed", outputs=[str(expected), validation["report"]],
                        result={"landuse_raster": str(expected), "validation": validation},
                        lifecycle_status="completed", message="HPSCIL PLUS GUI automation produced and validated the contracted output")
    transition(state, "waiting_export", status="waiting_interactive", reason="awaiting_contracted_output", updated_at=time.time())
    write_json(state_path, state)
    return response(envelope, "waiting_interactive", outputs=[str(state_path)], process_id=process_id,
                    lifecycle_status="waiting_export", message="HPSCIL PLUS GUI steps were submitted; resume after the contracted GeoTIFF is available")


def handle(envelope: dict[str, Any], *, elevated: bool) -> dict[str, Any]:
    if envelope.get("protocol_version") != "1.0":
        return response(envelope, "failed", error="unsupported protocol version")
    operation = envelope.get("operation")
    dry_run = bool(envelope.get("parameters", {}).get("dry_run", False))
    if (not elevated and requires_elevation() and operation in {"plus.calibrate", "plus.run_scenario"}
            and not (operation == "plus.run_scenario" and dry_run)):
        return elevated_worker(envelope)
    if operation == "system.capabilities":
        return capabilities(envelope)
    if operation == "plus.calibrate":
        return calibrate(envelope)
    if operation == "plus.run_scenario":
        return run_scenario(envelope)
    return response(envelope, "failed", error=f"unsupported PLUS operation: {operation}")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--elevated-request", type=Path)
    parser.add_argument("--elevated-response", type=Path)
    args, _ = parser.parse_known_args()
    envelope: dict[str, Any] = {}
    try:
        if bool(args.elevated_request) != bool(args.elevated_response):
            raise ValueError("elevated PLUS worker needs both request and response paths")
        elevated = bool(args.elevated_request)
        envelope = read_json(args.elevated_request, {}) if elevated else json.load(sys.stdin)
        if not isinstance(envelope, dict):
            raise ValueError("PLUS bridge request must be a JSON object")
        result = handle(envelope, elevated=elevated)
        if elevated:
            write_json(args.elevated_response, result)
    except Exception as caught:
        result = response(envelope, "failed", error=str(caught))
        if args.elevated_response:
            write_json(args.elevated_response, result)
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
