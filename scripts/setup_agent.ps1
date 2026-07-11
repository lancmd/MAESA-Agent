[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$WithPyTorch
)

$ErrorActionPreference = "Stop"
$skillRoot = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $skillRoot ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"

if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw "Python executable was not found: $Python"
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv $venv
}

& $venvPython -m pip install --upgrade pip
$package = Join-Path $skillRoot "mcp_server"
if ($WithPyTorch) {
    & $venvPython -m pip install -e "$package[pytorch]"
} else {
    & $venvPython -m pip install -e "$package[validation]"
}

$registry = Join-Path $skillRoot "interfaces\backend_registry.json"
$registryExample = Join-Path $skillRoot "interfaces\backend_registry.example.json"
if (-not (Test-Path -LiteralPath $registry)) {
    Copy-Item -LiteralPath $registryExample -Destination $registry
}
$localPaths = Join-Path $skillRoot "config\local_paths.json"
$localPathsExample = Join-Path $skillRoot "config\local_paths.example.json"
if (-not (Test-Path -LiteralPath $localPaths)) {
    Copy-Item -LiteralPath $localPathsExample -Destination $localPaths
}

& $venvPython (Join-Path $PSScriptRoot "verify_agent_install.py") --skill-root $skillRoot
Write-Output "Setup complete. Set local software paths or environment variables if needed, then start: .\scripts\start_agent_mcp.ps1"
