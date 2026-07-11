"""Keep the protocol status vocabulary consistent across code, templates, and documentation."""

from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"accepted", "running", "completed", "prepared", "pending_validation",
           "waiting_interactive", "failed", "cancelled"}
TEXT_SUFFIXES = {".md", ".json", ".csv", ".py", ".yaml", ".yml", ".ps1", ".toml", ".pro"}

bare_pending = []
for path in ROOT.rglob("*"):
    if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
        continue
    if path.resolve() == Path(__file__).resolve():
        continue
    if any(part in {".git", ".venv", "outputs", "__pycache__"} for part in path.parts):
        continue
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if re.search(r"(?<!_)\bpending\b(?!_)", text):
        bare_pending.append(str(path.relative_to(ROOT)))
assert not bare_pending, f"bare pending status found: {bare_pending}"

with (ROOT / "templates" / "plus_scenario_rules.csv").open("r", encoding="utf-8-sig", newline="") as stream:
    values = {row["status"] for row in csv.DictReader(stream)}
assert values <= ALLOWED, values

protocol = (ROOT / "interfaces" / "backend_protocol.md").read_text(encoding="utf-8")
for status in ALLOWED:
    assert f"`{status}`" in protocol, f"protocol omits {status}"
print("status vocabulary is consistent")
