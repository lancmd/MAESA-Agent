"""Exercise safe result packaging, dry-run and protected-input cleanup."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(project: Path, plan: Path, apply: bool = False) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(ROOT / "scripts" / "finalize_project_results.py"),
               "--project-root", str(project), "--plan", str(plan)]
    if apply:
        command.append("--apply")
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


with tempfile.TemporaryDirectory() as temporary:
    project = Path(temporary)
    (project / "imagery").mkdir()
    (project / "imagery" / "source.tif").write_bytes(b"raw")
    (project / "results_current").mkdir()
    (project / "results_current" / "map.png").write_bytes(b"figure")
    (project / "reports").mkdir()
    (project / "reports" / "final.docx").write_bytes(b"report")
    (project / "stale").mkdir()
    (project / "stale" / "old.txt").write_text("old", encoding="utf-8")

    plan = project / "plan.json"
    plan.write_text(json.dumps({
        "output_dir": "final_results",
        "preserve": ["imagery"],
        "items": [
            {"source": "results_current", "destination": "figures", "mode": "move"},
            {"source": "reports/final.docx", "destination": "report/final.docx", "mode": "copy"},
        ],
        "cleanup": ["stale"],
    }), encoding="utf-8")

    preview = run(project, plan)
    assert preview.returncode == 0, preview.stdout
    assert not (project / "final_results").exists()
    assert (project / "stale").exists()

    applied = run(project, plan, apply=True)
    assert applied.returncode == 0, applied.stdout
    assert (project / "final_results" / "figures" / "map.png").is_file()
    assert (project / "final_results" / "report" / "final.docx").is_file()
    assert (project / "final_results" / "final_results_manifest.json").is_file()
    assert not (project / "results_current").exists()
    assert not (project / "stale").exists()
    assert (project / "imagery" / "source.tif").is_file()

    unsafe = project / "unsafe.json"
    unsafe.write_text(json.dumps({
        "output_dir": "another_result",
        "preserve": ["imagery"],
        "items": [{"source": "reports/final.docx", "destination": "final.docx"}],
        "cleanup": ["imagery"],
    }), encoding="utf-8")
    rejected = run(project, unsafe)
    assert rejected.returncode != 0
    assert (project / "imagery" / "source.tif").is_file()

print('{"status":"completed","checks":["dry run","safe packaging","protected input cleanup rejection"]}')
