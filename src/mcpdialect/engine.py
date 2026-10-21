"""Rule engine: run a profile's checks over one tool's input schema."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from typing import Any

from ._walk import Node, is_local_ref, join_pointer, resolve_local_ref, walk
from .profiles import Profile, Rule

# Finding severities, lowest to highest.
SEVERITY_ORDER = {"warn": 0, "fixable": 1, "breaks": 2}


@dataclass(frozen=True)
class Finding:
    """One rule violation at one JSON Pointer inside a tool's inputSchema."""

    tool: str
    profile: str
    rule: str
    pointer: str
    severity: str  # "warn" | "fixable" | "breaks"
    message: str
    status: str  # "verified" | "unverified"
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Hit:
    """Raw check result before severity is decided."""

    pointer: str
    message: str


Check = Callable[[Any, Rule, str | None], Iterator[Hit]]
_CHECKS: dict[str, Check] = {}


def _check(name: str) -> Callable[[Check], Check]:
    def deco(fn: Check) -> Check:
        _CHECKS[name] = fn
        return fn

    return deco


def available_checks() -> list[str]:
    return sorted(_CHECKS)


def _is_object_schema(node: dict[str, Any]) -> bool:
    t = node.get("type")
    return t == "object" or (isinstance(t, list) and "object" in t) or "properties" in node


def _is_null_branch(sub: Any) -> bool:
    return isinstance(sub, dict) and sub.get("type") == "null" and not (set(sub) - {"type", "description", "title"})


# --- tool-level checks ------------------------------------------------------


