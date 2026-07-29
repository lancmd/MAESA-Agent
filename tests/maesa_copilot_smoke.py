"""Validate local-first LLM Copilot configuration without contacting a model."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from maesa_copilot import (controlled_plan, execute_project_creation_with_mcp, project_creation_contract,
                           project_creation_prompt, validate_execution_plan,
                           validate_project_creation_plan)  # noqa: E402


def normal_windows_path(value: str | Path) -> str:
    """Compare local Windows paths without relying on drive-letter casing."""
    return os.path.normcase(os.path.normpath(str(value)))


with tempfile.TemporaryDirectory() as temporary:
    provider = Path(temporary) / "provider.json"
    provider.write_text(json.dumps({"provider": "ollama", "base_url": "http://127.0.0.1:11434", "model": "qwen2.5:7b-instruct",
                                    "allow_cloud": False}), encoding="utf-8")
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "maesa_copilot.py"), "--provider", str(provider),
                              "--message", "检查我的输入", "--dry-run"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", check=False)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["status"] == "prepared" and result["endpoint_is_local"] is True, result
project = ROOT / "tests" / "fixtures" / "local_project" / "project.json"
plan = controlled_plan(project, "validate local workflow")
assert validate_execution_plan(plan, project)["status"] == "valid"
plan["steps"][0]["tool"] = "run_shell_command"
assert validate_execution_plan(plan, project)["status"] == "invalid"

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    nested = {
        "schema_version": 2, "project_id": "nested-inputs", "task_type": "invest_only", "workspace": "runtime",
        "inputs": {"imagery_periods": [{"year": 2020, "path": "inputs/image_2020.tif"}],
                   "driver_factors": {"dem": {"path": "inputs/dem.tif", "data_type": "continuous"}},
                   "historical_lulc": ["inputs/lulc_2020.tif"], "carbon_density": "inputs/carbon.csv"},
        "validation": {"enabled": True, "evidence_file": "evidence/custom_evidence.json",
                       "output_report": "reports/custom_validation.json"},
    }
    nested_project = root / "project.json"; nested_project.write_text(json.dumps(nested), encoding="utf-8")
    nested_plan = controlled_plan(nested_project, "nested paths")
    normalized_inputs = {normal_windows_path(value) for value in nested_plan["expected_inputs"]}
    assert normal_windows_path(root / "inputs" / "image_2020.tif") in normalized_inputs, nested_plan
    assert normal_windows_path(root / "inputs" / "dem.tif") in normalized_inputs, nested_plan
    validation_step = nested_plan["steps"][-1]["arguments"]
    assert validation_step["validation_file"] == str(root / "evidence" / "custom_evidence.json"), validation_step
    assert validation_step["output_report"] == str(root / "runtime" / "reports" / "custom_validation.json"), validation_step

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    inputs = root / "inputs"; inputs.mkdir()
    image = inputs / "image_2020.tif"; image.write_bytes(b"placeholder")
    roi = inputs / "training.geojson"; roi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    samples = inputs / "validation_2020.csv"; samples.write_text("reference,x,y\n1,0,0\n", encoding="utf-8")
    carbon = inputs / "carbon.csv"; carbon.write_text("lucode,c_above,c_below,c_soil,c_dead\n1,1,1,1,0\n", encoding="utf-8")
    model = inputs / "model"; model.mkdir(); (model / "model_config.json").write_text("{}", encoding="utf-8")
    manifest = root / "inputs.json"
    manifest.write_text(json.dumps({
        "schema_version": 1, "kind": "maesa_project_input_manifest", "project_id": "natural-create",
        "available_inputs": {"imagery_periods": [{"year": 2020, "path": "inputs/image_2020.tif",
                                                     "roi": "inputs/training.geojson",
                                                     "accuracy": {"validation_samples": "inputs/validation_2020.csv"}}],
                             "model_package": "inputs/model", "carbon_density": "inputs/carbon.csv"},
    }), encoding="utf-8")
    output_project = root / "outputs" / "project.json"
    workspace = root / "outputs" / "runtime"
    candidate = {
        "schema_version": 1, "kind": "maesa_project_creation_plan", "purpose": "classify one image",
        "input_manifest": str(manifest), "output_project": str(output_project), "workspace": str(workspace),
        "build_arguments": {"project_id": "natural-create", "task_type": "classification_only",
                            "imagery_periods": [{"year": 2020, "path": "inputs/image_2020.tif"}],
                            "model_package": "inputs/model"}, "confirmation_required": True,
    }
    checked = validate_project_creation_plan(candidate, manifest, output_project, str(workspace))
    assert checked["status"] == "valid", checked
    assert checked["normalized_plan"]["build_arguments"]["model_package"] == str(model), checked
    previous_input_root, previous_output_root = os.environ.get("MINING_GIS_INPUT_ROOTS"), os.environ.get("MINING_GIS_OUTPUT_ROOT")
    os.environ["MINING_GIS_INPUT_ROOTS"], os.environ["MINING_GIS_OUTPUT_ROOT"] = str(root), str(root)
    try:
        created = asyncio.run(execute_project_creation_with_mcp(checked["normalized_plan"]))
    finally:
        if previous_input_root is None:
            os.environ.pop("MINING_GIS_INPUT_ROOTS", None)
        else:
            os.environ["MINING_GIS_INPUT_ROOTS"] = previous_input_root
        if previous_output_root is None:
            os.environ.pop("MINING_GIS_OUTPUT_ROOT", None)
        else:
            os.environ["MINING_GIS_OUTPUT_ROOT"] = previous_output_root
    assert created["status"] == "completed" and output_project.is_file(), created
    created_project = json.loads(output_project.read_text(encoding="utf-8"))
    assert created_project["classification"]["engine"] == "pytorch", created_project
    invest_base = json.loads(json.dumps(candidate))
    invest_base["build_arguments"].pop("model_package")
    invest_base["build_arguments"]["imagery_periods"] = [{
        "year": 2020, "path": "inputs/image_2020.tif", "sensor": "landsat_8_oli", "roi": "inputs/training.geojson",
    }]
    missing_accuracy = json.loads(json.dumps(invest_base))
    missing_accuracy["build_arguments"].update({"task_type": "classification_invest", "carbon_density": "inputs/carbon.csv"})
    missing_accuracy_checked = validate_project_creation_plan(missing_accuracy, manifest, output_project, str(workspace))
    assert missing_accuracy_checked["status"] == "invalid", missing_accuracy_checked
    assert missing_accuracy_checked["preflight"]["status"] == "invalid", missing_accuracy_checked
    assert any("independent accuracy configuration" in item for item in missing_accuracy_checked["errors"]), missing_accuracy_checked
    blocked_plan = json.loads(json.dumps(missing_accuracy))
    blocked_project = root / "blocked" / "project.json"
    blocked_workspace = root / "blocked" / "runtime"
    blocked_plan["output_project"] = str(blocked_project)
    blocked_plan["workspace"] = str(blocked_workspace)
    blocked = asyncio.run(execute_project_creation_with_mcp(blocked_plan))
    assert blocked["status"] == "failed" and not blocked_project.exists(), blocked
    missing_carbon = json.loads(json.dumps(invest_base))
    missing_carbon["build_arguments"].update({"task_type": "classification_invest", "imagery_periods": [{
        "year": 2020, "path": "inputs/image_2020.tif", "sensor": "landsat_8_oli", "roi": "inputs/training.geojson",
        "accuracy": {"validation_samples": "inputs/validation_2020.csv", "x_field": "x", "y_field": "y",
                     "samples_crs": "EPSG:32650"},
    }]})
    missing_carbon_checked = validate_project_creation_plan(missing_carbon, manifest, output_project, str(workspace))
    assert missing_carbon_checked["status"] == "invalid", missing_carbon_checked
    assert any("missing required input: carbon_density" in item for item in missing_carbon_checked["errors"]), missing_carbon_checked
    complete_invest = json.loads(json.dumps(missing_carbon))
    complete_invest["build_arguments"]["carbon_density"] = "inputs/carbon.csv"
    complete_checked = validate_project_creation_plan(complete_invest, manifest, output_project, str(workspace))
    assert complete_checked["status"] == "valid" and complete_checked["preflight"]["status"] == "valid", complete_checked
    assert "available_inputs" not in project_creation_prompt(manifest, output_project, str(workspace), "create").split("Required returned-plan shape:")[-1]
    assert project_creation_contract(manifest, output_project, str(workspace), "create")["available_inputs"]
    candidate["build_arguments"]["mine_boundary"] = "inputs/invented.gpkg"
    invalid = validate_project_creation_plan(candidate, manifest, output_project, str(workspace))
    assert invalid["status"] == "invalid" and any("not declared" in item for item in invalid["errors"]), invalid
print(json.dumps({"status": "completed", "checks": ["LLM provider config", "local-first endpoint guard", "confirmation-gated plan"]}))
