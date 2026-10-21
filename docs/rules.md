# Rules

Generated from `src/mcpdialect/profiles/*.json` by `scripts/gen_rules_doc.py`. Do not edit by hand.

Every rule cites a source and the date it was last checked. **verified** rules cite the provider's own
documentation. **unverified** rules are backed only by reproducible API errors quoted in public issues;
skip them with `--no-unverified`.

## `anthropic`: Anthropic Messages API tools (input_schema)

Applies to: tools[].input_schema without strict mode

| Rule | Title | Severity | Fix | Status | Checked | Source |
|---|---|---|---|---|---|---|
| ANT001 | Tool name must match ^[a-zA-Z0-9_-]{1,128}$ | breaks | - | verified | 2026-10-21 | [link](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools) |
| ANT002 | No oneOf/allOf/anyOf at the top level of input_schema | breaks | strip_keywords | unverified | 2026-10-21 | [link](https://github.com/anthropics/claude-code/issues/4886) |

- **ANT001**: The tool name must match the regex ^[a-zA-Z0-9_-]{1,128}$.
- **ANT002**: The API returns 400 'input_schema does not support oneOf, allOf, or anyOf at the top level'. This is not stated in Anthropic's docs; the source is the API error text reproduced in public issues, so the rule is unverified. The rewrite drops the top-level combinator, which loosens validation.
  - evidence: https://github.com/anthropics/claude-code/issues/45106
  - evidence: https://github.com/langchain-ai/langchain/issues/39271

## `anthropic-strict`: Anthropic strict tool use (strict: true)

Applies to: tools[].input_schema with strict: true, and output_config.format JSON schemas

| Rule | Title | Severity | Fix | Status | Checked | Source |
|---|---|---|---|---|---|---|
| ANS001 | Objects must set additionalProperties: false | breaks | set_additional_properties_false | verified | 2026-10-21 | [link](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations) |
| ANS002 | Numerical constraints are not supported | breaks | strip_keywords | verified | 2026-10-21 | [link](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations) |
| ANS003 | String length constraints are not supported | breaks | strip_keywords | verified | 2026-10-21 | [link](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations) |
| ANS004 | Array constraints beyond minItems 0 or 1 | breaks | strip_min_items | verified | 2026-10-21 | [link](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations) |
| ANS005 | Recursive schemas are not supported | breaks | - | verified | 2026-10-21 | [link](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations) |
| ANS006 | External $ref is not supported | breaks | - | verified | 2026-10-21 | [link](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations) |
| ANS007 | allOf with $ref is not supported | breaks | inline_refs | verified | 2026-10-21 | [link](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations) |
| ANS008 | enum values must be scalars | breaks | - | verified | 2026-10-21 | [link](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations) |
| ANS009 | String format outside the supported list | warn | strip_format | verified | 2026-10-21 | [link](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations) |

- **ANS001**: additionalProperties must be set to false for objects.
- **ANS002**: Numerical constraints (such as minimum, maximum, multipleOf) are not supported. Anthropic's own SDK helpers move them into the description, which is what the rewrite does.
- **ANS003**: String constraints (minLength, maxLength) are not supported.
- **ANS004**: Array minItems supports only 0 and 1; other array constraints are not supported.
- **ANS005**: Recursive schemas are not supported.
- **ANS006**: External $ref (for example 'http://...') is not supported.
- **ANS007**: anyOf and allOf are supported, but allOf with $ref is not.
- **ANS008**: enum supports strings, numbers, bools, or nulls only - no complex types.
- **ANS009**: Supported formats: date-time, time, date, duration, email, hostname, uri, ipv4, ipv6, uuid.

## `gemini`: Gemini API function declarations (`parameters`, OpenAPI 3.0 subset)

Applies to: tools[].functionDeclarations[].parameters in generateContent requests; the shape most Gemini clients convert MCP inputSchema into

| Rule | Title | Severity | Fix | Status | Checked | Source |
|---|---|---|---|---|---|---|
| GEM001 | `type` must be a single value, not a list | breaks | type_list_to_nullable | verified | 2026-10-21 | [link](https://ai.google.dev/api/generate-content#FunctionDeclaration) |
| GEM002 | anyOf/oneOf with a null branch (Optional[T]) | breaks | null_union_to_nullable | unverified | 2026-10-21 | [link](https://ai.google.dev/api/generate-content#FunctionDeclaration) |
| GEM003 | `const` is not a Schema field | breaks | const_to_enum | verified | 2026-10-21 | [link](https://ai.google.dev/api/generate-content#FunctionDeclaration) |
| GEM004 | `$ref` / `$defs` / `definitions` are not Schema fields | breaks | inline_refs | verified | 2026-10-21 | [link](https://ai.google.dev/api/generate-content#FunctionDeclaration) |
| GEM005 | `oneOf` is not a Schema field | breaks | oneof_to_anyof | verified | 2026-10-21 | [link](https://ai.google.dev/api/generate-content#FunctionDeclaration) |
| GEM006 | `allOf` is not a Schema field | breaks | merge_allof | verified | 2026-10-21 | [link](https://ai.google.dev/api/generate-content#FunctionDeclaration) |
| GEM007 | Keyword is not part of the Gemini Schema subset | breaks | strip_keywords | verified | 2026-10-21 | [link](https://ai.google.dev/api/generate-content#FunctionDeclaration) |
| GEM008 | `enum` values must be strings | breaks | - | verified | 2026-10-21 | [link](https://ai.google.dev/api/generate-content#FunctionDeclaration) |
| GEM009 | Every schema needs a `type` | breaks | infer_type | verified | 2026-10-21 | [link](https://ai.google.dev/api/generate-content#FunctionDeclaration) |
| GEM010 | Function name characters and length | breaks | - | verified | 2026-10-21 | [link](https://ai.google.dev/api/generate-content#FunctionDeclaration) |

- **GEM001**: Schema.type is a single Type enum. A list such as ["string","null"] fails with 'Proto field is not repeating, cannot start list'. Nullability is the boolean `nullable` field.
  - evidence: https://github.com/taylorwilsdon/google_workspace_mcp/issues/1099
- **GEM002**: The documented way to express an optional value is `nullable: true`. The docs list `anyOf` and a NULL type, so the API itself may accept anyOf[T, null]; the reported 400s come from common client converters that turn it into a list-valued `type`. Marked unverified for that reason; the rewrite is lossless.
  - evidence: https://github.com/taylorwilsdon/google_workspace_mcp/issues/1099
- **GEM003**: The Schema object has no `const` field; use a one-value `enum`.
  - evidence: https://github.com/taylorwilsdon/google_workspace_mcp/issues/1099
- **GEM004**: The Schema object has no reference fields; local references must be inlined before sending.
  - evidence: https://github.com/google-gemini/gemini-cli/issues/13326
- **GEM005**: Only `anyOf` is available. Rewriting oneOf to anyOf loosens validation (an instance matching several branches becomes valid).
- **GEM006**: Only `anyOf` is available. allOf branches are merged into the parent when they do not conflict; otherwise allOf is dropped (loosens validation).
- **GEM007**: Gemini's Schema object accepts only: type, format, title, description, nullable, enum, maxItems, minItems, properties, required, minProperties, maxProperties, minLength, maxLength, pattern, example, anyOf, propertyOrdering, default, items, minimum, maximum. Unknown fields are rejected by the proto parser ('Unknown name ...').
- **GEM008**: Schema.enum is documented as string[]; numeric or boolean enums cannot be represented.
- **GEM009**: Schema.type is documented as Required. mcpdialect infers it from other keywords (properties -> object, items -> array, string enum -> string) when it can.
  - evidence: https://github.com/google-gemini/gemini-cli/issues/23382
- **GEM010**: FunctionDeclaration.name must be a-z, A-Z, 0-9, or contain underscores, colons, dots, and dashes, with a maximum length of 128.

## `mcp`: MCP specification (2025-11-25) tool definition

Applies to: tools/list Tool objects, independent of any model provider

| Rule | Title | Severity | Fix | Status | Checked | Source |
|---|---|---|---|---|---|---|
| MCP001 | inputSchema must be a JSON Schema object | breaks | - | verified | 2026-10-21 | [link](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) |
| MCP002 | Tool name should be 1-128 characters without spaces or commas | warn | - | verified | 2026-10-21 | [link](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) |

- **MCP001**: The spec says inputSchema MUST be a valid JSON Schema object (not null).
- **MCP002**: Tool names SHOULD be between 1 and 128 characters and SHOULD NOT contain spaces, commas, or other special characters.

## `openai-strict`: OpenAI Structured Outputs / function calling with strict: true

Applies to: function tools sent with strict: true (Chat Completions and Responses API)

| Rule | Title | Severity | Fix | Status | Checked | Source |
|---|---|---|---|---|---|---|
| OAS001 | Root schema must be type object | breaks | add_root_type_object | verified | 2026-10-21 | [link](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas) |
| OAS002 | Root schema must not use anyOf | breaks | - | verified | 2026-10-21 | [link](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas) |
| OAS003 | Objects must set additionalProperties: false | breaks | set_additional_properties_false | verified | 2026-10-21 | [link](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas) |
| OAS004 | All properties must be listed in required | breaks | require_all_nullable | verified | 2026-10-21 | [link](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas) |
| OAS005 | Unsupported composition keywords | breaks | strip_keywords | verified | 2026-10-21 | [link](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas) |
| OAS006 | String format outside the documented list | warn | strip_format | verified | 2026-10-21 | [link](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas) |
| OAS007 | At most 10 levels of object nesting | breaks | - | verified | 2026-10-21 | [link](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas) |
| OAS008 | At most 5000 object properties in total | breaks | - | verified | 2026-10-21 | [link](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas) |
| OAS009 | At most 1000 enum values in total | breaks | - | verified | 2026-10-21 | [link](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas) |

- **OAS001**: The root level of a schema must be an object.
- **OAS002**: The root level object of a schema must not use anyOf (for example a discriminated union).
- **OAS003**: additionalProperties: false must always be set in objects. Setting it narrows free-form objects (dict[str, Any]) to empty objects.
- **OAS004**: All fields must be required; optional fields are emulated with a union with null. The rewrite makes them required-and-nullable, so the server must treat null like an omitted argument.
- **OAS005**: Not yet supported: allOf, not, dependentRequired, dependentSchemas, if, then, else.
- **OAS006**: Documented formats: date-time, time, date, duration, email, hostname, ipv4, ipv6, uuid.
- **OAS007**: A schema may have up to 5000 object properties total, with up to 10 levels of nesting.
- **OAS008**: A schema may have up to 5000 object properties total.
- **OAS009**: A schema may have up to 1000 enum values across all enum properties.
