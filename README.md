# mcpdialect

Make your MCP server's tool schemas work on every model provider.

`mcpdialect` **lints** an MCP server's `tools/list` against dated, cited provider profiles (Gemini, OpenAI strict mode, Anthropic, the MCP spec) and **rewrites** schemas into a form each provider accepts. Every rewrite is recorded, and any rewrite that changes which arguments validate is flagged.

It ships as a zero-dependency Python library and CLI, a FastMCP middleware, and a pytest helper.

> Status: alpha (v0.1.0). Not on PyPI yet; install from GitHub (see below).

## Why

FastMCP and Pydantic emit standard JSON Schema: `anyOf: [T, null]` for optional fields, `const` for literals, `$defs`/`$ref` for nested models. Providers accept different subsets of JSON Schema. Gemini's function-declaration `Schema` has no `const`, `$ref` or `oneOf`, and `type` must be a single value. OpenAI strict mode needs `additionalProperties: false` and every property in `required`. Anthropic rejects `anyOf` at the top level of `input_schema`. One unsupported keyword in one tool fails the **whole request** with a 400 error, before any tool is called.

Server and client maintainers keep hand-writing the same sanitizer ([google_workspace_mcp#1099](https://github.com/taylorwilsdon/google_workspace_mcp/issues/1099), [gemini-cli#13326](https://github.com/google-gemini/gemini-cli/issues/13326), [github-mcp-server#376](https://github.com/github/github-mcp-server/issues/376)). `mcpdialect` is that sanitizer as a tested library, plus a CI gate that uses the same rules.

## Install

```bash
pip install "mcpdialect @ git+https://github.com/zzp-Mars/mcpdialect"            # core: no dependencies
pip install "mcpdialect[live] @ git+https://github.com/zzp-Mars/mcpdialect"      # + check a running server (MCP SDK)
pip install "mcpdialect[fastmcp] @ git+https://github.com/zzp-Mars/mcpdialect"   # + FastMCP middleware
```

Python 3.10 to 3.13.

## Quickstart

### Check

```console
$ mcpdialect check examples/tools.json -p gemini,anthropic
search_gmail_messages  gemini            FIXABLE
    fixable GEM002 [unverified]  /properties/page_token/anyOf  anyOf with a null branch (Optional[T])
search_gmail_messages  anthropic         OK
batch_update_doc       gemini            FIXABLE
    fixable GEM003  /properties/operations/items/oneOf/0/properties/type/const  unsupported keyword 'const'
    fixable GEM003  /properties/operations/items/oneOf/1/properties/type/const  unsupported keyword 'const'
    fixable GEM005  /properties/operations/items/oneOf  unsupported keyword 'oneOf'
batch_update_doc       anthropic         OK

2 tool(s) x 2 profile(s): 0 breaks, 4 fixable, 0 warn
Run `mcpdialect fix` (or the FastMCP middleware) to apply the fixable rewrites.
```

Check a running server instead of a file:

```bash
mcpdialect check --cmd "python my_server.py" -p gemini,openai-strict   # stdio, needs [live]
mcpdialect check --url http://localhost:8000/mcp -p all                  # Streamable HTTP, needs [live]
```

`check` accepts a JSON-RPC `tools/list` response, `{"tools": [...]}`, a bare list of tools, several files, or `-` for stdin.

Output formats: `-f text` (default), `json`, `sarif` (SARIF 2.1.0 for code scanning), `github` (workflow annotations).

**Exit codes:** `0` nothing at or above `--fail-on`; `1` findings at or above it; `2` usage or input error. `--fail-on` is `fixable` by default (anything a provider would reject as-is). Use `breaks` to fail only on problems that no rewrite can fix, or `never`.

### Fix

```console
$ mcpdialect fix examples/tools.json -p gemini -o tools.gemini.json --report changes.json
mcpdialect: 6 change(s), 1 lossy, 0 unresolved finding(s)
```

```json
"page_token": {"default": null, "description": "Token for retrieving the next page of results.",
               "type": "string", "nullable": true}
```

`changes.json` lists every rewrite with its JSON Pointer, rule, and whether it is lossy:

```json
{"pointer": "/properties/operations/items/oneOf", "rule": "GEM005", "action": "oneOf -> anyOf",
 "lossy": true, "effect": "loosens"}
```

### Serve portable schemas from FastMCP

```python
from fastmcp import FastMCP
from mcpdialect.fastmcp import PortableSchemaMiddleware

mcp = FastMCP("my-server")
mcp.add_middleware(PortableSchemaMiddleware())  # default profiles: gemini + anthropic + mcp
```

The middleware rewrites only the schema advertised on `tools/list`. FastMCP still validates `tools/call` arguments against your Python signature, so an omitted optional argument and an explicit `null` both keep working (this is tested against FastMCP 4.1.3).

### Guard it in your tests

```python
from mcpdialect.testing import assert_portable


def test_tools_are_portable():
    assert_portable(mcp, profiles=["gemini", "anthropic", "mcp"])  # a FastMCP server, or a tools/list payload
```

### Library

```python
from mcpdialect import check, portable

new_schema, changes = portable(schema, "gemini")
result = portable(schema, "openai-strict")
result.remaining  # findings no rewrite could fix
result.lossy  # True if any change alters which instances validate

findings = check(schema, ["openai-strict", "anthropic"])
```

## Profiles

```console
$ mcpdialect profiles
anthropic          2 rules, 1 unverified   verified 2026-10-21  Anthropic Messages API tools (input_schema)
anthropic-strict   9 rules                 verified 2026-10-21  Anthropic strict tool use (strict: true)
gemini            10 rules, 1 unverified   verified 2026-10-21  Gemini API function declarations (`parameters`, OpenAPI 3.0 subset)
mcp                2 rules                 verified 2026-10-21  MCP specification (2025-11-25) tool definition
openai-strict      9 rules                 verified 2026-10-21  OpenAI Structured Outputs / function calling with strict: true
```

Profiles are JSON data files in `src/mcpdialect/profiles/`. **No rule ships without a citation:** every rule has a `source` URL and a `verified_on` date, and a test enforces it. A rule is `verified` only when the provider's own documentation states it. Rules backed only by reproducible API errors in public issues are marked `unverified`; `--no-unverified` skips them. Full table: [docs/rules.md](docs/rules.md). Explain one rule:

```console
$ mcpdialect explain GEM001
GEM001  `type` must be a single value, not a list
profile:     gemini (tools[].functionDeclarations[].parameters in generateContent requests; ...)
severity:    breaks    status: verified    verified on: 2026-10-21
fix:         type_list_to_nullable
source:      https://ai.google.dev/api/generate-content#FunctionDeclaration
```

Some profiles conflict. OpenAI strict mode requires `additionalProperties: false`, and Gemini's `Schema` object has no such field. Rewrite per provider (`mcpdialect fix -p gemini`, `-p openai-strict`) rather than for both at once. `openai-strict` is not in the middleware's default set because it turns optional arguments into required-and-nullable ones. That only suits clients that send `strict: true`.

## What the rewrites do

| Rewrite | Lossy? |
|---|---|
| Inline local `$ref` / `$defs` (cycle guard; remote `$ref` is never fetched) | no. Cutting a recursive reference is lossy (loosens) |
| `anyOf`/`oneOf [T, null]` and `type: [T, "null"]` -> `T` + `nullable: true` (Gemini) | no |
| `type: [A, B]` -> `anyOf: [{type: A}, {type: B}]` | no |
| `const` -> one-value `enum` | no |
| Merge non-conflicting `allOf` branches into the parent | no. Dropping a conflicting `allOf` loosens |
| `oneOf` -> `anyOf` | yes, loosens |
| Strip unsupported keywords, moving constraints into `description` (e.g. `(constraints: maxLength=100)`) | annotations no; constraints loosen |
| Add `additionalProperties: false` (strict modes) | yes, narrows |
| Optional -> required + nullable (OpenAI strict) | yes, changes semantics |

Property-based tests (Hypothesis + `jsonschema`) check that rewrites marked lossless accept exactly the same instances, that rewrites marked `loosens` still accept every originally valid instance, and that `portable()` is idempotent.

## Limitations

- Static only: no provider API is called. The rules come from documentation and public error reports, not from live requests.
- No `gemini-jsonschema` (`parametersJsonSchema`) profile yet. Google documents a JSON Schema subset for `responseJsonSchema` but not for function parameters.
- Anthropic's per-request strict limits (20 strict tools, 24 optional parameters, 16 union parameters) are not checked yet.
- The middleware rewrites `inputSchema` only, not `outputSchema`.

## 中文简介

`mcpdialect` 检查并改写 MCP 服务器的工具 `inputSchema`，使其能被 Gemini、OpenAI strict 模式和 Anthropic 接受，并逐条记录每处改动（是否有损、放宽还是收紧）。每条规则都附有官方文档链接和核对日期；只有公开报错、没有文档依据的规则标为 `unverified`。用法：`mcpdialect check tools.json -p gemini`，`mcpdialect fix ...`，或在 FastMCP 中加入 `PortableSchemaMiddleware()`。

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Rule changes need a source URL. License: [MIT](LICENSE).
