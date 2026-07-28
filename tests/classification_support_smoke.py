"""Exercise sensor parameter selection and dependency-light ROI sample checks."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from classification_profiles import profile  # noqa: E402
from roi_quality import inspect  # noqa: E402


l5 = profile("Landsat 5", "maximum_likelihood")
assert l5["sensor_id"] == "landsat_5_tm" and l5["source_bands"][-1] == "SR_B7", l5
l8 = profile("landsat_8_oli", "minimum_distance", "standard_6class")
assert l8["classification_method"]["method"] == "minimum_distance" and l8["class_codes"] == [1, 2, 3, 4, 5, 6], l8
s2 = profile("Sentinel-2")
assert s2["classification_resolution_m"] == 10 and s2["post_classification_to_analysis_grid"] == "majority_10m_to_30m", s2
try:
    profile("MODIS")
except ValueError:
    pass
else:
    raise AssertionError("unknown sensor should fail")

fixture = ROOT / "tests" / "fixtures" / "roi_quality.geojson"
report = inspect(fixture, "class_id", role_field="sample_role", expected_classes=[1, 2], minimum_rois_per_class=1)
assert report["status"] == "completed" and report["validation_status"] == "completed", report
assert report["class_counts"] == {"1": 2, "2": 2}, report
mixed_training = inspect(fixture, "class_id", role_field="sample_role", expected_classes=[1, 2],
                         minimum_rois_per_class=1, require_training_only=True)
assert mixed_training["status"] == "failed" and any("non-training role" in item for item in mixed_training["errors"]), mixed_training
xml = inspect(ROOT / "tests" / "fixtures" / "roi_quality_envi.xml", "class_id", expected_classes=["water", "built_up"],
              minimum_rois_per_class=1)
assert xml["status"] == "completed" and xml["reader"] == "envi_roi_xml", xml
assert xml["class_counts"] == {"built_up": 1, "water": 2} and xml["validation_status"] == "pending_validation", xml
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    bad = root / "bad.geojson"
    bad.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"class_id": 1}, "geometry": None},
    ]}), encoding="utf-8")
    failed = inspect(bad, "class_id", expected_classes=[1, 2], minimum_rois_per_class=1)
    assert failed["status"] == "failed" and "expected classes absent" in failed["errors"][0], failed
    output = root / "roi_quality.json"
    envelope = {"protocol_version": "1.0", "operation": "classification.roi_quality", "parameters": {
        "roi_file": str(fixture), "output": str(output), "class_field": "class_id", "role_field": "sample_role",
        "expected_classes": [1, 2], "minimum_rois_per_class": 1,
    }}
    environment = dict(__import__("os").environ)
    environment["MINING_GIS_INPUT_ROOTS"] = str(ROOT)
    environment["MINING_GIS_OUTPUT_ROOT"] = str(root)
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "classification_backend.py")], input=json.dumps(envelope),
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                             env=environment, check=False)
    assert process.returncode == 0, process.stderr
    backend = json.loads(process.stdout)
    assert backend["status"] == "completed" and output.is_file(), backend
print(json.dumps({"status": "completed", "checks": ["sensor profiles", "ROI coverage", "local classification backend"]}))
