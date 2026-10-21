from __future__ import annotations

import copy
import json
import socket

import pytest

from mcpdialect import check, portable
from mcpdialect._walk import walk

from conftest import schema_of


def test_input_is_not_mutated():
    s = schema_of("real/workspace_gemini_1099.json", "batch_update_doc")
    before = copy.deepcopy(s)
    portable(s, "gemini")
    assert s == before


def test_null_union_to_nullable_gemini():
    s = schema_of("real/workspace_gemini_1099.json", "search_gmail_messages")
    new, changes = portable(s, "gemini")
    assert new["properties"]["page_token"] == {
        "type": "string",
        "nullable": True,
        "default": None,
        "description": "Token for retrieving the next page of results.",
    }
    assert [(c.rule, c.lossy) for c in changes] == [("GEM002", False)]
    assert new["required"] == ["query"]


def test_const_and_oneof_gemini():
    res = portable(schema_of("real/workspace_gemini_1099.json", "batch_update_doc"), "gemini")
    items = res.schema["properties"]["operations"]["items"]
    assert "oneOf" not in items and len(items["anyOf"]) == 2
    assert items["anyOf"][0]["properties"]["type"] == {"enum": ["insert_text"], "type": "string"}
    oneof = [c for c in res.changes if c.rule == "GEM005"]
    assert oneof and oneof[0].lossy and oneof[0].effect == "loosens"
    assert res.remaining == []
    assert check(res.schema, "gemini") == []


def test_type_list_variants():
    s = {
        "type": "object",
        "properties": {
            "a": {"type": ["string", "null"]},
            "b": {"type": ["string", "integer"], "minLength": 2},
            "c": {"type": ["null"]},
        },
    }
    new, changes = portable(s, "gemini")
    assert new["properties"]["a"] == {"type": "string", "nullable": True}
    assert new["properties"]["b"] == {"anyOf": [{"type": "string"}, {"type": "integer"}], "minLength": 2}
    assert new["properties"]["c"] == {"type": "null"}
    assert all(not c.lossy for c in changes)


def test_ref_inlining_and_defs_removed():
    s = schema_of("real/defs_refs_13326.json", "run_query")
    new, changes = portable(s, "gemini")
    assert "$defs" not in new
    assert new["properties"]["warehouse"]["properties"]["size"] == {"type": "string", "enum": ["XS", "S", "M", "L"]}
    assert "$ref" not in json.dumps(new)
    assert not any(c.lossy for c in changes)


def test_ref_sibling_keywords_win():
    s = {
        "type": "object",
        "$defs": {"S": {"type": "string", "description": "inner"}},
        "properties": {"x": {"$ref": "#/$defs/S", "description": "outer"}},
    }
    new, _ = portable(s, "gemini")
    assert new["properties"]["x"] == {"type": "string", "description": "outer"}


def test_recursive_ref_is_cut_and_terminates():
    s = schema_of("synthetic/unfixable.json", "tree")
    res = portable(s, "gemini")
    keys = {k for n in walk(res.schema) for k in n.schema}
    assert "$ref" not in keys and "$defs" not in keys
    assert "recursive reference #/$defs/Node not expanded" in json.dumps(res.schema)
    cut = [c for c in res.changes if c.action.startswith("cut recursive")]
    assert cut and all(c.lossy and c.effect == "loosens" for c in cut)


def test_self_reference_root():
    s = {"type": "object", "properties": {"child": {"$ref": "#"}}}
    res = portable(s, "gemini")
    assert "$ref" not in {k for n in walk(res.schema) for k in n.schema}


