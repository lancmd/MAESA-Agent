"""Local file-system guardrails for project and workflow execution."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


class PathSafetyError(ValueError):
    """Raised when a project path escapes its declared local boundary."""


def is_unc(value: str | os.PathLike[str]) -> bool:
    text = str(value).strip()
    return text.startswith("\\\\") or text.startswith("//")


def resolved(value: str | os.PathLike[str], base: Path) -> Path:
    if is_unc(value):
        raise PathSafetyError(f"UNC/network paths are not allowed: {value}")
    candidate = Path(os.path.expandvars(str(value))).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()


def within(path: Path, roots: Iterable[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root.resolve())
            return True
        except ValueError:
            pass
    return False


def require_within(path: Path, roots: Iterable[Path], label: str) -> Path:
    checked_roots = [root.resolve() for root in roots]
    if not checked_roots or not within(path, checked_roots):
        options = ", ".join(map(str, checked_roots)) or "<none>"
        raise PathSafetyError(f"{label} is outside the allowed local roots: {path} (allowed: {options})")
    return path


def resolve_input(value: str, project_dir: Path, input_roots: Iterable[Path]) -> Path:
    path = resolved(value, project_dir)
    return require_within(path, input_roots, "input")


def resolve_output(value: str, workspace: Path) -> Path:
    path = resolved(value, workspace)
    return require_within(path, [workspace], "output")


ARCGIS_OUTPUT_KEYS = {
    "output", "water_depth_output", "volume_table", "aquatic_vegetation_output", "bottom_sediment_output",
    "carbon_table", "aprx_output", "validation_output", "pdf", "png",
}


def validate_arcgis_spec_outputs(spec: dict, workspace: Path, allow_overwrite: bool = False) -> None:
    """Reject ArcGIS operation specifications that write beyond the local workspace."""
    environment = spec.get("environment", {})
    if isinstance(environment, dict) and environment.get("overwriteOutput") and not allow_overwrite:
        raise PathSafetyError("ArcGIS overwriteOutput requires an explicit workflow overwrite confirmation")
    operations = spec.get("operations", [])
    if not isinstance(operations, list):
        return
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        for key in ARCGIS_OUTPUT_KEYS:
            value = operation.get(key)
            if isinstance(value, str) and value:
                resolve_output(value, workspace)
