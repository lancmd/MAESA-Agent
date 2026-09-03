#!/usr/bin/env python3
"""Create a runnable local project from the files supplied to an agent.

This is intentionally a compiler input builder, not a data downloader.  It
keeps all paths local and makes the classification method explicit: imagery
alone cannot supply either a trained neural model or supervised ROI samples.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from classification_profiles import profile as resolve_classification_profile


TASK_TYPES = {
    "classification_only", "lulc_change_analysis", "plus_only", "invest_only",
    "classification_invest", "ecosystem_service_only", "mapping_only", "full_chain",
}


def _local(path: str | None) -> str | None:
    return str(Path(path).expanduser().resolve()) if path else None


def _object(value: dict[str, Any] | None, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object when supplied")
    return dict(value)


def _classification_accuracy(config: dict[str, Any] | None) -> dict[str, Any]:
    """Build the optional independent-sample accuracy contract."""
    supplied = _object(config, "accuracy_config")
    if not supplied:
        return {"enabled": False}
    result = {
        "enabled": True,
        "reference_field": "reference",
        "prediction_field": "prediction",
        "output": "outputs/validation/lulc_accuracy.json",
        "confusion_matrix": "outputs/validation/lulc_confusion_matrix.csv",
        **supplied,
    }
    if result.get("validation_samples"):
        result["validation_samples"] = _local(str(result["validation_samples"]))
    return result


def _period_training_roi(period: dict[str, Any]) -> str | None:
    """Return a dated ENVI training ROI, accepting ``roi`` as a short alias."""
    training_roi, roi = period.get("training_roi"), period.get("roi")
    if training_roi and roi:
        raise ValueError("an imagery period may use training_roi or roi, not both")
    value = training_roi or roi
    if value is not None and not isinstance(value, str):
        raise ValueError("imagery period training_roi must be a local path string")
    return value


def _period_accuracy(period: dict[str, Any], year: int) -> dict[str, Any] | None:
    """Normalise one dated independent-validation contract.

    Keeping the contract on the imagery item lets six-date projects retain the
    provenance of the particular reference samples used for each image.  The
    direct ``validation_samples`` member is deliberately retained as a compact
    input form for agents that do not need to override the default fields.
    """
    raw = period.get("accuracy")
    shorthand = period.get("validation_samples")
    if raw is None and shorthand is None:
        return None
    if raw is None:
        raw = {"validation_samples": shorthand}
    if not isinstance(raw, dict):
        raise ValueError("imagery period accuracy must be an object when supplied")
    if shorthand is not None and raw.get("validation_samples") not in {None, shorthand}:
        raise ValueError("imagery period validation_samples conflicts with accuracy.validation_samples")
    result = {
        "enabled": True,
        "reference_field": "reference",
        "prediction_field": "prediction",
        "output": "outputs/validation/lulc_accuracy_{year}.json",
        "confusion_matrix": "outputs/validation/lulc_confusion_matrix_{year}.csv",
        **raw,
    }
    if shorthand is not None:
        result["validation_samples"] = shorthand
    if result.get("validation_samples"):
        result["validation_samples"] = _local(str(result["validation_samples"]))
    return result


def _period_sensor_profile(period: dict[str, Any], classification_sensor: str | None,
                           envi_method: str, scheme: str) -> dict[str, Any]:
    """Normalise a dated ENVI sensor/method pair into a canonical profile."""
    period_sensor = period.get("sensor")
    if period_sensor is not None and (not isinstance(period_sensor, str) or not period_sensor.strip()):
        raise ValueError("imagery period sensor must be a non-empty string")
    if classification_sensor is not None and (not isinstance(classification_sensor, str) or not classification_sensor.strip()):
        raise ValueError("classification_sensor must be a non-empty string")
    sensor = period_sensor or classification_sensor
    if not sensor:
        raise ValueError("ENVI classification requires classification_sensor or imagery_periods[*].sensor")
    period_method = period.get("envi_method", envi_method)
    if not isinstance(period_method, str) or not period_method.strip():
        raise ValueError("imagery period envi_method must be a non-empty string")
    try:
        return resolve_classification_profile(sensor, period_method, scheme)
    except ValueError as error:
        raise ValueError(str(error)) from error


def _invest_model_config(models: dict[str, Any] | None, enabled: bool) -> dict[str, Any]:
    """Normalise agent-supplied InVEST model settings without inventing a model.

    Carbon remains the useful default for a full-chain project.  Supplying an
    explicit ``invest_models`` object, however, is an instruction to use that
    selection verbatim.  This lets an ``invest_only`` project run Annual Water
    Yield and Habitat Quality without also asking for a carbon-density table.
    """
    if not enabled:
        return {}
    if models is None:
        return {"carbon": {"enabled": True, "service_unit": "Mg C"}}
    if not isinstance(models, dict) or not models:
        raise ValueError("invest_models must be a non-empty object when InVEST is enabled")
    result: dict[str, Any] = {}
    for name, value in models.items():
        if not isinstance(name, str) or not name or not isinstance(value, dict):
            raise ValueError("each invest_models entry requires a model name and an object")
        item = dict(value)
        for key in ("datastack_template", "provided_datastack"):
            if item.get(key):
                item[key] = _local(str(item[key]))
        builder = item.get("datastack_builder")
        if isinstance(builder, str) and builder:
            item["datastack_builder"] = _local(builder)
        elif isinstance(builder, dict):
            item["datastack_builder"] = dict(builder)
            for key in ("config", "config_file"):
                if item["datastack_builder"].get(key):
                    item["datastack_builder"][key] = _local(str(item["datastack_builder"][key]))
        result[name] = item
    if not any(item.get("enabled") for item in result.values()):
        raise ValueError("invest_models must enable at least one model")
    return result


def build(project_file: Path, project_id: str, workspace: str, imagery_periods: list[dict[str, Any]] | None = None,
          driver_factors: dict[str, Any] | None = None, mine_boundary: str | None = None,
          carbon_density: str | None = None, *, task_type: str = "full_chain",
          historical_lulc_periods: list[dict[str, Any]] | None = None,
          ecosystem_criteria: str | None = None, ecosystem_config: str | None = None,
          gis_outputs: dict[str, Any] | None = None, w_dat: str | None = None,
          model_package: str | None = None, training_roi: str | None = None, scheme: str = "high_water_coal_7class",
          w_dat_unit: str | None = None, w_dat_convention: str | None = None,
          workface_boundary: str | None = None, w_dat_max_distance_m: float = 300.0,
          subsidence_depth_raster: str | None = None, patch_size: int | None = None,
          patch_stride: int | None = None, patch_band_indexes: list[int] | None = None,
          patch_input_scale: float | None = None, patch_batch_size: int | None = None,
          allow_patch_grid_as_lulc: bool = False, invest_models: dict[str, Any] | None = None,
          accuracy_config: dict[str, Any] | None = None, ecosystem_service_config: dict[str, Any] | None = None,
          subsidence_water_config: dict[str, Any] | None = None, subsidence_water_boundary: str | None = None,
          aquatic_vegetation_boundary: str | None = None, bottom_sediment_boundary: str | None = None,
          elevation_vertical_datum: str | None = None, water_level_vertical_datum: str | None = None,
          water_surface_elevation_m: float | None = None, classification_sensor: str | None = None,
          envi_method: str = "maximum_likelihood") -> dict[str, Any]:
    if task_type not in TASK_TYPES:
        raise ValueError("task_type must be one of " + ", ".join(sorted(TASK_TYPES)))
    imagery_periods = imagery_periods or []
    historical_lulc_periods = historical_lulc_periods or []
    driver_factors = driver_factors or {}
    requires_classification = task_type in {"classification_only", "classification_invest", "full_chain"}
    requires_history = task_type in {"lulc_change_analysis", "plus_only"}
    requires_plus = task_type in {"plus_only", "full_chain"}
    if requires_classification and not imagery_periods:
        raise ValueError(f"{task_type} requires one or more dated imagery_periods")
    if requires_plus and len(imagery_periods if requires_classification else historical_lulc_periods) < 2:
        raise ValueError(f"{task_type} requires at least two dated LULC sources")
    if requires_history and len(historical_lulc_periods) < 2:
        raise ValueError(f"{task_type} requires at least two historical_lulc_periods")
    if task_type == "invest_only" and not historical_lulc_periods:
        raise ValueError("invest_only requires at least one historical_lulc_period")
    if task_type == "ecosystem_service_only" and (not ecosystem_criteria or not ecosystem_config):
        raise ValueError("ecosystem_service_only requires ecosystem_criteria and ecosystem_config")
    if task_type == "mapping_only" and not isinstance(gis_outputs, dict):
        raise ValueError("mapping_only requires a gis_outputs object")
    if scheme not in {"standard_6class", "mining_water_6class", "high_water_coal_7class"}:
        raise ValueError("scheme must be standard_6class, mining_water_6class, or high_water_coal_7class")
    native_patch_model = bool(model_package and (Path(model_package).expanduser() / "model" / "model.json").is_file())
    if native_patch_model and scheme == "high_water_coal_7class":
        # This model has one water class, so high-water seven-class output would be false precision.
        scheme = "standard_6class"
    uses_envi = requires_classification and not model_package
    normalized_periods: list[dict[str, Any]] = []
    for item in imagery_periods:
        if not isinstance(item, dict) or not isinstance(item.get("year"), int) or not isinstance(item.get("path"), str):
            raise ValueError("each imagery period requires integer year and local path")
        normalized = dict(item)
        normalized["path"] = _local(item["path"])
        if uses_envi:
            resolved_profile = _period_sensor_profile(item, classification_sensor, envi_method, scheme)
            normalized["sensor"] = resolved_profile["sensor_id"]
            normalized["envi_method"] = resolved_profile["classification_method"]["method"]
        else:
            normalized.pop("envi_method", None)
        period_roi = _period_training_roi(item)
        normalized.pop("roi", None)
        if period_roi:
            normalized["training_roi"] = _local(period_roi)
        else:
            normalized.pop("training_roi", None)
        period_accuracy = _period_accuracy(item, item["year"])
        normalized.pop("validation_samples", None)
        if period_accuracy is not None:
            normalized["accuracy"] = period_accuracy
        else:
            normalized.pop("accuracy", None)
        normalized_periods.append(normalized)
    normalized_periods.sort(key=lambda item: item["year"])
    period_rois = [item.get("training_roi") for item in normalized_periods]
    if requires_classification:
        if model_package and (training_roi or any(period_rois)):
            raise ValueError("classification uses either model_package (PyTorch) or global/dated ENVI training ROI, not both")
        if not model_package and not training_roi and not all(period_rois):
            raise ValueError("ENVI classification needs training_roi globally or in every imagery period")
    if task_type == "classification_invest":
        missing_accuracy = [str(item["year"]) for item in normalized_periods
                            if not (isinstance(item.get("accuracy"), dict) and item["accuracy"].get("enabled"))]
        if missing_accuracy:
            raise ValueError("classification_invest requires independent accuracy configuration for every imagery period: " + ", ".join(missing_accuracy))
    normalized_lulc: list[dict[str, Any]] = []
    for item in historical_lulc_periods:
        if not isinstance(item, dict) or not isinstance(item.get("year"), int) or not isinstance(item.get("path"), str):
            raise ValueError("each historical LULC period requires integer year and local path")
        normalized_lulc.append({"year": item["year"], "path": _local(item["path"])})
    normalized_lulc.sort(key=lambda item: item["year"])
    invest_enabled = task_type in {"invest_only", "classification_invest", "full_chain"}
    normalized_invest_models = _invest_model_config(invest_models, invest_enabled)
    accuracy = _classification_accuracy(accuracy_config)
    ecosystem_options = _object(ecosystem_service_config, "ecosystem_service_config")
    subsidence_options = _object(subsidence_water_config, "subsidence_water_config")
    ecosystem_enabled = task_type == "ecosystem_service_only" or (task_type == "full_chain" and bool(ecosystem_config))
    if ecosystem_options.get("enabled") is not None:
        ecosystem_enabled = bool(ecosystem_options["enabled"])
    subsidence_enabled = bool(subsidence_options)
    if subsidence_options.get("enabled") is not None:
        subsidence_enabled = bool(subsidence_options["enabled"])
    factor_paths = [value.get("path") if isinstance(value, dict) else value for value in driver_factors.values()]
    invest_datastacks = [item.get(key) for item in normalized_invest_models.values() if isinstance(item, dict)
                         for key in ("datastack_template", "provided_datastack") if item.get(key)]
    habitat_builder_configs = [
        builder if isinstance(builder, str) else builder.get("config") or builder.get("config_file")
        for item in normalized_invest_models.values() if isinstance(item, dict)
        for builder in [item.get("datastack_builder")]
        if isinstance(builder, (str, dict))
    ]
    roots = sorted({str(Path(value).expanduser().resolve().parent) for value in [
        *[item["path"] for item in normalized_periods], *[item["path"] for item in normalized_lulc],
        *[item.get("training_roi") for item in normalized_periods],
        *[item.get("accuracy", {}).get("validation_samples") for item in normalized_periods if isinstance(item.get("accuracy"), dict)],
        *factor_paths,
        mine_boundary, carbon_density, ecosystem_criteria, ecosystem_config, w_dat, subsidence_depth_raster,
        model_package, training_roi, workface_boundary, subsidence_water_boundary, aquatic_vegetation_boundary,
        bottom_sediment_boundary, accuracy.get("validation_samples"), *invest_datastacks, *habitat_builder_configs] if value})
    if isinstance(gis_outputs, dict):
        for key in ("aprx",):
            if gis_outputs.get(key):
                roots.append(str(Path(str(gis_outputs[key])).expanduser().resolve().parent))
        for layer in gis_outputs.get("layers", []) if isinstance(gis_outputs.get("layers", []), list) else []:
            if isinstance(layer, dict):
                for key in ("path", "symbology_layer"):
                    if layer.get(key) and layer.get("source", "input") == "input":
                        roots.append(str(Path(str(layer[key])).expanduser().resolve().parent))
    project_root = project_file.expanduser().resolve().parent
    roots = sorted(set(roots)) or [str(project_root)]
    latest_year = (normalized_periods or normalized_lulc or [{"year": 0}])[-1]["year"]
    inputs: dict[str, Any] = {
        "imagery_periods": normalized_periods, "imagery": [], "mine_boundary": _local(mine_boundary),
        "carbon_density": _local(carbon_density), "historical_lulc": [item["path"] for item in normalized_lulc],
        "lulc_baseline": normalized_lulc[-1]["path"] if normalized_lulc else None,
        "model_package": _local(model_package), "training_roi": _local(training_roi), "subsidence_w_dat": _local(w_dat),
        "subsidence_depth_raster": _local(subsidence_depth_raster),
        "dem": _local(driver_factors.get("dem", {}).get("path") if isinstance(driver_factors.get("dem"), dict) else driver_factors.get("dem")),
        "workface_boundary": _local(workface_boundary), "subsidence_water_boundary": _local(subsidence_water_boundary),
        "aquatic_vegetation_boundary": _local(aquatic_vegetation_boundary), "bottom_sediment_boundary": _local(bottom_sediment_boundary),
        "elevation_vertical_datum": elevation_vertical_datum, "water_level_vertical_datum": water_level_vertical_datum,
        "water_surface_elevation_m": water_surface_elevation_m,
        "driver_factors": {key: ({**value, "path": _local(value.get("path"))} if isinstance(value, dict) else _local(value))
                           for key, value in driver_factors.items()},
    }
    ecosystem_payload = {"enabled": ecosystem_enabled, "method": "minmax", "criteria_table": _local(ecosystem_criteria),
                         "config": _local(ecosystem_config), **ecosystem_options}
    subsidence_payload = {"enabled": subsidence_enabled, "mode": "classify_only", **subsidence_options}
    if water_level_vertical_datum and "water_level_vertical_datum" not in subsidence_payload:
        subsidence_payload["water_level_vertical_datum"] = water_level_vertical_datum
    gis_payload = {"enabled": task_type == "mapping_only" or bool(gis_outputs), **(gis_outputs or {})}
    payload: dict[str, Any] = {
        "schema_version": 2, "project_id": project_id, "task_type": task_type, "workspace": workspace,
        "security": {"input_roots": roots, "output_root": str((project_root / workspace).resolve().parent)},
        "inputs": inputs,
        "classification": {"enabled": requires_classification, "engine": "pytorch" if model_package else ("envi" if requires_classification else "provided_lulc"), "scheme": scheme,
                           "output_lulc": "outputs/lulc/LULC_{year}.tif", "output_confidence": "outputs/lulc/confidence_{year}.tif",
                           "sensor": (resolve_classification_profile(classification_sensor, envi_method, scheme)["sensor_id"]
                                      if uses_envi and classification_sensor else None),
                           "envi_method": envi_method, "accuracy": accuracy,
                           "patch_classifier": {"enabled": native_patch_model, "patch_size": patch_size, "stride": patch_stride,
                                                "band_indexes": patch_band_indexes, "input_scale": patch_input_scale,
                                                "batch_size": patch_batch_size, "allow_as_lulc": bool(allow_patch_grid_as_lulc)}},
        "plus": {"enabled": requires_plus,
                 "baseline_year": latest_year, "target_year": latest_year + 5,
                 "scenarios": ["ND", "UD", "EP", "RE"], "output_workspace": "outputs/plus",
                 "resource_extraction": {"core_driver": "subsidence_depth", "core_driver_input": "inputs.subsidence_depth_raster",
                     "core_driver_unit": "m", "core_driver_convention": "positive_down", "requires_master_grid_alignment": True,
                     "additional_driver_factors": [name for name in ("dem", "slope", "road_distance", "mine_distance") if driver_factors.get(name)],
                     "w_dat_preprocessing": {"source_unit": w_dat_unit, "source_convention": w_dat_convention,
                         "output_depth_unit": "m", "output_depth_convention": "positive_down",
                         "interpolation": "nearest_within_scope", "scope_vector": _local(workface_boundary) or _local(mine_boundary),
                         "max_interpolation_distance_m": w_dat_max_distance_m}}},
        "invest": {"enabled": invest_enabled, "output_workspace": "outputs/invest", "models": normalized_invest_models},
        "subsidence_water": subsidence_payload,
        "ecosystem_service": ecosystem_payload,
        "gis_outputs": gis_payload,
        "validation": {"enabled": True, "output_report": "validation/analysis_validation_report.json"},
    }
    if normalized_lulc:
        inputs["historical_lulc_periods"] = normalized_lulc
    project_file = project_file.expanduser().resolve(); project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "completed", "project_file": str(project_file), "project_id": project_id,
            "task_type": task_type, "classification_engine": payload["classification"]["engine"],
            "model_mode": "registered_resnet50_patch_classifier" if native_patch_model else "segmentation_or_envi",
            "imagery_years": [item["year"] for item in normalized_periods],
            "pending_inputs": (["choose_one_subsidence_input"] if w_dat and subsidence_depth_raster else []) +
                              (["w_dat_unit_and_convention"] if w_dat and (not w_dat_unit or not w_dat_convention) else []) +
                              (["w_dat_max_distance_m"] if w_dat and (not isinstance(w_dat_max_distance_m, (int, float)) or w_dat_max_distance_m <= 0) else []) +
                              (["resnet50_patch_size_stride_rgb_scale"] if native_patch_model and
                               (not isinstance(patch_size, int) or not isinstance(patch_stride, int) or
                                not isinstance(patch_band_indexes, list) or not isinstance(patch_input_scale, (int, float))) else []) +
                              (["resnet50_patch_grid_lulc_confirmation_and_accuracy"] if native_patch_model and task_type in {"full_chain", "classification_invest"} else []) +
                              (["invest_model_datastack"] if any(item.get("enabled") and name != "carbon" and
                                                                   not (item.get("datastack_template") or item.get("provided_datastack") or
                                                                        (name == "habitat_quality" and item.get("datastack_builder")))
                                                                   for name, item in normalized_invest_models.items()) else []) +
                              (["independent_lulc_validation_samples"] if task_type == "full_chain" and not accuracy.get("enabled") else []) +
                              (["ecosystem_service_config"] if task_type == "full_chain" and not ecosystem_enabled else []) +
                              (["gis_layout_config"] if task_type == "full_chain" and not gis_payload.get("enabled") else [])}


def preflight_build_arguments(project_id: str, workspace: str, **arguments: Any) -> dict[str, Any]:
    """Check a project-build request without creating the requested project.

    Natural-language project creation needs to reject a plan *before* the user
    confirms a write to ``output_project``.  The builder alone only knows how
    to assemble a JSON document; some requirements (for example a Carbon
    density table for the default Carbon model) are checked by the project
    validator.  This helper deliberately exercises both layers in a temporary
    directory, so it stays in lockstep with the real MCP build path while
    leaving the selected workspace and output target untouched.
    """
    if not isinstance(project_id, str) or not project_id.strip():
        return {"status": "invalid", "errors": ["project_id must be a non-empty string"], "pending_inputs": []}
    if not isinstance(workspace, str) or not workspace.strip():
        return {"status": "invalid", "errors": ["workspace must be a non-empty string"], "pending_inputs": []}

    # Import lazily: project_validator is intentionally a downstream contract
    # and normal builder callers do not need to import its GIS dependencies.
    from project_validator import validate  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="maesa-project-preflight-") as temporary:
        preview_project = Path(temporary) / "project.json"
        try:
            build_report = build(preview_project, project_id.strip(), workspace, **arguments)
        except (OSError, TypeError, ValueError) as caught:
            return {"status": "invalid", "errors": [str(caught)], "pending_inputs": []}
        validation = validate(preview_project)
        errors = list(validation.get("errors", []))
        payload = json.loads(preview_project.read_text(encoding="utf-8"))
        pending_inputs = list(build_report.get("pending_inputs", []))
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": list(validation.get("warnings", [])),
        "pending_inputs": pending_inputs,
        "task_type": payload.get("task_type"),
    }
