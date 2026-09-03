#!/usr/bin/env python3
"""Package final MAESA artifacts and optionally remove superseded derivatives.

The operation is driven by an explicit JSON plan.  It is a dry run unless
``--apply`` is supplied.  Every path is constrained to the project root, and
preserved input roots cannot be used as sources for cleanup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("finalization plan must be a JSON object")
    if not isinstance(payload.get("items"), list) or not payload["items"]:
        raise ValueError("finalization plan requires a non-empty items list")
    return payload


def within(parent: Path, child: Path) -> bool:
    return child == parent or parent in child.parents


def local_path(root: Path, raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty relative path")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError(f"{label} must be relative to the project root: {raw}")
    resolved = (root / candidate).resolve(strict=False)
    if not within(root, resolved):
        raise ValueError(f"{label} escapes the project root: {raw}")
    return resolved


def cleanup_path(root: Path, raw: Any, label: str) -> Path:
    """Return the lexical cleanup entry without following a junction itself."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty relative path")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError(f"{label} must be relative to the project root: {raw}")
    lexical = Path(os.path.abspath(root / candidate))
    if not within(root, lexical):
        raise ValueError(f"{label} escapes the project root: {raw}")
    if lexical.exists() and not (lexical.is_symlink() or is_reparse_point(lexical)):
        resolved = lexical.resolve(strict=True)
        if not within(root, resolved):
            raise ValueError(f"{label} resolves outside the project root: {raw}")
    return lexical


def is_reparse_point(path: Path) -> bool:
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def remove_path(path: Path) -> None:
    if path.is_symlink() or is_reparse_point(path):
        if path.is_dir():
            os.rmdir(path)
        else:
            path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    output = local_path(root, plan.get("output_dir", "final_results"), "output_dir")
    if output == root:
        raise ValueError("output_dir cannot be the project root")
    preserve = [local_path(root, item, "preserve entry") for item in plan.get("preserve", [])]
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(plan["items"]):
        if not isinstance(raw, dict):
            raise ValueError(f"items[{index}] must be an object")
        source = local_path(root, raw.get("source"), f"items[{index}].source")
        destination_raw = raw.get("destination")
        if not isinstance(destination_raw, str) or not destination_raw.strip():
            raise ValueError(f"items[{index}].destination must be a non-empty relative path")
        destination = (output / destination_raw).resolve(strict=False)
        if not within(output, destination):
            raise ValueError(f"items[{index}].destination escapes output_dir")
        mode = raw.get("mode", "copy")
        if mode not in {"copy", "move"}:
            raise ValueError(f"items[{index}].mode must be copy or move")
        if within(output, source):
            raise ValueError(f"items[{index}].source is already inside output_dir")
        items.append({"source": source, "destination": destination, "mode": mode})

    cleanup: list[Path] = []
    for index, raw in enumerate(plan.get("cleanup", [])):
        target = cleanup_path(root, raw, f"cleanup[{index}]")
        if target == root or within(target, output) or within(output, target):
            raise ValueError(f"cleanup target overlaps output_dir: {raw}")
        for protected in preserve:
            if within(target, protected) or within(protected, target):
                raise ValueError(f"cleanup target overlaps preserved input: {raw}")
        cleanup.append(target)
    return {"output": output, "preserve": preserve, "items": items, "cleanup": cleanup}


def transfer(source: Path, destination: Path, mode: str) -> None:
    if not source.exists():
        raise FileNotFoundError(f"planned source does not exist: {source}")
    if destination.exists():
        raise FileExistsError(f"planned destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mode == "move":
        shutil.move(str(source), str(destination))
    elif source.is_dir():
        shutil.copytree(source, destination, copy_function=shutil.copy2)
    else:
        shutil.copy2(source, destination)


def write_manifest(output: Path, with_sha256: bool) -> Path:
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        if path.name == "final_results_manifest.json":
            continue
        row: dict[str, Any] = {
            "path": path.relative_to(output).as_posix(),
            "bytes": path.stat().st_size,
            "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        }
        if with_sha256:
            row["sha256"] = sha256(path)
        files.append(row)
    manifest = output / "final_results_manifest.json"
    manifest.write_text(json.dumps({
        "status": "completed",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "artifact_count": len(files),
        "artifacts": files,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def finalize(project_root: Path, plan_path: Path, apply: bool = False,
             with_sha256: bool = False) -> dict[str, Any]:
    root = project_root.expanduser().resolve(strict=True)
    plan = load_plan(plan_path.expanduser().resolve(strict=True))
    operation = validate(root, plan)
    preview = {
        "status": "ready" if not apply else "running",
        "mode": "apply" if apply else "dry_run",
        "project_root": str(root),
        "output_dir": str(operation["output"]),
        "items": [{"source": str(item["source"]), "destination": str(item["destination"]), "mode": item["mode"]}
                  for item in operation["items"]],
        "cleanup": [str(path) for path in operation["cleanup"]],
        "preserve": [str(path) for path in operation["preserve"]],
    }
    if not apply:
        return preview

    for item in operation["items"]:
        transfer(item["source"], item["destination"], item["mode"])
    for target in operation["cleanup"]:
        if target.exists() or target.is_symlink():
            remove_path(target)
    manifest = write_manifest(operation["output"], with_sha256)
    preview.update(status="completed", manifest=str(manifest))
    return preview


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="perform transfers and cleanup; default is dry-run")
    parser.add_argument("--sha256", action="store_true", help="hash final files; slower for large raster outputs")
    args = parser.parse_args()
    report = finalize(args.project_root, args.plan, args.apply, args.sha256)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
