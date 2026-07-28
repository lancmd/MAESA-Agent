#!/usr/bin/env python3
"""Build and verify a local InVEST Habitat Quality datastack from typed inputs.

The builder deliberately asks for threat parameters and class sensitivity
values.  It creates the two CSV files and a portable datastack, but it never
guesses ecological weights or sensitivities from imagery alone.

Example configuration::

  {
    "lulc_path": "data/LULC_2025.tif",
    "half_saturation_constant": 0.5,
    "threats": [{"name": "road", "raster": "data/road.tif",
                 "max_distance_m": 1000, "weight": 1, "decay": "linear"}],
    "sensitivity": [
      {"lulc": 1, "habitat": 0.8, "threats": {"road": 0.3}}
    ]
  }
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from carbon_density_contract import lulc_codes


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Habitat Quality builder configuration must be an object")
    return payload


def _resolve(value: Any, base: Path, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    raw = Path(value).expanduser()
    path = raw.resolve() if raw.is_absolute() else (base / raw).resolve()
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    return path


def _number(value: Any, label: str, *, positive: bool = False, bounded: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a number") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    if positive and result <= 0:
        raise ValueError(f"{label} must be positive")
    if bounded and not 0 <= result <= 1:
        raise ValueError(f"{label} must be between 0 and 1")
    return result


def _code(value: Any, label: str) -> int:
    number = _number(value, label)
    if not number.is_integer():
        raise ValueError(f"{label} must be an integer")
    return int(number)


def _same_grid(reference: Path, candidate: Path) -> bool:
    """Habitat threat rasters must be on the LULC grid before model execution."""
    import rasterio  # type: ignore

    with rasterio.open(reference) as left, rasterio.open(candidate) as right:
        if left.width != right.width or left.height != right.height:
            return False
        if not left.crs or not right.crs or left.crs != right.crs:
            return False
        return all(math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-8)
                   for a, b in zip(left.transform, right.transform))


def _threat_path(row: dict[str, Any], base: Path, names: tuple[str, ...], label: str) -> Path | None:
    for name in names:
        if row.get(name) not in (None, ""):
            return _resolve(row[name], base, label)
    return None


def _normalise_threats(value: Any, base: Path, lulc: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("threats must be a non-empty list")
    result: list[dict[str, Any]] = []
    warnings: list[str] = []
    names: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError(f"threats[{index}] must be an object")
        name = str(raw.get("name", raw.get("threat", ""))).strip()
        if not name:
            raise ValueError(f"threats[{index}].name is required")
        if name in names:
            raise ValueError(f"threats contains duplicate name: {name}")
        if any(char in name for char in (",", "\n", "\r")):
            raise ValueError(f"threats[{index}].name cannot contain CSV separators")
        names.add(name)
        current = _threat_path(raw, base, ("raster", "current_raster", "cur_path", "path"),
                               f"threats[{index}] current raster")
        if current is None:
            raise ValueError(f"threats[{index}] needs raster/current_raster/cur_path")
        if not _same_grid(lulc, current):
            raise ValueError(f"threats[{index}] raster is not aligned to lulc_path: {current}")
        future = _threat_path(raw, base, ("future_raster", "fut_path"), f"threats[{index}] future raster")
        if future and not _same_grid(lulc, future):
            raise ValueError(f"threats[{index}] future raster is not aligned to lulc_path: {future}")
        decay = str(raw.get("decay", "")).strip().lower()
        if decay not in {"linear", "exponential"}:
            raise ValueError(f"threats[{index}].decay must be linear or exponential")
        result.append({
            "threat": name,
            "max_dist": _number(raw.get("max_distance_m", raw.get("max_distance", raw.get("max_dist"))),
                                  f"threats[{index}].max_distance_m", positive=True),
            "weight": _number(raw.get("weight"), f"threats[{index}].weight", positive=True),
            "decay": decay,
            "cur_path": str(current),
            "fut_path": str(future) if future else "",
        })
        if future is None:
            warnings.append(f"threat {name} has no future raster; the datastack evaluates current habitat quality only")
    return result, warnings


def _read_sensitivity_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("sensitivity_table_path contains no data rows")
    return [{str(key).strip(): value for key, value in row.items() if key is not None} for row in rows]


def _sensitivity_rows(config: dict[str, Any], base: Path) -> list[dict[str, Any]]:
    table = config.get("sensitivity_table_path")
    if table not in (None, ""):
        return _read_sensitivity_csv(_resolve(table, base, "sensitivity_table_path"))
    raw = config.get("sensitivity")
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        rows: list[dict[str, Any]] = []
        for code, row in raw.items():
            if not isinstance(row, dict):
                raise ValueError(f"sensitivity[{code!r}] must be an object")
            rows.append({"lulc": code, **row})
        return rows
    raise ValueError("provide sensitivity as a list/mapping or sensitivity_table_path")


def _normalise_sensitivity(config: dict[str, Any], base: Path, lulc_values: set[int],
                           threat_names: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    rows = _sensitivity_rows(config, base)
    result: list[dict[str, Any]] = []
    codes: set[int] = set()
    warnings: list[str] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"sensitivity[{index}] must be an object")
        code = _code(raw.get("lulc"), f"sensitivity[{index}].lulc")
        if code in codes:
            raise ValueError(f"sensitivity has duplicate lulc code {code}")
        codes.add(code)
        habitat = _number(raw.get("habitat"), f"sensitivity[{index}].habitat", bounded=True)
        nested = raw.get("threats", {})
        if nested not in ({}, None) and not isinstance(nested, dict):
            raise ValueError(f"sensitivity[{index}].threats must be an object")
        nested = nested or {}
        values: dict[str, float] = {}
        for threat in threat_names:
            value = raw.get(threat, nested.get(threat))
            values[threat] = _number(value, f"sensitivity[{index}].{threat}", bounded=True)
        extras = (set(nested) | (set(raw) - {"lulc", "habitat", "threats"})) - set(threat_names)
        if extras:
            raise ValueError(f"sensitivity[{index}] names not declared in threats: {', '.join(sorted(extras))}")
        result.append({"lulc": code, "habitat": habitat, **values})
    missing = sorted(lulc_values - codes)
    extra = sorted(codes - lulc_values)
    if missing:
        raise ValueError("sensitivity has no LULC rows for: " + ", ".join(map(str, missing)))
    if extra:
        warnings.append("sensitivity contains LULC rows absent from this raster: " + ", ".join(map(str, extra)))
    return sorted(result, key=lambda row: int(row["lulc"])), warnings


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_habitat_quality_datastack(config: dict[str, Any], output_dir: Path, *,
                                    source_base: Path | None = None, lulc_override: str | Path | None = None,
                                    datastack_path: Path | None = None, allow_overwrite: bool = False) -> dict[str, Any]:
    """Write Habitat Quality tables and a datastack, then validate the result.

    ``lulc_override`` is intended for a dated LULC/PLUS workflow: one stable
    ecological parameter set can be reused while each year receives an
    independently generated datastack.
    """
    if not isinstance(config, dict):
        raise ValueError("Habitat Quality builder configuration must be an object")
    base = (source_base or Path.cwd()).resolve()
    lulc = _resolve(str(lulc_override) if lulc_override is not None else config.get("lulc_path"), base, "lulc_path")
    codes_report = lulc_codes(lulc)
    if codes_report["status"] != "completed":
        raise ValueError("; ".join(codes_report["errors"]))
    lulc_values = set(codes_report["codes"])
    threats, threat_warnings = _normalise_threats(config.get("threats"), base, lulc)
    threat_names = [str(row["threat"]) for row in threats]
    sensitivity, sensitivity_warnings = _normalise_sensitivity(config, base, lulc_values, threat_names)
    half_saturation = _number(config.get("half_saturation_constant"), "half_saturation_constant", positive=True)
    access = config.get("access_vector_path")
    access_path = _resolve(access, base, "access_vector_path") if access not in (None, "") else None
    workers = config.get("n_workers", -1)
    if not isinstance(workers, int):
        raise ValueError("n_workers must be an integer")
    suffix = config.get("results_suffix", "")
    if not isinstance(suffix, str):
        raise ValueError("results_suffix must be a string")

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    threats_table = output_dir / "habitat_threats.csv"
    sensitivity_table = output_dir / "habitat_sensitivity.csv"
    target = (datastack_path.expanduser().resolve() if datastack_path else output_dir / "habitat_quality_datastack.json")
    manifest = output_dir / "habitat_datastack_manifest.json"
    existing = [path for path in (threats_table, sensitivity_table, target, manifest) if path.exists()]
    if existing and not allow_overwrite:
        raise FileExistsError("Habitat Quality builder would overwrite existing outputs; pass confirm_overwrite: true or --confirm-overwrite: " +
                              ", ".join(str(path) for path in existing))
    _write_csv(threats_table, ["threat", "max_dist", "weight", "decay", "cur_path", "fut_path"], threats)
    _write_csv(sensitivity_table, ["lulc", "habitat", *threat_names], sensitivity)
    args: dict[str, Any] = {
        "lulc_cur_path": str(lulc), "threats_table_path": str(threats_table),
        "sensitivity_table_path": str(sensitivity_table), "half_saturation_constant": half_saturation,
        "n_workers": workers, "results_suffix": suffix,
    }
    if access_path:
        args["access_vector_path"] = str(access_path)
    payload: dict[str, Any] = {"model_name": "natcap.invest.habitat_quality", "args": args}
    if config.get("invest_version"):
        payload["invest_version"] = str(config["invest_version"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Import after file construction so the contract also validates generated
    # CSVs exactly as a later workflow stage will validate them.
    from invest_ecosystem_contract import validate  # noqa: PLC0415
    contract = validate("habitat_quality", target)
    report = {
        "status": contract["status"], "model": "habitat_quality", "lulc": str(lulc),
        "lulc_codes": sorted(lulc_values), "datastack": str(target),
        "threats_table": str(threats_table), "sensitivity_table": str(sensitivity_table),
        "warnings": [*threat_warnings, *sensitivity_warnings, *contract["warnings"]],
        "errors": contract["errors"], "contract": contract,
    }
    report["manifest"] = str(manifest)
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_from_file(config_path: Path, output_dir: Path, *, lulc_override: str | Path | None = None,
                    datastack_path: Path | None = None, allow_overwrite: bool = False) -> dict[str, Any]:
    return build_habitat_quality_datastack(_read_json(config_path), output_dir, source_base=config_path.parent,
                                           lulc_override=lulc_override, datastack_path=datastack_path,
                                           allow_overwrite=allow_overwrite)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--datastack", type=Path)
    parser.add_argument("--lulc", type=Path, help="replace config lulc_path for one date/scenario")
    parser.add_argument("--output", type=Path, help="optional JSON build report")
    parser.add_argument("--confirm-overwrite", action="store_true", help="allow replacement of prior generated tables/datastack")
    args = parser.parse_args()
    try:
        report = build_from_file(args.config.resolve(), args.output_dir, lulc_override=args.lulc,
                                 datastack_path=args.datastack, allow_overwrite=args.confirm_overwrite)
    except (OSError, ValueError, json.JSONDecodeError, ModuleNotFoundError) as error:
        report = {"status": "failed", "errors": [str(error)], "warnings": []}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
