"""Confirm that standalone analyses do not demand unrelated project inputs."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_validator import validate  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary); runtime = root / "runtime"
    config = root / "ecosystem.json"; config.write_text(json.dumps({"schema_version": 2, "method": "minmax", "id_field": "unit_id",
        "criteria": [{"field": "service", "direction": "benefit", "weight": 1}], "normalization": {"bounds": {}}}), encoding="utf-8")
    criteria = root / "criteria.csv"; criteria.write_text("unit_id,service\na,1\n", encoding="utf-8")
    ecosystem = {"schema_version": 2, "project_id": "ecosystem-only", "workspace": str(runtime),
        "security": {"input_roots": [str(root)], "output_root": str(runtime)}, "inputs": {},
        "classification": {"enabled": False}, "plus": {"enabled": False}, "invest": {"enabled": False},
        "subsidence_water": {"enabled": False}, "gis_outputs": {"enabled": False},
        "ecosystem_service": {"enabled": True, "method": "minmax", "criteria_table": str(criteria), "config": str(config)}}
    project = root / "ecosystem_project.json"; project.write_text(json.dumps(ecosystem), encoding="utf-8")
    assert validate(project)["status"] == "valid", validate(project)
    dem, depth = root / "dem.tif", root / "depth.tif"; dem.write_bytes(b"dem"); depth.write_bytes(b"depth")
    volume = {"schema_version": 2, "project_id": "volume-only", "workspace": str(runtime),
        "security": {"input_roots": [str(root)], "output_root": str(runtime)},
        "inputs": {"dem": str(dem), "subsidence_depth_raster": str(depth), "elevation_vertical_datum": "CGVD"},
        "classification": {"enabled": False}, "plus": {"enabled": False}, "invest": {"enabled": False},
        "ecosystem_service": {"enabled": False}, "gis_outputs": {"enabled": False},
        "subsidence_water": {"enabled": True, "mode": "estimate_volume", "water_level_elevation_m": 10,
            "water_level_vertical_datum": "CGVD", "output_depth_raster": "outputs/depth.tif", "output_volume_table": "outputs/volume.csv"}}
    project.write_text(json.dumps(volume), encoding="utf-8")
    assert validate(project)["status"] == "valid", validate(project)
print('{"status":"completed","checks":["ecosystem-only","volume-only"]}')
