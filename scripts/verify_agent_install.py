#!/usr/bin/env python3
"""Verify that an installed copy of the mining-area Skill can expose its MCP service."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


REQUIRED_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "mcp_server/mining_mcp_server.py",
    "mcp_server/pyproject.toml",
    "interfaces/backend_registry.example.json",
    "scripts/start_agent_mcp.ps1",
)
REQUIRED_BACKENDS = {"envi", "plus", "arcgis", "invest", "pytorch", "project", "ecosystem"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.skill_root.resolve()
    missing = [item for item in REQUIRED_FILES if not (root / item).is_file()]
    if missing:
        raise SystemExit(f"incomplete Skill installation: {', '.join(missing)}")
    registry_path = root / "interfaces" / "backend_registry.json"
    if not registry_path.exists():
        registry_path = root / "interfaces" / "backend_registry.example.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    backends = set(registry.get("backends", {}))
    absent = sorted(REQUIRED_BACKENDS - backends)
    if absent:
        raise SystemExit(f"backend registry misses: {', '.join(absent)}")
    if importlib.util.find_spec("mcp") is None:
        raise SystemExit("MCP dependency is unavailable; run scripts/setup_agent.ps1")
    print(json.dumps({"status": "ready", "skill_root": str(root), "backends": sorted(backends)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
