[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $repoRoot
try {
    Get-Command uv -ErrorAction Stop | Out-Null
    Get-Command npm.cmd -ErrorAction Stop | Out-Null

    uv run --locked --extra dev python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm.cmd --prefix frontend test -- --run
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm.cmd --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}
