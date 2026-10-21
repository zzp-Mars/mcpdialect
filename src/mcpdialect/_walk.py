"""Walking JSON Schema documents.

Only *schema positions* are visited: property names, ``enum`` values,
``default`` values and other instance data are never mistaken for schemas.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

# keyword -> how its value holds subschemas
#   "schema": the value is one schema
#   "list":   the value is a list of schemas
#   "map":    the value is a mapping name -> schema
_SUBSCHEMA_KEYWORDS: dict[str, str] = {
    "properties": "map",
    "patternProperties": "map",
    "$defs": "map",
    "definitions": "map",
    "dependentSchemas": "map",
    "items": "schema_or_list",
    "prefixItems": "list",
    "additionalItems": "schema",
    "additionalProperties": "schema",
    "unevaluatedProperties": "schema",
    "unevaluatedItems": "schema",
    "contains": "schema",
    "propertyNames": "schema",
    "not": "schema",
    "if": "schema",
    "then": "schema",
    "else": "schema",
    "anyOf": "list",
    "oneOf": "list",
    "allOf": "list",
}


def escape_pointer_token(token: str) -> str:
    """Escape one JSON Pointer reference token (RFC 6901)."""
    return token.replace("~", "~0").replace("/", "~1")


def unescape_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def join_pointer(base: str, *tokens: str | int) -> str:
    out = base
    for tok in tokens:
        out += "/" + escape_pointer_token(str(tok))
    return out


@dataclass(frozen=True)
class Node:
    """A schema found while walking."""

    pointer: str
    schema: dict[str, Any]
    depth: int  # number of schema hops from the root
    object_depth: int  # number of enclosing schemas that declare ``properties``
    parent_keyword: str | None  # keyword under which this schema sits


def iter_children(schema: dict[str, Any], pointer: str) -> Iterator[tuple[str, str, Any]]:
    """Yield ``(keyword, pointer, subschema)`` for every direct subschema."""
    for keyword, kind in _SUBSCHEMA_KEYWORDS.items():
        if keyword not in schema:
            continue
        value = schema[keyword]
        if kind == "map" and isinstance(value, dict):
            for name, sub in value.items():
                if isinstance(sub, (dict, bool)):
                    yield keyword, join_pointer(pointer, keyword, name), sub
        elif kind == "list" and isinstance(value, list):
            for i, sub in enumerate(value):
                if isinstance(sub, (dict, bool)):
                    yield keyword, join_pointer(pointer, keyword, i), sub
        elif kind == "schema_or_list":
            if isinstance(value, list):
                for i, sub in enumerate(value):
                    if isinstance(sub, (dict, bool)):
                        yield keyword, join_pointer(pointer, keyword, i), sub
            elif isinstance(value, (dict, bool)):
                yield keyword, join_pointer(pointer, keyword), value
        elif kind == "schema" and isinstance(value, (dict, bool)):
            yield keyword, join_pointer(pointer, keyword), value


def walk(schema: Any, pointer: str = "") -> Iterator[Node]:
    """Depth-first walk over every object-valued schema (boolean schemas skipped)."""
    stack: list[tuple[Any, str, int, int, str | None]] = [(schema, pointer, 0, 0, None)]
    while stack:
        node, ptr, depth, obj_depth, parent_kw = stack.pop()
        if not isinstance(node, dict):
            continue
        here_obj_depth = obj_depth + (1 if "properties" in node else 0)
        yield Node(ptr, node, depth, here_obj_depth, parent_kw)
        children = list(iter_children(node, ptr))
        for keyword, child_ptr, child in reversed(children):
            stack.append((child, child_ptr, depth + 1, here_obj_depth, keyword))


def resolve_local_ref(root: dict[str, Any], ref: str) -> Any:
    """Resolve a same-document ``$ref`` (``#`` or ``#/a/b``). Raises KeyError."""
    if ref == "#":
        return root
    if not ref.startswith("#/"):
        raise KeyError(ref)
    cur: Any = root
    for raw in ref[2:].split("/"):
        tok = unescape_pointer_token(raw)
        if isinstance(cur, dict) and tok in cur:
            cur = cur[tok]
        elif isinstance(cur, list) and tok.isdigit() and int(tok) < len(cur):
            cur = cur[int(tok)]
        else:
            raise KeyError(ref)
    return cur


def is_local_ref(ref: object) -> bool:
    return isinstance(ref, str) and (ref == "#" or ref.startswith("#/"))
