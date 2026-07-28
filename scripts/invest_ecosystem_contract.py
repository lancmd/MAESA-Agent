#!/usr/bin/env python3
"""Validate local non-Carbon InVEST datastacks before scenario execution."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from carbon_density_contract import lulc_codes


REQUIRED: dict[str, tuple[str, ...]] = {
    "annual_water_yield": ("lulc_path", "precipitation_path", "eto_path", "depth_to_root_rest_layer_path", "pawc_path",
                            "watersheds_path", "biophysical_table_path", "seasonality_constant"),
    "habitat_quality": ("lulc_cur_path", "threats_table_path", "sensitivity_table_path", "half_saturation_constant"),
    "sediment_delivery_ratio": ("lulc_path", "dem_path", "erosivity_path", "erodibility_path", "watersheds_path", "biophysical_table_path"),
    "nutrient_delivery_ratio": ("lulc_path", "dem_path", "runoff_proxy_path", "watersheds_path", "biophysical_table_path"),
}


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve(value: Any, base: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def headers(path: Path) -> set[str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return set(csv.DictReader(stream).fieldnames or [])


def rows(path: Path) -> list[dict[str, str]]:
    """Read a parameter table with case-insensitive field lookup."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return [{str(key).casefold(): value or "" for key, value in row.items() if key is not None}
                for row in csv.DictReader(stream)]


def missing_headers(actual: set[str], required: set[str]) -> set[str]:
    """Compare InVEST table headers case-insensitively without rewriting them."""
    present = {value.casefold() for value in actual}
    return {value for value in required if value.casefold() not in present}


def finite(value: Any, label: str, *, positive: bool = False, bounded: bool = False) -> float:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} is not a number") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    if positive and result <= 0:
        raise ValueError(f"{label} must be positive")
    if bounded and not 0 <= result <= 1:
        raise ValueError(f"{label} must be between 0 and 1")
    return result


def integer(value: Any, label: str) -> int:
    result = finite(value, label)
    if not result.is_integer():
        raise ValueError(f"{label} must be an integer")
    return int(result)


def aligned(reference: Path, candidate: Path) -> bool:
    """InVEST does not make an unaligned threat raster scientifically valid."""
    import rasterio  # type: ignore
    with rasterio.open(reference) as left, rasterio.open(candidate) as right:
        if left.width != right.width or left.height != right.height:
            return False
        if not left.crs or not right.crs or left.crs != right.crs:
            return False
        return all(math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-8)
                   for a, b in zip(left.transform, right.transform))


