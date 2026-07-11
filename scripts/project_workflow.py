#!/usr/bin/env python3
"""Compile a validated local project into the executable workflow-job schema."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from project_validator import validate


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve(value: str | None, base: Path) -> str | None:
    if value in (None, ""):
        return None
    path = Path(str(value)).expanduser()
    return str(path.resolve() if path.is_absolute() else (base / path).resolve())


def output_path(value: str, workspace: Path) -> str:
    path = Path(value).expanduser()
    return str(path.resolve() if path.is_absolute() else (workspace / path).resolve())


def carbon_datastack(lulc: str, carbon_table: str, output: Path) -> str:
    payload = {
        "args": {
            "calc_sequestration": False,
            "carbon_pools_path": carbon_table,
            "do_redd": False,
            "do_valuation": False,
            "lulc_cur_path": lulc,
            "n_workers": -1,
            "results_suffix": "",
        },
        "model_name": "natcap.invest.carbon",
    }
    write_json(output, payload)
    return str(output)


def compile_workflow(project_path: Path, output_job: Path | None = None) -> dict[str, Any]:
    project_path = project_path.expanduser().resolve()
    report = validate(project_path)
    if report["status"] != "valid":
        raise ValueError("project validation failed: " + "; ".join(report["errors"]))
    project = read_json(project_path)
    base = project_path.parent
    workspace = Path(resolve(project["workspace"], base) or (base / "outputs" / project["project_id"])).resolve()
    output_job = (output_job.expanduser().resolve() if output_job else workspace / "generated" / "workflow_job.json")
    inputs = project["inputs"]
    classification = project.get("classification", {})
    plus = project.get("plus", {})
    invest = project.get("invest", {})
    subsidence = project.get("subsidence_water", {})
    ecosystem = project.get("ecosystem_service", {})
    gis_outputs = project.get("gis_outputs", {})
    validation_config = project.get("validation", {})
    stages: list[dict[str, Any]] = []
    completed_dependencies: list[str] = []

    lulc: str
    if classification.get("enabled"):
        lulc = output_path(classification.get("output_lulc", "outputs/lulc.tif"), workspace)
        if classification["engine"] == "pytorch":
            confidence = output_path(classification.get("output_confidence", "outputs/lulc_confidence.tif"), workspace)
            stages.append({
                "id": "classification_pytorch", "adapter": "command", "enabled": True,
                "command": [sys.executable, str(ROOT / "scripts" / "pytorch_lulc.py"), "infer",
                            "--model-package", resolve(inputs["model_package"], base),
                            "--input-raster", resolve(inputs["imagery"][0], base),
                            "--class-output", lulc, "--confidence-output", confidence],
                "inputs": [resolve(inputs["model_package"], base), resolve(inputs["imagery"][0], base)],
                "outputs": [lulc, confidence], "depends_on": [],
            })
        elif classification["engine"] == "envi":
            stages.append({
                "id": "classification_envi", "adapter": "envi", "enabled": True,
                "batch_file": str(ROOT / "scripts" / ("envi_maximum_likelihood.pro" if classification.get("envi_method", "maximum_likelihood") == "maximum_likelihood" else "envi_minimum_distance.pro")),
                "entrypoint": "mining_envi_maximum_likelihood" if classification.get("envi_method", "maximum_likelihood") == "maximum_likelihood" else "mining_envi_minimum_distance",
                "env": {"MINING_INPUT_RASTER": resolve(inputs["imagery"][0], base),
                        "MINING_TRAINING_VECTOR": resolve(inputs["training_roi"], base),
                        "MINING_OUTPUT_RASTER": lulc},
                "inputs": [resolve(inputs["imagery"][0], base), resolve(inputs["training_roi"], base)],
                "outputs": [lulc], "depends_on": [],
            })
        else:
            lulc = resolve(inputs["lulc_baseline"], base) or ""
        if stages:
            completed_dependencies.append(stages[-1]["id"])
    else:
        lulc = resolve(inputs["lulc_baseline"], base) or ""

    if subsidence.get("enabled") and subsidence.get("mode") in {"estimate_volume", "composite_subsidence_water_carbon"}:
        mode = subsidence["mode"]
        level = subsidence.get("water_level_elevation_m", inputs.get("water_surface_elevation_m"))
        operation: dict[str, Any] = {
            "id": "subsidence_water", "type": "subsidence_water_volume" if mode == "estimate_volume" else "subsidence_water_carbon",
            "dem": resolve(inputs["dem"], base), "subsidence_depth": resolve(inputs["subsidence_depth_raster"], base),
            "water_level_elevation_m": level, "water_depth_output": output_path(subsidence["output_depth_raster"], workspace),
            "volume_table": output_path(subsidence["output_volume_table"], workspace),
        }
        outputs = [operation["water_depth_output"], operation["volume_table"]]
        if mode == "composite_subsidence_water_carbon":
            composite = subsidence["composite_carbon"]
            operation.update({
                "water_boundary": resolve(inputs["subsidence_water_boundary"], base),
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
                operation["aquatic_vegetation_mask"] = resolve(inputs["aquatic_vegetation_boundary"], base)
            if inputs.get("bottom_sediment_boundary"):
                operation["bottom_sediment_mask"] = resolve(inputs["bottom_sediment_boundary"], base)
            outputs.extend([operation["aquatic_vegetation_output"], operation["bottom_sediment_output"], operation["carbon_table"]])
        spec_path = workspace / "generated" / "subsidence_water.json"
        write_json(spec_path, {"environment": {"overwriteOutput": True}, "operations": [operation]})
        stages.append({"id": "subsidence_water", "adapter": "arcgis", "enabled": True, "spec": str(spec_path),
                       "inputs": [item for item in [operation["dem"], operation["subsidence_depth"], operation.get("water_boundary")] if item],
                       "outputs": outputs, "depends_on": completed_dependencies.copy()})
        completed_dependencies.append("subsidence_water")

    if plus.get("enabled"):
        driver_factors = {name: resolve(value, base) for name, value in inputs.get("driver_factors", {}).items() if value}
        historical_lulc = [resolve(value, base) for value in inputs.get("historical_lulc", [])]
        plus_inputs = [path for path in [*historical_lulc, *driver_factors.values(), resolve(inputs.get("subsidence_depth_raster"), base)] if path]
        for scenario in plus.get("scenarios", ["ND", "UD", "EP", "RE"]):
            stage_id = f"plus_{str(scenario).upper()}"
            request = {
                "protocol_version": "1.0", "request_id": stage_id, "operation": "plus.run_scenario",
                "parameters": {
                    "project": str(project_path), "scenario": str(scenario).upper(),
                    "workspace": output_path(plus.get("output_workspace", "outputs/plus"), workspace),
                    "parameters": {"historical_lulc": historical_lulc, "driver_factors": driver_factors,
                                   "resource_extraction": plus.get("resource_extraction", {})},
                },
            }
            stages.append({"id": stage_id, "adapter": "plus", "enabled": True, "request": request,
                           "inputs": plus_inputs, "outputs": [], "depends_on": completed_dependencies.copy()})

    if invest.get("enabled"):
        datastack = resolve(invest.get("datastack"), base)
        if not datastack:
            datastack = carbon_datastack(lulc, resolve(inputs["carbon_density"], base) or "", workspace / "generated" / "invest_carbon_datastack.json")
        model_workspace = output_path(invest.get("output_workspace", "outputs/invest"), workspace)
        stages.append({"id": "invest_carbon", "adapter": "invest", "enabled": True, "model": "carbon",
                       "datastack": datastack, "model_workspace": model_workspace,
                       "inputs": [datastack, lulc, resolve(inputs["carbon_density"], base)],
                       "outputs": [str(Path(model_workspace) / "tot_c_cur.tif")], "depends_on": completed_dependencies.copy()})
        completed_dependencies.append("invest_carbon")

    if ecosystem.get("enabled"):
        score_output = output_path(ecosystem.get("output_table", "outputs/ecosystem_service_scores.csv"), workspace)
        stages.append({"id": "ecosystem_service", "adapter": "command", "enabled": True,
                       "command": [sys.executable, str(ROOT / "scripts" / "ecosystem_service.py"),
                                   "--criteria-table", resolve(ecosystem["criteria_table"], base),
                                   "--config", resolve(ecosystem["config"], base), "--output", score_output],
                       "inputs": [resolve(ecosystem["criteria_table"], base), resolve(ecosystem["config"], base)],
                       "outputs": [score_output, score_output + ".metadata.json"], "depends_on": completed_dependencies.copy()})
        completed_dependencies.append("ecosystem_service")

    if gis_outputs.get("enabled"):
        spec = {
            "environment": {"overwriteOutput": True},
            "operations": [{
                "id": "compose_final_layout", "type": "compose_layout", "aprx": resolve(gis_outputs["aprx"], base),
                "layout_name": gis_outputs["layout_name"], "map_name": gis_outputs.get("map_name"),
                "map_frame_name": gis_outputs.get("map_frame_name"),
                "title_element_name": gis_outputs.get("title_element_name"),
                "extent_from_layer": gis_outputs.get("extent_from_layer"),
                "aprx_output": output_path(gis_outputs.get("aprx_output", "outputs/maps/composed_project.aprx"), workspace),
                "layers": gis_outputs.get("layers", []), "title_text": gis_outputs.get("title_text"),
                "legend_name": gis_outputs.get("legend_name"),
                "pdf": output_path(gis_outputs["pdf"], workspace) if gis_outputs.get("pdf") else None,
                "png": output_path(gis_outputs["png"], workspace) if gis_outputs.get("png") else None,
                "resolution": gis_outputs.get("resolution", 300),
                "validation_output": str(workspace / "validation" / "map_layout.json"),
            }],
        }
        spec_path = workspace / "generated" / "compose_layout.json"
        write_json(spec_path, spec)
        stages.append({"id": "map_layout", "adapter": "arcgis", "enabled": True, "spec": str(spec_path),
                       "inputs": [resolve(gis_outputs["aprx"], base)],
                       "outputs": [str(workspace / "validation" / "map_layout.json")], "depends_on": completed_dependencies.copy()})
        completed_dependencies.append("map_layout")

    if validation_config.get("enabled"):
        evidence = resolve(validation_config["evidence_file"], base)
        validation_output = output_path(validation_config["output_report"], workspace)
        stages.append({"id": "analysis_validation", "adapter": "command", "enabled": True,
                       "command": [sys.executable, str(ROOT / "scripts" / "analysis_validation.py"),
                                   "--validation-file", evidence, "--output-report", validation_output],
                       "inputs": [evidence], "outputs": [validation_output],
                       "depends_on": completed_dependencies.copy()})

    job = {"schema_version": 1, "project_id": project["project_id"], "workspace": str(workspace),
           "software": project.get("software", {}), "stages": stages}
    write_json(output_job, job)
    return {"project_id": project["project_id"], "workspace": str(workspace), "workflow_job": str(output_job),
            "stage_ids": [stage["id"] for stage in stages], "warnings": report["warnings"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output-job", type=Path)
    parser.add_argument("--run", action="store_true", help="run the compiled local workflow immediately")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()
    report = compile_workflow(args.project, args.output_job)
    if not args.run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    from workflow_agent import JobRunner
    runner = JobRunner(Path(report["workflow_job"]), args.dry_run, args.continue_on_error)
    return_code = runner.run()
    report.update({"agent_state": str(runner.state_path), "return_code": return_code})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
