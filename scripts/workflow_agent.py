#!/usr/bin/env python3
"""Cross-software workflow runner for the mining LULC/carbon skill."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def first_existing(candidates: list[str | None]) -> str | None:
    for item in candidates:
        if item and Path(item).exists():
            return str(Path(item).resolve())
    return None


def probe_software(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    overrides = overrides or {}
    path_candidates = {
        "arcgis_propy": [
            overrides.get("arcgis_propy"), os.getenv("ARCGIS_PROPY"),
            shutil.which("propy.bat"),
            r"E:\ArcgisPro3.01\PRO\bin\Python\Scripts\propy.bat",
            r"C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat",
        ],
        "arcgis_pro": [
            overrides.get("arcgis_pro"), os.getenv("ARCGIS_PRO_EXE"),
            r"E:\ArcgisPro3.01\PRO\bin\ArcGISPro.exe",
            r"C:\Program Files\ArcGIS\Pro\bin\ArcGISPro.exe",
        ],
        "invest": [
            overrides.get("invest"), os.getenv("INVEST_CLI"), shutil.which("invest"),
            r"E:\InVEST_3.12.1_x64\invest-3-x64\invest.exe",
        ],
        "idl": [
            overrides.get("idl"), os.getenv("IDL_EXE"), shutil.which("idl"),
            r"C:\ruanjian\envi5.6\ENVI56\IDL88\bin\bin.x86_64\idl.exe",
        ],
        "plus": [overrides.get("plus"), os.getenv("PLUS_EXE")],
        "gdalinfo": [
            overrides.get("gdalinfo"), os.getenv("GDALINFO"), shutil.which("gdalinfo"),
        ],
    }
    result: dict[str, Any] = {"probed_at": now(), "platform": sys.platform, "software": {}}
    for name, candidates in path_candidates.items():
        executable = first_existing(candidates)
        result["software"][name] = {"available": bool(executable), "path": executable}
    return result


class JobRunner:
    def __init__(self, job_path: Path, dry_run: bool = False, continue_on_error: bool = False):
        self.job_path = job_path.resolve()
        self.job_dir = self.job_path.parent
        self.job = load_json(self.job_path)
        if self.job.get("schema_version") != 1:
            raise ValueError("Only workflow job schema_version 1 is supported")
        self.workspace = self.resolve(self.job.get("workspace", "outputs/job"), self.job_dir)
        self.workspace.mkdir(parents=True, exist_ok=True)
        for folder in ("logs", "generated", "intermediate", "outputs", "validation"):
            (self.workspace / folder).mkdir(exist_ok=True)
        self.state_path = self.workspace / "agent_state.json"
        self.state = load_json(self.state_path) if self.state_path.exists() else {
            "project_id": self.job.get("project_id"), "created_at": now(), "stages": {}
        }
        self.probe = probe_software(self.job.get("software"))
        write_json(self.workspace / "software_probe.json", self.probe)
        self.dry_run = dry_run
        self.continue_on_error = continue_on_error

    @staticmethod
    def resolve(value: str, base: Path) -> Path:
        path = Path(os.path.expandvars(value)).expanduser()
        return path.resolve() if path.is_absolute() else (base / path).resolve()

    def stage_path(self, value: str) -> Path:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.is_absolute():
            return path.resolve()
        job_candidate = (self.job_dir / path).resolve()
        if job_candidate.exists():
            return job_candidate
        root_candidate = (ROOT / path).resolve()
        if root_candidate.exists():
            return root_candidate
        return (self.workspace / path).resolve()

    def save_state(self) -> None:
        self.state["updated_at"] = now()
        write_json(self.state_path, self.state)

    def declared_outputs_exist(self, stage: dict[str, Any]) -> bool:
        outputs = stage.get("outputs", [])
        return bool(outputs) and all(self.stage_path(item).exists() for item in outputs)

    def validate_stage(self, stage: dict[str, Any]) -> list[str]:
        errors = []
        if not stage.get("id") or not stage.get("adapter"):
            errors.append("stage requires id and adapter")
        for value in stage.get("inputs", []):
            if "replace_" in value or not self.stage_path(value).exists():
                errors.append(f"missing input: {value}")
        adapter = stage.get("adapter")
        required = {"arcgis": "arcgis_propy", "invest": "invest", "envi": "idl"}.get(adapter)
        if required and not self.probe["software"][required]["available"]:
            errors.append(f"software unavailable: {required}")
        return errors

    def plan(self) -> dict[str, Any]:
        stages = []
        for stage in self.job.get("stages", []):
            if not stage.get("enabled", False):
                status, issues = "disabled", []
            else:
                issues = self.validate_stage(stage)
                status = "blocked" if issues else "ready"
            stages.append({"id": stage.get("id"), "adapter": stage.get("adapter"),
                           "status": status, "issues": issues})
        return {"project_id": self.job.get("project_id"), "workspace": str(self.workspace),
                "software": self.probe["software"], "stages": stages}

    def command(self, stage_id: str, args: list[str], env: dict[str, str] | None = None) -> dict[str, Any]:
        log_path = self.workspace / "logs" / f"{stage_id}.log"
        if self.dry_run:
            return {"status": "prepared", "command": args, "log": f"logs/{stage_id}.log", "dry_run": True}
        process = subprocess.run(args, cwd=self.workspace, env=env, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 encoding="utf-8", errors="replace", check=False)
        log_path.write_text(process.stdout or "", encoding="utf-8")
        if process.returncode:
            raise RuntimeError(f"command returned {process.returncode}; see {log_path}")
        return {"status": "completed", "command": args, "returncode": process.returncode,
                "log": f"logs/{stage_id}.log"}

    def run_arcgis(self, stage: dict[str, Any]) -> dict[str, Any]:
        propy = self.probe["software"]["arcgis_propy"]["path"]
        spec = self.stage_path(stage["spec"])
        return self.command(stage["id"], [propy, str(ROOT / "scripts" / "arcgis_ops.py"), "--spec", str(spec),
                                           "--workspace", str(self.workspace)])

    def run_invest(self, stage: dict[str, Any]) -> dict[str, Any]:
        executable = self.probe["software"]["invest"]["path"]
        datastack = self.stage_path(stage["datastack"])
        model_workspace = self.stage_path(stage.get("model_workspace", f"outputs/{stage['id']}"))
        model_workspace.mkdir(parents=True, exist_ok=True)
        args = [executable, "run", stage.get("model", "carbon"), "-l", "-d", str(datastack),
                "-w", str(model_workspace)]
        return self.command(stage["id"], args)

    def run_envi(self, stage: dict[str, Any]) -> dict[str, Any]:
        executable = self.probe["software"]["idl"]["path"]
        batch = self.stage_path(stage.get("batch_file", "scripts/envi_maximum_likelihood.pro"))
        entrypoint = stage.get("entrypoint", "mining_envi_maximum_likelihood")
        env = os.environ.copy()
        env.update({str(key): str(self.stage_path(value)) for key, value in stage.get("env", {}).items()})
        expression = f".run '{batch.as_posix()}' & {entrypoint} & exit"
        return self.command(stage["id"], [executable, "-e", expression], env=env)

    def run_plus(self, stage: dict[str, Any]) -> dict[str, Any]:
        executable = stage.get("executable") or self.probe["software"]["plus"]["path"]
        if stage.get("command_args"):
            if not executable:
                raise RuntimeError("PLUS executable is unavailable")
            return self.command(stage["id"], [executable, *map(str, stage["command_args"])])
        if stage.get("launch_gui") and executable:
            if self.dry_run:
                return {"status": "prepared", "command": [executable], "dry_run": True}
            subprocess.Popen([executable], cwd=self.workspace)
            return {"status": "waiting_interactive", "reason": "PLUS GUI launched"}
        return {"status": "prepared", "reason": "inputs prepared; no verified PLUS automation entry supplied"}

    def run_command(self, stage: dict[str, Any]) -> dict[str, Any]:
        return self.command(stage["id"], [str(item) for item in stage["command"]])

    def run(self, selected_stage: str | None = None) -> int:
        failures = 0
        enabled_ids = {item["id"] for item in self.job.get("stages", []) if item.get("enabled")}
        for stage in self.job.get("stages", []):
            stage_id = stage.get("id", "unnamed")
            if not stage.get("enabled") or (selected_stage and stage_id != selected_stage):
                continue
            previous = self.state["stages"].get(stage_id, {})
            if previous.get("status") == "completed" and self.declared_outputs_exist(stage):
                print(f"SKIP {stage_id}: completed outputs still exist")
                continue
            dependencies = stage.get("depends_on", [])
            bad_dependencies = [item for item in dependencies if item not in enabled_ids or
                                self.state["stages"].get(item, {}).get("status") != "completed"]
            errors = self.validate_stage(stage)
            if bad_dependencies:
                errors.append(f"dependencies not completed: {', '.join(bad_dependencies)}")
            record: dict[str, Any] = {"adapter": stage.get("adapter"), "started_at": now()}
            self.state["stages"][stage_id] = record
            self.save_state()
            try:
                if errors:
                    raise RuntimeError("; ".join(errors))
                adapter = stage["adapter"]
                handler = getattr(self, f"run_{adapter}", None)
                if handler is None:
                    raise ValueError(f"unsupported adapter: {adapter}")
                result = handler(stage)
                record.update(result)
                if record["status"] == "completed" and stage.get("outputs") and not self.declared_outputs_exist(stage):
                    raise RuntimeError("command succeeded but one or more declared outputs are missing")
                print(f"{record['status'].upper()} {stage_id}")
            except Exception as error:
                record.update({"status": "failed", "error": str(error)})
                failures += 1
                print(f"FAILED {stage_id}: {error}", file=sys.stderr)
            finally:
                record["finished_at"] = now()
                self.save_state()
            if failures and not self.continue_on_error:
                break
        return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    probe = sub.add_parser("probe", help="detect supported software")
    probe.add_argument("--output", type=Path)
    for name in ("plan", "run"):
        command = sub.add_parser(name)
        command.add_argument("--job", required=True, type=Path)
        if name == "run":
            command.add_argument("--stage")
            command.add_argument("--dry-run", action="store_true")
            command.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()
    if args.action == "probe":
        result = probe_software()
        if args.output:
            write_json(args.output.resolve(), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    runner = JobRunner(args.job, getattr(args, "dry_run", False),
                       getattr(args, "continue_on_error", False))
    if args.action == "plan":
        print(json.dumps(runner.plan(), ensure_ascii=False, indent=2))
        return 0
    return runner.run(args.stage)


if __name__ == "__main__":
    raise SystemExit(main())
