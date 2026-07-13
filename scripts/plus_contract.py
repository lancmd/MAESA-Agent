"""One canonical contract for the PLUS resource-extraction (RE) scenario."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


CANONICAL_RE_KEYS = (
    "core_driver",
    "core_driver_input",
    "core_driver_unit",
    "core_driver_convention",
    "requires_master_grid_alignment",
    "additional_driver_factors",
)


def normalize_re_contract(resource: dict[str, Any], subsidence_depth_raster: str | None,
                          resolver: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Resolve the project shorthand to the bridge-facing RE contract.

    Project files may use the literal ``inputs.subsidence_depth_raster``.  A
    bridge always receives the resolved TIFF path in ``core_driver_input``.
    """
    if not isinstance(resource, dict):
        raise ValueError("RE requires plus.resource_extraction as an object")
    value = resource.get("core_driver_input")
    if value == "inputs.subsidence_depth_raster":
        value = subsidence_depth_raster
    if not isinstance(value, str) or not value.strip():
        raise ValueError("RE requires core_driver_input (or inputs.subsidence_depth_raster)")
    result = dict(resource)
    result["core_driver_input"] = resolver(value) if resolver else value
    return result


def re_contract_errors(resource: dict[str, Any], *, project_shorthand_allowed: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(resource, dict):
        return ["RE requires plus.resource_extraction configuration"]
    if resource.get("core_driver") != "subsidence_depth":
        errors.append("RE core_driver must be subsidence_depth")
    value = resource.get("core_driver_input")
    accepted_shorthand = project_shorthand_allowed and value == "inputs.subsidence_depth_raster"
    if not accepted_shorthand and (not isinstance(value, str) or not value.strip()):
        errors.append("RE core_driver_input must be the aligned subsidence-depth raster")
    if resource.get("core_driver_unit") != "m":
        errors.append("RE core_driver_unit must be m")
    if resource.get("core_driver_convention") != "positive_down":
        errors.append("RE core_driver_convention must be positive_down")
    if resource.get("requires_master_grid_alignment") is not True:
        errors.append("RE requires_master_grid_alignment must be true")
    additional = resource.get("additional_driver_factors")
    if not isinstance(additional, list) or not all(isinstance(item, str) and item for item in additional):
        errors.append("RE additional_driver_factors must contain one or more declared drivers")
    return errors


def canonical_re_contract(resource: dict[str, Any], subsidence_depth_raster: str | None,
                          resolver: Callable[[str], str] | None = None) -> dict[str, Any]:
    result = normalize_re_contract(resource, subsidence_depth_raster, resolver)
    errors = re_contract_errors(result)
    if errors:
        raise ValueError("; ".join(errors))
    return result


def expected_plus_raster(output_directory: str | Path, scenario: str) -> Path:
    return Path(output_directory) / f"PLUS_{scenario.strip().upper()}.tif"
