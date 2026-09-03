#!/usr/bin/env python3
"""Run and validate native InVEST 3.18 Habitat Quality for dated LULC maps.

The runner writes a manifest only after every requested period has a valid
``quality_c_hq_<year>.tif`` and degradation raster.  It never substitutes a
formula-based result for a native InVEST output.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def quality_stats(path: Path) -> dict[str, float | int]:
    import numpy as np  # type: ignore
    import rasterio  # type: ignore

    with rasterio.open(path) as dataset:
        array = dataset.read(1)
        mask = np.isfinite(array)
        if dataset.nodata is not None:
            mask &= array != dataset.nodata
        valid = array[mask]
        if valid.size == 0:
            raise ValueError(f"all cells are NoData: {path}")
        if float(valid.min()) < -1e-6 or float(valid.max()) > 1.000001:
            raise ValueError(f"Habitat Quality must be within [0, 1]: {path}")
        return {"valid_cell_count": int(valid.size), "min": float(valid.min()),
                "max": float(valid.max()), "mean": float(valid.mean())}


def native_result(workspace: Path, prefix: str, year: str) -> Path | None:
    """Find a native result with an optional scenario suffix.

    Historical stacks use ``hq_YYYY`` whereas scenario stacks deliberately use
    ``hq_YYYY_SCENARIO``.  Both are native InVEST output names and both must be
    accepted by this validator.
    """
    exact = workspace / f"{prefix}_c_hq_{year}.tif"
    if exact.is_file():
        return exact
    matches = sorted(workspace.glob(f"{prefix}_c_hq_{year}_*.tif"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"ambiguous native {prefix} outputs for {year}: {matches}")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--invest", required=True, type=Path)
    parser.add_argument("--datastack-dir", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--years", nargs="+", default=["2005", "2010", "2015", "2020", "2025"])
    args = parser.parse_args()
    invest = args.invest.expanduser().resolve()
    stack_dir = args.datastack_dir.expanduser().resolve()
    root = args.output_root.expanduser().resolve()
    if not invest.is_file():
        raise SystemExit(f"InVEST executable does not exist: {invest}")
    results: list[dict[str, object]] = []
    for year in args.years:
        if not str(year).isdigit():
            raise SystemExit(f"year must be numeric: {year}")
        stack = stack_dir / f"habitat_quality_{year}.json"
        workspace = root / str(year)
        quality = native_result(workspace, "quality", str(year))
        degradation = native_result(workspace, "deg_sum", str(year))
        if quality is None or degradation is None:
            workspace.mkdir(parents=True, exist_ok=True)
            command = [str(invest), "run", "habitat_quality", "-l", "-d", str(stack), "-w", str(workspace)]
            completed = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (workspace / "native_invest_command.log").write_text(completed.stdout, encoding="utf-8", errors="replace")
            if completed.returncode:
                raise SystemExit(f"InVEST Habitat Quality failed for {year}; see {workspace / 'native_invest_command.log'}")
            quality = native_result(workspace, "quality", str(year))
            degradation = native_result(workspace, "deg_sum", str(year))
        if quality is None:
            raise SystemExit(f"native InVEST quality raster is missing for {year}")
        if degradation is None:
            raise SystemExit(f"native InVEST degradation raster is missing: {degradation}")
        stats = quality_stats(quality)
        results.append({"year": int(year), "status": "completed", "quality": str(quality),
                        "degradation": str(degradation), "quality_statistics": stats})
        print(json.dumps(results[-1], ensure_ascii=False))
    manifest = {"status": "completed", "model": "InVEST Habitat Quality", "invest_version": "3.18.0",
                "datastack_dir": str(stack_dir), "results": results,
                "completed_at": datetime.now(timezone.utc).isoformat()}
    root.mkdir(parents=True, exist_ok=True)
    (root / "native_habitat_quality_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
