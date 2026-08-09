#!/usr/bin/env python
"""Summarise Habitat Quality and composite ecosystem-service raster series.

The program reads GeoTIFFs block-by-block, so it can be run on the full
Wanbei study area without loading an entire period into memory.  It writes a
machine-readable statistics table and a compact two-panel trend figure.  The
result is descriptive: it does not replace independent LULC accuracy
assessment or ecological parameter sensitivity analysis.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFont


PERIODS = (2005, 2010, 2015, 2020, 2025)


@dataclass(frozen=True)
class RasterStatistics:
    year: int
    service: str
    unit: str
    valid_pixel_count: int
    valid_area_ha: float
    minimum: float
    maximum: float
    mean: float
    total: float
    raster: str


def _valid_values(data: np.ma.MaskedArray) -> np.ndarray:
    values = np.ma.compressed(data).astype(np.float64, copy=False)
    return values[np.isfinite(values)]


def summarise_raster(path: Path, year: int, service: str, unit: str) -> RasterStatistics:
    """Return exact finite-value statistics using the raster's native grid."""
    count = 0
    total = 0.0
    minimum = np.inf
    maximum = -np.inf
    with rasterio.open(path) as src:
        for _, window in src.block_windows(1):
            values = _valid_values(src.read(1, window=window, masked=True))
            if not values.size:
                continue
            count += int(values.size)
            total += float(values.sum(dtype=np.float64))
            minimum = min(minimum, float(values.min()))
            maximum = max(maximum, float(values.max()))
        if count == 0:
            raise ValueError(f"No valid raster cells: {path}")
        pixel_area_ha = abs(src.transform.a * src.transform.e) / 10_000.0

    return RasterStatistics(
        year=year,
        service=service,
        unit=unit,
        valid_pixel_count=count,
        valid_area_ha=count * pixel_area_ha,
        minimum=minimum,
        maximum=maximum,
        mean=total / count,
        total=total,
        raster=str(path),
    )


def add_baseline_change(rows: Iterable[RasterStatistics]) -> list[dict[str, object]]:
    ordered = sorted(rows, key=lambda row: (row.service, row.year))
    baselines: dict[str, float] = {}
    result: list[dict[str, object]] = []
    for row in ordered:
        record = asdict(row)
        baseline = baselines.setdefault(row.service, row.mean)
        record["change_from_2005"] = row.mean - baseline
        record["change_percent_from_2005"] = (
            None if np.isclose(baseline, 0.0) else (row.mean - baseline) / baseline * 100.0
        )
        result.append(record)
    return result


