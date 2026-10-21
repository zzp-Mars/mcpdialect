"""Render a :class:`mcpdialect.Report` as text, JSON, SARIF 2.1.0, or GitHub annotations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .profiles import find_rule

if TYPE_CHECKING:
    from . import Report

FORMATS = ("text", "json", "sarif", "github")
_VERDICT_LABEL = {"ok": "OK", "warn": "WARN", "fixable": "FIXABLE", "breaks": "BREAKS"}


def render(report: Report, fmt: str, *, source_name: str = "tools.json") -> str:
    if fmt == "text":
        return render_text(report)
    if fmt == "json":
        return json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n"
    if fmt == "sarif":
        return json.dumps(render_sarif(report, source_name), indent=2, ensure_ascii=False) + "\n"
    if fmt == "github":
        return render_github(report, source_name)
    raise ValueError(f"unknown format {fmt!r}")


def render_text(report: Report) -> str:
    lines: list[str] = []
    width = max((len(t) for t in report.tools), default=4)
    for tool in report.tools:
        for prof in report.profiles:
            verdict = report.verdict(tool, prof)
            lines.append(f"{tool:<{width}}  {prof:<16}  {_VERDICT_LABEL[verdict]}")
            for f in report.findings:
                if f.tool == tool and f.profile == prof:
                    tag = "" if f.status == "verified" else " [unverified]"
                    lines.append(f"    {f.severity:<7} {f.rule}{tag}  {f.pointer or '/'}  {f.message}")
    s = report.to_dict()["summary"]
    lines.append("")
    lines.append(
        f"{len(report.tools)} tool(s) x {len(report.profiles)} profile(s): "
        f"{s['breaks']} breaks, {s['fixable']} fixable, {s['warn']} warn"
    )
    if s["fixable"]:
        lines.append("Run `mcpdialect fix` (or the FastMCP middleware) to apply the fixable rewrites.")
    return "\n".join(lines) + "\n"


_SARIF_LEVEL = {"breaks": "error", "fixable": "error", "warn": "warning"}


def render_sarif(report: Report, source_name: str) -> dict[str, Any]:
    from . import __version__

    rule_ids = sorted({f.rule for f in report.findings})
    rules = []
    for rid in rule_ids:
        _prof, rule = find_rule(rid)
        rules.append(
            {
                "id": rule.id,
                "name": rule.id,
                "shortDescription": {"text": rule.title},
                "fullDescription": {"text": rule.rationale},
                "helpUri": rule.source,
                "properties": {"status": rule.status, "verified_on": rule.verified_on},
            }
        )
    results = []
    for f in report.findings:
        results.append(
            {
                "ruleId": f.rule,
                "level": _SARIF_LEVEL[f.severity],
                "message": {"text": f"{f.tool} [{f.profile}] {f.pointer or '/'}: {f.message} ({f.severity})"},
                "locations": [
                    {
                        "physicalLocation": {"artifactLocation": {"uri": source_name}},
                        "logicalLocations": [{"name": f.tool, "fullyQualifiedName": f"{f.tool}{f.pointer}"}],
                    }
                ],
                "properties": {"profile": f.profile, "severity": f.severity, "pointer": f.pointer},
            }
        )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "mcpdialect",
                        "version": __version__,
                        "informationUri": "https://github.com/zzp-Mars/mcpdialect",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def _gh_escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def render_github(report: Report, source_name: str) -> str:
    out = []
    for f in report.findings:
        level = "error" if f.severity in ("breaks", "fixable") else "warning"
        title = _gh_escape(f"{f.rule} {f.tool} [{f.profile}]")
        msg = _gh_escape(f"{f.pointer or '/'}: {f.message} ({f.severity}) - {f.source}")
        out.append(f"::{level} file={source_name},title={title}::{msg}")
    return "\n".join(out) + ("\n" if out else "")
