"""A small FastMCP server whose tool schemas trip several provider dialects.

python examples/demo_server.py            # serve over stdio, schemas as FastMCP emits them
python examples/demo_server.py --portable # same server with PortableSchemaMiddleware

mcpdialect check --cmd "python examples/demo_server.py" -p gemini,anthropic
"""

from __future__ import annotations

import sys
from typing import Literal

from fastmcp import FastMCP
from pydantic import BaseModel, Field

mcp = FastMCP("mcpdialect-demo")


class InsertText(BaseModel):
    kind: Literal["insert_text"] = "insert_text"
    text: str
    index: int = Field(ge=1)


class DeleteRange(BaseModel):
    kind: Literal["delete_range"] = "delete_range"
    start: int
    end: int


@mcp.tool
def search_messages(query: str, page_token: str | None = None, max_results: int = Field(10, le=100)) -> str:
    """Search messages; page_token continues a previous search."""
    return f"query={query!r} page_token={page_token!r} max_results={max_results}"


@mcp.tool
def edit_document(document_id: str, requests: list[InsertText | DeleteRange]) -> str:
    """Apply edit requests to a document."""
    return f"{document_id}: {len(requests)} request(s)"


if __name__ == "__main__":
    if "--portable" in sys.argv:
        from mcpdialect.fastmcp import PortableSchemaMiddleware

        mcp.add_middleware(PortableSchemaMiddleware())
    mcp.run(show_banner=False)
