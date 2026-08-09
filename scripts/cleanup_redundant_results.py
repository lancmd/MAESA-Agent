"""Remove output-only duplicates after scripts/organize_results.py has run."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

TARGETS = (
    "maps/project1",
    "maps/project2",
    "maps/project3",
    "maps/maesa_results_20260805",
    "maps/论文制图_20260806",
    "maps/论文出图_20260806/PLUS2026",
    "outputs/figures",
    "outputs/论文分析结果_20260806",
    "outputs/论文分析结果_20260807",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True,
                        help="project workspace; this is required because the command removes derived folders")
    args = parser.parse_args()
    root = args.project_root.expanduser().resolve()
    removed: list[str] = []
    for relative in TARGETS:
        target = (root / relative).resolve()
        if target.exists():
            if root not in target.parents:
                raise RuntimeError(f"refusing path outside project root: {target}")
            shutil.rmtree(target)
            removed.append(relative)
    print({"removed": removed})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
