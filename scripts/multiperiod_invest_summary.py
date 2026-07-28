#!/usr/bin/env python3
"""Summarise dated InVEST raster outputs into a reproducible table and SVG figure.

The command accepts one or more ``YEAR=SERVICE=RASTER`` records.  It calculates
each service with its declared aggregation rule instead of treating every
InVEST raster as an additive quantity: carbon is normally summed, whereas
Habitat Quality is reported as an area-weighted mean.  The CSV is suitable for
thesis tables; the SVG is a portable, publication-ready trend figure.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


VALID_AGGREGATIONS = {"sum", "mean", "depth_mm_to_m3"}
DEFAULT_AGGREGATIONS = {
    "carbon_storage_t_c": "sum",
    "habitat_quality": "mean",
    "water_yield_m3": "depth_mm_to_m3",
}
DEFAULT_UNITS = {
    "carbon_storage_t_c": "Mg C",
    "habitat_quality": "index_0_to_1",
    "water_yield_m3": "m3",
}
PALETTE = ("#2563eb", "#16a34a", "#c2410c", "#7c3aed", "#0f766e", "#be123c")


def parse_service_record(raw: str) -> tuple[int, str, Path]:
    year_raw, separator, remainder = raw.partition("=")
    service, separator2, path_raw = remainder.partition("=")
    if not separator or not separator2 or not service.strip() or not path_raw.strip():
        raise ValueError("--service-raster uses YEAR=SERVICE=path")
    try:
        year = int(year_raw)
    except ValueError as error:
        raise ValueError("service-raster YEAR must be an integer") from error
    if not 1900 <= year <= 2200:
        raise ValueError("service-raster YEAR must be between 1900 and 2200")
    return year, service.strip(), Path(path_raw).expanduser().resolve()


def parse_mapping(raw_values: list[str], label: str, allowed: set[str] | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in raw_values:
        key, separator, value = raw.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise ValueError(f"{label} uses SERVICE=value")
        if allowed is not None and value.strip() not in allowed:
            raise ValueError(f"{label} value must be one of {sorted(allowed)}")
        result[key.strip()] = value.strip()
    return result


def grid_signature(source: Any) -> dict[str, Any]:
    return {
        "crs": str(source.crs), "width": source.width, "height": source.height,
        "transform": tuple(float(value) for value in source.transform),
        "nodata": source.nodata,
    }


def raster_statistics(path: Path, aggregation: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        import numpy as np  # type: ignore
        import rasterio  # type: ignore
    except ImportError as error:
        raise RuntimeError("multi-period InVEST summary requires numpy and rasterio") from error
    if not path.is_file():
        raise FileNotFoundError(f"InVEST raster does not exist: {path}")
    with rasterio.open(path) as source:
        if not source.crs or not source.crs.is_projected:
            raise ValueError(f"InVEST statistics require a projected raster: {path}")
        pixel_area_m2 = abs(float(source.transform.a * source.transform.e))
        if pixel_area_m2 <= 0:
            raise ValueError(f"InVEST raster has invalid pixel area: {path}")
        count, total, minimum, maximum = 0, 0.0, math.inf, -math.inf
        nodata = source.nodata
        for _, window in source.block_windows(1):
            values = source.read(1, window=window, masked=False)
            valid = np.isfinite(values)
            if nodata is not None:
                valid &= values != nodata
            selected = values[valid]
            if not selected.size:
                continue
            count += int(selected.size)
            total += float(selected.sum(dtype="float64"))
            minimum = min(minimum, float(selected.min()))
            maximum = max(maximum, float(selected.max()))
        if count == 0:
            raise ValueError(f"InVEST raster contains no valid cells: {path}")
        if aggregation == "sum":
            value = total
        elif aggregation == "mean":
            value = total / count
        elif aggregation == "depth_mm_to_m3":
            value = total / 1000.0 * pixel_area_m2
        else:  # Defensive: CLI validation prevents this path.
            raise ValueError(f"unsupported aggregation: {aggregation}")
        stats = {
            "value": value, "raw_sum": total, "raw_mean": total / count,
            "minimum": minimum, "maximum": maximum, "valid_pixel_count": count,
            "valid_area_ha": count * pixel_area_m2 / 10000.0,
        }
        return stats, grid_signature(source)


def figure(rows: list[dict[str, Any]], output: Path) -> None:
    services = sorted({str(row["service"]) for row in rows})
    years = sorted({int(row["year"]) for row in rows})
    panel_height, width, margin_left, margin_right = 310, 1120, 145, 120
    height = 115 + panel_height * max(1, len(services)) + 55
    min_year, max_year = min(years), max(years)
    x0, x1 = margin_left, width - margin_right

    def x(year: int) -> float:
        return (x0 + (x1 - x0) / 2) if max_year == min_year else x0 + (year - min_year) * (x1 - x0) / (max_year - min_year)

    panels: list[str] = []
    for index, service in enumerate(services):
        records = sorted((row for row in rows if row["service"] == service), key=lambda item: int(item["year"]))
        values = [float(row["value"]) for row in records]
        minimum, maximum = min(values), max(values)
        padding = max((maximum - minimum) * 0.12, abs(maximum) * 0.04, 1e-12)
        low, high = minimum - padding, maximum + padding
        top, bottom = 95 + index * panel_height, 95 + index * panel_height + 205

        def y(value: float) -> float:
            return (top + bottom) / 2 if high <= low else bottom - (value - low) * (bottom - top) / (high - low)

        color = PALETTE[index % len(PALETTE)]
        grid = []
        for fraction in range(5):
            value = low + (high - low) * fraction / 4
            yy = y(value)
            grid.append(f'<line x1="{x0}" y1="{yy:.2f}" x2="{x1}" y2="{yy:.2f}" class="grid"/>')
            grid.append(f'<text x="{x0 - 12}" y="{yy + 4:.2f}" text-anchor="end" class="axis">{value:.4g}</text>')
        points = " ".join(f"{x(int(row['year'])):.2f},{y(float(row['value'])):.2f}" for row in records)
        dots = []
        for row in records:
            xx, yy = x(int(row["year"])), y(float(row["value"]))
            dots.append(f'<circle cx="{xx:.2f}" cy="{yy:.2f}" r="5.2" fill="{color}"/><text x="{xx:.2f}" y="{yy-12:.2f}" text-anchor="middle" class="value">{float(row["value"]):.4g}</text>')
        unit = html.escape(str(records[0]["unit"]))
        panels.append(
            f'<g><text x="{x0}" y="{top - 28}" class="panel-title">{html.escape(service)}</text>'
            f'<text x="{x1}" y="{top - 28}" text-anchor="end" class="unit">{unit}</text>{"".join(grid)}'
            f'<line x1="{x0}" y1="{bottom}" x2="{x1}" y2="{bottom}" class="axis-line"/>'
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>{"".join(dots)}'
            + "".join(f'<text x="{x(year):.2f}" y="{bottom + 28}" text-anchor="middle" class="axis">{year}</text>' for year in years)
            + "</g>"
        )
    document = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
.title{{font:700 27px 'Segoe UI',Arial,sans-serif;fill:#172033}} .subtitle{{font:14px 'Segoe UI',Arial,sans-serif;fill:#536174}}
.panel-title{{font:700 18px 'Segoe UI',Arial,sans-serif;fill:#172033}} .unit{{font:13px 'Segoe UI',Arial,sans-serif;fill:#536174}}
.axis{{font:12px 'Segoe UI',Arial,sans-serif;fill:#536174}} .value{{font:600 12px 'Segoe UI',Arial,sans-serif;fill:#172033}}
.grid{{stroke:#dce3ed;stroke-width:1}} .axis-line{{stroke:#7a8699;stroke-width:1.2}}
</style><rect width="100%" height="100%" fill="#ffffff"/><text x="{width/2}" y="38" text-anchor="middle" class="title">Multi-period InVEST ecosystem-service change</text>
<text x="{width/2}" y="64" text-anchor="middle" class="subtitle">Values are calculated from valid raster cells; baseline changes are recorded in the accompanying CSV.</text>
{''.join(panels)}</svg>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")


def build(records: list[tuple[int, str, Path]], output_csv: Path, output_svg: Path,
          aggregations: dict[str, str], units: dict[str, str]) -> dict[str, Any]:
    grouped: dict[str, list[tuple[int, Path]]] = defaultdict(list)
    for year, service, path in records:
        grouped[service].append((year, path))
    rows: list[dict[str, Any]] = []
    reference_grids: dict[str, dict[str, Any]] = {}
    for service, dated in sorted(grouped.items()):
        dates = sorted(dated)
        years = [year for year, _ in dates]
        if len(years) != len(set(years)):
            raise ValueError(f"duplicate year for service {service}")
        aggregation = aggregations.get(service, DEFAULT_AGGREGATIONS.get(service, "sum"))
        if aggregation not in VALID_AGGREGATIONS:
            raise ValueError(f"unsupported aggregation for {service}: {aggregation}")
        unit = units.get(service, DEFAULT_UNITS.get(service, "undeclared"))
        baseline: float | None = None
        for year, path in dates:
            stats, signature = raster_statistics(path, aggregation)
            previous = reference_grids.get(service)
            if previous is None:
                reference_grids[service] = signature
            elif previous != signature:
                raise ValueError(f"same-service InVEST rasters must share one analysis grid: {path}")
            value = float(stats["value"])
            if baseline is None:
                baseline = value
            delta = value - baseline
            denominator = max(abs(baseline), 1e-12)
            rows.append({"year": year, "service": service, "aggregation": aggregation, "unit": unit,
                         "value": value, "change_from_baseline": delta,
                         "change_percent_from_baseline": delta / denominator * 100.0,
                         "raw_sum": stats["raw_sum"], "raw_mean": stats["raw_mean"],
                         "minimum": stats["minimum"], "maximum": stats["maximum"],
                         "valid_pixel_count": stats["valid_pixel_count"], "valid_area_ha": stats["valid_area_ha"],
                         "raster": str(path)})
    fields = ["year", "service", "aggregation", "unit", "value", "change_from_baseline", "change_percent_from_baseline",
              "raw_sum", "raw_mean", "minimum", "maximum", "valid_pixel_count", "valid_area_ha", "raster"]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    figure(rows, output_svg)
    metadata = {"status": "completed", "records": len(rows), "years": sorted({row["year"] for row in rows}),
                "services": sorted(grouped), "output_csv": str(output_csv.resolve()), "output_svg": str(output_svg.resolve()),
                "reference_grids": reference_grids}
    output_csv.with_suffix(output_csv.suffix + ".metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-raster", action="append", default=[], help="YEAR=SERVICE=path; repeat")
    parser.add_argument("--aggregation", action="append", default=[], help="SERVICE=sum|mean|depth_mm_to_m3")
    parser.add_argument("--unit", action="append", default=[], help="SERVICE=unit")
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument("--output-svg", required=True, type=Path)
    args = parser.parse_args()
    if not args.service_raster:
        raise SystemExit("at least one --service-raster is required")
    report = build([parse_service_record(item) for item in args.service_raster], args.output_csv.expanduser().resolve(),
                   args.output_svg.expanduser().resolve(), parse_mapping(args.aggregation, "--aggregation", VALID_AGGREGATIONS),
                   parse_mapping(args.unit, "--unit"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
