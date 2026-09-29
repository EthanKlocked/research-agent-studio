"""Locale-independent text I/O: static guard and simulated cp949 reads."""
import ast
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]


def implicit_text_io(source):
    """Find standard text I/O calls without a non-None encoding (no linter dependency)."""
    violations = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name not in {"open", "read_text", "write_text"}:
            continue
        if name == "open":
            # Path.open has no filename argument; builtins.open/io.open do.
            path_open = isinstance(node.func, ast.Attribute) and not (
                isinstance(node.func.value, ast.Name) and node.func.value.id in {"io", "builtins"}
            )
            mode_index, encoding_index = (0, 2) if path_open else (1, 3)
            mode = next((kw.value for kw in node.keywords if kw.arg == "mode"),
                        node.args[mode_index] if len(node.args) > mode_index else ast.Constant("r"))
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value:
                continue
        else:
            encoding_index = 0 if name == "read_text" else 1
        encoding = next((kw.value for kw in node.keywords if kw.arg == "encoding"),
                        node.args[encoding_index] if len(node.args) > encoding_index else None)
        if encoding is None or isinstance(encoding, ast.Constant) and encoding.value is None:
            violations.append(node.lineno)
    return violations


@pytest.mark.parametrize("source, expected", [
    ('path.read_text()', [1]),
    ('path.write_text("hello")', [1]),
    ('open("file")', [1]),
    ('path.open("w")', [1]),
    ('io.open("file", encoding=None)', [1]),
    ('path.read_text(encoding="utf-8")', []),
    ('path.write_text("hello", "utf-8")', []),
    ('open("file", "r", -1, "utf-8")', []),
    ('path.open("r", -1, "utf-8")', []),
    ('open("file", "rb")', []),
    ('path.open(mode="wb")', []),
])
def test_encoding_guard_cases(source, expected):
    assert implicit_text_io(source) == expected


def test_project_text_io_has_explicit_encoding():
    violations = []
    for directory in ("backend", "mcp_server", "tests"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            violations.extend(f"{path.relative_to(ROOT)}:{line}" for line in
                              implicit_text_io(path.read_text(encoding="utf-8")))
    assert not violations, "Implicit text encoding: " + ", ".join(violations)


@pytest.mark.parametrize("target", ["backend.mcp_client", "backend.api", "mcp_server.server"])
def test_bundled_data_with_simulated_cp949_default(target):
    # Fresh interpreters ensure import-time reads cannot hide behind sys.modules.
    script = textwrap.dedent('''
        import importlib
        import json
        from pathlib import Path
        import sys

        dataset = (Path.cwd() / "data/apple_fy2024.json").resolve()
        original = Path.read_text
        expected = json.loads(original(dataset, encoding="utf-8"))
        reads = []

        def simulated(self, encoding=None, errors=None):
            if self.resolve() == dataset:
                reads.append(encoding)
                encoding = encoding or "cp949"
            return original(self, encoding=encoding, errors=errors)

        Path.read_text = simulated
        # Prove this simulation really rejects implicit reads of this UTF-8 fixture.
        try:
            dataset.read_text()
        except UnicodeDecodeError:
            pass
        else:
            raise AssertionError("fixture no longer detects a cp949 default")
        reads.clear()
        module = importlib.import_module(sys.argv[1])
        if sys.argv[1] == "backend.api":
            from backend.config import Settings
            assert module.create_app(Settings(test_mode=True)).state.manager
        elif sys.argv[1] == "backend.mcp_client":
            assert module.SECTION_IDS == frozenset(
                (s["document_id"], s["section_id"]) for s in expected["sections"])
        else:
            assert module.DATA == expected
            section = expected["sections"][0]
            assert module.get_section(section["document_id"], section["section_id"])["excerpt"] == section["excerpt"]
            assert module.search_documents(section["title"])
        assert reads, "No bundled data read was exercised"
    ''')
    result = subprocess.run([sys.executable, "-c", script, target], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
