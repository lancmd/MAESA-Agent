"""Verify both Min-Max and consistent AHP ecosystem-service scores."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ecosystem_service import evaluate  # noqa: E402


workspace = ROOT / "outputs" / "ecosystem_smoke"
workspace.mkdir(parents=True, exist_ok=True)
table = workspace / "criteria.csv"
with table.open("w", encoding="utf-8", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["unit_id", "scenario", "carbon_storage_t_c", "annual_water_yield_m3", "habitat_quality"])
    writer.writerows([["A", "ND", 100, 30, 0.7], ["B", "EP", 50, 60, 0.9]])
for method in ("minmax", "ahp"):
    config = json.loads((ROOT / "templates" / "ecosystem_service_config.json").read_text(encoding="utf-8"))
    config["method"] = method
    config["passthrough_fields"] = ["scenario"]
    config["criteria"][0]["weight"] = 0.4
    config["criteria"][1]["weight"] = 0.3
    config["criteria"][2]["weight"] = 0.3
    config["ahp"]["pairwise_matrix"] = [[1, 2, 2], [0.5, 1, 1], [0.5, 1, 1]]
    config_path = workspace / f"{method}.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output = workspace / f"{method}.csv"
    report = evaluate(table, config_path, output)
    assert output.exists() and report["method"] == method
    if method == "ahp":
        assert report["consistency_ratio"] is not None and report["consistency_ratio"] <= 0.1
print("ecosystem smoke passed")
