from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlparse

import pytest

from mcpdialect.engine import available_checks
from mcpdialect.profiles import (
    ProfileError,
    find_rule,
    list_profiles,
    load_profile,
    profile_from_dict,
    resolve_profiles,
)
from mcpdialect.transforms import FIX_ORDER, available_fixes

# Verified rules must cite the provider's own documentation.
OFFICIAL_DOC_HOSTS = {
    "ai.google.dev",
    "developers.openai.com",
    "platform.claude.com",
    "modelcontextprotocol.io",
}

ALL_RULES = [(pid, r) for pid in list_profiles() for r in load_profile(pid).rules]


def test_expected_profiles_ship():
    assert set(list_profiles()) >= {"mcp", "gemini", "openai-strict", "anthropic", "anthropic-strict"}


@pytest.mark.parametrize(("pid", "rule"), ALL_RULES, ids=[r.id for _, r in ALL_RULES])
def test_every_rule_has_source_and_date(pid, rule):
    assert rule.source.startswith("https://")
    dt.date.fromisoformat(rule.verified_on)
    assert rule.rationale.strip()
    assert rule.status in ("verified", "unverified")
    if rule.status == "verified":
        assert urlparse(rule.source).hostname in OFFICIAL_DOC_HOSTS, f"{rule.id} cites a non-official source"
    for ev in rule.evidence:
        assert ev.startswith("https://")


@pytest.mark.parametrize(("pid", "rule"), ALL_RULES, ids=[r.id for _, r in ALL_RULES])
def test_rule_check_and_fix_exist(pid, rule):
    assert rule.check in available_checks()
    if rule.fix:
        assert rule.fix in available_fixes()
        assert rule.fix in FIX_ORDER


def test_rule_ids_unique_and_prefixed():
    ids = [r.id for _, r in ALL_RULES]
    assert len(ids) == len(set(ids))
    for _, r in ALL_RULES:
        assert re.fullmatch(r"[A-Z]{3}\d{3}", r.id)


def test_resolve_profiles_variants():
    assert [p.id for p in resolve_profiles("gemini,anthropic")] == ["gemini", "anthropic"]
    assert len(resolve_profiles("all")) == len(list_profiles())
    assert [p.id for p in resolve_profiles(["gemini", "gemini"])] == ["gemini"]
    with pytest.raises(ProfileError):
        resolve_profiles("nope")
    with pytest.raises(ProfileError):
        resolve_profiles("")


def test_find_rule_case_insensitive():
    prof, rule = find_rule("gem001")
    assert prof.id == "gemini" and rule.id == "GEM001"
    with pytest.raises(ProfileError):
        find_rule("XXX999")


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "x", "rules": [{"id": "X001"}]},
        {
            "id": "x",
            "rules": [
                {
                    "id": "X001",
                    "title": "t",
                    "check": "type_list",
                    "severity": "fatal",
                    "status": "verified",
                    "source": "https://a",
                    "verified_on": "2026-01-01",
                    "rationale": "r",
                }
            ],
        },
        {
            "id": "x",
            "rules": [
                {
                    "id": "X001",
                    "title": "t",
                    "check": "type_list",
                    "severity": "breaks",
                    "status": "verified",
                    "source": "http://insecure",
                    "verified_on": "2026-01-01",
                    "rationale": "r",
                }
            ],
        },
        {"rules": []},
    ],
)
def test_malformed_profiles_rejected(bad):
    with pytest.raises(ProfileError):
        profile_from_dict(bad)
