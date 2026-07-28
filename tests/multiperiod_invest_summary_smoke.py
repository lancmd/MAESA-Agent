"""Check period-wise carbon and habitat summaries use the correct aggregation."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]


def write_raster(path: Path, values: list[list[float]]) -> None:
    with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=1, dtype="float32",
                       crs="EPSG:32650", transform=from_origin(500000, 3700060, 30, 30), nodata=-9999) as sink:
        sink.write(np.asarray(values, dtype="float32"), 1)


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    carbon_2010, carbon_2020 = root / "carbon_2010.tif", root / "carbon_2020.tif"
    habitat_2010, habitat_2020 = root / "habitat_2010.tif", root / "habitat_2020.tif"
    write_raster(carbon_2010, [[1, 2], [3, 4]])
    write_raster(carbon_2020, [[2, 3], [4, 5]])
    write_raster(habitat_2010, [[0.2, 0.4], [0.6, 0.8]])
    write_raster(habitat_2020, [[0.4, 0.6], [0.8, 1.0]])
    table, figure = root / "summary.csv", root / "summary.svg"
    command = [sys.executable, str(ROOT / "scripts" / "multiperiod_invest_summary.py"),
               "--service-raster", f"2010=carbon_storage_t_c={carbon_2010}",
               "--service-raster", f"2020=carbon_storage_t_c={carbon_2020}",
               "--service-raster", f"2010=habitat_quality={habitat_2010}",
               "--service-raster", f"2020=habitat_quality={habitat_2020}",
               "--output-csv", str(table), "--output-svg", str(figure)]
    process = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    assert process.returncode == 0, process.stdout
    rows = list(csv.DictReader(table.open(encoding="utf-8-sig")))
    lookup = {(row["year"], row["service"]): row for row in rows}
    assert float(lookup[("2010", "carbon_storage_t_c")]["value"]) == 10
    assert float(lookup[("2020", "carbon_storage_t_c")]["change_from_baseline"]) == 4
    assert abs(float(lookup[("2010", "habitat_quality")]["value"]) - 0.5) < 1e-6
    assert abs(float(lookup[("2020", "habitat_quality")]["change_percent_from_baseline"]) - 40) < 1e-5
    assert figure.is_file() and "Multi-period InVEST" in figure.read_text(encoding="utf-8")

print('{"status":"completed","checks":["carbon sum","habitat mean","change table","trend figure"]}')
