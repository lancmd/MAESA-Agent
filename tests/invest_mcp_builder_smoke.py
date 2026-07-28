"""Exercise the public MCP tools for Habitat datastack and Carbon coverage contracts."""

from __future__ import annotations

import asyncio
import csv
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import rasterio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "outputs" / "invest_mcp_builder_inputs"
WORKSPACE = ROOT / "outputs" / "mcp" / "invest_mcp_builder_smoke"


def write_raster(path: Path, values: list[list[int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=1, dtype="int16",
                       crs="EPSG:32650", transform=from_origin(500000, 3700060, 30, 30), nodata=-9999) as sink:
        sink.write(np.array(values, dtype="int16"), 1)


async def run() -> None:
    shutil.rmtree(WORKSPACE, ignore_errors=True)
    lulc, threat = INPUTS / "lulc.tif", INPUTS / "road.tif"
    write_raster(lulc, [[1, 2], [1, 2]]); write_raster(threat, [[1, 0], [0, 1]])
    carbon = INPUTS / "carbon.csv"
    with carbon.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(["lucode", "c_above", "c_below", "c_soil", "c_dead"])
        writer.writerows([[1, 1, 1, 1, 0], [2, 2, 2, 2, 0], [3, 3, 3, 3, 0]])
    environment = dict(os.environ)
    environment["MINING_GIS_INPUT_ROOTS"] = str(ROOT)
    environment["MINING_GIS_OUTPUT_ROOT"] = str(ROOT / "outputs")
    parameters = StdioServerParameters(command=sys.executable,
                                       args=[str(ROOT / "mcp_server" / "mining_mcp_server.py"), "--transport", "stdio"],
                                       env=environment)
    config = {
        "lulc_path": str(lulc), "half_saturation_constant": 0.5,
        "threats": [{"name": "road", "raster": str(threat), "max_distance_m": 1000, "weight": 1, "decay": "linear"}],
        "sensitivity": [{"lulc": 1, "habitat": 0.7, "threats": {"road": 0.2}},
                        {"lulc": 2, "habitat": 0.3, "threats": {"road": 0.8}}],
    }
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool("build_habitat_quality_datastack", {
                "habitat_config": config, "workspace": str(WORKSPACE),
            })
            payload = json.loads(result.content[0].text)
            assert payload["status"] == "completed", payload
            assert Path(payload["result"]["datastack"]).is_file()
            coverage_result = await session.call_tool("validate_carbon_density_coverage", {
                "lulc_path": str(lulc), "carbon_density": str(carbon),
            })
            coverage = json.loads(coverage_result.content[0].text)
            assert coverage["status"] == "completed", coverage
            assert coverage["result"]["extra_carbon_codes"] == [3], coverage


asyncio.run(run())
print('{"status":"completed","checks":["MCP Habitat datastack builder","MCP Carbon coverage validator"]}')
