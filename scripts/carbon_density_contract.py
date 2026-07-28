#!/usr/bin/env python3
"""Validate InVEST Carbon pool tables and compare them with actual LULC codes.

The Carbon model accepts a table even when it has a typo in a density field or
when one of the land-cover codes is absent.  That usually fails only after the
model has started.  This small, dependency-light contract is shared by project
validation and raster preflight so both paths report the same problem.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = ("lucode", "c_above", "c_below", "c_soil", "c_dead")


def _number(value: Any, field: str, row_number: int) -> float:
    """Return a finite value or describe the offending row precisely."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ValueError(f"row {row_number}: {field} is not a number") from error
    if not math.isfinite(number):
        raise ValueError(f"row {row_number}: {field} must be finite")
    return number


def _lucode(value: Any, row_number: int) -> int:
    number = _number(value, "lucode", row_number)
    if not number.is_integer():
        raise ValueError(f"row {row_number}: lucode must be an integer")
    return int(number)


def validate_table(path: Path) -> dict[str, Any]:
    """Validate the InVEST Carbon CSV itself, without a raster dependency."""
    report: dict[str, Any] = {
        "status": "completed", "carbon_density": str(path.resolve()), "codes": [],
        "row_count": 0, "errors": [], "warnings": [],
    }
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            header = reader.fieldnames or []
            missing = [field for field in REQUIRED_COLUMNS if field not in header]
            if missing:
                report["errors"].append("carbon density table misses columns: " + ", ".join(missing))
                report["status"] = "failed"
                return report
            codes: set[int] = set()
            for row_number, row in enumerate(reader, start=2):
                report["row_count"] += 1
                code = _lucode(row.get("lucode"), row_number)
                if code in codes:
                    raise ValueError(f"row {row_number}: duplicate lucode {code}")
                codes.add(code)
                for field in REQUIRED_COLUMNS[1:]:
                    value = _number(row.get(field), field, row_number)
                    if value < 0:
                        raise ValueError(f"row {row_number}: {field} must be non-negative")
            if not codes:
                raise ValueError("carbon density table contains no data rows")
            report["codes"] = sorted(codes)
    except (OSError, csv.Error, ValueError) as error:
        report["status"] = "failed"
        report["errors"].append(str(error))
    return report


def lulc_codes(path: Path) -> dict[str, Any]:
    """Read all valid integer LULC codes while excluding the raster NoData value."""
    report: dict[str, Any] = {
        "status": "completed", "lulc": str(path.resolve()), "codes": [],
        "nodata": None, "errors": [], "warnings": [],
    }
    try:
        import numpy as np  # type: ignore
        import rasterio  # type: ignore

        with rasterio.open(path) as source:
            report["nodata"] = source.nodata
            if source.count < 1:
                raise ValueError("LULC raster has no bands")
            if not all("int" in dtype or "uint" in dtype for dtype in source.dtypes):
                raise ValueError("LULC raster must use an integer pixel type")
            values: set[int] = set()
            for _, window in source.block_windows(1):
                data = source.read(1, window=window, masked=True)
                raw = data.compressed()
                if raw.size:
                    values.update(int(value) for value in np.unique(raw))
            if not values:
                raise ValueError("LULC raster contains no valid pixels")
            report["codes"] = sorted(values)
    except (ImportError, OSError, ValueError) as error:
        report["status"] = "failed"
        report["errors"].append(str(error))
    return report


def compare_code_sets(lulc_values: set[int], carbon_values: set[int], *, require_exact_codes: bool = False) -> dict[str, Any]:
    """Compare already-read codes; used by streaming spatial preflight."""
    missing = sorted(lulc_values - carbon_values)
    extra = sorted(carbon_values - lulc_values)
    errors: list[str] = []
    warnings: list[str] = []
    if missing:
        errors.append("carbon density has no lucode for LULC codes: " + ", ".join(map(str, missing)))
    if extra:
        message = "carbon density contains lucode values absent from this LULC: " + ", ".join(map(str, extra))
        (errors if require_exact_codes else warnings).append(message)
    return {"missing_carbon_codes": missing, "extra_carbon_codes": extra,
            "require_exact_codes": require_exact_codes, "errors": errors, "warnings": warnings}


def compare_codes(lulc: Path, carbon_density: Path, *, require_exact_codes: bool = False) -> dict[str, Any]:
    """Compare a LULC raster with a Carbon table.

    Missing carbon rows are always errors.  Extra rows are normally warnings:
    a single carbon table often legitimately covers all six historical dates
    while a particular date contains only a subset of classes.  Set
    ``require_exact_codes`` for a one-to-one audit.
    """
    table = validate_table(carbon_density)
    raster = lulc_codes(lulc)
    errors = [*table["errors"], *raster["errors"]]
    warnings = [*table["warnings"], *raster["warnings"]]
    details = compare_code_sets(set(raster["codes"]), set(table["codes"]), require_exact_codes=require_exact_codes)
    errors.extend(details["errors"])
    warnings.extend(details["warnings"])
    return {
        "status": "failed" if errors else "completed",
        "lulc": raster["lulc"], "carbon_density": table["carbon_density"],
        "lulc_codes": raster["codes"], "carbon_codes": table["codes"],
        "missing_carbon_codes": details["missing_carbon_codes"], "extra_carbon_codes": details["extra_carbon_codes"],
        "require_exact_codes": require_exact_codes, "errors": errors, "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--carbon-density", required=True, type=Path)
    parser.add_argument("--lulc", type=Path)
    parser.add_argument("--require-exact-codes", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = (compare_codes(args.lulc, args.carbon_density, require_exact_codes=args.require_exact_codes)
              if args.lulc else validate_table(args.carbon_density))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
