#!/usr/bin/env python3
"""Validate the enabled parts of a local mining-area analysis project."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from path_safety import PathSafetyError, resolved, require_within, resolve_input
from plus_contract import re_contract_errors


REQUIRED_CARBON_COLUMNS = {"lucode", "c_above", "c_below", "c_soil", "c_dead"}
VALID_ENGINES = {"envi", "pytorch", "provided_lulc"}
VALID_ECOSYSTEM_METHODS = {"minmax", "ahp"}
VALID_PLUS_SCENARIOS = {"ND", "UD", "EP", "RE"}
VALID_SUBSIDENCE_WATER_MODES = {"classify_only", "estimate_volume", "composite_subsidence_water_carbon"}
VALID_INVEST_MODELS = {"carbon", "annual_water_yield", "habitat_quality", "sediment_delivery_ratio", "nutrient_delivery_ratio"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def security_roots(project: dict[str, Any], base: Path, errors: list[str]) -> tuple[list[Path], Path, Path]:
    security = project.get("security", {})
    if not isinstance(security, dict):
        errors.append("security must be an object")
        security = {}
    raw_inputs = security.get("input_roots", ["."])
    if not isinstance(raw_inputs, list) or not raw_inputs:
        errors.append("security.input_roots must be a non-empty list")
        raw_inputs = ["."]
    roots: list[Path] = []
    for value in raw_inputs:
        try:
            roots.append(resolved(str(value), base))
        except PathSafetyError as error:
            errors.append(str(error))
    try:
        output_root = resolved(str(security.get("output_root", ".")), base)
        workspace = resolved(str(project.get("workspace", "")), base)
        require_within(workspace, [output_root], "workspace")
    except PathSafetyError as error:
        errors.append(str(error))
        output_root, workspace = base, base / "runtime"
    return roots, output_root, workspace


def required_path(label: str, value: str | None, base: Path, input_roots: list[Path], errors: list[str]) -> Path | None:
    if not value or "replace_" in str(value):
        errors.append(f"missing required input: {label}")
        return None
    try:
        path = resolve_input(str(value), base, input_roots)
    except PathSafetyError as error:
        errors.append(f"{label}: {error}")
        return None
    if not path.exists():
        errors.append(f"input does not exist: {label} = {path}")
    return path


def optional_path(label: str, value: str | None, base: Path, input_roots: list[Path], errors: list[str]) -> Path | None:
    return required_path(label, value, base, input_roots, errors) if value else None


def validate_carbon_table(path: Path | None, errors: list[str]) -> None:
    if path is None or not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            header = set((csv.DictReader(stream).fieldnames or []))
        missing = REQUIRED_CARBON_COLUMNS - header
        if missing:
            errors.append(f"carbon density table misses columns: {', '.join(sorted(missing))}")
    except Exception as error:
        errors.append(f"cannot read carbon density table: {error}")


def lulc_needed(classification: dict[str, Any], plus: dict[str, Any], invest: dict[str, Any]) -> bool:
    return bool(classification.get("enabled") or (invest.get("enabled") and not plus.get("enabled")))


def validate(project_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    project = load_json(project_path)
    base = project_path.parent
    if project.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if not project.get("project_id") or project.get("project_id") == "replace_me":
        errors.append("project_id must be set")
    input_roots, output_root, workspace = security_roots(project, base, errors)
    inputs = project.get("inputs", {})
    if not isinstance(inputs, dict):
        errors.append("inputs must be an object")
        inputs = {}
    classification = project.get("classification", {})
    plus = project.get("plus", {})
    invest = project.get("invest", {})
    subsidence = project.get("subsidence_water", {})
    ecosystem = project.get("ecosystem_service", {})
    gis_outputs = project.get("gis_outputs", {})
    validation = project.get("validation", {})

    if classification.get("enabled"):
        engine = classification.get("engine")
        if engine not in VALID_ENGINES:
            errors.append(f"classification.engine must be one of {sorted(VALID_ENGINES)}")
        imagery = inputs.get("imagery", [])
        if not isinstance(imagery, list) or not imagery:
            errors.append("classification requires inputs.imagery")
        else:
            for index, item in enumerate(imagery):
                required_path(f"imagery[{index}]", item, base, input_roots, errors)
        if engine == "envi":
            required_path("training_roi", inputs.get("training_roi"), base, input_roots, errors)
        elif engine == "pytorch":
            package = required_path("model_package", inputs.get("model_package"), base, input_roots, errors)
            if package and package.is_dir() and not (package / "model_config.json").exists():
                errors.append("PyTorch model_package must contain model_config.json")
        elif engine == "provided_lulc":
            required_path("lulc_baseline", inputs.get("lulc_baseline"), base, input_roots, errors)
        if classification.get("scheme") not in {"standard_6class", "high_water_coal_7class"}:
            errors.append("classification.scheme must be standard_6class or high_water_coal_7class")
        threshold = classification.get("low_confidence_threshold")
        if threshold is not None and (not isinstance(threshold, (int, float)) or not 0 < threshold < 1):
            errors.append("classification.low_confidence_threshold must be between 0 and 1")
        if classification.get("output_low_confidence") and threshold is None:
            errors.append("classification.output_low_confidence requires low_confidence_threshold")
        accuracy = classification.get("accuracy", {})
        if accuracy and accuracy.get("enabled"):
            required_path("classification.accuracy.validation_samples", accuracy.get("validation_samples"), base, input_roots, errors)
            for key in ("reference_field", "prediction_field", "output", "confusion_matrix"):
                if not accuracy.get(key):
                    errors.append(f"classification.accuracy.{key} is required when accuracy is enabled")
            if bool(accuracy.get("x_field")) != bool(accuracy.get("y_field")):
                errors.append("classification.accuracy.x_field and y_field are supplied together")

    if plus.get("enabled"):
        historical = inputs.get("historical_lulc", [])
        if not isinstance(historical, list) or len(historical) < 2:
            errors.append("PLUS requires at least two historical_lulc rasters for backcasting")
        else:
            for index, item in enumerate(historical):
                required_path(f"historical_lulc[{index}]", item, base, input_roots, errors)
        factors = inputs.get("driver_factors", {})
        if not isinstance(factors, dict) or not any(factors.values()):
            errors.append("PLUS requires local driver_factors")
            factors = {}
        for key, value in factors.items():
            if value:
                required_path(f"driver_factors.{key}", value, base, input_roots, errors)
        scenarios = plus.get("scenarios", [])
        if not isinstance(scenarios, list) or not scenarios:
            errors.append("PLUS requires at least one scenario")
            scenario_codes: list[str] = []
        else:
            scenario_codes = [str(item).strip().upper() for item in scenarios]
            invalid = sorted(set(scenario_codes) - VALID_PLUS_SCENARIOS)
            if invalid:
                errors.append(f"PLUS scenarios must be within {sorted(VALID_PLUS_SCENARIOS)}; got {invalid}")
            if len(set(scenario_codes)) != len(scenario_codes):
                errors.append("PLUS scenarios must not contain duplicates")
        if plus.get("target_year", 0) <= plus.get("baseline_year", 0):
            errors.append("PLUS target_year must be later than baseline_year")
        for field in ("transition_matrix", "constraint_raster"):
            if plus.get(field):
                optional_path(f"plus.{field}", plus.get(field), base, input_roots, errors)
        if plus.get("random_seed") is not None and not isinstance(plus.get("random_seed"), int):
            errors.append("PLUS random_seed must be an integer when supplied")
        if "RE" in scenario_codes:
            resource = plus.get("resource_extraction", {})
            errors.extend(re_contract_errors(resource, project_shorthand_allowed=True))
            required_path("subsidence_depth_raster", inputs.get("subsidence_depth_raster"), base, input_roots, errors)
            if isinstance(resource, dict):
                for factor in resource.get("additional_driver_factors", []):
                    if factor not in factors or not factors.get(factor):
                        errors.append(f"PLUS RE additional driver is missing: driver_factors.{factor}")
                if inputs.get("subsidence_w_dat"):
                    source = resource.get("w_dat_preprocessing", {})
                    if source.get("source_unit") not in {"m", "mm"}:
                        errors.append("PLUS RE w.dat source_unit must be m or mm")
                    if source.get("source_convention") not in {"negative_down", "positive_down"}:
                        errors.append("PLUS RE w.dat source_convention must be negative_down or positive_down")
                    required_path("subsidence_w_dat", inputs.get("subsidence_w_dat"), base, input_roots, errors)
                    warnings.append("RE uses the aligned positive subsidence-depth raster; w.dat remains the external source record.")

    if invest.get("enabled"):
        models = invest.get("models")
        if models is not None and (not isinstance(models, dict) or not models):
            errors.append("invest.models must be a non-empty object when supplied")
            models = {}
        active_models = models if isinstance(models, dict) and models else {"carbon": {"enabled": True, "provided_datastack": invest.get("datastack")}}
        for name, config in active_models.items():
            if name not in VALID_INVEST_MODELS:
                errors.append(f"unsupported InVEST model: {name}")
                continue
            if not isinstance(config, dict):
                errors.append(f"invest.models.{name} must be an object")
                continue
            if not config.get("enabled"):
                continue
            template = config.get("datastack_template") or config.get("provided_datastack")
            if template:
                required_path(f"invest.models.{name} datastack", template, base, input_roots, errors)
            elif name != "carbon":
                errors.append(f"invest.models.{name} requires datastack_template or provided_datastack")
            outputs = config.get("expected_outputs")
            if outputs is not None and (not isinstance(outputs, list) or any(not isinstance(item, str) or not item for item in outputs)):
                errors.append(f"invest.models.{name}.expected_outputs must be a list of non-empty paths")
            if name != "carbon" and (not isinstance(outputs, list) or not outputs):
                errors.append(f"invest.models.{name}.expected_outputs is required to verify scenario outputs")
        carbon_config = active_models.get("carbon", {}) if isinstance(active_models.get("carbon", {}), dict) else {}
        if carbon_config.get("enabled") and not (carbon_config.get("datastack_template") or carbon_config.get("provided_datastack")):
            carbon = required_path("carbon_density", inputs.get("carbon_density"), base, input_roots, errors)
            validate_carbon_table(carbon, errors)
        if not plus.get("enabled") and not classification.get("enabled"):
            required_path("lulc_baseline", inputs.get("lulc_baseline"), base, input_roots, errors)

    if subsidence.get("enabled"):
        mode = subsidence.get("mode")
        if mode not in VALID_SUBSIDENCE_WATER_MODES:
            errors.append(f"subsidence_water.mode must be one of {sorted(VALID_SUBSIDENCE_WATER_MODES)}")
        if mode in {"estimate_volume", "composite_subsidence_water_carbon"}:
            required_path("dem", inputs.get("dem"), base, input_roots, errors)
            required_path("subsidence_depth_raster", inputs.get("subsidence_depth_raster"), base, input_roots, errors)
            level = subsidence.get("water_level_elevation_m", inputs.get("water_surface_elevation_m"))
            if not isinstance(level, (int, float)):
                errors.append("subsidence volume requires water_level_elevation_m")
            if inputs.get("elevation_vertical_datum") != subsidence.get("water_level_vertical_datum"):
                errors.append("DEM and water level must declare the same elevation vertical datum")
            for field in ("output_depth_raster", "output_volume_table"):
                if not subsidence.get(field):
                    errors.append(f"subsidence_water.{field} is required for volume calculation")
        if mode == "composite_subsidence_water_carbon":
            required_path("subsidence_water_boundary", inputs.get("subsidence_water_boundary"), base, input_roots, errors)
            composite = subsidence.get("composite_carbon", {})
            for field in ("water_carbon_density_g_c_m3", "aquatic_vegetation_carbon_density_t_c_ha", "bottom_sediment_carbon_density_t_c_ha"):
                value = composite.get(field)
                if not isinstance(value, (int, float)) or value < 0:
                    errors.append(f"subsidence_water.composite_carbon.{field} must be a non-negative number")
            if not inputs.get("aquatic_vegetation_boundary"):
                threshold = composite.get("aquatic_vegetation_depth_threshold_m")
                if not isinstance(threshold, (int, float)) or threshold < 0:
                    errors.append("provide aquatic_vegetation_boundary or a non-negative aquatic_vegetation_depth_threshold_m")
            if not inputs.get("bottom_sediment_boundary") and composite.get("bottom_sediment_assume_full_waterbed") is not True:
                errors.append("provide bottom_sediment_boundary or set bottom_sediment_assume_full_waterbed to true")
            for field in ("output_depth_raster", "output_volume_table", "output_aquatic_vegetation_raster",
                          "output_bottom_sediment_raster", "output_carbon_table"):
                if not subsidence.get(field):
                    errors.append(f"subsidence_water.{field} is required for composite_subsidence_water_carbon")
            total, water = composite.get("invest_total_carbon_t_c"), composite.get("invest_subsidence_water_carbon_t_c")
            if (total is None) != (water is None):
                errors.append("invest_total_carbon_t_c and invest_subsidence_water_carbon_t_c are supplied together")

    if ecosystem.get("enabled"):
        if ecosystem.get("method") not in VALID_ECOSYSTEM_METHODS:
            errors.append(f"ecosystem_service.method must be one of {sorted(VALID_ECOSYSTEM_METHODS)}")
        required_path("ecosystem config", ecosystem.get("config"), base, input_roots, errors)
        # In a PLUS scenario chain this table is supplemental (water/habitat/etc.);
        # standalone ecosystem scoring consumes it directly.
        if not plus.get("enabled"):
            required_path("ecosystem criteria_table", ecosystem.get("criteria_table"), base, input_roots, errors)
        elif ecosystem.get("criteria_table"):
            optional_path("ecosystem criteria_table", ecosystem.get("criteria_table"), base, input_roots, errors)
        if plus.get("enabled") and not invest.get("enabled"):
            errors.append("ecosystem scenario comparison after PLUS requires invest.enabled so carbon can be generated per scenario")
        analysis = ecosystem.get("analysis", {})
        if isinstance(analysis, dict) and analysis.get("grid_cell_pixels") is not None:
            value = analysis.get("grid_cell_pixels")
            if not isinstance(value, int) or value < 1:
                errors.append("ecosystem_service.analysis.grid_cell_pixels must be a positive integer")
        if isinstance(analysis, dict) and analysis.get("geodetector_factor_fields"):
            required_path("ecosystem geodetector_samples", analysis.get("geodetector_samples"), base, input_roots, errors)

    if gis_outputs.get("enabled"):
        required_path("gis_outputs.aprx", gis_outputs.get("aprx"), base, input_roots, errors)
        if not gis_outputs.get("layout_name"):
            errors.append("gis_outputs.layout_name is required when GIS outputs are enabled")
        if not gis_outputs.get("pdf") and not gis_outputs.get("png"):
            errors.append("configure gis_outputs.pdf and/or gis_outputs.png")
        layers = gis_outputs.get("layers", [])
        if not isinstance(layers, list) or not layers:
            errors.append("gis_outputs.layers must contain the result layers to add to the layout")
        else:
            for index, layer in enumerate(layers):
                if not isinstance(layer, dict):
                    errors.append(f"gis_outputs.layers[{index}] must be an object")
                    continue
                required_path(f"gis_outputs.layers[{index}].path", layer.get("path"), base, input_roots, errors)
                if layer.get("symbology_layer"):
                    optional_path(f"gis_outputs.layers[{index}].symbology_layer", layer.get("symbology_layer"), base, input_roots, errors)

    if validation.get("enabled"):
        if validation.get("evidence_file"):
            optional_path("validation.evidence_file", validation.get("evidence_file"), base, input_roots, errors)
        if not validation.get("output_report"):
            errors.append("validation.output_report is required when validation is enabled")
        sections = validation.get("required_sections")
        if sections is not None and (not isinstance(sections, list) or not sections or any(item not in {"lulc", "plus", "invest", "ecosystem", "map"} for item in sections)):
            errors.append("validation.required_sections must be a non-empty list of known sections")

    if not any(item.get("enabled") for item in (classification, plus, invest, subsidence, ecosystem, gis_outputs, validation)):
        warnings.append("No analysis module is enabled; configure one module before running the project.")
    return {"status": "valid" if not errors else "invalid", "project_id": project.get("project_id"),
            "workspace": str(workspace), "output_root": str(output_root), "errors": errors, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    args = parser.parse_args()
    result = validate(args.project.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
