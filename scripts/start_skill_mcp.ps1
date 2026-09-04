[CmdletBinding()]
param(
    [int]$Port = 8765,
    [Alias("Host")]
    [string]$BindHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $OutputEncoding
$skillRoot = Split-Path -Parent $PSScriptRoot
$listeners = @()
try { $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) } catch {}
if ($listeners.Count -gt 0) {
    $processIds = @($listeners | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique) -join ", "
    throw "Port $Port is occupied by process id(s): $processIds. Try: .\scripts\start_skill_mcp.ps1 -Port $($Port + 1)"
}
$python = Join-Path $skillRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "MCP environment is missing. Run .\scripts\setup_skill.ps1 first."
}
& $python (Join-Path $skillRoot "mcp_server\mining_mcp_server.py") --transport streamable-http --host $BindHost --port $Port
