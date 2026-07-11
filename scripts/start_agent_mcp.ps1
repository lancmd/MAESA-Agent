[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$Host = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$skillRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $skillRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "MCP environment is missing. Run .\scripts\setup_agent.ps1 first."
}
& $python (Join-Path $skillRoot "mcp_server\mining_mcp_server.py") --transport streamable-http --host $Host --port $Port
