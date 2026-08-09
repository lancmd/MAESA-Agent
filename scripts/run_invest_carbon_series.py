#!/usr/bin/env python3
"""Run InVEST Carbon for a dated local LULC series with an auditable manifest.

The source LULC rasters and carbon-pool table are treated as read-only.  A
resolved Carbon datastack is written per year below the output directory so an
InVEST result can be rerun without depending on the current shell session.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = ("lucode", "c_above", "c_below", "c_soil", "c_dead")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_lulc(items: list[str]) -> list[tuple[int, Path]]:
    parsed: list[tuple[int, Path]] = []
    seen: set[int] = set()
    for raw in items:
        year_text, separator, source_text = raw.partition("=")
        if not separator:
            raise ValueError("--lulc must use YEAR=PATH")
        year = int(year_text)
        source = Path(source_text).expanduser().resolve()
        if year in seen or not source.is_file():
            raise ValueError(f"invalid or duplicate LULC input: {raw}")
        seen.add(year)
        parsed.append((year, source))
    if not parsed:
        raise ValueError("at least one --lulc input is required")
    return sorted(parsed)


def pool_codes(path: Path) -> set[int]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if any(field not in (reader.fieldnames or []) for field in REQUIRED_FIELDS):
            raise ValueError("carbon table is missing a required InVEST Carbon field")
        return {int(float(str(row["lucode"]))) for row in reader}


def raster_codes(path: Path) -> tuple[set[int], dict[str, Any]]:
    try:
        import numpy as np
        import rasterio
    except ImportError as error:
        raise RuntimeError("the MAESA virtual environment needs rasterio and numpy") from error
    with rasterio.open(path) as source:
        if not source.crs or not source.crs.is_projected:
            raise ValueError(f"LULC has no projected CRS: {path}")
        if not any(token in source.dtypes[0] for token in ("int", "uint")):
            raise ValueError(f"LULC must use an integer data type: {path}")
        values: set[int] = set()
        nodata = source.nodata
        for _, window in source.block_windows(1):
            block = source.read(1, window=window, masked=False)
            valid = np.isfinite(block)
            if nodata is not None:
                valid &= block != nodata
            if valid.any():
                values.update(int(item) for item in np.unique(block[valid]))
        signature = {
            "crs": str(source.crs), "width": source.width, "height": source.height,
            "resolution": [abs(float(source.transform.a)), abs(float(source.transform.e))],
            "nodata": nodata,
        }
    if not values:
        raise ValueError(f"LULC has no valid classes: {path}")
    return values, signature


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def named_pool_copy(source: Path, destination: Path) -> Path:
    names = {
        "1": "subsidence_water", "2": "natural_water", "3": "built_up",
        "4": "cropland", "5": "forest", "6": "grassland",
    }
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if "LULC_Name" not in fields:
        fields.insert(1, "LULC_Name")
    for row in rows:
        row["LULC_Name"] = row.get("LULC_Name") or names.get(str(row.get("lucode", "")).strip(), "user_defined")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--invest", required=True, type=Path)
    parser.add_argument("--carbon-pools", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--lulc", action="append", default=[], metavar="YEAR=PATH")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    executable = args.invest.expanduser().resolve()
    table = args.carbon_pools.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    series = parse_lulc(args.lulc)
    if not executable.is_file() or not table.is_file():
        raise SystemExit("InVEST executable or carbon-pool table is unavailable")
    probe = subprocess.run([str(executable), "--version"], text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", check=False)
    version = next((line.strip() for line in reversed((probe.stdout or "").splitlines())
                    if line.strip() and line.strip()[0].isdigit()), "unknown")
    if probe.returncode or version == "unknown":
        raise SystemExit("cannot identify the selected local InVEST executable")
    codes = pool_codes(table)
    resolved_table = named_pool_copy(table, output_root / "inputs" / "carbon_pools_resolved_names.csv")
    manifest: dict[str, Any] = {
        "status": "running", "model": "InVEST Carbon", "started_at_unix": time.time(),
        "invest_executable": str(executable), "invest_version": version, "carbon_pools_source": str(table),
        "carbon_pools_runtime_copy": str(resolved_table), "carbon_pools_sha256": sha256(table),
        "classification_validation_status": "pending_validation", "runs": [],
    }
    write_json(output_root / "carbon_series_manifest.json", manifest)
    for year, lulc in series:
        lulc_codes, grid = raster_codes(lulc)
        missing = sorted(lulc_codes - codes)
        if missing:
            raise SystemExit(f"{year}: carbon table has no density for LULC codes {missing}")
        run_dir = output_root / str(year)
        result = run_dir / "tot_c_cur.tif"
        datastack = output_root / "datastacks" / f"carbon_{year}.json"
        write_json(datastack, {"args": {
            "calc_sequestration": False, "carbon_pools_path": str(resolved_table),
            "do_redd": False, "do_valuation": False, "lulc_cur_path": str(lulc),
            "n_workers": -1, "results_suffix": "",
        }, "model_name": "natcap.invest.carbon", "invest_version": version})
        record: dict[str, Any] = {
            "year": year, "lulc": str(lulc), "lulc_sha256": sha256(lulc), "lulc_codes": sorted(lulc_codes),
            "grid": grid, "datastack": str(datastack), "workspace": str(run_dir), "output": str(result),
        }
        if result.is_file() and not args.overwrite:
            record.update({"status": "completed", "reused_existing_output": True})
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            command = [str(executable), "run", "carbon", "-l", "-d", str(datastack), "-w", str(run_dir)]
            started = time.time()
            process = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     encoding="utf-8", errors="replace", check=False)
            (run_dir / "invest_carbon.log").write_text(process.stdout or "", encoding="utf-8")
            record.update({"return_code": process.returncode, "runtime_seconds": time.time() - started,
                           "log": str(run_dir / "invest_carbon.log")})
            if process.returncode or not result.is_file():
                record["status"] = "failed"
                manifest["runs"].append(record)
                manifest.update({"status": "failed", "finished_at_unix": time.time()})
                write_json(output_root / "carbon_series_manifest.json", manifest)
                raise SystemExit(f"{year}: InVEST Carbon did not produce {result}")
            record["status"] = "completed"
        manifest["runs"].append(record)
        write_json(output_root / "carbon_series_manifest.json", manifest)
    manifest.update({"status": "pending_validation", "finished_at_unix": time.time(),
                     "note": "Carbon outputs are complete, while their source LULC classification awaits independent validation."})
    write_json(output_root / "carbon_series_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