def habitat_checks(args: dict[str, Any], datastack: Path, errors: list[str], warnings: list[str]) -> None:
    """Validate Habitat Quality tables, values, codes, and threat-grid alignment."""
    threats = resolve(args.get("threats_table_path"), datastack.parent)
    sensitivity = resolve(args.get("sensitivity_table_path"), datastack.parent)
    lulc = resolve(args.get("lulc_cur_path"), datastack.parent)
    threat_headers = headers(threats) if threats else set()
    sensitivity_headers = headers(sensitivity) if sensitivity else set()
    missing_threat = missing_headers(threat_headers, {"threat", "max_dist", "weight", "decay", "cur_path"})
    if missing_threat:
        errors.append("Habitat Quality threats table misses: " + ", ".join(sorted(missing_threat)))
    missing_sensitivity = missing_headers(sensitivity_headers, {"lulc", "habitat"})
    if missing_sensitivity:
        errors.append("Habitat Quality sensitivity table misses: " + ", ".join(sorted(missing_sensitivity)))
    if not (threats and sensitivity and lulc) or missing_threat or missing_sensitivity:
        return
    try:
        threat_rows = rows(threats)
        sensitivity_rows = rows(sensitivity)
        if not threat_rows:
            raise ValueError("Habitat Quality threats table contains no rows")
        if not sensitivity_rows:
            raise ValueError("Habitat Quality sensitivity table contains no rows")
        names: set[str] = set()
        for index, row in enumerate(threat_rows, start=2):
            name = row.get("threat", "").strip()
            if not name:
                raise ValueError(f"Habitat Quality threats row {index} has an empty threat")
            if name in names:
                raise ValueError(f"Habitat Quality threats table has duplicate threat: {name}")
            names.add(name)
            finite(row.get("max_dist"), f"Habitat Quality threats row {index} max_dist", positive=True)
            finite(row.get("weight"), f"Habitat Quality threats row {index} weight", positive=True)
            if row.get("decay", "").strip().casefold() not in {"linear", "exponential"}:
                raise ValueError(f"Habitat Quality threats row {index} decay must be linear or exponential")
            for field, label in (("cur_path", "current"), ("fut_path", "future"), ("base_path", "baseline")):
                value = row.get(field, "").strip()
                if not value:
                    continue
                raster = resolve(value, threats.parent)
                if raster is None or not raster.exists():
                    raise ValueError(f"Habitat Quality {label} threat raster does not exist for {name}: {raster}")
                if not aligned(lulc, raster):
                    raise ValueError(f"Habitat Quality {label} threat raster is not aligned to LULC for {name}: {raster}")
        absent = sorted(name for name in names if name.casefold() not in {value.casefold() for value in sensitivity_headers})
        if absent:
            errors.append("Habitat Quality sensitivity table has no columns for threats: " + ", ".join(absent))
        extra_columns = sorted({value for value in sensitivity_headers
                                if value.casefold() not in {"lulc", "habitat", *[name.casefold() for name in names]}})
        if extra_columns:
            warnings.append("Habitat Quality sensitivity table has unused columns: " + ", ".join(extra_columns))
        sensitivity_codes: set[int] = set()
        for index, row in enumerate(sensitivity_rows, start=2):
            code = integer(row.get("lulc"), f"Habitat Quality sensitivity row {index} lulc")
            if code in sensitivity_codes:
                raise ValueError(f"Habitat Quality sensitivity table has duplicate lulc: {code}")
            sensitivity_codes.add(code)
            finite(row.get("habitat"), f"Habitat Quality sensitivity row {index} habitat", bounded=True)
            for name in names:
                finite(row.get(name.casefold()), f"Habitat Quality sensitivity row {index} {name}", bounded=True)
        lulc_report = lulc_codes(lulc)
        if lulc_report["status"] != "completed":
            raise ValueError("Habitat Quality LULC: " + "; ".join(lulc_report["errors"]))
        actual_codes = set(lulc_report["codes"])
        missing_codes, extra_codes = sorted(actual_codes - sensitivity_codes), sorted(sensitivity_codes - actual_codes)
        if missing_codes:
            errors.append("Habitat Quality sensitivity has no LULC rows for: " + ", ".join(map(str, missing_codes)))
        if extra_codes:
            warnings.append("Habitat Quality sensitivity has LULC rows absent from this raster: " + ", ".join(map(str, extra_codes)))
    except (OSError, csv.Error, ValueError, ModuleNotFoundError) as error:
        errors.append(f"cannot validate Habitat Quality parameter tables: {error}")


def validate(model: str, datastack: Path) -> dict[str, Any]:
    payload = read(datastack); args = payload.get("args", {})
    if not isinstance(args, dict):
        raise ValueError("datastack args must be an object")
    errors: list[str] = []; warnings: list[str] = []
    for name in REQUIRED[model]:
        value = args.get(name)
        if value in (None, ""):
            errors.append(f"missing InVEST argument: {name}")
        elif name.endswith("_path"):
            path = resolve(value, datastack.parent)
            if path is None or not path.exists():
                errors.append(f"input does not exist: {name} = {path}")
    numeric = "seasonality_constant" if model == "annual_water_yield" else "half_saturation_constant" if model == "habitat_quality" else None
    if numeric and args.get(numeric) not in (None, "") and (not isinstance(args[numeric], (int, float)) or float(args[numeric]) <= 0):
        errors.append(f"{numeric} must be a positive number")
    try:
        if model == "annual_water_yield" and args.get("biophysical_table_path"):
            table = resolve(args["biophysical_table_path"], datastack.parent)
            missing = missing_headers(headers(table), {"lucode", "root_depth", "kc", "lulc_veg"}) if table else {"table"}
            if missing: errors.append("Annual Water Yield biophysical table misses: " + ", ".join(sorted(missing)))
        if model == "habitat_quality":
            habitat_checks(args, datastack, errors, warnings)
            access = args.get("access_vector_path")
            if access:
                access_path = resolve(access, datastack.parent)
                if access_path is None or not access_path.exists():
                    errors.append(f"Habitat Quality access vector does not exist: {access_path}")
            else:
                warnings.append("access_vector_path is absent; habitat access is treated as unrestricted")
        if model in {"sediment_delivery_ratio", "nutrient_delivery_ratio"} and args.get("biophysical_table_path"):
            table = resolve(args["biophysical_table_path"], datastack.parent)
            missing = missing_headers(headers(table), {"lucode"}) if table else {"table"}
            if missing:
                errors.append(f"{model} biophysical table misses: " + ", ".join(sorted(missing)))
    except (OSError, csv.Error) as error:
        errors.append(f"cannot read InVEST parameter table: {error}")
    return {"status": "completed" if not errors else "failed", "model": model, "datastack": str(datastack.resolve()),
            "errors": errors, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=sorted(REQUIRED)); parser.add_argument("--datastack", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path); args = parser.parse_args()
    result = validate(args.model, args.datastack.resolve()); args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
