#!/usr/bin/env python3
"""Compile one validated local project into a resumable, local workflow job."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from path_safety import PathSafetyError, require_within, resolved, resolve_output
from plus_contract import canonical_re_contract, expected_plus_raster
from project_validator import validate


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_path(value: str | None, base: Path) -> str | None:
    return str(resolved(value, base)) if value else None


def output_path(value: str, workspace: Path) -> str:
    return str(resolve_output(value, workspace))


def carbon_datastack(lulc: str, carbon_table: str, output: Path) -> str:
    write_json(output, {"args": {"calc_sequestration": False, "carbon_pools_path": carbon_table,
        "do_redd": False, "do_valuation": False, "lulc_cur_path": lulc, "n_workers": -1,
        "results_suffix": ""}, "model_name": "natcap.invest.carbon"})
    return str(output)


def allowed_codes(scheme: str) -> list[int]:
    return list(range(1, 8 if scheme == "high_water_coal_7class" else 7))


def add_preflight(stages: list[dict[str, Any]], workspace: Path, inputs: dict[str, Any], base: Path,
                  classification: dict[str, Any], plus: dict[str, Any], subsidence: dict[str, Any]) -> str | None:
    datasets: list[dict[str, Any]] = []
    scheme = classification.get("scheme", "standard_6class")
    historical = [source_path(item, base) for item in inputs.get("historical_lulc", []) if item]
    baseline = source_path(inputs.get("lulc_baseline"), base)
    imagery = [source_path(item, base) for item in inputs.get("imagery", []) if item]
    master: str | None = None
    if plus.get("enabled") and historical:
        master = "historical_lulc_latest"
        for index, path in enumerate(historical):
            datasets.append({"name": "historical_lulc_latest" if index == len(historical) - 1 else f"historical_lulc_{index + 1}",
                             "path": path, "kind": "lulc", "allowed_codes": allowed_codes(scheme), "must_align": True})
    elif baseline:
        master = "lulc_baseline"
        datasets.append({"name": master, "path": baseline, "kind": "lulc", "allowed_codes": allowed_codes(scheme), "must_align": True})
    elif classification.get("enabled") and imagery:
        master = "imagery"
        datasets.append({"name": master, "path": imagery[0], "kind": "continuous", "must_align": False})
    if plus.get("enabled"):
        for name, value in inputs.get("driver_factors", {}).items():
            if value:
                datasets.append({"name": f"driver_{name}", "path": source_path(value, base), "kind": "continuous", "must_align": True})
        if inputs.get("subsidence_depth_raster"):
            datasets.append({"name": "subsidence_depth", "path": source_path(inputs["subsidence_depth_raster"], base),
                             "kind": "subsidence_depth", "must_align": True})
    if subsidence.get("enabled") and subsidence.get("mode") in {"estimate_volume", "composite_subsidence_water_carbon"}:
        for name, value, kind in (("dem", inputs.get("dem"), "continuous"),
                                  ("subsidence_depth", inputs.get("subsidence_depth_raster"), "subsidence_depth")):
            if value and not any(item["name"] == name for item in datasets):
                datasets.append({"name": name, "path": source_path(value, base), "kind": kind, "must_align": bool(master)})
    if not datasets:
        return None
    vertical_datum: dict[str, Any] = {}
    if subsidence.get("enabled") and subsidence.get("mode") in {"estimate_volume", "composite_subsidence_water_carbon"}:
        vertical_datum = {"dem": inputs.get("elevation_vertical_datum"),
                          "water_level": subsidence.get("water_level_vertical_datum")}
    spec = {"master": master, "datasets": datasets, "carbon_density": source_path(inputs.get("carbon_density"), base),
            "vertical_datum": vertical_datum}
    spec_path = workspace / "generated" / "spatial_preflight.json"
    report = workspace / "validation" / "spatial_preflight.json"
    write_json(spec_path, spec)
    stages.append({"id": "spatial_preflight", "adapter": "command", "enabled": True,
                   "command": [sys.executable, str(ROOT / "scripts" / "spatial_preflight.py"), "--spec", str(spec_path),
                               "--output", str(report)], "inputs": [item["path"] for item in datasets],
                   "outputs": [str(report)], "depends_on": []})
    return "spatial_preflight"


def lulc_validation_stage(stages: list[dict[str, Any],], identifier: str, lulc: str, master: str | None,
                          scheme: str, carbon: str | None, workspace: Path, dependencies: list[str]) -> str:
    spec = {"master": "master" if master else "lulc", "datasets": [
        {"name": "master", "path": master, "kind": "continuous", "must_align": False}] if master else []}
    spec["datasets"].append({"name": "lulc", "path": lulc, "kind": "lulc", "allowed_codes": allowed_codes(scheme),
                             "must_align": bool(master)})
    spec["carbon_density"] = carbon
    spec_path = workspace / "generated" / f"{identifier}.json"
    report = workspace / "validation" / f"{identifier}.json"
    write_json(spec_path, spec)
    stages.append({"id": identifier, "adapter": "command", "enabled": True,
                   "command": [sys.executable, str(ROOT / "scripts" / "spatial_preflight.py"), "--spec", str(spec_path),
                               "--output", str(report)], "inputs": [lulc] + ([master] if master else []) + ([carbon] if carbon else []),
                   "outputs": [str(report)], "depends_on": dependencies})
    return identifier


def compile_workflow(project_path: Path, output_job: Path | None = None) -> dict[str, Any]:
    project_path = project_path.expanduser().resolve()
    report = validate(project_path)
    if report["status"] != "valid":
        raise ValueError("project validation failed: " + "; ".join(report["errors"]))
    project, base, workspace = read_json(project_path), project_path.parent, Path(report["workspace"]).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    output_job = output_job.expanduser().resolve() if output_job else workspace / "generated" / "workflow_job.json"
    try:
        require_within(output_job, [workspace], "workflow job")
    except PathSafetyError as error:
        raise ValueError("workflow_job must be written inside the project workspace") from error
    inputs = project["inputs"]
    classification, plus, invest = project.get("classification", {}), project.get("plus", {}), project.get("invest", {})
    subsidence, ecosystem = project.get("subsidence_water", {}), project.get("ecosystem_service", {})
    gis_outputs, validation_config = project.get("gis_outputs", {}), project.get("validation", {})
    stages: list[dict[str, Any]] = []
    preflight = add_preflight(stages, workspace, inputs, base, classification, plus, subsidence)
    dependencies = [preflight] if preflight else []
    carbon = source_path(inputs.get("carbon_density"), base)
    lulc: str | None = source_path(inputs.get("lulc_baseline"), base)
    lulc_dependency = dependencies.copy()

    if classification.get("enabled"):
        lulc = output_path(classification.get("output_lulc", "outputs/lulc.tif"), workspace)
        if classification["engine"] == "pytorch":
            confidence = output_path(classification.get("output_confidence", "outputs/lulc_confidence.tif"), workspace)
            stages.append({"id": "classification_pytorch", "adapter": "command", "enabled": True,
                "command": [sys.executable, str(ROOT / "scripts" / "pytorch_lulc.py"), "infer", "--model-package",
                            source_path(inputs["model_package"], base), "--input-raster", source_path(inputs["imagery"][0], base),
                            "--class-output", lulc, "--confidence-output", confidence],
                "inputs": [source_path(inputs["model_package"], base), source_path(inputs["imagery"][0], base)],
                "outputs": [lulc, confidence], "depends_on": dependencies.copy()})
            classify_id = "classification_pytorch"
        elif classification["engine"] == "envi":
            method = classification.get("envi_method", "maximum_likelihood")
            stages.append({"id": "classification_envi", "adapter": "envi", "enabled": True,
                "batch_file": str(ROOT / "scripts" / ("envi_maximum_likelihood.pro" if method == "maximum_likelihood" else "envi_minimum_distance.pro")),
                "entrypoint": "mining_envi_maximum_likelihood" if method == "maximum_likelihood" else "mining_envi_minimum_distance",
                "env": {"MINING_INPUT_RASTER": source_path(inputs["imagery"][0], base),
                        "MINING_TRAINING_VECTOR": source_path(inputs["training_roi"], base), "MINING_OUTPUT_RASTER": lulc},
                "inputs": [source_path(inputs["imagery"][0], base), source_path(inputs["training_roi"], base)],
                "outputs": [lulc], "depends_on": dependencies.copy()})
            classify_id = "classification_envi"
        else:
            classify_id = "provided_lulc"
        if classification["engine"] != "provided_lulc":
            master = source_path(inputs["imagery"][0], base)
            lulc_dependency = [lulc_validation_stage(stages, "lulc_output_validation", lulc, master,
                                                      classification["scheme"], carbon, workspace, [classify_id])]
            accuracy = classification.get("accuracy", {})
            if accuracy.get("enabled"):
                acc_output = output_path(accuracy["output"], workspace)
                matrix = output_path(accuracy["confusion_matrix"], workspace)
                stages.append({"id": "lulc_accuracy", "adapter": "command", "enabled": True,
                    "command": [sys.executable, str(ROOT / "scripts" / "lulc_accuracy.py"), "--samples",
                                source_path(accuracy["validation_samples"], base), "--reference-field", accuracy["reference_field"],
                                "--prediction-field", accuracy["prediction_field"], "--output", acc_output,
                                "--confusion-matrix", matrix] + (["--classification-raster", lulc, "--x-field", accuracy["x_field"],
                                "--y-field", accuracy["y_field"]] if accuracy.get("x_field") and accuracy.get("y_field") else []) +
                               (["--samples-crs", accuracy["samples_crs"]] if accuracy.get("samples_crs") else []),
                    "inputs": [source_path(accuracy["validation_samples"], base), lulc], "outputs": [acc_output, matrix],
                    "depends_on": lulc_dependency.copy()})
                lulc_dependency.append("lulc_accuracy")

    if subsidence.get("enabled") and subsidence.get("mode") in {"estimate_volume", "composite_subsidence_water_carbon"}:
        mode = subsidence["mode"]
        level = subsidence.get("water_level_elevation_m", inputs.get("water_surface_elevation_m"))
        operation: dict[str, Any] = {"id": "subsidence_water", "type": "subsidence_water_volume" if mode == "estimate_volume" else "subsidence_water_carbon",
            "dem": source_path(inputs["dem"], base), "subsidence_depth": source_path(inputs["subsidence_depth_raster"], base),
            "water_level_elevation_m": level, "water_depth_output": output_path(subsidence["output_depth_raster"], workspace),
            "volume_table": output_path(subsidence["output_volume_table"], workspace)}
        outputs = [operation["water_depth_output"], operation["volume_table"]]
        if mode == "composite_subsidence_water_carbon":
            composite = subsidence["composite_carbon"]
            operation.update({
                "water_boundary": source_path(inputs["subsidence_water_boundary"], base),
                "aquatic_vegetation_output": output_path(subsidence["output_aquatic_vegetation_raster"], workspace),
                "bottom_sediment_output": output_path(subsidence["output_bottom_sediment_raster"], workspace),
                "carbon_table": output_path(subsidence["output_carbon_table"], workspace),
                "water_carbon_density_g_c_m3": composite["water_carbon_density_g_c_m3"],
                "aquatic_vegetation_carbon_density_t_c_ha": composite["aquatic_vegetation_carbon_density_t_c_ha"],
                "bottom_sediment_carbon_density_t_c_ha": composite["bottom_sediment_carbon_density_t_c_ha"],
                "aquatic_vegetation_depth_threshold_m": composite.get("aquatic_vegetation_depth_threshold_m"),
                "bottom_sediment_assume_full_waterbed": composite.get("bottom_sediment_assume_full_waterbed", False),
                "invest_total_carbon_t_c": composite.get("invest_total_carbon_t_c"),
                "invest_subsidence_water_carbon_t_c": composite.get("invest_subsidence_water_carbon_t_c"),
            })
            if inputs.get("aquatic_vegetation_boundary"):
                operation["aquatic_vegetation_mask"] = source_path(inputs["aquatic_vegetation_boundary"], base)
            if inputs.get("bottom_sediment_boundary"):
                operation["bottom_sediment_mask"] = source_path(inputs["bottom_sediment_boundary"], base)
            outputs.extend([operation["aquatic_vegetation_output"], operation["bottom_sediment_output"], operation["carbon_table"]])
        spec_path = workspace / "generated" / "subsidence_water.json"
        write_json(spec_path, {"environment": {"overwriteOutput": False}, "operations": [operation]})
        stages.append({"id": "subsidence_water", "adapter": "arcgis", "enabled": True, "spec": str(spec_path),
                       "inputs": [operation["dem"], operation["subsidence_depth"]], "outputs": outputs,
                       "depends_on": dependencies.copy()})

    plus_outputs: dict[str, str] = {}
    plus_validation_dependencies: list[str] = []
    if plus.get("enabled"):
        driver_factors = {name: source_path(value, base) for name, value in inputs.get("driver_factors", {}).items() if value}
        historical = [source_path(value, base) for value in inputs.get("historical_lulc", [])]
        plus_root = Path(output_path(plus.get("output_workspace", "outputs/plus"), workspace))
        for raw_scenario in plus.get("scenarios", ["ND", "UD", "EP", "RE"]):
            scenario = str(raw_scenario).upper()
            stage_id, scenario_dir = f"plus_{scenario}", plus_root / scenario
            expected = expected_plus_raster(scenario_dir, scenario)
            parameters: dict[str, Any] = {"historical_lulc": historical, "driver_factors": driver_factors,
                "output_directory": str(scenario_dir), "expected_output": str(expected)}
            if scenario == "RE":
                parameters["resource_extraction"] = canonical_re_contract(
                    plus["resource_extraction"], source_path(inputs["subsidence_depth_raster"], base),
                    lambda value: source_path(value, base) or value)
            request = {"protocol_version": "1.0", "request_id": stage_id, "operation": "plus.run_scenario",
                       "parameters": {"project": str(project_path), "scenario": scenario, "workspace": str(scenario_dir),
                                      "parameters": parameters}}
            stage_inputs = [*historical, *driver_factors.values()]
            if scenario == "RE":
                stage_inputs.append(parameters["resource_extraction"]["core_driver_input"])
            stages.append({"id": stage_id, "adapter": "plus", "enabled": True, "request": request,
                           "inputs": stage_inputs, "outputs": [str(expected)], "depends_on": dependencies.copy()})
            validation_id = lulc_validation_stage(stages, f"plus_output_validation_{scenario}", str(expected), historical[-1],
                                                  classification.get("scheme", "standard_6class"), carbon, workspace, [stage_id])
            plus_outputs[scenario] = str(expected)
            plus_validation_dependencies.append(validation_id)

    invest_outputs: dict[str, str] = {}
    invest_dependencies: list[str] = []
    if invest.get("enabled"):
        if plus_outputs:
            lulc_sources = plus_outputs
            dependency_by_scenario = {scenario: [f"plus_output_validation_{scenario}"] for scenario in plus_outputs}
        else:
            if not lulc:
                raise ValueError("InVEST needs a classified or provided LULC raster")
            lulc_sources = {"baseline": lulc}
            dependency_by_scenario = {"baseline": lulc_dependency}
        for scenario, source_lulc in lulc_sources.items():
            suffix = "" if scenario == "baseline" else f"_{scenario}"
            stage_id = f"invest_carbon{suffix}"
            datastack = source_path(invest.get("datastack"), base) if scenario == "baseline" and invest.get("datastack") else carbon_datastack(
                source_lulc, carbon or "", workspace / "generated" / f"{stage_id}_datastack.json")
            model_workspace = Path(output_path(invest.get("output_workspace", "outputs/invest"), workspace)) / scenario
            output = model_workspace / "tot_c_cur.tif"
            stages.append({"id": stage_id, "adapter": "invest", "enabled": True, "model": "carbon", "datastack": datastack,
                           "model_workspace": str(model_workspace), "inputs": [datastack, source_lulc, carbon],
                           "outputs": [str(output)], "depends_on": dependency_by_scenario[scenario]})
            invest_outputs[scenario] = str(output); invest_dependencies.append(stage_id)

    ecosystem_dependencies: list[str] = []
    if ecosystem.get("enabled"):
        criteria = source_path(ecosystem.get("criteria_table"), base)
        config = source_path(ecosystem["config"], base)
        if plus_outputs:
            criteria = output_path(ecosystem.get("generated_criteria_table", "outputs/ecosystem/scenario_criteria.csv"), workspace)
            config_payload = read_json(Path(config))
            command = [sys.executable, str(ROOT / "scripts" / "scenario_service_table.py"), "--output", criteria,
                       "--scenario-field", ecosystem.get("analysis", {}).get("scenario_field", "scenario"),
                       "--id-field", config_payload.get("id_field", "unit_id")]
            if ecosystem.get("criteria_table"):
                command.extend(["--supplemental", source_path(ecosystem["criteria_table"], base)])
            for scenario in ("ND", "UD", "EP", "RE"):
                if scenario in invest_outputs:
                    command.extend(["--carbon-raster", f"{scenario}={invest_outputs[scenario]}"])
            stages.append({"id": "ecosystem_scenario_inputs", "adapter": "command", "enabled": True, "command": command,
                           "inputs": list(invest_outputs.values()) + ([source_path(ecosystem["criteria_table"], base)] if ecosystem.get("criteria_table") else []),
                           "outputs": [criteria, criteria + ".metadata.json"], "depends_on": invest_dependencies.copy()})
            ecosystem_dependencies = ["ecosystem_scenario_inputs"]
        else:
            ecosystem_dependencies = invest_dependencies.copy() or lulc_dependency.copy()
        score = output_path(ecosystem.get("output_table", "outputs/ecosystem_service_scores.csv"), workspace)
        stages.append({"id": "ecosystem_service", "adapter": "command", "enabled": True,
            "command": [sys.executable, str(ROOT / "scripts" / "ecosystem_service.py"), "--criteria-table", criteria,
                        "--config", config, "--output", score], "inputs": [criteria, config],
            "outputs": [score, score + ".metadata.json"], "depends_on": ecosystem_dependencies.copy()})
        analysis = ecosystem.get("analysis", {})
        services = analysis.get("tradeoff_fields", [])
        if isinstance(services, list) and len(services) >= 2:
            out = output_path(analysis.get("tradeoff_output", "outputs/ecosystem/tradeoffs.csv"), workspace)
            stages.append({"id": "ecosystem_tradeoffs", "adapter": "command", "enabled": True,
                "command": [sys.executable, str(ROOT / "scripts" / "ecosystem_analysis.py"), "tradeoff", "--table", criteria,
                            "--fields", ",".join(services), "--output", out], "inputs": [criteria], "outputs": [out],
                "depends_on": ["ecosystem_service"]})
        if analysis.get("sensitivity_enabled", True):
            out = output_path(analysis.get("sensitivity_output", "outputs/ecosystem/sensitivity.csv"), workspace)
            stages.append({"id": "ecosystem_sensitivity", "adapter": "command", "enabled": True,
                "command": [sys.executable, str(ROOT / "scripts" / "ecosystem_analysis.py"), "sensitivity", "--table", criteria,
                            "--config", config, "--relative-delta", str(analysis.get("sensitivity_relative_delta", 0.1)), "--output", out],
                "inputs": [criteria, config], "outputs": [out], "depends_on": ["ecosystem_service"]})
        if plus_outputs and analysis.get("reference_scenario", "ND") in plus_outputs:
            out = output_path(analysis.get("scenario_compare_output", "outputs/ecosystem/scenario_comparison.csv"), workspace)
            fields = analysis.get("scenario_value_fields", ["ecosystem_service_score"])
            stages.append({"id": "ecosystem_scenario_comparison", "adapter": "command", "enabled": True,
                "command": [sys.executable, str(ROOT / "scripts" / "ecosystem_analysis.py"), "compare", "--table", score,
                            "--reference", analysis.get("reference_scenario", "ND"), "--scenario-field", analysis.get("scenario_field", "scenario"),
                            "--fields", ",".join(fields), "--output", out], "inputs": [score], "outputs": [out],
                "depends_on": ["ecosystem_service"]})
        geo_fields = analysis.get("geodetector_factor_fields", [])
        geo_table = source_path(analysis.get("geodetector_samples"), base)
        if geo_fields and geo_table:
            out = output_path(analysis.get("geodetector_output", "outputs/ecosystem/geodetector.csv"), workspace)
            stages.append({"id": "ecosystem_geodetector", "adapter": "command", "enabled": True,
                "command": [sys.executable, str(ROOT / "scripts" / "ecosystem_analysis.py"), "geodetector", "--table", geo_table,
                            "--target", analysis.get("geodetector_target_field", "ecosystem_service_score"), "--fields", ",".join(geo_fields), "--output", out],
                "inputs": [geo_table], "outputs": [out], "depends_on": ["ecosystem_service"]})

    completed = [stage["id"] for stage in stages if stage.get("enabled")]
    if gis_outputs.get("enabled"):
        spec = {"environment": {"overwriteOutput": False}, "operations": [{"id": "compose_final_layout", "type": "compose_layout",
            "aprx": source_path(gis_outputs["aprx"], base), "layout_name": gis_outputs["layout_name"], "map_name": gis_outputs.get("map_name"),
            "map_frame_name": gis_outputs.get("map_frame_name"), "title_element_name": gis_outputs.get("title_element_name"),
            "extent_from_layer": gis_outputs.get("extent_from_layer"), "aprx_output": output_path(gis_outputs.get("aprx_output", "outputs/maps/composed_project.aprx"), workspace),
            "layers": gis_outputs.get("layers", []), "title_text": gis_outputs.get("title_text"), "legend_name": gis_outputs.get("legend_name"),
            "pdf": output_path(gis_outputs["pdf"], workspace) if gis_outputs.get("pdf") else None,
            "png": output_path(gis_outputs["png"], workspace) if gis_outputs.get("png") else None, "resolution": gis_outputs.get("resolution", 300),
            "validation_output": str(workspace / "validation" / "map_layout.json")}]}
        spec_path = workspace / "generated" / "compose_layout.json"; write_json(spec_path, spec)
        stages.append({"id": "map_layout", "adapter": "arcgis", "enabled": True, "spec": str(spec_path),
                       "inputs": [source_path(gis_outputs["aprx"], base)], "outputs": [str(workspace / "validation" / "map_layout.json")],
                       "depends_on": completed.copy()})
        completed.append("map_layout")
    if validation_config.get("enabled"):
        evidence, output = source_path(validation_config["evidence_file"], base), output_path(validation_config["output_report"], workspace)
        stages.append({"id": "analysis_validation", "adapter": "command", "enabled": True,
                       "command": [sys.executable, str(ROOT / "scripts" / "analysis_validation.py"), "--validation-file", evidence,
                                   "--output-report", output], "inputs": [evidence], "outputs": [output], "depends_on": completed.copy()})
    job = {"schema_version": 1, "project_id": project["project_id"], "workspace": str(workspace), "project_file": str(project_path),
           "security": {"input_roots": [str(resolved(item, base)) for item in project.get("security", {}).get("input_roots", ["."])],
                        "output_root": str(workspace), "confirm_overwrite": bool(project.get("security", {}).get("confirm_overwrite", False))},
           "software": project.get("software", {}), "stages": stages}
    write_json(output_job, job)
    return {"project_id": project["project_id"], "workspace": str(workspace), "workflow_job": str(output_job),
            "stage_ids": [stage["id"] for stage in stages], "warnings": report["warnings"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path); parser.add_argument("--output-job", type=Path)
    parser.add_argument("--run", action="store_true"); parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true"); parser.add_argument("--confirm-overwrite", action="store_true")
    args = parser.parse_args(); report = compile_workflow(args.project, args.output_job)
    if not args.run:
        print(json.dumps(report, ensure_ascii=False, indent=2)); return 0
    from workflow_agent import JobRunner
    runner = JobRunner(Path(report["workflow_job"]), args.dry_run, args.continue_on_error, args.confirm_overwrite)
    code = runner.run(); report.update({"agent_state": str(runner.state_path), "return_code": code})
    print(json.dumps(report, ensure_ascii=False, indent=2)); return code


if __name__ == "__main__":
    raise SystemExit(main())
