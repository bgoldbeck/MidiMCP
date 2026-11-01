"""Advertised MCP tool schemas stay within the subset Gemini-based clients accept."""

from __future__ import annotations

import asyncio

import pytest
from mcp import Client

from midimcp.context import AppContext
from midimcp.mcp_schema import KEEP, SchemaNotPortable, portable_schema
from midimcp.mcp_server import build_mcp_server
from tests.test_mcp import call, ctx  # noqa: F401  (fixture)


def test_portable_schema_rewrites_rich_json_schema() -> None:
    schema = {
        "$defs": {
            "Note": {
                "title": "Note",
                "type": "object",
                "properties": {"pitch": {"type": "integer", "minimum": 0, "title": "Pitch"}},
                "required": ["pitch"],
            }
        },
        "title": "args",
        "type": "object",
        "properties": {
            "notes": {"type": "array", "items": {"$ref": "#/$defs/Note"}, "title": "Notes"},
            "seed": {"type": "integer", "default": 1, "description": "Same seed, same result"},
            "id": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
            "op": {"const": "add"},
        },
        "required": ["notes"],
    }
    assert portable_schema(schema) == {
        "type": "object",
        "properties": {
            "notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"pitch": {"type": "integer", "minimum": 0}},
                    "required": ["pitch"],
                },
            },
            "seed": {"type": "integer", "description": "Same seed, same result (default: 1)"},
            "id": {"type": "string"},
            "op": {"enum": ["add"]},
        },
        "required": ["notes"],
    }
    with pytest.raises(SchemaNotPortable):
        portable_schema(
            {
                "type": "object",
                "properties": {"x": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
            }
        )
    with pytest.raises(SchemaNotPortable):
        portable_schema({"type": "object", "properties": {"x": {"type": "object"}}})
    hinted = portable_schema(
        {
            "type": "object",
            "properties": {"changes": {"type": "object", "additionalProperties": True}},
        },
        {"changes": {"mood": {"type": "string"}}},
    )
    assert hinted["properties"]["changes"] == {
        "type": "object",
        "properties": {"mood": {"type": "string"}},
    }


def _keywords(node: object, found: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            if key == "properties":
                for child in value.values():
                    _keywords(child, found)
            else:
                _keywords(value, found)
    elif isinstance(node, list):
        for item in node:
            _keywords(item, found)


def test_every_advertised_tool_schema_is_portable_and_calls_still_work(ctx: AppContext) -> None:  # noqa: F811
    async def go() -> None:
        async with Client(build_mcp_server(ctx)) as mcp:
            tools = (await mcp.list_tools()).tools
            assert len(tools) >= 26
            for tool in tools:
                found: set[str] = set()
                _keywords(tool.input_schema, found)
                assert found <= KEEP, (tool.name, found - KEEP)
                assert tool.input_schema["type"] == "object"
            brief = next(t for t in tools if t.name == "update_brief").input_schema
            assert "mood" in brief["properties"]["changes"]["properties"]
            # Optional arguments are still optional and validated by the server's models.
            created = await call(
                mcp,
                "create_project",
                title="Schema Test",
                tempo_bpm=90,
                meter_numerator=4,
                meter_denominator=4,
                tonic="C",
                bars=4,
            )
            changed = await call(
                mcp,
                "update_brief",
                project_id=created["projectId"],
                expected_revision=created["revision"],
                changes={"mood": "calm"},
            )
            assert changed["revision"] == created["revision"] + 1

    asyncio.run(go())
