# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-21

### Added
- Provider profiles as dated, cited JSON data: `mcp` (spec 2025-11-25), `gemini`
  (function declaration `parameters`, OpenAPI 3.0 subset), `openai-strict`, `anthropic`,
  `anthropic-strict`. Every rule has a source URL, a `verified_on` date and a
  `verified`/`unverified` status.
- Rule engine with JSON Pointer findings and severities `warn` / `fixable` / `breaks`.
- `portable(schema, profile)` rewrites with a change log (`lossy`, `effect`): local `$ref`
  inlining with a cycle guard (remote refs are never fetched), null unions and list types
  to `nullable`, `const` to `enum`, `allOf` merging, `oneOf` to `anyOf`, keyword stripping
  with constraints moved into `description`, `additionalProperties: false`, and
  required-and-nullable for OpenAI strict mode.
- CLI: `mcpdialect check | fix | profiles | explain`; input from tools.json files, stdin, a
  stdio server (`--cmd`) or Streamable HTTP (`--url`); output as text, JSON, SARIF 2.1.0, or
  GitHub annotations; exit codes 0/1/2.
- `mcpdialect.fastmcp.PortableSchemaMiddleware` for FastMCP servers.
- `mcpdialect.testing.assert_portable` pytest helper.
- Composite GitHub Action (`action.yml`) and a pre-commit hook definition.
