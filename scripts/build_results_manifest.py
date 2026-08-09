#!/usr/bin/env python
"""Create a provenance-oriented manifest for the generated Wanbei results.

The manifest only records files that are actually present.  It deliberately
distinguishes completed raster processing from outstanding scientific
validation, including LULC independent accuracy assessment and PLUS output
handover.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import rasterio


PERIODS = (2005, 2010, 2015, 2020, 2025)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def raster_metadata(path: Path) -> dict[str, object]:
    with rasterio.open(path) as src:
        return {
            "crs": src.crs.to_string() if src.crs else None,
            "width": src.width,
            "height": src.height,
            "resolution": [abs(src.transform.a), abs(src.transform.e)],
            "bounds": [src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top],
            "dtype": src.dtypes[0],
            "nodata": src.nodata,
        }


def record(path: Path, stage: str, data_root: Path) -> dict[str, object]:
    result: dict[str, object] = {
        "path": str(path.relative_to(data_root)),
        "stage": stage,
        "file_type": path.suffix.lower().lstrip("."),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }
    if path.suffix.lower() in {".tif", ".tiff"}:
        result["spatial"] = raster_metadata(path)
    return result


def existing(paths: Iterable[tuple[Path, str]]) -> list[tuple[Path, str]]:
    return [(path, stage) for path, stage in paths if path.is_file()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.data_root.resolve()

    planned: list[tuple[Path, str]] = []
    for year in PERIODS:
        planned.extend([
            (root / "outputs" / "classification" / "final_grid_v3" / f"LULC_{year}_30m_masked.tif", "lulc_classification"),
            (root / "outputs" / "invest" / "carbon_series_20260805" / str(year) / "tot_c_cur.tif", "invest_carbon"),
            (root / "outputs" / "invest" / "water_yield_20260805" / str(year) / "output" / "per_pixel" / f"wyield_wy_{year}.tif", "invest_water_yield"),
            (root / "outputs" / "invest" / "habitat_quality_tiled_318_v2" / str(year) / f"quality_{year}_30m.tif", "invest_habitat_quality"),
            (root / "outputs" / "ecosystem_service_ahp_minmax_20260805" / f"ecosystem_service_{year}.tif", "ecosystem_service_ahp_minmax"),
        ])
    statistics = root / "outputs" / "statistics"
    planned.extend((path, "statistics") for path in sorted(statistics.glob("*.csv")))
    planned.extend((path, "statistics_metadata") for path in sorted(statistics.glob("*.metadata.json")))
    figure_root = root / "maps" / "maesa_results_20260805" / "图件成果"
    planned.extend((path, "cartography") for path in sorted(figure_root.rglob("*.png")))
    planned.extend((path, "cartography") for path in sorted(figure_root.rglob("*.svg")))
    planned.extend((path, "cartography_layout") for path in sorted(figure_root.rglob("*.pdf")))
    planned.extend((path, "cartography_project") for path in sorted(figure_root.rglob("*.aprx")))
    planned.extend((path, "cartography_layout_template") for path in sorted(figure_root.rglob("*.pagx")))
    analysis_root = root / "maps" / "maesa_results_20260805" / "分析成果"
    planned.extend((path, "paper_analysis") for path in sorted(analysis_root.rglob("*.csv")))
    planned.extend((path, "paper_analysis") for path in sorted(analysis_root.rglob("*.json")))
    planned.extend((path, "paper_analysis") for path in sorted(analysis_root.rglob("*.png")))
    planned.extend((path, "paper_analysis") for path in sorted(analysis_root.rglob("*.svg")))
    planned.extend((path, "paper_analysis") for path in sorted(analysis_root.rglob("*.md")))

    output = args.output.resolve()
    artifacts = [record(path, stage, root) for path, stage in existing(planned)]
    manifest = {
        "status": "completed_with_validation_pending",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "project_data_root": str(root),
        "periods": list(PERIODS),
        "analysis_grid": {"target_resolution_m": 30, "crs": "EPSG:32650"},
        "validation_status": {
            "lulc_accuracy": "pending_validation",
            "invest_carbon": "completed_output_not_independently_cross_checked",
            "invest_water_yield": "completed_parameter_review_required",
            "invest_habitat_quality": "completed_parameter_review_required",
            "ecosystem_service": "completed_ahp_consistency_checked",
            "plus_2026": "prepared_no_verified_output",
        },
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(output), "artifact_count": len(artifacts)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
