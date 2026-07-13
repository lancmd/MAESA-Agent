"""Ensure PLUS scenarios fan out to InVEST and ecosystem comparison stages."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_workflow import compile_workflow  # noqa: E402


fixture = ROOT / "tests" / "fixtures" / "local_project"
with tempfile.TemporaryDirectory() as temporary:
    temp = Path(temporary)
    config = temp / "ecosystem.json"
    config.write_text(json.dumps({"schema_version": 2, "method": "minmax", "id_field": "unit_id",
        "passthrough_fields": ["scenario"], "criteria": [
            {"field": "carbon_storage_t_c", "direction": "benefit", "weight": 0.4},
            {"field": "annual_water_yield_m3", "direction": "benefit", "weight": 0.3},
            {"field": "habitat_quality", "direction": "benefit", "weight": 0.3}], "normalization": {"bounds": {}}}), encoding="utf-8")
    supplemental = temp / "services.csv"
    with supplemental.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["unit_id", "scenario", "annual_water_yield_m3", "habitat_quality"])
        writer.writeheader()
        for code in ("ND", "UD", "EP", "RE"):
            writer.writerow({"unit_id": code, "scenario": code, "annual_water_yield_m3": 1, "habitat_quality": 1})
    project = json.loads((fixture / "plus_project.json").read_text(encoding="utf-8"))
    project["workspace"] = "runtime"
    project["security"] = {"input_roots": [str(fixture), str(temp)], "output_root": "runtime"}
    for key, value in list(project["inputs"].items()):
        if isinstance(value, str) and value:
            project["inputs"][key] = str((fixture / value).resolve())
        elif isinstance(value, list):
            project["inputs"][key] = [str((fixture / item).resolve()) for item in value]
    project["inputs"]["driver_factors"] = {key: str((fixture / value).resolve()) for key, value in project["inputs"]["driver_factors"].items()}
    project["invest"] = {"enabled": True, "output_workspace": "outputs/invest", "models": {
        "carbon": {"enabled": True, "service_unit": "Mg C"}}}
    project["ecosystem_service"] = {"enabled": True, "method": "minmax", "criteria_table": str(supplemental), "config": str(config),
        "output_table": "outputs/ecosystem/scores.csv", "analysis": {"tradeoff_fields": ["carbon_storage_t_c", "annual_water_yield_m3"],
        "reference_scenario": "ND", "scenario_field": "scenario", "scenario_value_fields": ["ecosystem_service_score"], "sensitivity_enabled": True,
        "geodetector_factor_fields": []}}
    project_file = temp / "project.json"; project_file.write_text(json.dumps(project), encoding="utf-8")
    report = compile_workflow(project_file)
    expected = {f"invest_carbon_{code}" for code in ("ND", "UD", "EP", "RE")} | {
        "ecosystem_scenario_inputs", "ecosystem_service", "ecosystem_tradeoffs", "ecosystem_sensitivity", "ecosystem_scenario_comparison"}
    assert expected.issubset(set(report["stage_ids"])), report
print('{"status":"completed","checks":["PLUS to InVEST","scenario ecosystem comparison"]}')
