"""Write output inventory, reproducibility provenance, and validation summary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def directory_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256(); total = 0
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(str(child.relative_to(path)).replace("\\", "/").encode("utf-8"))
        digest.update(sha256(child).encode("ascii")); total += child.stat().st_size
    return digest.hexdigest(), total


def raster_metadata(path: Path) -> dict[str, Any] | None:
    if path.suffix.lower() not in {".tif", ".tiff", ".img", ".dat"}:
        return None
    try:
        from spatial_preflight import inspect_raster
        info = inspect_raster(path)
        return {key: info.get(key) for key in ("crs", "width", "height", "transform", "nodata", "dtypes")}
    except Exception as error:
        return {"inspection_error": str(error)}


def file_record(path: Path, stage: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"path": str(path.resolve()), "stage": stage, "exists": path.exists()}
    if path.is_file():
        record.update({"type": path.suffix.lower().lstrip(".") or "file", "bytes": path.stat().st_size,
                       "sha256": sha256(path)})
        spatial = raster_metadata(path)
        if spatial is not None:
            record["spatial"] = spatial
    elif path.is_dir():
        digest, total = directory_sha256(path)
        record.update({"type": "directory", "bytes": total, "sha256": digest})
    return record


def _input_records(job: dict[str, Any]) -> list[dict[str, Any]]:
    values: dict[str, None] = {}
    for stage in job.get("stages", []):
        for raw in stage.get("inputs", []):
            try:
                path = Path(str(raw)).expanduser().resolve()
                if path.exists():
                    values[str(path)] = None
            except OSError:
                pass
    return [file_record(Path(path)) for path in sorted(values)]


def write_records(workspace: Path, job: dict[str, Any], state: dict[str, Any], software: dict[str, Any]) -> dict[str, str]:
    workspace = workspace.resolve()
    declared: dict[str, str] = {}
    for stage in job.get("stages", []):
        for raw in stage.get("outputs", []):
            path = Path(str(raw)).expanduser().resolve()
            declared[str(path)] = str(stage.get("id"))
    for stage_id, record in state.get("stages", {}).items():
        for raw in record.get("outputs", []) or []:
            path = Path(str(raw)).expanduser().resolve()
            declared[str(path)] = stage_id
    artifacts = [file_record(Path(path), stage) for path, stage in sorted(declared.items())]
    manifest = {"schema_version": 1, "project_id": job.get("project_id"), "workspace": str(workspace),
                "artifacts": artifacts}
    manifest_path = workspace / "outputs_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provenance = {
        "schema_version": 1, "project_id": job.get("project_id"), "job_sha256": sha256(Path(job["_path"])) if job.get("_path") else None,
        "inputs": _input_records(job), "software": software, "stages": state.get("stages", {}),
        "parameters": [{"id": item.get("id"), "request": item.get("request"), "command": item.get("command"),
                        "random_seed": item.get("random_seed")} for item in job.get("stages", [])],
    }
    provenance_path = workspace / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validation_files = []
    for path in sorted((workspace / "validation").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            validation_files.append({"path": str(path.resolve()), "status": payload.get("status"),
                                     "errors": payload.get("errors", [])})
        except (OSError, json.JSONDecodeError) as error:
            validation_files.append({"path": str(path.resolve()), "status": "unreadable", "error": str(error)})
    summary = {"schema_version": 1, "project_id": job.get("project_id"), "stage_statuses": {
        key: value.get("status") for key, value in state.get("stages", {}).items()}, "validation_files": validation_files}
    summary_path = workspace / "validation_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"outputs_manifest": str(manifest_path), "provenance": str(provenance_path),
            "validation_summary": str(summary_path)}