def test_remote_ref_never_fetched(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    s = {"type": "object", "properties": {"c": {"$ref": "https://example.com/s.json"}}}
    res = portable(s, "gemini")
    assert res.schema["properties"]["c"]["$ref"] == "https://example.com/s.json"
    assert [f.rule for f in res.remaining] == ["GEM004"]


def test_unknown_keywords_stripped_with_description():
    s = {
        "type": "object",
        "properties": {
            "n": {"type": "integer", "exclusiveMinimum": 0, "multipleOf": 5, "description": "count", "examples": [5]}
        },
    }
    new, changes = portable(s, "gemini")
    n = new["properties"]["n"]
    assert set(n) == {"type", "description"}
    assert n["description"] == "count (constraints: exclusiveMinimum=0, multipleOf=5)"
    lossy = {c.pointer.rsplit("/", 1)[-1]: c.lossy for c in changes}
    assert lossy == {"exclusiveMinimum": True, "multipleOf": True, "examples": False}


def test_describe_dropped_can_be_disabled():
    s = {"type": "object", "properties": {"n": {"type": "integer", "multipleOf": 5}}}
    new, _ = portable(s, "gemini", describe_dropped=False)
    assert new["properties"]["n"] == {"type": "integer"}


def test_allof_merge_and_conflict():
    s = {
        "type": "object",
        "properties": {
            "m": {
                "allOf": [
                    {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
                    {"properties": {"b": {"type": "integer"}}, "required": ["b"]},
                ]
            },
            "c": {"allOf": [{"type": "string"}, {"type": "integer"}]},
        },
    }
    res = portable(s, "gemini")
    m = res.schema["properties"]["m"]
    assert m == {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    }
    by_ptr = {c.pointer: c for c in res.changes if c.rule == "GEM006"}
    assert by_ptr["/properties/m/allOf"].lossy is False
    assert by_ptr["/properties/c/allOf"].lossy is True


def test_infer_type():
    s = {
        "type": "object",
        "properties": {"e": {"enum": ["a", "b"]}, "o": {"properties": {}}, "any": {"description": "anything"}},
    }
    res = portable(s, "gemini")
    assert res.schema["properties"]["e"]["type"] == "string"
    assert res.schema["properties"]["o"]["type"] == "object"
    assert [f.pointer for f in res.remaining] == ["/properties/any"]  # cannot infer: stays a finding


def test_openai_strict_rewrite():
    s = schema_of("real/openai_strict_376.json", "create_issue")
    res = portable(s, "openai-strict")
    assert res.remaining == []
    assert res.schema["additionalProperties"] is False
    assert res.schema["required"] == ["owner", "repo", "title", "labels"]
    assert res.schema["properties"]["labels"]["type"] == ["array", "null"]
    effects = {c.effect for c in res.changes}
    assert effects == {"narrows", "changes"}
    assert check(res.schema, "openai-strict") == []


def test_openai_strict_nullable_enum_and_complex():
    s = {
        "type": "object",
        "properties": {
            "u": {"type": "string", "enum": ["c", "f"]},
            "k": {"const": "x"},
            "a": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        },
    }
    new, _ = portable(s, "openai-strict")
    assert new["properties"]["u"] == {"type": ["string", "null"], "enum": ["c", "f", None]}
    assert new["properties"]["k"] == {"anyOf": [{"const": "x"}, {"type": "null"}]}
    assert new["properties"]["a"]["anyOf"][-1] == {"type": "null"}


def test_root_type_added():
    new, changes = portable({}, "openai-strict")
    assert new == {"type": "object", "additionalProperties": False}
    assert [c.rule for c in changes] == ["OAS001", "OAS003"]


def test_anthropic_strict_moves_constraints_to_description():
    s = {
        "type": "object",
        "properties": {
            "n": {"type": "integer", "minimum": 1, "maximum": 10},
            "s": {"type": "string", "maxLength": 5},
            "l": {"type": "array", "items": {"type": "string"}, "minItems": 2},
        },
        "required": ["n", "s", "l"],
        "additionalProperties": False,
    }
    res = portable(s, "anthropic-strict")
    p = res.schema["properties"]
    assert p["n"] == {"type": "integer", "description": "(constraints: maximum=10, minimum=1)"}
    assert p["s"] == {"type": "string", "description": "(constraints: maxLength=5)"}
    assert p["l"] == {"type": "array", "items": {"type": "string"}, "description": "(constraints: minItems=2)"}
    assert check(res.schema, "anthropic-strict") == []


def test_anthropic_top_level_anyof_dropped():
    s = schema_of("real/toplevel_anyof_39271.json", "notion_create_attachment")
    res = portable(s, "anthropic")
    assert "anyOf" not in res.schema
    assert res.lossy


@pytest.mark.parametrize("profile", ["gemini", "openai-strict", "anthropic", "anthropic-strict", "mcp"])
@pytest.mark.parametrize(
    "fixture,tool",
    [
        ("real/workspace_gemini_1099.json", "search_gmail_messages"),
        ("real/workspace_gemini_1099.json", "batch_update_doc"),
        ("real/defs_refs_13326.json", "run_query"),
        ("real/missing_type_23382.json", "echo"),
        ("real/openai_strict_376.json", "create_issue"),
        ("real/toplevel_anyof_39271.json", "notion_create_attachment"),
    ],
)
def test_idempotent_on_fixtures(profile, fixture, tool):
    once = portable(schema_of(fixture, tool), profile)
    twice = portable(once.schema, profile)
    assert twice.schema == once.schema
    assert twice.changes == []


def test_portable_result_unpacks():
    res = portable({"type": "object"}, "gemini")
    schema, changes = res
    assert schema == {"type": "object"} and changes == []
    with pytest.raises(TypeError):
        portable([], "gemini")  # type: ignore[arg-type]
