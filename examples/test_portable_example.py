"""Copy into your server's test suite: one line guards every tool schema.

Run with: pytest examples/test_portable_example.py
"""

from pathlib import Path

from mcpdialect.testing import assert_portable


def test_snapshot_is_portable_after_fix():
    # A committed tools.json snapshot, fixed with `mcpdialect fix`:
    import json
    import subprocess
    import sys

    here = Path(__file__).parent
    fixed = subprocess.run(
        [sys.executable, "-m", "mcpdialect", "fix", str(here / "tools.json"), "-p", "gemini"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert_portable(json.loads(fixed), profiles=["gemini", "anthropic", "mcp"])


def test_fastmcp_server_is_portable():
    # With FastMCP installed, pass the server itself; tools/list goes through its middleware.
    import importlib.util

    if importlib.util.find_spec("fastmcp") is None:
        return
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from demo_server import mcp

    from mcpdialect.fastmcp import PortableSchemaMiddleware

    mcp.add_middleware(PortableSchemaMiddleware())
    assert_portable(mcp, profiles=["gemini", "anthropic", "mcp"])
