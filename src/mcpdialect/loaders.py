"""Load MCP tool definitions from a file, a stdio server, or a Streamable HTTP URL."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any


class LoadError(ValueError):
    """The input could not be read as a list of MCP tools."""


def normalize_tools(data: Any) -> list[dict[str, Any]]:
    """Accept a JSON-RPC ``tools/list`` response, ``{"tools": [...]}``, a bare list, or one tool."""
    if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict):
        data = data["result"]
    if isinstance(data, dict) and "tools" in data:
        data = data["tools"]
    elif isinstance(data, dict) and "name" in data and ("inputSchema" in data or "input_schema" in data):
        data = [data]
    if not isinstance(data, list):
        raise LoadError("expected a tools/list response, {'tools': [...]}, or a list of tools")
    tools = []
    for i, tool in enumerate(data):
        if not isinstance(tool, dict) or "name" not in tool:
            raise LoadError(f"tool #{i} has no 'name'")
        tool = dict(tool)
        if "inputSchema" not in tool and "input_schema" in tool:
            tool["inputSchema"] = tool.pop("input_schema")
        if "inputSchema" not in tool:
            raise LoadError(f"tool {tool['name']!r} has no inputSchema")
        tools.append(tool)
    return tools


def load_tools_file(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoadError(f"cannot read {p}: {exc.strerror}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LoadError(f"{p} is not valid JSON: {exc}") from exc
    return normalize_tools(data)


def _require_mcp() -> None:
    try:
        import mcp  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise LoadError("live loading needs the MCP SDK: pip install 'mcpdialect[live]'") from exc


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        return tool
    data: dict[str, Any] = tool.model_dump(by_alias=True, exclude_none=True, mode="json")
    if "inputSchema" not in data and "input_schema" in data:
        data["inputSchema"] = data.pop("input_schema")
    return data


async def _list_all(session: Any) -> list[dict[str, Any]]:
    await session.initialize()
    tools: list[dict[str, Any]] = []
    cursor = None
    for _ in range(1000):  # pagination guard
        if cursor is None:
            result = await session.list_tools()
        else:
            from mcp import types

            result = await session.list_tools(params=types.PaginatedRequestParams(cursor=cursor))
        tools.extend(_tool_to_dict(t) for t in result.tools)
        cursor = getattr(result, "next_cursor", None) or getattr(result, "nextCursor", None)
        if not cursor:
            break
    return normalize_tools(tools)


def _root_message(exc: BaseException) -> str:
    """Unwrap anyio/asyncio exception groups to the first real error message."""
    while True:
        inner = getattr(exc, "exceptions", None)
        if not inner:
            break
        exc = inner[0]
    return str(exc) or type(exc).__name__


def _run_session(run: Any, timeout: float, source: str) -> list[dict[str, Any]]:
    import anyio

    try:
        result: list[dict[str, Any]] = anyio.run(run)
    except TimeoutError as exc:
        raise LoadError(f"server did not answer tools/list within {timeout:g}s") from exc
    except LoadError:
        raise
    except Exception as exc:
        raise LoadError(
            f"could not list tools from {source}: {_root_message(exc)} "
            "(the server may have exited early; run it by hand to see its error)"
        ) from exc
    return result


def load_tools_stdio(command: str, *, cwd: str | None = None, timeout: float = 30.0) -> list[dict[str, Any]]:
    """Start ``command`` as an MCP stdio server and return its tools/list."""
    _require_mcp()
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    argv = shlex.split(command)
    if not argv:
        raise LoadError("empty --cmd")
    params = StdioServerParameters(command=argv[0], args=argv[1:], cwd=cwd)

    async def run() -> list[dict[str, Any]]:
        with anyio.fail_after(timeout):
            async with stdio_client(params) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    return await _list_all(session)

    return _run_session(run, timeout, f"--cmd {command!r}")


def load_tools_http(url: str, *, timeout: float = 30.0) -> list[dict[str, Any]]:
    """Connect to a Streamable HTTP MCP endpoint and return its tools/list."""
    _require_mcp()
    import anyio
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def run() -> list[dict[str, Any]]:
        with anyio.fail_after(timeout):
            async with streamable_http_client(url) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    return await _list_all(session)

    return _run_session(run, timeout, f"--url {url}")
