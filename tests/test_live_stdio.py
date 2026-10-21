"""Spawn the example FastMCP server over stdio and check it (no network)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
pytest.importorskip("fastmcp")

SERVER = Path(__file__).resolve().parents[1] / "examples" / "demo_server.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mcpdialect", *args], capture_output=True, text=True, timeout=120, check=False
    )


def test_stdio_check_original_server():
    r = run("check", "--cmd", f'"{sys.executable}" "{SERVER}"', "-p", "gemini,anthropic", "-f", "json")
    assert r.returncode == 1, r.stderr
    data = json.loads(r.stdout)
    names = {t["name"] for t in data["tools"]}
    assert names == {"search_messages", "edit_document"}
    assert {f["rule"] for f in data["findings"]} >= {"GEM002", "GEM003"}


def test_stdio_check_portable_server():
    r = run("check", "--cmd", f'"{sys.executable}" "{SERVER}" --portable', "-p", "gemini,anthropic,mcp")
    assert r.returncode == 0, r.stdout + r.stderr


def test_stdio_bad_command_exits_nonzero():
    r = run("check", "--cmd", f'"{sys.executable}" -c "import sys; sys.exit(3)"', "--timeout", "10")
    assert r.returncode != 0
