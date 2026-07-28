"""Regression coverage for year-keyed LULC alignment and Sankey transitions."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_builder import build  # noqa: E402
from project_workflow import compile_workflow, configured_lulc_periods  # noqa: E402
from project_validator import validate  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    # Deliberately supply these out of order.  The builder records the explicit
    # year key and the compiler must use it, rather than file-list order.
    supplied = []
    for year in (2025, 2000, 2015):
        path = root / f"lulc_{year}.tif"
        path.write_bytes(b"fixture")
        supplied.append({"year": year, "path": str(path)})
    project_file = root / "project.json"
    build(project_file, "chronological-history", "runtime", task_type="lulc_change_analysis",
          historical_lulc_periods=supplied)
    project = json.loads(project_file.read_text(encoding="utf-8"))
    assert [item["year"] for item in project["inputs"]["historical_lulc_periods"]] == [2000, 2015, 2025]
    assert validate(project_file)["status"] == "valid", validate(project_file)

    # The lower-level loader also remains defensive for a manually assembled
    # job/configuration.  Validation reports an unsorted project, but no
    # consumer may reverse the scientific time axis if it is called directly.
    unsorted_inputs = {"historical_lulc_periods": supplied}
    assert [year for year, _ in configured_lulc_periods(unsorted_inputs, root)] == [2000, 2015, 2025]

    compiled = compile_workflow(project_file)
    job = json.loads(Path(compiled["workflow_job"]).read_text(encoding="utf-8"))
    stages = {item["id"]: item for item in job["stages"]}
    assert stages["analysis_master_grid"]["inputs"][0].endswith("lulc_2025.tif")
    assert {"lulc_sankey_2000_2015", "lulc_sankey_2015_2025"}.issubset(stages)
    first = stages["lulc_sankey_2000_2015"]["command"]
    second = stages["lulc_sankey_2015_2025"]["command"]
    assert first[first.index("--from-year") + 1:first.index("--to-year") + 2] == ["2000", "--to-year", "2015"]
    assert second[second.index("--from-year") + 1:second.index("--to-year") + 2] == ["2015", "--to-year", "2025"]

print('{"status":"completed","checks":["chronological LULC alignment","chronological Sankey transitions"]}')
