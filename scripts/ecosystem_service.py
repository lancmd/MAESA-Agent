#!/usr/bin/env python3
"""Compute Min-Max or AHP-weighted ecosystem-service scores from a local CSV."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from itertools import combinations
from pathlib import Path
from typing import Any


RANDOM_INDEX = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def normalise_weights(values: list[float]) -> list[float]:
    total = sum(values)
    if total <= 0:
        raise ValueError("weights must sum to a positive number")
    return [value / total for value in values]


def ahp_weights(matrix: list[list[float]]) -> tuple[list[float], float, float]:
    size = len(matrix)
    if size < 1 or any(len(row) != size for row in matrix):
        raise ValueError("AHP matrix must be square")
    for row in matrix:
        if any(not isinstance(value, (int, float)) or value <= 0 for value in row):
            raise ValueError("AHP matrix values must be positive")
    for i in range(size):
        if not math.isclose(matrix[i][i], 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError("AHP diagonal values must be 1")
        for j in range(i + 1, size):
            if not math.isclose(matrix[i][j] * matrix[j][i], 1.0, rel_tol=1e-4, abs_tol=1e-4):
                raise ValueError("AHP matrix must be reciprocal")
    vector = [1.0 / size] * size
    for _ in range(1000):
        product = [sum(matrix[i][j] * vector[j] for j in range(size)) for i in range(size)]
        updated = normalise_weights(product)
        if max(abs(updated[i] - vector[i]) for i in range(size)) < 1e-12:
            vector = updated
            break
        vector = updated
    products = [sum(matrix[i][j] * vector[j] for j in range(size)) for i in range(size)]
    lambda_max = sum(products[i] / vector[i] for i in range(size)) / size
    ci = 0.0 if size <= 2 else (lambda_max - size) / (size - 1)
    ri = RANDOM_INDEX.get(size)
    if ri is None:
        raise ValueError("AHP supports at most 10 criteria")
    cr = 0.0 if ri == 0 else ci / ri
    return vector, lambda_max, cr


def evaluate(criteria_table: Path, config_path: Path, output_path: Path) -> dict[str, Any]:
    config = load_json(config_path)
    if config.get("schema_version") not in {1, 2}:
        raise ValueError("ecosystem config schema_version must be 1 or 2")
    method = config.get("method")
    if method not in {"minmax", "ahp"}:
        raise ValueError("method must be minmax or ahp")
    criteria = config.get("criteria", [])
    if not criteria:
        raise ValueError("criteria are required")
    with criteria_table.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("criteria table has no rows")
    id_field = config.get("id_field", "unit_id")
    passthrough = config.get("passthrough_fields", [])
    if not isinstance(passthrough, list) or any(not isinstance(field, str) or not field for field in passthrough):
        raise ValueError("passthrough_fields must be a list of non-empty field names")
    if id_field in passthrough or len(set(passthrough)) != len(passthrough):
        raise ValueError("passthrough_fields must not repeat id_field or field names")
    required = [id_field, *passthrough] + [item.get("field") for item in criteria]
    missing = [field for field in required if not field or field not in rows[0]]
    if missing:
        raise ValueError(f"criteria table misses columns: {', '.join(missing)}")
    values: dict[str, list[float]] = {}
    for item in criteria:
        field = item["field"]
        try:
            values[field] = [float(row[field]) for row in rows]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"criterion {field} must contain finite numeric values") from error
        if any(not math.isfinite(value) for value in values[field]):
            raise ValueError(f"criterion {field} contains non-finite values")
    if method == "minmax":
        try:
            weights = normalise_weights([float(item["weight"]) for item in criteria])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Min-Max evaluation requires one numeric user weight for every criterion") from error
        lambda_max = consistency_ratio = None
    else:
        matrix = config.get("ahp", {}).get("pairwise_matrix")
        if not isinstance(matrix, list) or len(matrix) != len(criteria):
            raise ValueError("AHP pairwise_matrix must match criteria length")
        weights, lambda_max, consistency_ratio = ahp_weights(matrix)
        threshold = float(config.get("ahp", {}).get("consistency_threshold", 0.1))
        if consistency_ratio > threshold:
            raise ValueError(f"AHP consistency ratio {consistency_ratio:.4f} exceeds threshold {threshold:.4f}")
    output_rows: list[dict[str, Any]] = []
    normalised: dict[str, list[float]] = {}
    resolved_bounds: dict[str, dict[str, float]] = {}
    normalization = config.get("normalization", {})
    if normalization and not isinstance(normalization, dict):
        raise ValueError("normalization must be an object")
    normalization_mode = normalization.get("mode", "within_project") if isinstance(normalization, dict) else "within_project"
    if normalization_mode not in {"within_project", "fixed_reference"}:
        raise ValueError("normalization.mode must be within_project or fixed_reference")
    configured_bounds = normalization.get("bounds", {}) if isinstance(normalization, dict) else {}
    if configured_bounds and not isinstance(configured_bounds, dict):
        raise ValueError("normalization.bounds must be an object keyed by criterion field")
    if normalization_mode == "fixed_reference":
        missing_bounds = [item["field"] for item in criteria if item["field"] not in configured_bounds]
        if missing_bounds:
            raise ValueError("fixed_reference normalization requires bounds for: " + ", ".join(missing_bounds))
    clipped_counts: dict[str, int] = {}
    for item in criteria:
        field = item["field"]
        specified = configured_bounds.get(field) if isinstance(configured_bounds, dict) else None
        if specified is None:
            lower, upper = min(values[field]), max(values[field])
        else:
            try:
                lower, upper = float(specified["min"]), float(specified["max"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"normalization.bounds.{field} requires numeric min and max") from error
            if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
                raise ValueError(f"normalization.bounds.{field} requires min < max")
        resolved_bounds[field] = {"min": lower, "max": upper}
        if math.isclose(lower, upper):
            scores = [0.5] * len(rows)
        elif item.get("direction", "benefit") == "benefit":
            scores = [(value - lower) / (upper - lower) for value in values[field]]
        elif item.get("direction") == "cost":
            scores = [(upper - value) / (upper - lower) for value in values[field]]
        else:
            raise ValueError(f"criterion direction must be benefit or cost: {field}")
        clipped_counts[field] = sum(value < 0 or value > 1 for value in scores)
        normalised[field] = [min(1.0, max(0.0, value)) for value in scores]
    for index, row in enumerate(rows):
        result = {id_field: row[id_field], **{field: row[field] for field in passthrough}}
        total = 0.0
        for criterion, weight in zip(criteria, weights):
            field = criterion["field"]
            result[f"value_{field}"] = values[field][index]
            result[f"norm_{field}"] = normalised[field][index]
            total += weight * normalised[field][index]
        result["ecosystem_service_score"] = total
        output_rows.append(result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output_rows[0]))
        writer.writeheader(); writer.writerows(output_rows)
    metadata = {"method": method, "criteria": [item["field"] for item in criteria], "weights": weights,
                "normalization_bounds": resolved_bounds, "lambda_max": lambda_max,
                "consistency_ratio": consistency_ratio, "output": str(output_path.resolve()),
                "normalization_mode": normalization_mode,
                "cross_project_comparable": normalization_mode == "fixed_reference",
                "clipped_value_counts": clipped_counts}
    output_path.with_suffix(output_path.suffix + ".metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def _rows_and_fields(table: Path, required: list[str]) -> list[dict[str, str]]:
    with table.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("input table has no rows")
    missing = [field for field in required if field not in rows[0]]
    if missing:
        raise ValueError(f"input table misses columns: {', '.join(missing)}")
    return rows


def _numeric_column(rows: list[dict[str, str]], field: str) -> list[float]:
    try:
        values = [float(row[field]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{field} must contain finite numeric values") from error
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f"{field} contains non-finite values")
    return values


def _average_ranks(values: list[float]) -> list[float]:
    ranks = [0.0] * len(values)
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and math.isclose(ordered[end][1], ordered[start][1], rel_tol=0, abs_tol=1e-12):
            end += 1
        rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[ordered[position][0]] = rank
        start = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left, mean_right = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - mean_left) ** 2 for a in left) * sum((b - mean_right) ** 2 for b in right))
    return None if math.isclose(denominator, 0.0) else numerator / denominator


def tradeoff_analysis(criteria_table: Path, fields: list[str], output_path: Path,
                      permutations: int = 999, bootstrap: int = 999, seed: int = 20260713) -> dict[str, Any]:
    if len(fields) < 2 or len(set(fields)) != len(fields):
        raise ValueError("trade-off analysis requires at least two distinct service fields")
    rows = _rows_and_fields(criteria_table, fields)
    values = {field: _numeric_column(rows, field) for field in fields}
    if permutations < 0 or bootstrap < 0:
        raise ValueError("permutations and bootstrap must be non-negative")
    rng = random.Random(seed)
    output_rows: list[dict[str, Any]] = []
    for left, right in combinations(fields, 2):
        rho = _pearson(_average_ranks(values[left]), _average_ranks(values[right]))
        relation = "undefined" if rho is None else "synergy" if rho > 0 else "tradeoff" if rho < 0 else "neutral"
        output_rows.append({"service_a": left, "service_b": right, "sample_count": len(rows),
                            "spearman_rho": "" if rho is None else rho, "relation": relation})
    for row in output_rows:
        left, right = row["service_a"], row["service_b"]
        rho = row["spearman_rho"]
        if rho == "" or len(rows) < 3 or not permutations:
            row["permutation_p_value"] = ""
        else:
            left_ranks = _average_ranks(values[left]); right_ranks = _average_ranks(values[right])
            extreme = 0
            for _ in range(permutations):
                shuffled = right_ranks.copy(); rng.shuffle(shuffled)
                simulated = _pearson(left_ranks, shuffled)
                extreme += int(simulated is not None and abs(simulated) >= abs(float(rho)))
            row["permutation_p_value"] = (extreme + 1) / (permutations + 1)
        samples: list[float] = []
        if rho != "" and len(rows) >= 3 and bootstrap:
            for _ in range(bootstrap):
                indices = [rng.randrange(len(rows)) for _ in rows]
                value = _pearson(_average_ranks([values[left][index] for index in indices]),
                                 _average_ranks([values[right][index] for index in indices]))
                if value is not None:
                    samples.append(value)
        if samples:
            samples.sort()
            row["bootstrap_ci95_low"] = samples[max(0, int(0.025 * (len(samples) - 1)))]
            row["bootstrap_ci95_high"] = samples[min(len(samples) - 1, int(0.975 * (len(samples) - 1)))]
        else:
            row["bootstrap_ci95_low"] = row["bootstrap_ci95_high"] = ""
    p_rows = sorted((row for row in output_rows if isinstance(row["permutation_p_value"], float)),
                    key=lambda row: row["permutation_p_value"])
    previous = 1.0
    for rank, row in reversed(list(enumerate(p_rows, 1))):
        adjusted = min(previous, row["permutation_p_value"] * len(p_rows) / rank)
        row["fdr_bh_p_value"] = adjusted; previous = adjusted
    for row in output_rows:
        row.setdefault("fdr_bh_p_value", "")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output_rows[0])); writer.writeheader(); writer.writerows(output_rows)
    return {"method": "spearman_permutation_bootstrap", "fields": fields, "permutations": permutations,
            "bootstrap": bootstrap, "seed": seed, "output": str(output_path.resolve())}


def scenario_compare(scores_table: Path, scenario_field: str, reference_scenario: str,
                     value_fields: list[str], output_path: Path) -> dict[str, Any]:
    if not value_fields:
        raise ValueError("scenario comparison requires one or more value_fields")
    rows = _rows_and_fields(scores_table, [scenario_field, *value_fields])
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row[scenario_field], []).append(row)
    if reference_scenario not in grouped:
        raise ValueError(f"reference scenario is absent: {reference_scenario}")
    means = {scenario: {field: sum(_numeric_column(group, field)) / len(group) for field in value_fields}
             for scenario, group in grouped.items()}
    output_rows = []
    for scenario in sorted(grouped):
        row: dict[str, Any] = {scenario_field: scenario, "unit_count": len(grouped[scenario])}
        for field in value_fields:
            row[f"mean_{field}"] = means[scenario][field]
            row[f"delta_{field}_vs_{reference_scenario}"] = means[scenario][field] - means[reference_scenario][field]
        output_rows.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output_rows[0])); writer.writeheader(); writer.writerows(output_rows)
    return {"reference_scenario": reference_scenario, "scenario_field": scenario_field,
            "value_fields": value_fields, "output": str(output_path.resolve())}


def calibrate_water_yield(candidates_table: Path, parameter_field: str, modeled_volume_field: str,
                          observed_volume_m3: float, output_path: Path) -> dict[str, Any]:
    observed = float(observed_volume_m3)
    if not math.isfinite(observed) or observed <= 0:
        raise ValueError("observed_volume_m3 must be a finite positive volume with the same time basis as the model")
    rows = _rows_and_fields(candidates_table, [parameter_field, modeled_volume_field])
    modeled = _numeric_column(rows, modeled_volume_field)
    output_rows = []
    for row, value in zip(rows, modeled):
        error = abs(value - observed)
        output_rows.append({parameter_field: row[parameter_field], "modeled_volume_m3": value,
                            "observed_volume_m3": observed, "absolute_error_m3": error,
                            "relative_error": error / observed})
    output_rows.sort(key=lambda row: row["absolute_error_m3"])
    for index, row in enumerate(output_rows):
        row["selected"] = index == 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output_rows[0])); writer.writeheader(); writer.writerows(output_rows)
    return {"selected_parameter": output_rows[0][parameter_field], "output": str(output_path.resolve())}


def _population_variance(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def geodetector_factor_analysis(samples_table: Path, target_field: str, factor_fields: list[str],
                                output_path: Path, permutations: int = 999, seed: int = 20260713) -> dict[str, Any]:
    """Calculate GeoDetector q statistics and permutation p-values on classified factor strata."""
    if not factor_fields or len(set(factor_fields)) != len(factor_fields):
        raise ValueError("GeoDetector requires one or more distinct factor fields")
    rows = _rows_and_fields(samples_table, [target_field, *factor_fields])
    target = _numeric_column(rows, target_field)
    total_variance = _population_variance(target)
    if math.isclose(total_variance, 0.0):
        raise ValueError("GeoDetector target field has zero variance")

    def q_for(strata: list[str], values: list[float] = target) -> float:
        groups: dict[str, list[float]] = {}
        for value, stratum in zip(values, strata):
            if not stratum:
                raise ValueError("GeoDetector factor strata must not be blank")
            groups.setdefault(stratum, []).append(value)
        within = sum(len(group) * _population_variance(group) for group in groups.values())
        variance = _population_variance(values)
        return max(0.0, min(1.0, 1.0 - within / (len(values) * variance))) if not math.isclose(variance, 0.0) else 0.0

    q_values = {field: q_for([row[field] for row in rows]) for field in factor_fields}
    rng = random.Random(seed)
    def permutation_p(strata: list[str], observed: float) -> float | str:
        if not permutations:
            return ""
        extreme = 0
        for _ in range(permutations):
            shuffled = target.copy(); rng.shuffle(shuffled)
            extreme += int(q_for(strata, shuffled) >= observed)
        return (extreme + 1) / (permutations + 1)
    output_rows: list[dict[str, Any]] = []
    for field, value in q_values.items():
        strata = [row[field] for row in rows]
        output_rows.append({"analysis": "factor", "factor_a": field, "factor_b": "", "q": value,
                            "permutation_p_value": permutation_p(strata, value), "interaction_relation": "",
                            "note": "factor strata are user-classified"})
    for left, right in combinations(factor_fields, 2):
        joint_q = q_for([f"{row[left]}|{row[right]}" for row in rows])
        low, high = min(q_values[left], q_values[right]), max(q_values[left], q_values[right])
        total = q_values[left] + q_values[right]
        relation = "weaken_or_non_enhance" if joint_q <= high else "independent" if math.isclose(joint_q, total, abs_tol=1e-9) else "bi_factor_enhancement" if joint_q < total else "nonlinear_enhancement"
        strata = [f"{row[left]}|{row[right]}" for row in rows]
        output_rows.append({"analysis": "interaction", "factor_a": left, "factor_b": right, "q": joint_q,
                            "permutation_p_value": permutation_p(strata, joint_q), "interaction_relation": relation,
                            "note": "factor strata are user-classified"})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output_rows[0])); writer.writeheader(); writer.writerows(output_rows)
    return {"target_field": target_field, "factor_fields": factor_fields, "permutations": permutations,
            "seed": seed, "output": str(output_path.resolve())}


def sensitivity_analysis(criteria_table: Path, config_path: Path, relative_delta: float,
                         output_path: Path) -> dict[str, Any]:
    """Perturb each criterion weight and report score and rank sensitivity."""
    if not math.isfinite(relative_delta) or not 0 < relative_delta < 1:
        raise ValueError("relative_delta must be between 0 and 1")
    base_scores = output_path.with_name(output_path.stem + "_base_scores.csv")
    metadata = evaluate(criteria_table, config_path, base_scores)
    with base_scores.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    fields = metadata["criteria"]
    base_weights = [float(value) for value in metadata["weights"]]
    base_values = [float(row["ecosystem_service_score"]) for row in rows]

    def ranks(values: list[float]) -> list[int]:
        order = sorted(range(len(values)), key=lambda index: (-values[index], index))
        result = [0] * len(values)
        for rank, index in enumerate(order, 1):
            result[index] = rank
        return result

    base_ranks = ranks(base_values)
    output_rows: list[dict[str, Any]] = []
    for field_index, field in enumerate(fields):
        for direction, factor in (("decrease", 1 - relative_delta), ("increase", 1 + relative_delta)):
            weights = base_weights.copy()
            weights[field_index] *= factor
            weights = normalise_weights(weights)
            scores = [sum(weights[index] * float(row[f"norm_{name}"]) for index, name in enumerate(fields))
                      for row in rows]
            changed_ranks = ranks(scores)
            differences = [abs(value - base) for value, base in zip(scores, base_values)]
            rank_shifts = [abs(value - base) for value, base in zip(changed_ranks, base_ranks)]
            output_rows.append({
                "criterion": field, "direction": direction, "relative_delta": relative_delta,
                "perturbed_weight": weights[field_index],
                "mean_absolute_score_change": sum(differences) / len(differences),
                "max_absolute_score_change": max(differences),
                "rank_change_count": sum(shift > 0 for shift in rank_shifts),
                "max_rank_shift": max(rank_shifts),
            })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output_rows[0])); writer.writeheader(); writer.writerows(output_rows)
    return {"relative_delta": relative_delta, "criteria": fields, "base_scores": str(base_scores.resolve()),
            "output": str(output_path.resolve()), "maximum_rank_shift": max(row["max_rank_shift"] for row in output_rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--criteria-table", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.criteria_table.resolve(), args.config.resolve(), args.output.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
