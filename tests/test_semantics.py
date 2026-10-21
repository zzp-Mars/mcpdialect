"""Property tests: rewrites terminate, are idempotent, and never reject an instance
the original schema accepted unless a change says it narrows or changes semantics."""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mcpdialect import portable

from conftest import openapi_nullable_to_jsonschema, schema_of

NAMES = ["a", "b", "c"]
STRINGS = ["", "x", "insert_text", "delete_text"]

scalars = st.one_of(
    st.none(), st.booleans(), st.integers(-3, 12), st.sampled_from(STRINGS), st.sampled_from([0.5, 2.0])
)
json_values = st.recursive(
    scalars,
    lambda inner: st.one_of(
        st.lists(inner, max_size=3),
        st.dictionaries(st.sampled_from(NAMES), inner, max_size=3),
    ),
    max_leaves=8,
)
instances = st.dictionaries(st.sampled_from(NAMES), json_values, max_size=3)

TYPES = ["string", "integer", "number", "boolean", "null", "object", "array"]


def leaf_schemas() -> st.SearchStrategy[dict[str, Any]]:
    return st.one_of(
        st.builds(lambda t: {"type": t}, st.sampled_from(TYPES)),
        st.builds(lambda t: {"type": [t, "null"]}, st.sampled_from(["string", "integer", "boolean"])),
        st.builds(
            lambda a, b: {"type": [a, b]}, st.sampled_from(["string", "integer"]), st.sampled_from(["boolean", "array"])
        ),
        st.builds(lambda v: {"const": v}, st.sampled_from(STRINGS)),
        st.builds(
            lambda vs: {"type": "string", "enum": vs},
            st.lists(st.sampled_from(STRINGS), min_size=1, max_size=3, unique=True),
        ),
        st.builds(lambda n: {"type": "string", "maxLength": n}, st.integers(0, 3)),
        st.builds(lambda n: {"type": "integer", "minimum": n, "exclusiveMaximum": n + 5}, st.integers(-2, 3)),
        st.just({"$ref": "#/$defs/D"}),
        st.just({"type": "string", "format": "uri"}),
    )


def schemas() -> st.SearchStrategy[dict[str, Any]]:
    def extend(inner: st.SearchStrategy[dict[str, Any]]) -> st.SearchStrategy[dict[str, Any]]:
        return st.one_of(
            st.builds(lambda s: {"anyOf": [s, {"type": "null"}], "default": None}, inner),
            st.builds(lambda a, b: {"oneOf": [a, b]}, inner, inner),
            st.builds(lambda a, b: {"anyOf": [a, b]}, inner, inner),
            st.builds(lambda s: {"type": "array", "items": s, "minItems": 0}, inner),
            st.builds(
                lambda props, req, ap: {
                    "type": "object",
                    "properties": props,
                    "required": [n for n in props if n in req],
                    **({"additionalProperties": ap} if ap is not None else {}),
                },
                st.dictionaries(st.sampled_from(NAMES), inner, max_size=3),
                st.sets(st.sampled_from(NAMES)),
                st.sampled_from([None, True, False]),
            ),
            st.builds(
                lambda a, b: {
                    "allOf": [
                        {"type": "object", "properties": {"a": a}},
                        {"properties": {"b": b}, "required": ["b"]},
                    ]
                },
                inner,
                inner,
            ),
        )

    return st.recursive(leaf_schemas(), extend, max_leaves=6)


@st.composite
def tool_schemas(draw: st.DrawFn) -> dict[str, Any]:
    props = draw(st.dictionaries(st.sampled_from(NAMES), schemas(), min_size=1, max_size=3))
    req = draw(st.sets(st.sampled_from(NAMES)))
    root: dict[str, Any] = {
        "type": "object",
        "properties": props,
        "required": [n for n in props if n in req],
        "$defs": {"D": draw(leaf_schemas().filter(lambda s: "$ref" not in s))},
    }
    if draw(st.booleans()):
        root["additionalProperties"] = False
    return root


def _valid(schema: dict[str, Any], instance: Any) -> bool:
    return jsonschema.Draft202012Validator(schema).is_valid(instance)


SETTINGS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
PROFILES = ["gemini", "openai-strict", "anthropic", "anthropic-strict", "mcp"]


@pytest.mark.parametrize("profile", PROFILES)
@SETTINGS
@given(schema=tool_schemas(), data=st.lists(instances, min_size=1, max_size=8))
def test_non_narrowing_rewrites_accept_original_valid_instances(profile, schema, data):
    jsonschema.Draft202012Validator.check_schema(schema)
    res = portable(schema, profile)
    narrows = any(c.effect in ("narrows", "changes") for c in res.changes)
    rewritten = openapi_nullable_to_jsonschema(res.schema)
    jsonschema.Draft202012Validator.check_schema(rewritten)
    for inst in data:
        if _valid(schema, inst) and not narrows:
            assert _valid(rewritten, inst), (inst, res.changes)
        if not res.lossy and _valid(rewritten, inst):
            # Lossless means equivalent: nothing new is accepted either.
            assert _valid(schema, inst), (inst, res.changes)


@pytest.mark.parametrize("profile", PROFILES)
@SETTINGS
@given(schema=tool_schemas())
def test_idempotent(profile, schema):
    once = portable(schema, profile)
    twice = portable(once.schema, profile)
    assert twice.changes == []
    assert twice.schema == once.schema


@SETTINGS
@given(schema=tool_schemas())
def test_gemini_output_has_no_gemini_findings_except_unfixable(schema):
    res = portable(schema, "gemini")
    # Anything left must be a rule without an automatic fix (or an uninferable type).
    assert {f.rule for f in res.remaining} <= {"GEM008", "GEM009", "GEM001"}


def test_known_instances_workspace_fixture():
    s = schema_of("real/workspace_gemini_1099.json", "search_gmail_messages")
    new = openapi_nullable_to_jsonschema(portable(s, "gemini").schema)
    for inst in ({"query": "x"}, {"query": "x", "page_token": None}, {"query": "x", "page_token": "t"}):
        assert _valid(s, inst) and _valid(new, inst)
    assert not _valid(new, {"query": "x", "page_token": 3})
