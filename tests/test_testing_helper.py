from __future__ import annotations

import pytest

from mcpdialect.testing import NotPortableError, assert_portable

from conftest import load_fixture


def test_assert_portable_passes_on_clean_tools():
    report = assert_portable(load_fixture("synthetic/clean.json"), profiles=["openai-strict", "anthropic"])
    assert report.worst() == "ok"


def test_assert_portable_fails_with_readable_message():
    with pytest.raises(NotPortableError) as exc:
        assert_portable(load_fixture("real/workspace_gemini_1099.json"), profiles=["gemini"])
    assert "GEM002" in str(exc.value)
    assert exc.value.report.worst() == "fixable"


def test_assert_portable_fail_on_breaks():
    assert_portable(load_fixture("real/workspace_gemini_1099.json"), profiles=["gemini"], fail_on="breaks")


def test_assert_portable_rejects_unknown_objects():
    with pytest.raises(TypeError):
        assert_portable(object(), profiles=["gemini"])
