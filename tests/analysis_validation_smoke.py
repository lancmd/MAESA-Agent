"""Check that the unified analysis-evidence validator accepts a complete report."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analysis_validation import validate_results  # noqa: E402


source = ROOT / "tests" / "fixtures" / "analysis_validation.json"
output = ROOT / "outputs" / "analysis_validation_smoke.json"
report = validate_results(source, output)
assert report["status"] == "completed", report
assert output.exists()
print(json.dumps({"status": report["status"], "output": report["output"]}, ensure_ascii=False))
