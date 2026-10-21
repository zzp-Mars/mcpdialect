"""Conservative schema rewrites that make a tool schema fit a provider profile.

Every rewrite is recorded as a :class:`Change`. ``lossy`` is True when the
rewritten schema accepts or rejects different instances than the original;
``effect`` says which way (``loosens``: accepts more; ``narrows``: accepts
less; ``changes``: both, e.g. optional -> required-but-nullable).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ._walk import is_local_ref, iter_children, join_pointer, resolve_local_ref
from .profiles import Profile, Rule, resolve_profiles

# Keywords whose removal does not change which instances validate.
ANNOTATION_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$comment",
        "$anchor",
        "$dynamicAnchor",
        "title",
        "description",
        "examples",
        "example",
        "deprecated",
        "readOnly",
        "writeOnly",
        "default",
        "format",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "propertyOrdering",
        "nullable",
    }
)

#: Order in which fixes run. Earlier fixes simplify the input of later ones.
FIX_ORDER = (
    "inline_refs",
    "merge_allof",
    "const_to_enum",
    "type_list_to_nullable",
    "null_union_to_nullable",
    "oneof_to_anyof",
    "strip_keywords",
    "strip_format",
    "strip_min_items",
    "infer_type",
    "add_root_type_object",
    "set_additional_properties_false",
    "require_all_nullable",
)


@dataclass(frozen=True)
class Change:
    pointer: str
    rule: str
    action: str
    lossy: bool
    effect: str = "none"  # none | loosens | narrows | changes

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortableResult:
    """Result of :func:`portable`. Unpacks as ``schema, changes``."""

    schema: dict[str, Any]
    changes: list[Change] = field(default_factory=list)
    remaining: list[Any] = field(default_factory=list)  # engine.Finding

    def __iter__(self) -> Iterator[Any]:
        yield self.schema
        yield self.changes

    @property
    def lossy(self) -> bool:
        return any(c.lossy for c in self.changes)


class _Ctx:
    def __init__(self, rule: Rule, root: dict[str, Any], describe_dropped: bool) -> None:
        self.rule = rule
        self.root = root
        self.describe_dropped = describe_dropped
        self.changes: list[Change] = []

    def record(self, pointer: str, action: str, lossy: bool, effect: str = "none") -> None:
        if lossy and effect == "none":
            effect = "loosens"
        self.changes.append(Change(pointer, self.rule.id, action, lossy, effect))


NodeFn = Callable[[dict[str, Any], str, _Ctx], Any]


def _rewrite(node: Any, ptr: str, fn: NodeFn, ctx: _Ctx) -> Any:
    """Post-order rewrite of every schema position."""
    if not isinstance(node, dict):
        return node
    out = dict(node)
    for keyword, child_ptr, child in list(iter_children(node, ptr)):
        _set_child(out, keyword, child_ptr, ptr, _rewrite(child, child_ptr, fn, ctx))
    return fn(out, ptr, ctx)


# Structural keywords that make poor prose in a description.
_NOT_DESCRIBED = frozenset(
    {
        "additionalProperties",
        "unevaluatedProperties",
        "patternProperties",
        "propertyNames",
        "dependentSchemas",
        "if",
        "then",
        "else",
        "not",
    }
)
_MAX_DESCRIBED_VALUE = 80


def _describe(node: dict[str, Any], dropped: dict[str, Any]) -> None:
    if not dropped:
        return
    rendered = []
    for k, v in sorted(dropped.items()):
        text = json.dumps(v, sort_keys=True, ensure_ascii=False)
        rendered.append(f"{k}={text}" if len(text) <= _MAX_DESCRIBED_VALUE else k)
    parts = ", ".join(rendered)
    note = f"(constraints: {parts})"
    desc = node.get("description")
    if isinstance(desc, str) and note in desc:
        return
    node["description"] = f"{desc} {note}" if isinstance(desc, str) and desc else note


def _keyword_lossy(kw: str, value: Any) -> bool:
    if kw in ANNOTATION_KEYWORDS:
        return False
    if kw in ("additionalProperties", "unevaluatedProperties", "additionalItems", "unevaluatedItems"):
        return not (value is True or value == {})
    if kw in ("$defs", "definitions"):
        return False  # only reachable through $ref, which is handled separately
    return True


# --- fixes ------------------------------------------------------------------


def _fix_inline_refs(schema: dict[str, Any], ctx: _Ctx) -> dict[str, Any]:
    root = schema

    def expand(node: Any, ptr: str, stack: tuple[str, ...]) -> Any:
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and is_local_ref(ref):
            if ref in stack:
                # Cycle guard: stop expanding; keep only the target's type (loosens).
                target = _safe_resolve(root, ref)
                stub: dict[str, Any] = {}
                if isinstance(target, dict) and isinstance(target.get("type"), str):
                    stub["type"] = target["type"]
                desc = node.get("description") or (target.get("description") if isinstance(target, dict) else None)
                stub["description"] = (f"{desc} " if desc else "") + f"(recursive reference {ref} not expanded)"
                ctx.record(ptr, f"cut recursive $ref {ref}", lossy=True, effect="loosens")
                return stub
            target = _safe_resolve(root, ref)
            if isinstance(target, dict):
                merged = {k: v for k, v in node.items() if k != "$ref"}
                body = expand(copy.deepcopy(target), ptr, (*stack, ref))
                if isinstance(body, dict):
                    for k, v in body.items():
                        if k in ("$defs", "definitions", "$id", "$schema"):
                            continue
                        merged.setdefault(k, v)
                ctx.record(ptr, f"inline $ref {ref}", lossy=False)
                node = merged
            # unresolvable or remote refs are left in place
        out = dict(node)
        for keyword, child_ptr, child in list(iter_children(node, ptr)):
            if keyword in ("$defs", "definitions"):
                continue
            new_child = expand(child, child_ptr, stack)
            _set_child(out, keyword, child_ptr, ptr, new_child)
        return out

    result = expand(schema, "", ())
    if isinstance(result, dict):
        outside_defs = {k: v for k, v in result.items() if k not in ("$defs", "definitions")}
        if not _has_local_ref(outside_defs):
            for kw in ("$defs", "definitions"):
                if kw in result:
                    del result[kw]
                    ctx.record(join_pointer("", kw), f"remove {kw} (all references inlined)", lossy=False)
        return result
    return schema


def _safe_resolve(root: dict[str, Any], ref: str) -> Any:
    try:
        return resolve_local_ref(root, ref)
    except KeyError:
        return None


def _has_local_ref(node: Any) -> bool:
    if isinstance(node, dict):
        if is_local_ref(node.get("$ref")):
            return True
        return any(_has_local_ref(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_local_ref(v) for v in node)
    return False


def _set_child(out: dict[str, Any], keyword: str, child_ptr: str, ptr: str, new_child: Any) -> None:
    container = out[keyword]
    if child_ptr == join_pointer(ptr, keyword):
        out[keyword] = new_child
        return
    last = child_ptr.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
    if isinstance(container, list):
        container = list(container)
        container[int(last)] = new_child
    else:
        container = dict(container)
        container[last] = new_child
    out[keyword] = container


def _node_merge_allof(node: dict[str, Any], ptr: str, ctx: _Ctx) -> Any:
    branches = node.get("allOf")
    if not isinstance(branches, list):
        return node
    merged = {k: v for k, v in node.items() if k != "allOf"}
    ok = True
    for b in branches:
        if not isinstance(b, dict) or "$ref" in b:
            ok = False
            break
        for k, v in b.items():
            if k not in merged:
                merged[k] = copy.deepcopy(v)
            elif k == "properties" and isinstance(v, dict) and isinstance(merged[k], dict):
                if set(v) & set(merged[k]) and any(merged[k][n] != v[n] for n in set(v) & set(merged[k])):
                    ok = False
                    break
                merged[k] = {**merged[k], **v}
            elif k == "required" and isinstance(v, list) and isinstance(merged[k], list):
                merged[k] = list(dict.fromkeys([*merged[k], *v]))
            elif k in ("description", "title"):
                continue  # parent annotation wins
            elif merged[k] != v:
                ok = False
                break
        if not ok:
            break
    if ok:
        ctx.record(join_pointer(ptr, "allOf"), "merge allOf into parent", lossy=False)
        return merged
    out = {k: v for k, v in node.items() if k != "allOf"}
    if ctx.describe_dropped:
        _describe(out, {"allOf": branches})
    ctx.record(join_pointer(ptr, "allOf"), "drop conflicting allOf", lossy=True, effect="loosens")
    return out


def _node_const_to_enum(node: dict[str, Any], ptr: str, ctx: _Ctx) -> Any:
    if "const" not in node:
        return node
    value = node["const"]
    if "enum" in node and value not in node["enum"]:
        return node
    out = {k: v for k, v in node.items() if k != "const"}
    out["enum"] = [value]
    ctx.record(join_pointer(ptr, "const"), "const -> one-value enum", lossy=False)
    return out


def _node_type_list_to_nullable(node: dict[str, Any], ptr: str, ctx: _Ctx) -> Any:
    types = node.get("type")
    if not isinstance(types, list):
        return node
    non_null = [t for t in dict.fromkeys(types) if t != "null"]
    out = dict(node)
    if "null" in types:
        out["nullable"] = True
    if len(non_null) == 1:
        out["type"] = non_null[0]
        ctx.record(join_pointer(ptr, "type"), f"type {types} -> {non_null[0]!r} + nullable", lossy=False)
    elif not non_null:
        out["type"] = "null"
        out.pop("nullable", None)
        ctx.record(join_pointer(ptr, "type"), "type ['null'] -> 'null'", lossy=False)
    else:
        if "anyOf" in node:
            return node  # would need allOf; leave for the check to report
        del out["type"]
        out["anyOf"] = [{"type": t} for t in non_null]
        ctx.record(join_pointer(ptr, "type"), f"type {types} -> anyOf of single types", lossy=False)
    return out


def _node_null_union_to_nullable(node: dict[str, Any], ptr: str, ctx: _Ctx) -> Any:
    from .engine import _is_null_branch

    for kw in ("anyOf", "oneOf"):
        branches = node.get(kw)
        if not (isinstance(branches, list) and len(branches) > 1 and any(_is_null_branch(b) for b in branches)):
            continue
        rest = [b for b in branches if not _is_null_branch(b)]
        out = {k: v for k, v in node.items() if k != kw}
        if not rest:
            if "type" in out:
                return node  # e.g. type + anyOf[null, null]; leave for the check to report
            out["type"] = "null"
            ctx.record(join_pointer(ptr, kw), f"{kw} of only null branches -> type 'null'", lossy=False)
            return out
        if len(rest) == 1 and isinstance(rest[0], dict) and not (set(rest[0]) & (set(out) - ANNOTATION_KEYWORDS)):
            for k, v in rest[0].items():
                out.setdefault(k, v)
        else:
            out[kw] = rest
        out["nullable"] = True
        ctx.record(join_pointer(ptr, kw), f"{kw}[T, null] -> T + nullable", lossy=False)
        return out
    return node


def _node_oneof_to_anyof(node: dict[str, Any], ptr: str, ctx: _Ctx) -> Any:
    if "oneOf" not in node or "anyOf" in node:
        return node
    out = {("anyOf" if k == "oneOf" else k): v for k, v in node.items()}
    branches = node["oneOf"]
    lossy = isinstance(branches, list) and len(branches) > 1
    ctx.record(join_pointer(ptr, "oneOf"), "oneOf -> anyOf", lossy=lossy, effect="loosens" if lossy else "none")
    return out


def _keywords_to_strip(node: dict[str, Any], ptr: str, rule: Rule) -> list[str]:
    if rule.check == "keyword_present":
        return [k for k in rule.params["keywords"] if k in node]
    if rule.check == "keyword_allowlist":
        allowed = set(rule.params["allowed"]) | set(rule.params.get("ignore", ()))
        return [k for k in node if k not in allowed]
    if rule.check == "root_combinator":
        return [k for k in rule.params["keywords"] if k in node] if ptr == "" else []
    return []


def _node_strip_keywords(node: dict[str, Any], ptr: str, ctx: _Ctx) -> Any:
    strip = _keywords_to_strip(node, ptr, ctx.rule)
    if not strip:
        return node
    out = {k: v for k, v in node.items() if k not in strip}
    dropped = {}
    for kw in strip:
        lossy = _keyword_lossy(kw, node[kw])
        if lossy and kw not in _NOT_DESCRIBED:
            dropped[kw] = node[kw]
        ctx.record(join_pointer(ptr, kw), f"remove {kw}", lossy=lossy)
    if ctx.describe_dropped:
        _describe(out, dropped)
    return out


def _node_strip_format(node: dict[str, Any], ptr: str, ctx: _Ctx) -> Any:
    fmt = node.get("format")
    if isinstance(fmt, str) and fmt not in set(ctx.rule.params["allowed"]):
        out = {k: v for k, v in node.items() if k != "format"}
        if ctx.describe_dropped:
            _describe(out, {"format": fmt})
        ctx.record(join_pointer(ptr, "format"), f"remove format {fmt!r}", lossy=False)
        return out
    return node


def _node_strip_min_items(node: dict[str, Any], ptr: str, ctx: _Ctx) -> Any:
    limit = int(ctx.rule.params["max"])
    dropped: dict[str, Any] = {}
    out = dict(node)
    for kw in ("minItems", "maxItems", "uniqueItems", "contains", "minContains", "maxContains"):
        if kw not in node:
            continue
        if kw == "minItems" and isinstance(node[kw], int) and node[kw] <= limit:
            continue
        dropped[kw] = out.pop(kw)
        ctx.record(join_pointer(ptr, kw), f"remove {kw}", lossy=True)
    if dropped and ctx.describe_dropped:
        _describe(out, dropped)
    return out if dropped else node


def _node_infer_type(node: dict[str, Any], ptr: str, ctx: _Ctx) -> Any:
    if "type" in node or any(k in node for k in ("anyOf", "oneOf", "allOf", "$ref")):
        return node
    inferred: str | None = None
    lossy = True
    if any(k in node for k in ("properties", "required", "additionalProperties", "minProperties", "maxProperties")):
        inferred = "object"
    elif any(k in node for k in ("items", "prefixItems", "minItems", "maxItems")):
        inferred = "array"
    elif isinstance(node.get("enum"), list) and node["enum"]:
        kinds = {type(v) for v in node["enum"]}
        if kinds == {str}:
            inferred, lossy = "string", False
        elif kinds <= {int} and bool not in kinds:
            inferred, lossy = "integer", False
        elif kinds <= {int, float} and bool not in kinds:
            inferred, lossy = "number", False
        elif kinds == {bool}:
            inferred, lossy = "boolean", False
    elif any(k in node for k in ("minLength", "maxLength", "pattern")):
        inferred = "string"
    elif any(k in node for k in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf")):
        inferred = "number"
    if inferred is None:
        return node
    out = dict(node)
    out["type"] = inferred
    ctx.record(
        join_pointer(ptr, "type"), f"infer type {inferred!r}", lossy=lossy, effect="narrows" if lossy else "none"
    )
    return out


def _fix_root_type(schema: dict[str, Any], ctx: _Ctx) -> dict[str, Any]:
    if "type" in schema:
        return schema
    if any(k in schema for k in ("anyOf", "oneOf", "allOf", "$ref", "enum", "const", "items")):
        return schema
    out = dict(schema)
    out["type"] = "object"
    # MCP tool arguments are always a JSON object, so this is lossless in context.
    ctx.record(join_pointer("", "type"), "add root type 'object'", lossy=False)
    return out


def _node_set_ap_false(node: dict[str, Any], ptr: str, ctx: _Ctx) -> Any:
    from .engine import _is_object_schema

    if not _is_object_schema(node) or node.get("additionalProperties") is False:
        return node
    out = dict(node)
    previous = node.get("additionalProperties", True)
    out["additionalProperties"] = False
    ctx.record(
        join_pointer(ptr, "additionalProperties"),
        f"additionalProperties {json.dumps(previous)} -> false",
        lossy=True,
        effect="narrows",
    )
    return out


def _make_nullable(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return {"anyOf": [schema, {"type": "null"}]}
    t = schema.get("type")
    simple = not any(k in schema for k in ("anyOf", "oneOf", "allOf", "$ref", "const"))
    if isinstance(t, str) and simple:
        if t == "null":
            return schema
        out = dict(schema)
        out["type"] = [t, "null"]
        if isinstance(out.get("enum"), list) and None not in out["enum"]:
            out["enum"] = [*out["enum"], None]
        return out
    if isinstance(t, list) and simple:
        if "null" in t:
            return schema
        out = dict(schema)
        out["type"] = [*t, "null"]
        if isinstance(out.get("enum"), list) and None not in out["enum"]:
            out["enum"] = [*out["enum"], None]
        return out
    if isinstance(schema.get("anyOf"), list):
        from .engine import _is_null_branch

        if any(_is_null_branch(b) for b in schema["anyOf"]):
            return schema
        out = dict(schema)
        out["anyOf"] = [*schema["anyOf"], {"type": "null"}]
        return out
    desc = {k: schema[k] for k in ("description", "title") if k in schema}
    inner = {k: v for k, v in schema.items() if k not in desc}
    return {**desc, "anyOf": [inner, {"type": "null"}]}


def _node_require_all(node: dict[str, Any], ptr: str, ctx: _Ctx) -> Any:
    props = node.get("properties")
    if not isinstance(props, dict):
        return node
    required = list(node.get("required") or [])
    missing = [n for n in props if n not in required]
    if not missing:
        return node
    out = dict(node)
    new_props = dict(props)
    for name in missing:
        new_props[name] = _make_nullable(props[name])
        ctx.record(
            join_pointer(ptr, "properties", name), "optional -> required + nullable", lossy=True, effect="changes"
        )
    out["properties"] = new_props
    out["required"] = [*required, *missing]
    return out


_NODE_FIXES: dict[str, NodeFn] = {
    "merge_allof": _node_merge_allof,
    "const_to_enum": _node_const_to_enum,
    "type_list_to_nullable": _node_type_list_to_nullable,
    "null_union_to_nullable": _node_null_union_to_nullable,
    "oneof_to_anyof": _node_oneof_to_anyof,
    "strip_keywords": _node_strip_keywords,
    "strip_format": _node_strip_format,
    "strip_min_items": _node_strip_min_items,
    "infer_type": _node_infer_type,
    "set_additional_properties_false": _node_set_ap_false,
    "require_all_nullable": _node_require_all,
}
_ROOT_FIXES: dict[str, Callable[[dict[str, Any], _Ctx], dict[str, Any]]] = {
    "inline_refs": _fix_inline_refs,
    "add_root_type_object": _fix_root_type,
}


def available_fixes() -> list[str]:
    return sorted([*_NODE_FIXES, *_ROOT_FIXES])


def _apply_profile(
    schema: dict[str, Any], profile: Profile, describe_dropped: bool, include_unverified: bool
) -> tuple[dict[str, Any], list[Change]]:
    changes: list[Change] = []
    rules = [r for r in profile.rules if r.fix and (include_unverified or r.status == "verified")]
    rules.sort(key=lambda r: FIX_ORDER.index(r.fix) if r.fix in FIX_ORDER else len(FIX_ORDER))
    for rule in rules:
        ctx = _Ctx(rule, schema, describe_dropped)
        if rule.fix is None:  # filtered above; keeps type checkers happy
            continue
        if rule.fix in _ROOT_FIXES:
            schema = _ROOT_FIXES[rule.fix](schema, ctx)
        elif rule.fix in _NODE_FIXES:
            fn = _NODE_FIXES[rule.fix]
            schema = _rewrite(schema, "", fn, ctx)
        else:
            raise ValueError(f"rule {rule.id} uses unknown fix {rule.fix!r}")
        changes.extend(ctx.changes)
    return schema, changes


def portable(
    schema: dict[str, Any],
    profile: str | Profile | Sequence[str | Profile],
    *,
    tool_name: str | None = None,
    describe_dropped: bool = True,
    include_unverified: bool = True,
    max_rounds: int = 4,
) -> PortableResult:
    """Rewrite ``schema`` so it satisfies ``profile`` (one or several).

    The input is never mutated. Returns a :class:`PortableResult`; unpack it
    as ``new_schema, changes``. ``result.remaining`` lists findings that no
    fix could resolve.
    """
    from .engine import Finding, raw_findings

    profiles = resolve_profiles(profile)
    if not isinstance(schema, dict):
        raise TypeError("schema must be a JSON object")
    current = copy.deepcopy(schema)
    all_changes: list[Change] = []
    for _ in range(max_rounds):
        round_changes: list[Change] = []
        for prof in profiles:
            current, ch = _apply_profile(current, prof, describe_dropped, include_unverified)
            round_changes.extend(ch)
        all_changes.extend(round_changes)
        if not round_changes:
            break
    remaining: list[Finding] = []
    for prof in profiles:
        remaining.extend(
            f
            for f in raw_findings(current, prof, tool_name, include_unverified=include_unverified)
            if f.severity == "breaks"
        )
    return PortableResult(current, all_changes, remaining)
