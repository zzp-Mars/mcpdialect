"""mcpdialect: make MCP tool schemas portable across model providers.

>>> from mcpdialect import portable
>>> new_schema, changes = portable({"type": "object", "properties": {
...     "q": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}, "gemini")
>>> new_schema["properties"]["q"]
{'type': 'string', 'nullable': True}
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .engine import SEVERITY_ORDER, Finding, check_schema
from .profiles import Profile, ProfileError, Rule, list_profiles, load_profile, resolve_profiles
from .transforms import Change, PortableResult, portable

__version__ = "0.1.0"

__all__ = [
    "Change",
    "Finding",
    "PortableResult",
    "Profile",
    "ProfileError",
    "Report",
    "Rule",
    "__version__",
    "check",
    "check_tools",
    "list_profiles",
    "load_profile",
    "portable",
]


@dataclass
class Report:
    """Findings for a tool catalog checked against one or more profiles."""

    findings: list[Finding] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)

    def verdict(self, tool: str, profile: str) -> str:
        """``ok``, ``warn``, ``fixable`` or ``breaks`` for one tool on one profile."""
        sev = [f.severity for f in self.findings if f.tool == tool and f.profile == profile]
        if not sev:
            return "ok"
        return max(sev, key=lambda s: SEVERITY_ORDER[s])

    def worst(self) -> str:
        if not self.findings:
            return "ok"
        return max((f.severity for f in self.findings), key=lambda s: SEVERITY_ORDER[s])

    def to_dict(self) -> dict[str, Any]:
        return {
            "profiles": self.profiles,
            "tools": [{"name": t, "verdicts": {p: self.verdict(t, p) for p in self.profiles}} for t in self.tools],
            "findings": [f.to_dict() for f in self.findings],
            "summary": {
                sev: sum(1 for f in self.findings if f.severity == sev) for sev in ("breaks", "fixable", "warn")
            },
        }


def check_tools(
    tools: Sequence[dict[str, Any]],
    profiles: str | Profile | Sequence[str | Profile] = "all",
    *,
    include_unverified: bool = True,
) -> Report:
    """Check a list of MCP tool dicts (``name`` + ``inputSchema``)."""
    profs = resolve_profiles(profiles)
    report = Report(tools=[str(t.get("name", "")) for t in tools], profiles=[p.id for p in profs])
    for tool in tools:
        name = str(tool.get("name", ""))
        schema = tool.get("inputSchema", tool.get("input_schema"))
        for prof in profs:
            report.findings.extend(check_schema(schema, prof, name, include_unverified=include_unverified))
    return report


def check(
    schema: dict[str, Any],
    profiles: str | Profile | Sequence[str | Profile] = "all",
    *,
    tool_name: str = "tool",
    include_unverified: bool = True,
) -> list[Finding]:
    """Check one input schema; returns its findings."""
    return check_tools(
        [{"name": tool_name, "inputSchema": schema}], profiles, include_unverified=include_unverified
    ).findings
