[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$WithPyTorch,
    [switch]$WithPlusGui
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
$extras = @("validation")
if ($WithPyTorch) { $extras += "pytorch" }
if ($WithPlusGui) { $extras += "plus-gui" }
& $venvPython -m pip install -e "$package[$($extras -join ',')]"

$registry = Join-Path $skillRoot "interfaces\backend_registry.json"
$registryExample = Join-Path $skillRoot "interfaces\backend_registry.example.json"
if (-not (Test-Path -LiteralPath $registry)) {
    Copy-Item -LiteralPath $registryExample -Destination $registry
}
else {
    # Preserve personal software paths while adding bundled local backends
    # introduced by an upgrade.  Explicit MINING_GIS_BACKENDS files are not
    # touched; this only migrates the setup-managed registry.
    $current = Get-Content -LiteralPath $registry -Raw | ConvertFrom-Json
    $defaults = Get-Content -LiteralPath $registryExample -Raw | ConvertFrom-Json
    $registryChanged = $false
    if (-not $current.backends.PSObject.Properties['classification']) {
        $current.backends | Add-Member -NotePropertyName classification -NotePropertyValue $defaults.backends.classification
        $registryChanged = $true
    }
    if (-not $current.backends.PSObject.Properties['invest']) {
        $current.backends | Add-Member -NotePropertyName invest -NotePropertyValue $defaults.backends.invest
        $registryChanged = $true
    }
    else {
        $currentCapabilities = @($current.backends.invest.capabilities)
        foreach ($capability in @($defaults.backends.invest.capabilities)) {
            if ($currentCapabilities -notcontains $capability) {
                $currentCapabilities += $capability
                $registryChanged = $true
            }
        }
        if ($registryChanged) {
            $current.backends.invest.capabilities = @($currentCapabilities)
        }
    }
    if ($registryChanged) {
        $current | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $registry -Encoding utf8
    }
}
$localPaths = Join-Path $skillRoot "config\local_paths.json"
$localPathsExample = Join-Path $skillRoot "config\local_paths.example.json"
if (-not (Test-Path -LiteralPath $localPaths)) {
    Copy-Item -LiteralPath $localPathsExample -Destination $localPaths
}
$plusProfile = Join-Path $skillRoot "config\plus_v142_ui_profile.json"
$plusProfileExample = Join-Path $skillRoot "config\plus_v142_ui_profile.example.json"
if (-not (Test-Path -LiteralPath $plusProfile)) {
    Copy-Item -LiteralPath $plusProfileExample -Destination $plusProfile
}

& $venvPython (Join-Path $PSScriptRoot "verify_agent_install.py") --skill-root $skillRoot
Write-Output "Setup complete. Set local software paths or environment variables if needed, then start: .\scripts\start_agent_mcp.ps1"
