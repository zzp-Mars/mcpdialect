from __future__ import annotations

from mcpdialect import check, check_tools

from conftest import schema_of, tools_of


def rules(findings, profile=None, severity=None):
    return sorted(
        {
            f.rule
            for f in findings
            if (profile is None or f.profile == profile) and (severity is None or f.severity == severity)
        }
    )


def test_clean_schema_has_no_findings():
    report = check_tools(tools_of("synthetic/clean.json"), "mcp,openai-strict,anthropic,anthropic-strict")
    assert report.findings == []
    assert report.worst() == "ok"
    assert report.verdict("get_weather", "anthropic") == "ok"


def test_additional_properties_false_conflicts_between_gemini_and_openai_strict():
    # OpenAI strict requires additionalProperties: false; Gemini's Schema object has no such field.
    report = check_tools(tools_of("synthetic/clean.json"), "gemini")
    assert [(f.rule, f.pointer, f.severity) for f in report.findings] == [
        ("GEM007", "/additionalProperties", "fixable")
    ]


def test_workspace_1099_on_gemini():
    f = check(schema_of("real/workspace_gemini_1099.json", "search_gmail_messages"), "gemini")
    assert rules(f) == ["GEM002"]
    assert all(x.severity == "fixable" for x in f)
    assert f[0].pointer == "/properties/page_token/anyOf"
    assert f[0].status == "unverified"

    f = check(schema_of("real/workspace_gemini_1099.json", "batch_update_doc"), "gemini")
    assert rules(f) == ["GEM003", "GEM005"]
    assert {x.pointer for x in f if x.rule == "GEM003"} == {
        "/properties/operations/items/oneOf/0/properties/type/const",
        "/properties/operations/items/oneOf/1/properties/type/const",
    }


def test_workspace_1099_is_fine_on_anthropic():
    for tool in ("search_gmail_messages", "batch_update_doc"):
        assert check(schema_of("real/workspace_gemini_1099.json", tool), "anthropic") == []


def test_defs_refs_on_gemini_are_fixable_and_allowed_elsewhere():
    s = schema_of("real/defs_refs_13326.json", "run_query")
    f = check(s, "gemini")
    assert rules(f) == ["GEM004"]
    assert all(x.severity == "fixable" for x in f)
    assert rules(check(s, "anthropic")) == []


def test_missing_root_type():
    s = schema_of("real/missing_type_23382.json", "echo")
    assert rules(check(s, "gemini")) == ["GEM009"]
    assert rules(check(s, "openai-strict"), severity="fixable") == ["OAS001", "OAS003"]


def test_openai_strict_376():
    f = check(schema_of("real/openai_strict_376.json", "create_issue"), "openai-strict")
    assert rules(f) == ["OAS003", "OAS004"]
    assert {x.pointer for x in f if x.rule == "OAS004"} == {"/properties/labels"}


def test_top_level_anyof_anthropic_unverified_rule():
    s = schema_of("real/toplevel_anyof_39271.json", "notion_create_attachment")
    f = check(s, "anthropic")
    assert rules(f) == ["ANT002"]
    assert f[0].status == "unverified" and f[0].severity == "fixable"
    assert check(s, "anthropic", include_unverified=False) == []
    assert rules(check(s, "openai-strict"), severity="breaks") == ["OAS002"]


def test_unfixable_findings_are_breaks():
    report = check_tools(tools_of("synthetic/unfixable.json"), "gemini,anthropic,anthropic-strict,mcp")
    by_rule = {(f.tool, f.rule): f.severity for f in report.findings}
    assert by_rule[("bad name with spaces", "GEM010")] == "breaks"
    assert by_rule[("bad name with spaces", "ANT001")] == "breaks"
    assert by_rule[("bad name with spaces", "MCP002")] == "warn"
    assert by_rule[("bad name with spaces", "GEM008")] == "breaks"  # integer enum
    assert by_rule[("bad name with spaces", "GEM004")] == "breaks"  # remote $ref cannot be inlined
    assert by_rule[("bad name with spaces", "ANS006")] == "breaks"
    assert by_rule[("tree", "ANS005")] == "breaks"
    assert report.verdict("tree", "gemini") == "fixable"  # recursion is cut (lossy) for gemini
    assert report.worst() == "breaks"


def test_non_object_schema():
    report = check_tools([{"name": "x", "inputSchema": None}], "mcp")
    assert [(f.rule, f.severity) for f in report.findings] == [("MCP001", "breaks")]


def test_limits_openai():
    deep = {"type": "string"}
    for i in range(11):
        deep = {"type": "object", "properties": {f"p{i}": deep}, "required": [f"p{i}"], "additionalProperties": False}
    assert rules(check(deep, "openai-strict")) == ["OAS007"]
    many = {
        "type": "object",
        "properties": {"e": {"type": "string", "enum": [str(i) for i in range(1001)]}},
        "required": ["e"],
        "additionalProperties": False,
    }
    assert rules(check(many, "openai-strict")) == ["OAS009"]


def test_format_warnings():
    s = {
        "type": "object",
        "properties": {"u": {"type": "string", "format": "uri"}},
        "required": ["u"],
        "additionalProperties": False,
    }
    f = check(s, "openai-strict")
    assert [(x.rule, x.severity) for x in f] == [("OAS006", "warn")]
    assert check(s, "anthropic-strict") == []  # uri is on Anthropic's list


def test_property_named_like_keyword_is_not_a_keyword():
    s = {"type": "object", "properties": {"const": {"type": "string"}, "$ref": {"type": "string"}}}
    assert rules(check(s, "gemini")) == []


def test_report_to_dict_shape():
    report = check_tools(tools_of("real/workspace_gemini_1099.json"), "gemini")
    d = report.to_dict()
    assert d["profiles"] == ["gemini"]
    assert d["summary"]["fixable"] == len(d["findings"])
    assert d["tools"][0]["verdicts"]["gemini"] == "fixable"
