"""Contract checks for the reproducible reporting and publication scripts.

The test deliberately examines source contracts only: CI has no private mine
rasters, ArcGIS/ENVI licences, or Microsoft Word installation.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    assets = source("scripts/build_wanbei_report_assets.py")
    report = source("scripts/build_ecosystem_service_report.py")
    maps = source("scripts/render_publication_results.py")
    readme = source("README.md")

    # Water Yield is depth in mm.  Convert depth to volume once, using the
    # native pixel area rather than a hard-coded raster resolution.
    assert "array * area_m2 / 1000.0" in assets
    # InVEST Carbon's tot_c_cur is Mg C per pixel.  Its sum is already a
    # total; only display maps are converted to a density surface.
    assert "tot_c_cur.tif`` stores Mg C per pixel" in assets
    assert "vals.sum() / 1_000_000.0" in maps
    assert "vals.sum() * 0.9 / 1_000_000.0" in maps
    assert "continuous_array" in maps

    # Do not let a report imply unmeasured classification or PLUS accuracy.
    assert '"validation_status": "pending_validation"' in report
    assert "PLUS FoM and multi-seed stability are not available" in report
    assert "scenario labels are not treated as verified policy effects" in report
    assert "three_line_table" in report

    # The public entry point documents local-first execution and doesn't
    # carry the common mojibake marker caused by Windows code-page writes.
    assert "local-first" in readme
    assert "锟" not in readme
    assert "replace_with_" not in readme
    print("report asset contract smoke passed")


if __name__ == "__main__":
    main()
