"""CLI integration tests: run the real entry point in a subprocess."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mcpdialect", *args],
        capture_output=True,
        text=True,
        input=stdin,
        timeout=60,
        check=False,
    )


def test_check_clean_exits_0():
    r = run("check", str(FIX / "synthetic/clean.json"), "-p", "openai-strict,anthropic,mcp")
    assert r.returncode == 0, r.stderr
    assert "get_weather" in r.stdout and "OK" in r.stdout


def test_check_fixable_exits_1_and_fail_on_breaks_exits_0():
    f = str(FIX / "real/workspace_gemini_1099.json")
    r = run("check", f, "-p", "gemini")
    assert r.returncode == 1
    assert "GEM002" in r.stdout and "FIXABLE" in r.stdout
    assert run("check", f, "-p", "gemini", "--fail-on", "breaks").returncode == 0
    assert run("check", f, "-p", "gemini", "--fail-on", "never").returncode == 0


def test_check_breaks_exits_1_even_with_fail_on_breaks():
    r = run("check", str(FIX / "synthetic/unfixable.json"), "-p", "gemini", "--fail-on", "breaks")
    assert r.returncode == 1
    assert "BREAKS" in r.stdout


def test_check_json_output():
    r = run("check", str(FIX / "real/defs_refs_13326.json"), "-p", "gemini,anthropic", "-f", "json")
    data = json.loads(r.stdout)
    assert data["profiles"] == ["gemini", "anthropic"]
    assert data["tools"][0]["verdicts"] == {"gemini": "fixable", "anthropic": "ok"}
    assert {f["rule"] for f in data["findings"]} == {"GEM004"}


def test_check_sarif_output(tmp_path):
    out = tmp_path / "r.sarif"
    r = run("check", str(FIX / "real/workspace_gemini_1099.json"), "-p", "gemini", "-f", "sarif", "-o", str(out))
    assert r.returncode == 1
    sarif = json.loads(out.read_text())
    assert sarif["version"] == "2.1.0"
    run0 = sarif["runs"][0]
    assert {rule["id"] for rule in run0["tool"]["driver"]["rules"]} == {"GEM002", "GEM003", "GEM005"}
    assert all(res["ruleId"] in {"GEM002", "GEM003", "GEM005"} for res in run0["results"])
    assert all(rule["helpUri"].startswith("https://") for rule in run0["tool"]["driver"]["rules"])


def test_check_github_annotations():
    r = run("check", str(FIX / "real/openai_strict_376.json"), "-p", "openai-strict", "-f", "github")
    lines = r.stdout.strip().splitlines()
    assert lines and all(line.startswith("::error file=") for line in lines)


@pytest.mark.parametrize("name", ["synthetic/jsonrpc_envelope.json", "synthetic/bare_list.json"])
def test_input_shapes(name):
    r = run("check", str(FIX / name), "-p", "mcp")
    assert r.returncode == 0, r.stdout + r.stderr


def test_multiple_files_are_combined():
    r = run(
        "check", str(FIX / "synthetic/clean.json"), str(FIX / "synthetic/bare_list.json"), "-p", "mcp", "-f", "json"
    )
    assert r.returncode == 0, r.stderr
    assert [t["name"] for t in json.loads(r.stdout)["tools"]] == ["get_weather", "t"]


def test_stdin_input():
    r = run("check", "-", "-p", "mcp", stdin=json.dumps([{"name": "t", "inputSchema": {"type": "object"}}]))
    assert r.returncode == 0, r.stderr


def test_usage_errors_exit_2(tmp_path):
    assert run("check").returncode == 2  # no source
    assert run("check", str(FIX / "synthetic/clean.json"), "--cmd", "x").returncode == 2  # two sources
    assert run("check", "missing.json").returncode == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert run("check", str(bad)).returncode == 2
    assert run("check", str(FIX / "synthetic/clean.json"), "-p", "nope").returncode == 2
    assert run("explain", "XXX999").returncode == 2
    assert run("bogus-command").returncode == 2
    weird = tmp_path / "weird.json"
    weird.write_text(json.dumps({"tools": [{"inputSchema": {}}]}))
    assert run("check", str(weird)).returncode == 2


def test_fix_writes_portable_tools_and_report(tmp_path):
    out, rep = tmp_path / "fixed.json", tmp_path / "changes.json"
    r = run("fix", str(FIX / "real/workspace_gemini_1099.json"), "-p", "gemini", "-o", str(out), "--report", str(rep))
    assert r.returncode == 0, r.stderr
    assert "change(s)" in r.stderr
    fixed = json.loads(out.read_text())
    assert run("check", str(out), "-p", "gemini").returncode == 0
    page_token = fixed["tools"][0]["inputSchema"]["properties"]["page_token"]
    assert page_token["nullable"] is True and page_token["type"] == "string"
    report = json.loads(rep.read_text())
    assert report["profiles"] == ["gemini"]
    lossy = [c for t in report["tools"] for c in t["changes"] if c["lossy"]]
    assert lossy and all(c["effect"] == "loosens" for c in lossy)  # oneOf -> anyOf


def test_fix_with_unresolved_exits_1(tmp_path):
    r = run("fix", str(FIX / "synthetic/unfixable.json"), "-p", "gemini", "-o", str(tmp_path / "o.json"))
    assert r.returncode == 1
    assert "unresolved" in r.stderr


def test_profiles_and_explain():
    r = run("profiles")
    assert r.returncode == 0
    for pid in ("gemini", "openai-strict", "anthropic", "anthropic-strict", "mcp"):
        assert pid in r.stdout
    r = run("explain", "GEM001")
    assert r.returncode == 0
    assert "https://ai.google.dev/" in r.stdout and "verified on: 2026-10-21" in r.stdout
    assert "unverified" in run("explain", "ant002").stdout


def test_version():
    r = run("--version")
    assert r.returncode == 0 and r.stdout.startswith("mcpdialect 0.1.0")
