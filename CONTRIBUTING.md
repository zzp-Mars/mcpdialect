# Contributing

Thanks for helping. Issues and pull requests are welcome.

## Development setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,live,fastmcp]"
ruff check . && ruff format --check .
mypy
pytest -q
```

Python 3.10 to 3.13 are supported. The core package must stay free of runtime dependencies;
the MCP SDK and FastMCP are optional extras, and their tests skip when the extras are missing.

## Adding or changing a rule

Rules live in `src/mcpdialect/profiles/<profile>.json`. Each rule needs:

- `id` (three capital letters and three digits, unique across profiles), `title`, `rationale`
- `check`: one of the checks in `engine.py` (`mcpdialect.engine.available_checks()`)
- `severity`: `breaks` (the provider rejects it) or `warn`
- `fix` (optional): one of the rewrites in `transforms.py`
- `source`: an https URL. For `status: "verified"` it must be the provider's own documentation.
  A rule backed only by API error text in public issues must be `status: "unverified"`, with
  the issues under `evidence`.
- `verified_on`: the date you checked the source (YYYY-MM-DD)

Then regenerate the rules table and add a test with a minimal schema that triggers the rule:

```bash
python scripts/gen_rules_doc.py
pytest -q
```

## Rewrites

A rewrite must record a `Change` for everything it alters, and must set `lossy` and `effect`
honestly (`loosens`, `narrows`, or `changes`). The property tests in `tests/test_semantics.py`
check these claims; please extend the schema strategy when you add a rewrite.

## Fixtures from real reports

`tests/fixtures/real/` holds minimized schemas from public issues. Each file has a `_source`
field with the issue URL. Do not add private or proprietary schemas.
