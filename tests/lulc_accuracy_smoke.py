"""Exercise OA, F1, IoU, and per-class metrics on a small validation table."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lulc_accuracy import evaluate  # noqa: E402


report = evaluate(ROOT / "tests" / "fixtures" / "lulc_accuracy.csv", "reference", "prediction",
                  ROOT / "outputs" / "lulc_accuracy_smoke.json")
assert abs(report["oa"] - 2 / 3) < 1e-12, report
assert set(report["classes"]) == {"1", "2"}
print(report["oa"])
