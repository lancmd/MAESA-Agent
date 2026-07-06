"""Verify MCP initialization, tool discovery, and backend registry access."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


async def run() -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "mcp_server" / "mining_mcp_server.py"), "--transport", "stdio"],
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            expected = {
                "list_backends", "backend_capabilities", "inspect_dataset", "run_gee_export",
                "run_envi_classification", "run_arcgis_operations", "run_plus_scenario",
                "run_invest_carbon", "get_job_status", "cancel_job", "list_job_outputs",
            }
            missing = expected - names
            if missing:
                raise AssertionError(f"missing MCP tools: {sorted(missing)}")
            result = await session.call_tool("list_backends", {})
            payload = json.loads(result.content[0].text)
            if not {"gee", "envi", "plus", "arcgis", "invest"}.issubset(payload["backends"]):
                raise AssertionError("backend registry is incomplete")
            capability_result = await session.call_tool("backend_capabilities", {"backend": "arcgis"})
            capability = json.loads(capability_result.content[0].text)
            if capability.get("status") != "completed":
                raise AssertionError(f"local command bridge failed: {capability}")
            end_to_end = {}
            raster = ROOT / "outputs" / "arcgis_smoke" / "lulc.tif"
            if raster.exists():
                inspected_result = await session.call_tool("inspect_dataset", {"path": str(raster)})
                inspected = json.loads(inspected_result.content[0].text)
                if inspected.get("status") != "completed" or inspected["result"].get("factory_code") != 32650:
                    raise AssertionError(f"ArcGIS MCP inspection failed: {inspected}")
                end_to_end["arcgis_crs"] = inspected["result"]["factory_code"]
            datastack = ROOT / "tests" / "invest_carbon_smoke_datastack.json"
            if datastack.exists() and raster.exists():
                invest_workspace = ROOT / "outputs" / "mcp_invest_smoke"
                invest_result = await session.call_tool("run_invest_carbon", {
                    "datastack": str(datastack), "workspace": str(invest_workspace)
                })
                invest = json.loads(invest_result.content[0].text)
                if invest.get("status") != "completed":
                    raise AssertionError(f"InVEST MCP run failed: {invest}")
                end_to_end["invest_outputs"] = len(invest.get("outputs", []))
            print(json.dumps({"tools": sorted(names), "backends": sorted(payload["backends"]),
                              "arcgis_bridge": capability["result"], "end_to_end": end_to_end}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(run())
