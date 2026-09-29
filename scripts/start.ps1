# Run with -TestMode for deterministic fixtures instead of live model calls.
[CmdletBinding()]
param(
    [switch]$TestMode
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$previousTestMode = [Environment]::GetEnvironmentVariable('RESEARCH_TEST_MODE', 'Process')
Push-Location -LiteralPath $repoRoot
try {
    Get-Command uv -ErrorAction Stop | Out-Null
    if (-not (Test-Path -LiteralPath 'frontend/dist/index.html' -PathType Leaf)) {
        throw 'Run scripts/setup.ps1 first to build the frontend.'
    }
    if ($TestMode) {
        $env:RESEARCH_TEST_MODE = '1'
    }
    Write-Host 'Research Agent Studio: http://127.0.0.1:8765 - Ctrl+C to stop'
    uv run --locked --extra dev python -m uvicorn backend.api:app --host 127.0.0.1 --port 8765
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    [Environment]::SetEnvironmentVariable('RESEARCH_TEST_MODE', $previousTestMode, 'Process')
    Pop-Location
}
