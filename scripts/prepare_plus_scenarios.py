#!/usr/bin/env python3
"""Prepare all configured PLUS scenarios for one local GUI session without launching it."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from project_workflow import compile_workflow


ROOT = Path(__file__).resolve().parents[1]


def prepare(project_file: Path, output_job: Path | None = None) -> dict[str, Any]:
    compiled = compile_workflow(project_file, output_job)
    job = json.loads(Path(compiled["workflow_job"]).read_text(encoding="utf-8"))
    requests = [stage["request"] for stage in job["stages"]
                if stage.get("adapter") == "plus" and isinstance(stage.get("request"), dict)]
    if not requests:
        raise ValueError("project has no enabled PLUS scenarios")
    prepared: list[dict[str, Any]] = []
    for request in requests:
        envelope = json.loads(json.dumps(request))
        envelope.setdefault("parameters", {})["dry_run"] = True
        process = subprocess.run([sys.executable, str(ROOT / "scripts" / "plus_backend.py")],
                                 input=json.dumps(envelope, ensure_ascii=True), text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                                 errors="replace", check=False)
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or f"PLUS preparation returned {process.returncode}")
        result = json.loads(process.stdout)
        if result.get("status") not in {"prepared", "completed"}:
            raise RuntimeError(result.get("error") or f"PLUS scenario preparation failed: {result.get('status')}")
        prepared.append({"scenario": envelope["parameters"].get("scenario"), "status": result["status"],
                         "outputs": result.get("outputs", []), "message": result.get("message")})
    plus_root = Path(requests[0]["parameters"]["parameters"]["output_directory"]).resolve().parent
    manifest = plus_root / "plus_scenario_handoffs.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    report = {"status": "completed", "project": str(project_file.resolve()), "workflow_job": compiled["workflow_job"],
              "scenarios": prepared, "instruction": "Open PLUS once, complete the prepared scenarios in order, then rerun the project to adopt outputs."}
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["manifest"] = str(manifest)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output-job", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.project.expanduser().resolve(), args.output_job), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