def write_csv(records: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "year", "service", "unit", "valid_pixel_count", "valid_area_ha", "minimum",
        "maximum", "mean", "total", "change_from_2005", "change_percent_from_2005", "raster",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _chart_points(values: list[float], left: int, top: int, right: int, bottom: int) -> list[tuple[int, int]]:
    width = right - left
    height = bottom - top
    return [
        (round(left + index * width / (len(values) - 1)), round(bottom - max(0.0, min(1.0, value)) * height))
        for index, value in enumerate(values)
    ]


def make_trend_figure(records: list[dict[str, object]], png: Path, svg: Path) -> None:
    by_service: dict[str, list[dict[str, object]]] = {"habitat_quality": [], "ecosystem_service": []}
    for record in records:
        by_service[str(record["service"])].append(record)

    labels = {
        "habitat_quality": ("Habitat Quality", "生境质量指数"),
        "ecosystem_service": ("Composite Ecosystem Services", "综合生态服务指数"),
    }
    colors = {"habitat_quality": "#277f45", "ecosystem_service": "#8a2c79"}

    # Pillow keeps the reporting dependency set small: rasterio + numpy + Pillow.
    image = Image.new("RGB", (1600, 640), "white")
    draw = ImageDraw.Draw(image)
    draw.text((800, 30), "2005–2025 Ecosystem-service temporal trend", fill="#1f2933",
              font=_font(28, bold=True), anchor="ma")
    svg_parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="640" viewBox="0 0 1600 640">',
        '<rect width="1600" height="640" fill="white"/>',
        '<style>text{font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif;fill:#1f2933}</style>',
        '<text x="800" y="54" font-size="28" font-weight="700" text-anchor="middle">2005–2025 Ecosystem-service temporal trend</text>',
    ]
    panel_boxes = [(105, 145, 735, 510), (865, 145, 1495, 510)]
    for (left, top, right, bottom), service in zip(panel_boxes, ("habitat_quality", "ecosystem_service"), strict=True):
        values = sorted(by_service[service], key=lambda item: int(item["year"]))
        years = [int(item["year"]) for item in values]
        means = [float(item["mean"]) for item in values]
        title_en, title_cn = labels[service]
        draw.text(((left + right) // 2, 92), title_en, fill="#1f2933", font=_font(20, bold=True), anchor="ma")
        draw.text(((left + right) // 2, 120), title_cn, fill="#4b5563", font=_font(15), anchor="ma")
        svg_parts.extend([
            f'<text x="{(left + right) // 2}" y="112" font-size="20" font-weight="700" text-anchor="middle">{html.escape(title_en)}</text>',
            f'<text x="{(left + right) // 2}" y="136" font-size="15" fill="#4b5563" text-anchor="middle">{html.escape(title_cn)}</text>',
        ])
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = round(bottom - fraction * (bottom - top))
            draw.line((left, y, right, y), fill="#d9dee5", width=1)
            draw.text((left - 12, y), f"{fraction:.2f}", fill="#64748b", font=_font(13), anchor="rm")
            svg_parts.append(f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" stroke="#d9dee5" stroke-width="1"/>')
            svg_parts.append(f'<text x="{left - 12}" y="{y + 5}" font-size="13" fill="#64748b" text-anchor="end">{fraction:.2f}</text>')
        draw.line((left, top, left, bottom), fill="#475569", width=2)
        draw.line((left, bottom, right, bottom), fill="#475569", width=2)
        svg_parts.extend([
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#475569" stroke-width="2"/>',
            f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#475569" stroke-width="2"/>',
        ])
        points = _chart_points(means, left, top, right, bottom)
        for (x, _), year in zip(points, years, strict=True):
            draw.text((x, bottom + 24), str(year), fill="#4b5563", font=_font(14), anchor="ma")
            svg_parts.append(f'<text x="{x}" y="{bottom + 29}" font-size="14" fill="#4b5563" text-anchor="middle">{year}</text>')
        draw.line(points, fill=colors[service], width=5, joint="curve")
        svg_parts.append('<polyline points="' + " ".join(f"{x},{y}" for x, y in points) +
                         f'" fill="none" stroke="{colors[service]}" stroke-width="5" stroke-linejoin="round"/>')
        for (x, y), mean in zip(points, means, strict=True):
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill="white", outline=colors[service], width=4)
            draw.text((x, y - 15), f"{mean:.3f}", fill="#334155", font=_font(13), anchor="ms")
            svg_parts.extend([
                f'<circle cx="{x}" cy="{y}" r="7" fill="white" stroke="{colors[service]}" stroke-width="4"/>',
                f'<text x="{x}" y="{y - 15}" font-size="13" text-anchor="middle">{mean:.3f}</text>',
            ])
        draw.text(((left + right) // 2, bottom + 58), "Year", fill="#334155", font=_font(15), anchor="ma")
        svg_parts.append(f'<text x="{(left + right) // 2}" y="{bottom + 63}" font-size="15" text-anchor="middle">Year</text>')

    png.parent.mkdir(parents=True, exist_ok=True)
    image.save(png, format="PNG", optimize=True)
    svg_parts.append("</svg>")
    svg.write_text("\n".join(svg_parts), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True, help="Wanbei project data directory")
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--figure-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_root = args.data_root.resolve()
    rows: list[RasterStatistics] = []
    for year in PERIODS:
        habitat = data_root / "outputs" / "invest" / "habitat_quality_tiled_318_v2" / str(year) / f"quality_{year}_30m.tif"
        composite = data_root / "outputs" / "ecosystem_service_ahp_minmax_20260805" / f"ecosystem_service_{year}.tif"
        rows.append(summarise_raster(habitat, year, "habitat_quality", "index_0_to_1"))
        rows.append(summarise_raster(composite, year, "ecosystem_service", "index_0_to_1"))

    records = add_baseline_change(rows)
    write_csv(records, args.output_csv)
    metadata = {
        "status": "completed",
        "method": "blockwise_exact_statistics_on_valid_cells",
        "periods": list(PERIODS),
        "classification_status": "pending_validation",
        "interpretation_note": "Descriptive service statistics; review habitat parameters and LULC accuracy before formal reporting.",
        "records": records,
    }
    metadata_path = args.output_csv.with_suffix(".metadata.json")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    make_trend_figure(
        records,
        args.figure_dir / "Habitat_EcosystemService_Trend_2005_2025.png",
        args.figure_dir / "Habitat_EcosystemService_Trend_2005_2025.svg",
    )
    print(json.dumps({"csv": str(args.output_csv), "metadata": str(metadata_path), "records": len(records)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
