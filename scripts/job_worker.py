#!/usr/bin/env python3
"""Execute one local workflow job and write an authoritative terminal status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from job_manager import now, read_json, release_lock, write_json
from workflow_agent import JobRunner


def terminal_status(state: dict, return_code: int) -> str:
    values = {item.get("status") for item in state.get("stages", {}).values()}
    if return_code or "failed" in values:
        return "failed"
    for name in ("waiting_interactive", "prepared", "pending_validation"):
        if name in values:
            return name
    return "completed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, type=Path)
    args = parser.parse_args()
    record_path = args.record.expanduser().resolve()
    record = read_json(record_path)
    options = record.get("options", {})
    try:
        runner = JobRunner(Path(record["job_file"]), bool(options.get("dry_run")),
                           bool(options.get("continue_on_error")), bool(options.get("confirm_overwrite")))
        return_code = runner.run()
        state = read_json(runner.state_path) if runner.state_path.exists() else {"stages": {}}
        record.update({"status": terminal_status(state, return_code), "return_code": return_code,
                       "stage_statuses": state.get("stages", {}), "finished_at": now(), "heartbeat": now()})
    except Exception as error:
        record.update({"status": "failed", "error": str(error), "return_code": 1, "finished_at": now()})
        return_code = 1
    finally:
        write_json(record_path, record)
        release_lock(record)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
