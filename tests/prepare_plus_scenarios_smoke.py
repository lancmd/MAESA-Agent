"""Prepare all four PLUS hand-offs without launching a PLUS GUI process."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_plus_scenarios import prepare  # noqa: E402


with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as temporary:
    root = Path(temporary); data = root / "data"; data.mkdir()
    for name in ("a.tif", "b.tif", "driver.tif", "subsidence.tif"):
        (data / name).write_bytes(b"placeholder")
    project = {
        "schema_version": 2, "project_id": "prepare-plus-smoke", "workspace": "runtime",
        "security": {"input_roots": ["data"], "output_root": "."},
        "inputs": {"historical_lulc": ["data/a.tif", "data/b.tif"], "driver_factors": {"slope": "data/driver.tif"},
                   "subsidence_depth_raster": "data/subsidence.tif", "imagery": [], "lulc_baseline": None},
        "classification": {"enabled": False},
        "plus": {"enabled": True, "baseline_year": 2020, "target_year": 2025, "scenarios": ["ND", "UD", "EP", "RE"],
                 "resource_extraction": {"core_driver": "subsidence_depth", "core_driver_input": "inputs.subsidence_depth_raster",
                     "core_driver_unit": "m", "core_driver_convention": "positive_down", "requires_master_grid_alignment": True,
                     "additional_driver_factors": [], "w_dat_preprocessing": {}}},
        "invest": {"enabled": False}, "subsidence_water": {"enabled": False}, "ecosystem_service": {"enabled": False},
        "gis_outputs": {"enabled": False}, "validation": {"enabled": False},
    }
    project_file = root / "project.json"; project_file.write_text(json.dumps(project), encoding="utf-8")
    report = prepare(project_file)
    assert [item["scenario"] for item in report["scenarios"]] == ["ND", "UD", "EP", "RE"]
    assert all(item["status"] == "prepared" for item in report["scenarios"])
    assert Path(report["manifest"]).is_file()

print('{"status":"completed","checks":["four scenario hand-offs","no GUI launch"]}')
