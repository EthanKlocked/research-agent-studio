"""Static PowerShell contracts, not a substitute for Windows execution.

These tests deliberately need no pwsh installation. Runtime behavior (including
finally on interruption and native argument passing) still needs Windows QA.
"""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = {
    "setup": [
        "uv sync --locked --extra dev",
        "npm.cmd --prefix frontend ci",
        "npm.cmd --prefix frontend run build",
    ],
    "start": [
        "uv run --locked --extra dev python -m uvicorn backend.api:app --host 127.0.0.1 --port 8765",
    ],
    "test": [
        "uv run --locked --extra dev python -m pytest tests -q",
        "npm.cmd --prefix frontend test -- --run",
        "npm.cmd --prefix frontend run build",
    ],
}


def source(name):
    path = ROOT / "scripts" / f"{name}.ps1"
    assert path.is_file(), f"Missing Windows launcher: {path.name}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", COMMANDS)
def test_native_commands_match_existing_workflow_and_stop_on_failure(name):
    text = source(name)
    positions = []
    for command in COMMANDS[name]:
        # Native programs do not reliably honor ErrorActionPreference in PS 5.1.
        pattern = re.escape(command) + r"\s+if \(\$LASTEXITCODE -ne 0\) \{\s*exit \$LASTEXITCODE\s*\}"
        match = re.search(pattern, text)
        assert match, f"Command must immediately propagate its nonzero exit: {command}"
        positions.append(match.start())
    assert positions == sorted(positions)


@pytest.mark.parametrize("name", COMMANDS)
def test_location_is_script_relative_and_restored_in_finally(name):
    text = source(name)
    assert "$ErrorActionPreference = 'Stop'" in text
    assert "$repoRoot = Split-Path -Parent $PSScriptRoot" in text
    assert "Push-Location -LiteralPath $repoRoot" in text
    assert re.search(r"Push-Location[^\n]*\ntry \{", text)
    assert re.search(r"finally \{[\s\S]*Pop-Location", text)
    assert "Get-Command uv -ErrorAction Stop" in text
    if name != "start":
        assert "Get-Command npm.cmd -ErrorAction Stop" in text


def test_start_requires_built_frontend_before_server():
    text = source("start")
    assert "Test-Path -LiteralPath 'frontend/dist/index.html' -PathType Leaf" in text
    assert re.search(r"throw ['\"][^\n]*setup\.ps1", text)
    assert text.index("Test-Path") < text.index(COMMANDS["start"][0])


def test_start_test_mode_is_opt_in_and_environment_is_restored():
    text = source("start")
    assert "[switch]$TestMode" in text
    assert "$previousTestMode = [Environment]::GetEnvironmentVariable('RESEARCH_TEST_MODE', 'Process')" in text
    assert re.search(r"if \(\$TestMode\) \{\s*\$env:RESEARCH_TEST_MODE = '1'\s*\}", text)
    assert text.count("$env:RESEARCH_TEST_MODE =") == 1
    assert re.search(
        r"finally \{\s*\[Environment\]::SetEnvironmentVariable\('RESEARCH_TEST_MODE', \$previousTestMode, 'Process'\)",
        text,
    )
    assert text.index("$previousTestMode =") < text.index("if ($TestMode)")


@pytest.mark.parametrize("name", COMMANDS)
def test_no_bootstrap_downloads_or_security_config_bypasses(name):
    text = source(name).lower()
    for forbidden in (
        "invoke-webrequest", "invoke-restmethod", "invoke-expression", "curl ",
        "set-executionpolicy", "-executionpolicy", "--no-verify", "--no-config",
        "0.0.0.0", "setx ",
    ):
        assert forbidden not in text
