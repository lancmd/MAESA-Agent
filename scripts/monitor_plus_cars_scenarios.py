"""Controlled local continuation for long-running CARS scenarios.

It only advances after PLUS has written a candidate GeoTIFF.  Each result is
adopted through the normal bridge, spatially validated, and checked against
the requested six-class demand before the next scenario is launched.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


def run(command: list[str], log: Path) -> None:
    process = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write("\n$ " + " ".join(command) + "\n" + (process.stdout or "") + "\n")
    if process.returncode:
        raise RuntimeError(f"command failed ({process.returncode}): {' '.join(command)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--demand-manifest", type=Path, required=True)
    parser.add_argument("--scenarios", nargs="+", choices=("ND", "UD", "EP", "RE"), required=True)
    parser.add_argument("--poll-seconds", type=int, default=20)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    log = workspace / "logs" / "plus_cars_continuation.log"
    status_path = workspace / "generated" / "plus_cars_continuation_status.json"
    for scenario in args.scenarios:
        output_dir = workspace / "outputs" / "plus_harmonized_v2" / scenario
        expected = output_dir / f"PLUS_{scenario}.tif"
        report = output_dir / "plus_land_demand_validation.json"
        while not expected.is_file():
            candidate = list(output_dir.glob(f"PLUS_{scenario}_candidateSimulation_*.tif"))
            if candidate:
                run([args.python, "scripts/workflow_agent.py", "run", "--job", str(args.job), "--stage", f"plus_{scenario}", "--continue-on-error"], log)
                continue
            run([args.python, "scripts/workflow_agent.py", "run", "--job", str(args.job), "--stage", f"plus_{scenario}", "--continue-on-error"], log)
            time.sleep(max(5, args.poll_seconds))
        run([args.python, "scripts/workflow_agent.py", "run", "--job", str(args.job), "--stage", f"plus_output_validation_{scenario}", "--continue-on-error"], log)
        run([args.python, "scripts/validate_plus_land_demand.py", "--raster", str(expected), "--demand-manifest", str(args.demand_manifest), "--scenario", scenario, "--output", str(report)], log)
        status_path.write_text(json.dumps({"status": "completed", "last_completed": scenario,
                                           "expected_output": str(expected), "demand_report": str(report)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
