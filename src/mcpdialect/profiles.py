"""Provider profiles: dated, cited rule sets stored as JSON data files."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

SEVERITIES = ("breaks", "warn")
STATUSES = ("verified", "unverified")


class ProfileError(ValueError):
    """Raised for unknown profiles or malformed profile data."""


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    check: str
    severity: str
    status: str
    source: str
    verified_on: str
    rationale: str
    params: dict[str, Any] = field(default_factory=dict)
    fix: str | None = None
    evidence: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any], profile_id: str) -> Rule:
        required = ("id", "title", "check", "severity", "status", "source", "verified_on", "rationale")
        missing = [k for k in required if not data.get(k)]
        if missing:
            raise ProfileError(f"{profile_id}: rule {data.get('id', '?')} is missing {missing}")
        if data["severity"] not in SEVERITIES:
            raise ProfileError(f"{profile_id}/{data['id']}: bad severity {data['severity']!r}")
        if data["status"] not in STATUSES:
            raise ProfileError(f"{profile_id}/{data['id']}: bad status {data['status']!r}")
        if not str(data["source"]).startswith("https://"):
            raise ProfileError(f"{profile_id}/{data['id']}: source must be an https URL")
        return cls(
            id=data["id"],
            title=data["title"],
            check=data["check"],
            severity=data["severity"],
            status=data["status"],
            source=data["source"],
            verified_on=data["verified_on"],
            rationale=data["rationale"],
            params=dict(data.get("params", {})),
            fix=data.get("fix"),
            evidence=tuple(data.get("evidence", ())),
        )


@dataclass(frozen=True)
class Profile:
    id: str
    title: str
    applies_to: str
    verified_on: str
    rules: tuple[Rule, ...]

    def rule(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.id == rule_id:
                return r
        raise KeyError(rule_id)


def _profile_files() -> dict[str, Any]:
    pkg = resources.files("mcpdialect") / "profiles"
    out: dict[str, Any] = {}
    for entry in pkg.iterdir():
        if entry.name.endswith(".json"):
            out[entry.name[: -len(".json")]] = entry
    return out


@cache
def load_profile(profile_id: str) -> Profile:
    files = _profile_files()
    if profile_id not in files:
        raise ProfileError(f"unknown profile {profile_id!r}; available: {', '.join(sorted(files))}")
    data = json.loads(files[profile_id].read_text(encoding="utf-8"))
    return profile_from_dict(data)


def profile_from_dict(data: dict[str, Any]) -> Profile:
    pid = data.get("id")
    if not pid:
        raise ProfileError("profile is missing 'id'")
    rules = tuple(Rule.from_dict(r, pid) for r in data.get("rules", []))
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise ProfileError(f"{pid}: duplicate rule ids")
    return Profile(
        id=pid,
        title=data.get("title", pid),
        applies_to=data.get("applies_to", ""),
        verified_on=data.get("verified_on", ""),
        rules=rules,
    )


def list_profiles() -> list[str]:
    return sorted(_profile_files())


def resolve_profiles(spec: str | Profile | Sequence[str | Profile]) -> list[Profile]:
    """Accept ``"gemini"``, ``"gemini,openai-strict"``, ``"all"``, a Profile, or a list."""
    if isinstance(spec, Profile):
        return [spec]
    items: list[str | Profile]
    if isinstance(spec, str):
        items = [s.strip() for s in spec.split(",") if s.strip()]
    else:
        items = list(spec)
    out: list[Profile] = []
    for item in items:
        if isinstance(item, Profile):
            out.append(item)
        elif item == "all":
            out.extend(load_profile(p) for p in list_profiles())
        else:
            out.append(load_profile(item))
    if not out:
        raise ProfileError("no profile given")
    seen: set[str] = set()
    unique = []
    for p in out:
        if p.id not in seen:
            seen.add(p.id)
            unique.append(p)
    return unique


def find_rule(rule_id: str) -> tuple[Profile, Rule]:
    for pid in list_profiles():
        prof = load_profile(pid)
        for r in prof.rules:
            if r.id.upper() == rule_id.upper():
                return prof, r
    raise ProfileError(f"unknown rule {rule_id!r}")
