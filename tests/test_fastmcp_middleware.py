"""PortableSchemaMiddleware against a real in-memory FastMCP server."""

from __future__ import annotations

import pytest

fastmcp = pytest.importorskip("fastmcp")

import anyio  # noqa: E402  (installed with fastmcp)
from fastmcp import Client, FastMCP  # noqa: E402

from mcpdialect import check_tools  # noqa: E402
from mcpdialect.fastmcp import PortableSchemaMiddleware  # noqa: E402
from mcpdialect.testing import NotPortableError, assert_portable  # noqa: E402


def make_server(with_middleware: bool) -> tuple[FastMCP, PortableSchemaMiddleware | None]:
    mcp = FastMCP("t")

    @mcp.tool
    def search(query: str, page_token: str | None = None) -> str:
        return f"{query}|{page_token}"

    mw = None
    if with_middleware:
        mw = PortableSchemaMiddleware()
        mcp.add_middleware(mw)
    return mcp, mw


def list_and_call(mcp: FastMCP) -> tuple[list[dict], list[str]]:
    async def go():
        async with Client(mcp) as c:
            tools = await c.list_tools()
            r1 = await c.call_tool("search", {"query": "q"})
            r2 = await c.call_tool("search", {"query": "q", "page_token": None})
            r3 = await c.call_tool("search", {"query": "q", "page_token": "p2"})
        dumped = [t.model_dump(by_alias=True, exclude_none=True, mode="json") for t in tools]
        texts = [r.content[0].text for r in (r1, r2, r3)]
        return dumped, texts

    return anyio.run(go)


def test_baseline_is_not_gemini_portable():
    mcp, _ = make_server(False)
    tools, _texts = list_and_call(mcp)
    report = check_tools(tools, "gemini")
    assert report.verdict("search", "gemini") == "fixable"
    with pytest.raises(NotPortableError):
        assert_portable(mcp, profiles=["gemini"])


def test_middleware_rewrites_advertised_schema_only():
    mcp, mw = make_server(True)
    tools, texts = list_and_call(mcp)
    schema = tools[0]["inputSchema"]
    assert schema["properties"]["page_token"]["nullable"] is True
    assert schema["properties"]["page_token"]["type"] == "string"
    assert check_tools(tools, "gemini,anthropic,mcp").findings == []
    # Runtime validation still uses the Python signature.
    assert texts == ["q|None", "q|None", "q|p2"]
    assert mw is not None and mw.last_changes["search"]


def test_assert_portable_with_server_and_middleware():
    mcp, _ = make_server(True)
    report = assert_portable(mcp, profiles=["gemini", "anthropic", "mcp"])
    assert report.worst() == "ok"
