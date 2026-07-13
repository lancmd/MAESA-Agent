#!/usr/bin/env python3
"""Small local background-job registry for resumable workflow execution."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def job_dir(job_file: Path) -> Path:
    workspace = Path(read_json(job_file)["workspace"]).resolve()
    return workspace / ".jobs"


def record_path(job_file: Path, job_id: str) -> Path:
    return job_dir(job_file) / f"{job_id}.json"


def alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def submit(job_file: Path, dry_run: bool = False, continue_on_error: bool = False,
           confirm_overwrite: bool = False) -> dict[str, Any]:
    job_file = job_file.resolve()
    workspace = Path(read_json(job_file)["workspace"]).resolve()
    job_id = uuid.uuid4().hex
    log = workspace / "logs" / f"background_{job_id}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, str(ROOT / "scripts" / "workflow_agent.py"), "run", "--job", str(job_file)]
    if dry_run:
        args.append("--dry-run")
    if continue_on_error:
        args.append("--continue-on-error")
    if confirm_overwrite:
        args.append("--confirm-overwrite")
    stream = log.open("w", encoding="utf-8")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(args, cwd=workspace, stdout=stream, stderr=subprocess.STDOUT, creationflags=creationflags)
    stream.close()
    record = {"job_id": job_id, "job_file": str(job_file), "workspace": str(workspace), "pid": process.pid,
              "status": "running", "started_at": now(), "heartbeat": now(), "log": str(log),
              "options": {"dry_run": dry_run, "continue_on_error": continue_on_error, "confirm_overwrite": confirm_overwrite}}
    write_json(record_path(job_file, job_id), record)
    return record


def find(job_id: str, root: Path | None = None) -> tuple[Path, dict[str, Any]]:
    search_root = root or Path(os.getenv("MINING_GIS_JOB_ROOT", ROOT / "outputs")).resolve()
    matches = list(search_root.glob(f"**/.jobs/{job_id}.json"))
    if len(matches) != 1:
        raise FileNotFoundError(f"local job record not found: {job_id}")
    return matches[0], read_json(matches[0])


def status(job_id: str) -> dict[str, Any]:
    path, record = find(job_id)
    workspace = Path(record["workspace"])
    state_path = workspace / "agent_state.json"
    state = read_json(state_path) if state_path.is_file() else {"stages": {}}
    stages = state.get("stages", {})
    total = len(read_json(Path(record["job_file"])).get("stages", []))
    done = sum(1 for value in stages.values() if value.get("status") in {"completed", "failed", "prepared", "waiting_interactive", "pending_validation"})
    running = alive(record.get("pid"))
    if running:
        record["status"] = "running"
    elif record.get("status") == "running":
        stage_states = {value.get("status") for value in stages.values()}
        record["status"] = "failed" if "failed" in stage_states else "waiting_interactive" if "waiting_interactive" in stage_states else "completed"
        record["finished_at"] = now()
    if Path(record["log"]).is_file():
        record["heartbeat"] = datetime.fromtimestamp(Path(record["log"]).stat().st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds")
    record["progress"] = done / total if total else 1.0 if record["status"] in {"completed", "cancelled"} else 0.0
    record["stage_statuses"] = stages
    write_json(path, record)
    return record


def cancel(job_id: str) -> dict[str, Any]:
    path, record = find(job_id)
    if alive(record.get("pid")):
        command = ["taskkill", "/PID", str(record["pid"]), "/T", "/F"] if os.name == "nt" else ["kill", "-TERM", str(record["pid"])]
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or "could not cancel local job")
    record.update({"status": "cancelled", "cancelled_at": now()})
    write_json(path, record)
    return record


def outputs(job_id: str) -> dict[str, Any]:
    record = status(job_id)
    workspace = Path(record["workspace"])
    manifest = workspace / "outputs_manifest.json"
    payload = read_json(manifest) if manifest.is_file() else {}
    return {"job_id": job_id, "status": record["status"], "manifest": str(manifest) if manifest.is_file() else None,
            "outputs": payload.get("records", []), "workspace": str(workspace)}
