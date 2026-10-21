"""FastMCP middleware that advertises portable tool schemas on ``tools/list``.

Only the *advertised* ``inputSchema`` changes. FastMCP still validates
``tools/call`` arguments against the tool's original Python signature, so an
omitted optional argument and an explicit ``null`` keep working.

    from fastmcp import FastMCP
    from mcpdialect.fastmcp import PortableSchemaMiddleware

    mcp = FastMCP("demo")
    mcp.add_middleware(PortableSchemaMiddleware())  # profiles: gemini + anthropic + mcp
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from .profiles import Profile, resolve_profiles
from .transforms import Change, portable

try:
    from fastmcp.server.middleware import Middleware
except ImportError as exc:  # pragma: no cover - depends on environment
    raise ImportError("mcpdialect.fastmcp needs FastMCP: pip install 'mcpdialect[fastmcp]'") from exc

logger = logging.getLogger("mcpdialect")

#: Profiles that can be satisfied at the same time without conflicting rewrites.
DEFAULT_PROFILES = ("gemini", "anthropic", "mcp")


class PortableSchemaMiddleware(Middleware):
    """Rewrite each tool's advertised parameters schema for the given profiles.

    ``profiles`` defaults to gemini + anthropic + mcp. ``openai-strict`` is not
    in the default set: it makes optional arguments required-and-nullable,
    which only suits clients that send ``strict: true``.
    """

    def __init__(
        self,
        profiles: str | Sequence[str | Profile] = DEFAULT_PROFILES,
        *,
        describe_dropped: bool = True,
        log_changes: bool = True,
    ) -> None:
        self.profiles = resolve_profiles(profiles)
        self.describe_dropped = describe_dropped
        self.log_changes = log_changes
        self.last_changes: dict[str, list[Change]] = {}
        self._cache: dict[str, tuple[dict[str, Any], list[Change]]] = {}

    def _rewrite(self, name: str, schema: dict[str, Any]) -> tuple[dict[str, Any], list[Change]]:
        import json

        key = name + "\0" + json.dumps(schema, sort_keys=True, default=str)
        if key not in self._cache:
            res = portable(schema, self.profiles, tool_name=name, describe_dropped=self.describe_dropped)
            self._cache[key] = (res.schema, res.changes)
            if self.log_changes and res.changes:
                lossy = sum(1 for c in res.changes if c.lossy)
                logger.info("mcpdialect: %s: %d schema change(s), %d lossy", name, len(res.changes), lossy)
        return self._cache[key]

    async def on_list_tools(self, context: Any, call_next: Any) -> Any:
        tools = await call_next(context)
        out = []
        for tool in tools:
            params = getattr(tool, "parameters", None)
            if not isinstance(params, dict):
                out.append(tool)
                continue
            new_schema, changes = self._rewrite(tool.name, params)
            self.last_changes[tool.name] = changes
            out.append(tool.model_copy(update={"parameters": new_schema}) if changes else tool)
        return out
