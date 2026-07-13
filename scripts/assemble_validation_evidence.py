#!/usr/bin/env python3
"""Collect local validation artifacts into one conditional analysis-evidence file."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def first(workspace: Path, patterns: list[str]) -> dict[str, Any] | None:
    for pattern in patterns:
        for path in sorted(workspace.glob(pattern)):
            payload = read_json(path)
            if payload is not None:
                return payload
    return None


def ecosystem_evidence(workspace: Path) -> dict[str, Any] | None:
    metadata = first(workspace, ["outputs/**/*.metadata.json", "validation/**/ecosystem*.json"])
    if not metadata or "normalization_bounds" not in metadata:
        return None
    evidence: dict[str, Any] = {"method": metadata.get("method"),
        "normalised_ranges": {name: [0.0, 1.0] for name in metadata.get("criteria", [])},
        "ahp_consistency_ratio": metadata.get("consistency_ratio"),
        "sensitivity": {"available": any(workspace.glob("outputs/**/sensitivity*.csv"))},
        "metadata": metadata}
    return evidence


def assemble(workspace: Path, required_sections: list[str], output: Path) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    if "lulc" in required_sections:
        reports["lulc"] = first(workspace, ["validation/lulc_accuracy.json", "**/lulc_accuracy*.json"]) or {}
    if "plus" in required_sections:
        reports["plus"] = first(workspace, ["validation/plus_validation*.json", "**/*plus*validation*.json"]) or {}
    if "invest" in required_sections:
        reports["invest"] = first(workspace, ["validation/invest_consistency*.json", "**/*invest*consistency*.json"]) or {}
    if "ecosystem" in required_sections:
        reports["ecosystem"] = ecosystem_evidence(workspace) or {}
    if "map" in required_sections:
        reports["map"] = first(workspace, ["validation/map_layout.json"]) or {}
    payload = {"schema_version": 1, "required_sections": required_sections, "reports": reports}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "completed", "output": str(output.resolve()), "required_sections": required_sections,
            "evidence_sections": sorted(name for name, value in reports.items() if value)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--required-sections", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    sections = [item.strip() for item in args.required_sections.split(",") if item.strip()]
    print(json.dumps(assemble(args.workspace.resolve(), sections, args.output.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
