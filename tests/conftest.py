from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def tools_of(name: str) -> list[dict[str, Any]]:
    from mcpdialect.loaders import normalize_tools

    return normalize_tools(load_fixture(name))


def schema_of(fixture: str, tool: str) -> dict[str, Any]:
    for t in tools_of(fixture):
        if t["name"] == tool:
            return t["inputSchema"]
    raise KeyError(tool)


def openapi_nullable_to_jsonschema(schema: Any) -> Any:
    """Interpret Gemini/OpenAPI 3.0 ``nullable: true`` as JSON Schema so jsonschema can validate it."""
    if isinstance(schema, list):
        return [openapi_nullable_to_jsonschema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k in ("enum", "const", "default", "examples", "example"):
            out[k] = v
        elif k in ("properties", "$defs", "definitions", "patternProperties"):
            out[k] = {n: openapi_nullable_to_jsonschema(s) for n, s in v.items()} if isinstance(v, dict) else v
        else:
            out[k] = openapi_nullable_to_jsonschema(v)
    if out.pop("nullable", False) is True:
        out = {"anyOf": [out, {"type": "null"}]}
    return out


@pytest.fixture
def fixture_tools():
    return tools_of
