"""Exercise criterion-weight sensitivity for the ecosystem-service score."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ecosystem_service import sensitivity_analysis  # noqa: E402


report = sensitivity_analysis(ROOT / "tests" / "fixtures" / "ecosystem_criteria.csv",
                              ROOT / "tests" / "fixtures" / "ecosystem_service_config.json", 0.1,
                              ROOT / "outputs" / "ecosystem_sensitivity_smoke.csv")
assert Path(report["output"]).exists()
assert Path(report["base_scores"]).exists()
print(report["maximum_rank_shift"])
