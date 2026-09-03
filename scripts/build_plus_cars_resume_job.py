"""Build a traceable CARS-only resume job from a compiled MAESA workflow.

LEAS estimates development suitability from the same historical transition and
driver stack.  When those six potential surfaces have already passed the
non-zero-band contract, each policy scenario can reuse them and run only CARS
with its own land-demand and constraint settings.  This utility keeps that
decision explicit in the runtime job instead of silently copying GUI state.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("stages"), list):
        raise ValueError(f"Not a compiled workflow job: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-job", type=Path, required=True)
    parser.add_argument("--output-job", type=Path, required=True)
    parser.add_argument("--potential-folder", type=Path, required=True)
    parser.add_argument("--scenarios", nargs="+", choices=("ND", "UD", "EP", "RE"), required=True)
    args = parser.parse_args()

    source = args.source_job.expanduser().resolve()
    destination = args.output_job.expanduser().resolve()
    potential_folder = args.potential_folder.expanduser().resolve()
    if not potential_folder.is_dir():
        raise ValueError(f"LEAS potential folder does not exist: {potential_folder}")
    bands = [potential_folder / f"development_potential_band_{code}.tif" for code in range(1, 7)]
    missing = [str(path) for path in bands if not path.is_file()]
    if missing:
        raise ValueError("LEAS potential folder is incomplete: " + ", ".join(missing))

    job = read_json(source)
    selected = set(args.scenarios)
    changed: list[str] = []
    for stage in job["stages"]:
        stage_id = stage.get("id")
        if stage_id not in {f"plus_{scenario}" for scenario in selected}:
            continue
        request = stage.get("request")
        if not isinstance(request, dict):
            raise ValueError(f"PLUS stage has no request envelope: {stage_id}")
        envelope = request.setdefault("parameters", {})
        if not isinstance(envelope, dict):
            raise ValueError(f"PLUS stage has invalid request parameters: {stage_id}")
        detail = envelope.setdefault("parameters", {})
        if not isinstance(detail, dict):
            raise ValueError(f"PLUS stage has invalid detail parameters: {stage_id}")
        settings = detail.setdefault("plus_settings", {})
        if not isinstance(settings, dict):
            raise ValueError(f"PLUS stage has invalid plus settings: {stage_id}")
        settings["phase"] = "cars_only"
        settings["leas_potential_folder"] = str(potential_folder)
        settings["leas_potential_provenance"] = {
            "reused_from_scenario": "ND",
            "reason": "same historical LULC transition and curated driver stack; policy distinction is applied in CARS demand and constraints",
            "required_bands": [str(path) for path in bands],
        }
        changed.append(stage_id)

    if len(changed) != len(selected):
        raise ValueError(f"Missing selected PLUS stages; changed={changed}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_job": str(destination), "cars_only_stages": changed,
                      "leas_potential_folder": str(potential_folder)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
