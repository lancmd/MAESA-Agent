"""Exercise the non-destructive project readiness report on real tiny rasters."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]


def write_lulc(path: Path) -> None:
    profile = {
        "driver": "GTiff", "height": 2, "width": 2, "count": 1, "dtype": "uint8",
        "crs": "EPSG:32650", "transform": from_origin(500000, 3700000, 30, 30), "nodata": 0,
    }
    with rasterio.open(path, "w", **profile) as target:
        target.write(np.array([[1, 2], [3, 6]], dtype="uint8"), 1)


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    lulc, carbon = root / "lulc.tif", root / "carbon.csv"
    write_lulc(lulc)
    carbon.write_text("lucode,c_above,c_below,c_soil,c_dead\n" +
                      "\n".join(f"{code},1,1,1,0" for code in range(1, 7)) + "\n", encoding="utf-8")
    project = root / "project.json"
    project.write_text(json.dumps({
        "schema_version": 2, "project_id": "readiness-smoke", "task_type": "classification_only",
        "workspace": "runtime", "security": {"input_roots": ["."], "output_root": "."},
        "inputs": {"lulc_baseline": "lulc.tif", "carbon_density": "carbon.csv"},
        "classification": {"enabled": True, "engine": "provided_lulc", "scheme": "standard_6class"},
        "plus": {"enabled": False}, "invest": {"enabled": False}, "subsidence_water": {"enabled": False},
        "ecosystem_service": {"enabled": False}, "gis_outputs": {"enabled": False}, "validation": {"enabled": False},
    }, ensure_ascii=False), encoding="utf-8")
    output = root / "readiness.json"
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "project_readiness.py"),
                              "--project", str(project), "--output", str(output)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    assert process.returncode == 0, process.stdout
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "pending_validation", report
    assert report["spatial_preflight"]["status"] == "completed", report
    assert report["software_readiness"]["missing"] == [], report
    assert any(item["state"] == "present" and item.get("sha256") for item in report["input_inventory"]), report

    envelope = {"operation": "project.inspect_readiness", "parameters": {
        "project_file": str(project), "output_report": str(root / "mcp_readiness.json"),
    }}
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "project_backend.py")], input=json.dumps(envelope),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    assert process.returncode == 0, process.stdout
    result = json.loads(process.stdout)
    assert result["status"] == "pending_validation", result
    assert Path(result["outputs"][0]).is_file(), result

print('{"status":"completed","checks":["project readiness report","spatial evidence","MCP readiness operation"]}')
