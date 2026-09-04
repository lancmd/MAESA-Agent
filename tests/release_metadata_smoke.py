"""Keep source, package, licence and change records aligned for a release."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
package = tomllib.loads((ROOT / "mcp_server" / "pyproject.toml").read_text(encoding="utf-8"))
assert version == package["project"]["version"] == "0.6.0"
assert "MIT License" in (ROOT / "LICENSE").read_text(encoding="utf-8")
assert version in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

guides = [
    "project.md", "classification.md", "spatial.md", "plus.md",
    "invest-ecosystem.md", "runtime.md", "reference-data.md", "results.md",
]
for guide in guides:
    assert (ROOT / "docs" / guide).is_file(), guide

for legacy_directory in ("arcgis_steps", "envi_classification", "plus_model", "invest_carbon",
                         "ecosystem_service", "open_gis_workflows", "execution"):
    assert not list((ROOT / legacy_directory).glob("*.md")), legacy_directory

entry_points = ((ROOT / "README.md").read_text(encoding="utf-8") +
                (ROOT / "SKILL.md").read_text(encoding="utf-8"))
assert "docs/project.md" in entry_points and "docs/invest-ecosystem.md" in entry_points
assert "plus_model/" not in entry_points and "arcgis_steps/" not in entry_points
assert (ROOT / "scripts" / "project_readiness.py").is_file()
assert (ROOT / "scripts" / "finalize_project_results.py").is_file()
assert (ROOT / "scripts" / "workflow_runner.py").is_file()
assert (ROOT / "scripts" / "setup_skill.ps1").is_file()
example_directories = {path.name for path in (ROOT / "examples").iterdir() if path.is_dir()}
assert example_directories <= {"real_project_template", "synthetic_multiperiod"}
assert (ROOT / "templates" / "final_results_plan.example.json").is_file()
assert "project.inspect_readiness" in (ROOT / "interfaces" / "backend_registry.example.json").read_text(encoding="utf-8")
assert "project.finalize_results" in (ROOT / "interfaces" / "backend_registry.example.json").read_text(encoding="utf-8")
print('{"status":"completed","checks":["version","license","changelog","documentation-surface"]}')
