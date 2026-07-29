#!/usr/bin/env python3
"""Write a readable, model-specific InVEST parameter report before execution.

The report is generated from the exact datastack handed to local InVEST.  It
does not infer carbon density values, threat weights, or ecological
coefficients.  A failed contract is recorded in the report and returns a
non-zero exit code, preventing a model run with an ambiguous input table.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from carbon_density_contract import compare_codes, validate_table
from invest_ecosystem_contract import REQUIRED, resolve, validate as validate_ecosystem


MODEL_TITLES = {
    "carbon": "Carbon Storage and Sequestration",
    "annual_water_yield": "Annual Water Yield",
    "habitat_quality": "Habitat Quality",
    "sediment_delivery_ratio": "Sediment Delivery Ratio",
    "nutrient_delivery_ratio": "Nutrient Delivery Ratio",
}


def read_datastack(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("args"), dict):
        raise ValueError("datastack args must be an object")
    return payload


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def mark(value: bool) -> str:
    return "PASS" if value else "FAIL"


def path_value(value: Any, datastack: Path) -> str:
    resolved = resolve(value, datastack.parent)
    return str(resolved) if resolved else "(not supplied)"


def carbon_sections(datastack: Path, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    lulc = resolve(args.get("lulc_cur_path"), datastack.parent)
    density = resolve(args.get("carbon_pools_path"), datastack.parent)
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[dict[str, str]] = []
    if not lulc:
        errors.append("missing InVEST argument: lulc_cur_path")
    if not density:
        errors.append("missing InVEST argument: carbon_pools_path")
    if density:
        density_report = validate_table(density)
        errors.extend(density_report["errors"])
        warnings.extend(density_report["warnings"])
        try:
            rows = csv_rows(density)
        except (OSError, csv.Error) as error:
            errors.append(f"cannot read carbon density rows: {error}")
    if lulc and density and lulc.exists() and density.exists():
        comparison = compare_codes(lulc, density)
        errors.extend(comparison["errors"])
        warnings.extend(comparison["warnings"])
    else:
        comparison = {"lulc_codes": [], "carbon_codes": [], "missing_carbon_codes": [], "extra_carbon_codes": []}
        if lulc and not lulc.exists():
            errors.append(f"LULC input does not exist: {lulc}")
        if density and not density.exists():
            errors.append(f"carbon density input does not exist: {density}")
    return {
        "status": "completed" if not errors else "failed", "errors": errors, "warnings": warnings,
        "lulc": str(lulc) if lulc else None, "carbon_density": str(density) if density else None,
        "comparison": comparison, "density_rows": rows,
    }, []


def ecosystem_sections(model: str, datastack: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    report = validate_ecosystem(model, datastack)
    return report, read_datastack(datastack)["args"]


def render(model: str, datastack: Path) -> tuple[dict[str, Any], str]:
    payload = read_datastack(datastack)
    args = payload["args"]
    lines = ["# InVEST parameter report", "", f"Model: {MODEL_TITLES[model]}",
             f"Datastack: `{datastack.resolve()}`", ""]
    if model == "carbon":
        result, _ = carbon_sections(datastack, args)
        comparison = result["comparison"]
        lines.extend(["## Carbon model", "", f"LULC: `{result['lulc'] or '(not supplied)'}`",
                      f"Carbon density source: user supplied CSV `{result['carbon_density'] or '(not supplied)'}`",
                      "Unit: Mg C/ha", "", "### LULC classes", "",
                      "| Raster codes | Carbon-table codes | Missing density codes | Extra density codes |",
                      "|---|---|---|---|",
                      "| " + " / ".join(map(str, comparison.get("lulc_codes", []))) + " | " +
                      " / ".join(map(str, comparison.get("carbon_codes", []))) + " | " +
                      " / ".join(map(str, comparison.get("missing_carbon_codes", []))) + " | " +
                      " / ".join(map(str, comparison.get("extra_carbon_codes", []))) + " |", "",
                      "### Carbon density", "",
                      "| lucode | c_above | c_below | c_soil | c_dead |", "|---:|---:|---:|---:|---:|"])
        for row in result["density_rows"]:
            lines.append("| {lucode} | {c_above} | {c_below} | {c_soil} | {c_dead} |".format(
                lucode=row.get("lucode", ""), c_above=row.get("c_above", ""), c_below=row.get("c_below", ""),
                c_soil=row.get("c_soil", ""), c_dead=row.get("c_dead", "")))
    else:
        result, args = ecosystem_sections(model, datastack)
        lines.extend(["## Model inputs", ""])
        for key in REQUIRED[model]:
            value = args.get(key)
            shown = path_value(value, datastack) if key.endswith("_path") else str(value)
            lines.append(f"- `{key}`: {shown}")
        if model == "habitat_quality":
            threats = resolve(args.get("threats_table_path"), datastack.parent)
            lines.extend(["", "### Habitat threats", "", "| Threat | Max distance | Weight | Decay |", "|---|---:|---:|---|"])
            if threats and threats.exists():
                for row in csv_rows(threats):
                    lines.append("| {threat} | {max_dist} | {weight} | {decay} |".format(
                        threat=row.get("threat", ""), max_dist=row.get("max_dist", ""),
                        weight=row.get("weight", ""), decay=row.get("decay", "")))
            else:
                lines.append("| (unavailable) |  |  |  |")
    lines.extend(["", "## Validation", "", f"Status: **{mark(result['status'] == 'completed')}**"])
    if result["warnings"]:
        lines.extend(["", "Warnings:"] + [f"- {item}" for item in result["warnings"]])
    if result["errors"]:
        lines.extend(["", "Errors:"] + [f"- {item}" for item in result["errors"]])
    lines.append("")
    return result, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=sorted(MODEL_TITLES))
    parser.add_argument("--datastack", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result, text = render(args.model, args.datastack.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()),
                      "errors": result["errors"], "warnings": result["warnings"]}, ensure_ascii=False))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