@_check("schema_not_object")
def _schema_not_object(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    if not isinstance(schema, dict):
        yield Hit("", f"inputSchema is {type(schema).__name__}, not a JSON object")


@_check("tool_name_pattern")
def _tool_name_pattern(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    pattern = rule.params["pattern"]
    if not re.fullmatch(pattern, tool_name or ""):
        yield Hit("", f"tool name {tool_name!r} does not match {pattern}")


# --- schema-level checks ----------------------------------------------------


@_check("type_list")
def _type_list(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    for n in walk(schema):
        if isinstance(n.schema.get("type"), list):
            yield Hit(join_pointer(n.pointer, "type"), f"type is a list {n.schema['type']}")


@_check("null_union")
def _null_union(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    for n in walk(schema):
        for kw in ("anyOf", "oneOf"):
            branches = n.schema.get(kw)
            if isinstance(branches, list) and len(branches) > 1 and any(_is_null_branch(b) for b in branches):
                yield Hit(join_pointer(n.pointer, kw), f"{kw} with a null branch (Optional[T])")


@_check("keyword_present")
def _keyword_present(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    keywords = rule.params["keywords"]
    for n in walk(schema):
        for kw in keywords:
            if kw in n.schema:
                yield Hit(join_pointer(n.pointer, kw), f"unsupported keyword {kw!r}")


@_check("keyword_allowlist")
def _keyword_allowlist(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    allowed = set(rule.params["allowed"]) | set(rule.params.get("ignore", ()))
    for n in walk(schema):
        for kw in n.schema:
            if kw not in allowed:
                yield Hit(join_pointer(n.pointer, kw), f"keyword {kw!r} is not in this profile's subset")


@_check("root_type")
def _root_type(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    if isinstance(schema, dict) and schema.get("type") != "object":
        yield Hit("", f"root type is {schema.get('type')!r}, expected 'object'")


@_check("root_combinator")
def _root_combinator(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    if isinstance(schema, dict):
        for kw in rule.params["keywords"]:
            if kw in schema:
                yield Hit(join_pointer("", kw), f"{kw} at the root of inputSchema")


@_check("additional_properties_not_false")
def _ap_not_false(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    for n in walk(schema):
        if _is_object_schema(n.schema) and n.schema.get("additionalProperties") is not False:
            yield Hit(n.pointer, "object without additionalProperties: false")


@_check("not_all_required")
def _not_all_required(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    for n in walk(schema):
        props = n.schema.get("properties")
        if isinstance(props, dict):
            required = set(n.schema.get("required") or [])
            for name in props:
                if name not in required:
                    yield Hit(join_pointer(n.pointer, "properties", name), f"property {name!r} is optional")


_JSON_TYPE_NAMES = {str: "string", bool: "boolean", int: "number", float: "number", type(None): "null"}


def _json_type(value: Any) -> str:
    for py, name in _JSON_TYPE_NAMES.items():
        if type(value) is py:
            return name
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


@_check("enum_value_types")
def _enum_value_types(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    allowed = set(rule.params["allowed"])
    for n in walk(schema):
        values = n.schema.get("enum")
        if isinstance(values, list):
            bad = sorted({_json_type(v) for v in values} - allowed)
            if bad:
                yield Hit(join_pointer(n.pointer, "enum"), f"enum contains {', '.join(bad)} values")


@_check("format_allowlist")
def _format_allowlist(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    allowed = set(rule.params["allowed"])
    for n in walk(schema):
        fmt = n.schema.get("format")
        if isinstance(fmt, str) and fmt not in allowed:
            yield Hit(join_pointer(n.pointer, "format"), f"format {fmt!r} is not in the documented list")


@_check("max_object_depth")
def _max_object_depth(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    limit = int(rule.params["max"])
    for n in walk(schema):
        if n.object_depth > limit and "properties" in n.schema:
            yield Hit(n.pointer, f"object nesting depth {n.object_depth} exceeds {limit}")
            return


@_check("max_total_properties")
def _max_total_properties(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    limit = int(rule.params["max"])
    total = sum(len(n.schema["properties"]) for n in walk(schema) if isinstance(n.schema.get("properties"), dict))
    if total > limit:
        yield Hit("", f"{total} object properties in total exceed {limit}")


@_check("max_enum_values")
def _max_enum_values(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    limit = int(rule.params["max"])
    total = sum(len(n.schema["enum"]) for n in walk(schema) if isinstance(n.schema.get("enum"), list))
    if total > limit:
        yield Hit("", f"{total} enum values in total exceed {limit}")


_TYPE_HINT_KEYWORDS = ("type", "anyOf", "oneOf", "allOf", "$ref", "const", "enum", "not")


@_check("type_missing")
def _type_missing(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    for n in walk(schema):
        if n.parent_keyword in ("$defs", "definitions"):
            continue
        if not any(k in n.schema for k in _TYPE_HINT_KEYWORDS):
            yield Hit(n.pointer, "schema has no 'type'")
        elif (
            "type" not in n.schema
            and "enum" in n.schema
            and not any(k in n.schema for k in ("anyOf", "oneOf", "allOf", "$ref"))
        ):
            yield Hit(n.pointer, "enum without 'type'")


def _ref_targets(schema: dict[str, Any]) -> Iterator[tuple[Node, str]]:
    for n in walk(schema):
        ref = n.schema.get("$ref")
        if isinstance(ref, str):
            yield n, ref


@_check("remote_ref")
def _remote_ref(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    if isinstance(schema, dict):
        for n, ref in _ref_targets(schema):
            if not is_local_ref(ref):
                yield Hit(join_pointer(n.pointer, "$ref"), f"external $ref {ref!r}")


def find_cycles(schema: dict[str, Any]) -> set[str]:
    """Return the local $ref strings that participate in a reference cycle."""
    graph: dict[str, set[str]] = {}
    for _n, ref in _ref_targets(schema):
        graph.setdefault(ref, set())
    # edges: target ref -> refs used inside that target
    for ref in list(graph):
        if not is_local_ref(ref):
            continue
        try:
            target = resolve_local_ref(schema, ref)
        except KeyError:
            continue
        if isinstance(target, dict):
            inner = {r for _m, r in _ref_targets(target)} if ref != "#" else {r for _m, r in _ref_targets(schema)}
            graph[ref] = {r for r in inner if is_local_ref(r)}
    cyclic: set[str] = set()
    for start in graph:
        stack = list(graph.get(start, ()))
        seen: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur == start:
                cyclic.add(start)
                break
            if cur in seen:
                continue
            seen.add(cur)
            if cur not in graph and is_local_ref(cur):
                try:
                    tgt = resolve_local_ref(schema, cur)
                    graph[cur] = {r for _m, r in _ref_targets(tgt)} if isinstance(tgt, dict) else set()
                except KeyError:
                    graph[cur] = set()
            stack.extend(graph.get(cur, ()))
    return cyclic


@_check("recursive_ref")
def _recursive_ref(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    if isinstance(schema, dict):
        cyclic = find_cycles(schema)
        for n, ref in _ref_targets(schema):
            if ref in cyclic:
                yield Hit(join_pointer(n.pointer, "$ref"), f"recursive reference {ref!r}")


@_check("allof_with_ref")
def _allof_with_ref(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    for n in walk(schema):
        branches = n.schema.get("allOf")
        if isinstance(branches, list) and any(isinstance(b, dict) and "$ref" in b for b in branches):
            yield Hit(join_pointer(n.pointer, "allOf"), "allOf with a $ref branch")


@_check("min_items_gt")
def _min_items_gt(schema: Any, rule: Rule, tool_name: str | None) -> Iterator[Hit]:
    limit = int(rule.params["max"])
    for n in walk(schema):
        for kw in ("minItems", "maxItems", "uniqueItems", "contains", "minContains", "maxContains"):
            if kw not in n.schema:
                continue
            if kw == "minItems" and isinstance(n.schema[kw], int) and n.schema[kw] <= limit:
                continue
            yield Hit(join_pointer(n.pointer, kw), f"array constraint {kw}={n.schema[kw]!r}")


def run_rule(rule: Rule, schema: Any, tool_name: str | None) -> list[Hit]:
    try:
        fn = _CHECKS[rule.check]
    except KeyError as exc:
        raise ValueError(f"rule {rule.id} uses unknown check {rule.check!r}") from exc
    if rule.check == "tool_name_pattern" and tool_name is None:
        return []
    if rule.check not in ("schema_not_object", "tool_name_pattern") and not isinstance(schema, dict):
        return []
    return list(fn(schema, rule, tool_name))


def check_schema(
    schema: Any, profile: Profile, tool_name: str = "", *, include_unverified: bool = True
) -> list[Finding]:
    """Return findings for one schema. Severity is decided by trying the fixes."""
    from .transforms import portable  # local import: transforms imports engine

    raw: list[tuple[Rule, Hit]] = []
    for rule in profile.rules:
        if rule.status == "unverified" and not include_unverified:
            continue
        for hit in run_rule(rule, schema, tool_name):
            raw.append((rule, hit))
    if not raw:
        return []

    remaining_rules: dict[str, set[str]] = {}
    if isinstance(schema, dict):
        fixed = portable(schema, profile, tool_name=tool_name, include_unverified=include_unverified)
        for f in fixed.remaining:
            remaining_rules.setdefault(f.rule, set()).add(f.pointer)
    out: list[Finding] = []
    for rule, hit in raw:
        if rule.severity == "warn":
            sev = "warn"
        elif (
            rule.fix
            and isinstance(schema, dict)
            and (rule.id not in remaining_rules or hit.pointer not in remaining_rules[rule.id])
        ):
            sev = "fixable"
        else:
            sev = "breaks"
        out.append(
            Finding(
                tool=tool_name,
                profile=profile.id,
                rule=rule.id,
                pointer=hit.pointer,
                severity=sev,
                message=hit.message,
                status=rule.status,
                source=rule.source,
            )
        )
    return out


def raw_findings(
    schema: Any, profile: Profile, tool_name: str | None = None, *, include_unverified: bool = True
) -> list[Finding]:
    """Findings without the fixability pass (every non-warn finding is 'breaks')."""
    out = []
    for rule in profile.rules:
        if rule.status == "unverified" and not include_unverified:
            continue
        for hit in run_rule(rule, schema, tool_name):
            out.append(
                Finding(
                    tool_name or "",
                    profile.id,
                    rule.id,
                    hit.pointer,
                    "warn" if rule.severity == "warn" else "breaks",
                    hit.message,
                    rule.status,
                    rule.source,
                )
            )
    return out
