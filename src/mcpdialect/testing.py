"""pytest helper: ``assert_portable(tools_or_server, profiles=[...])``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from . import Report, check_tools
from .engine import SEVERITY_ORDER
from .loaders import normalize_tools
from .profiles import Profile
from .report import render_text


class NotPortableError(AssertionError):
    def __init__(self, report: Report) -> None:
        super().__init__("tool schemas are not portable:\n" + render_text(report))
        self.report = report


def _tools_from(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, (list, dict)):
        return normalize_tools(obj)
    # A FastMCP server: list tools through an in-memory client so middleware runs.
    try:
        from fastmcp import Client, FastMCP
    except ImportError as exc:  # pragma: no cover
        raise TypeError("pass a list of tool dicts, or install mcpdialect[fastmcp] to pass a server") from exc
    if not isinstance(obj, FastMCP):
        raise TypeError(f"cannot read tools from {type(obj).__name__}")
    import anyio

    async def run() -> list[dict[str, Any]]:
        async with Client(obj) as client:
            tools = await client.list_tools()
        return [t.model_dump(by_alias=True, exclude_none=True, mode="json") for t in tools]

    return normalize_tools(anyio.run(run))


def assert_portable(
    tools_or_server: Any,
    profiles: str | Sequence[str | Profile] = ("gemini", "anthropic", "mcp"),
    *,
    fail_on: str = "fixable",
    include_unverified: bool = True,
) -> Report:
    """Fail the test if any tool has findings at or above ``fail_on``.

    ``tools_or_server`` is a tools/list payload (any shape ``mcpdialect check``
    accepts) or a FastMCP server instance. Returns the report on success.
    """
    report = check_tools(_tools_from(tools_or_server), profiles, include_unverified=include_unverified)
    threshold = SEVERITY_ORDER[fail_on]
    if any(SEVERITY_ORDER[f.severity] >= threshold for f in report.findings):
        raise NotPortableError(report)
    return report
