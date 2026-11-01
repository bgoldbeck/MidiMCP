"""Portable tool input schemas.

Pydantic produces rich JSON Schema (``$defs``/``$ref``, ``anyOf`` with ``null`` for
optional values, ``title``, ``default``, ``additionalProperties``). Several MCP
clients - notably Gemini-based ones such as Google Antigravity - only accept a
small OpenAPI-like subset and silently drop (or refuse) tools whose schemas use
anything else, leaving the agent with no tools at all. This module rewrites each
advertised schema into that common subset:

* ``$ref`` is inlined and ``$defs`` removed;
* ``anyOf: [X, {"type": "null"}]`` becomes ``X`` (optional = not required);
* ``default`` moves into the description; ``title`` is dropped;
* free-form objects get explicit ``properties`` where the server knows them;
* only these keywords remain: type, description, enum, items, properties,
  required, minimum, maximum, minItems, maxItems.

Only the *advertised* schema changes. Arguments are still validated by the
server's own models, so behaviour is identical for every client.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Final

KEEP: Final = frozenset(
    {
        "type",
        "description",
        "enum",
        "items",
        "properties",
        "required",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
    }
)


class SchemaNotPortable(ValueError):
    """A schema construct with no portable equivalent (keeps the build honest)."""


def _resolve(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_resolve(n, defs) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        merged = {**copy.deepcopy(defs[name]), **{k: v for k, v in node.items() if k != "$ref"}}
        return _resolve(merged, defs)
    return {k: _resolve(v, defs) for k, v in node.items()}


def _simplify(node: dict[str, Any], hints: dict[str, dict[str, Any]], path: str) -> dict[str, Any]:
    node = dict(node)
    if "anyOf" in node:
        options = [o for o in node.pop("anyOf") if o.get("type") != "null"]
        if len(options) != 1:
            raise SchemaNotPortable(f"{path}: anyOf with {len(options)} non-null options")
        node = {**options[0], **node}
    if "const" in node:
        node["enum"] = [node.pop("const")]
    description = node.get("description") or ""
    default = node.get("default")
    if default is not None and default != [] and default != {}:
        shown = json.dumps(default) if not isinstance(default, str) else default
        description = f"{description} (default: {shown})".strip()
    if description:
        node["description"] = description
    if node.get("type") == "object" and "properties" not in node and path in hints:
        node["properties"] = copy.deepcopy(hints[path])
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key not in KEEP:
            continue
        if key == "properties":
            out[key] = {
                name: _simplify(child, hints, f"{path}.{name}" if path else name)
                for name, child in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            out[key] = _simplify(value, hints, f"{path}[]")
        else:
            out[key] = value
    if out.get("type") == "object" and "properties" not in out:
        raise SchemaNotPortable(f"{path or 'root'}: object without properties")
    return out


def portable_schema(
    schema: dict[str, Any], hints: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Rewrite ``schema`` into the portable subset (see module docstring).

    ``hints`` maps a property path (``"changes"``) to explicit properties for a
    free-form object parameter.
    """
    defs = schema.get("$defs", {})
    resolved = _resolve({k: v for k, v in schema.items() if k != "$defs"}, defs)
    result = _simplify(resolved, hints or {}, "")
    result.setdefault("properties", {})
    result["type"] = "object"
    return result


def make_tools_portable(server: Any, hints: dict[str, dict[str, dict[str, Any]]]) -> None:
    """Replace every registered tool's advertised input schema with a portable one."""
    for tool in server._tool_manager.list_tools():
        tool.parameters = portable_schema(tool.parameters, hints.get(tool.name))
