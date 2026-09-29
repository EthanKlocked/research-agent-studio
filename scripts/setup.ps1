# Requires an existing uv installation and Node.js 22 (including npm.cmd).
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $repoRoot
try {
    Get-Command uv -ErrorAction Stop | Out-Null
    Get-Command npm.cmd -ErrorAction Stop | Out-Null

    # Native failures must stop even on Windows PowerShell 5.1.
    uv sync --locked --extra dev
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm.cmd --prefix frontend ci
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm.cmd --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}
