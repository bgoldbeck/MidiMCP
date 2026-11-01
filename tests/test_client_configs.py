"""Downloadable MCP client configs and the tool schema listing."""

from __future__ import annotations

import json
import tomllib

import pytest
from starlette.testclient import TestClient

from midimcp.client_configs import UnknownClient, claude_command, client_config
from tests.test_web_api import AUTH, TOKEN, client, ctx  # noqa: F401  (fixtures)

URL = "http://192.168.1.140:8765/mcp"


def test_antigravity_config_uses_server_url_and_headers() -> None:
    name, media, text = client_config("antigravity", URL, "secret-token-123456")
    assert name == "mcp_config.json" and media == "application/json"
    assert json.loads(text) == {
        "mcpServers": {
            "midimcp": {
                "serverUrl": URL,
                "headers": {"Authorization": "Bearer secret-token-123456"},
            }
        }
    }


def test_other_clients() -> None:
    _, _, claude = client_config("claude", URL, "tok-0123456789abcdef")
    assert json.loads(claude)["mcpServers"]["midimcp"] == {
        "type": "http",
        "url": URL,
        "headers": {"Authorization": "Bearer tok-0123456789abcdef"},
    }
    _, _, generic = client_config("generic", URL, None)  # auth disabled: no headers
    assert json.loads(generic) == {"mcpServers": {"midimcp": {"url": URL}}}
    name, _, codex = client_config("codex", URL, "tok-0123456789abcdef")
    assert name == "config.toml"
    parsed = tomllib.loads(codex)
    assert parsed["mcp_servers"]["midimcp"] == {"url": URL, "bearer_token_env_var": "MIDIMCP_TOKEN"}
    assert "export MIDIMCP_TOKEN=tok-0123456789abcdef" in codex
    assert claude_command(URL, "t" * 20) == (
        f"claude mcp add --transport http --scope user midimcp {URL} "
        f'--header "Authorization: Bearer {"t" * 20}"'
    )
    with pytest.raises(UnknownClient):
        client_config("vscode", URL, None)


def test_config_download_route(client: TestClient) -> None:  # noqa: F811
    assert client.get("/api/mcp-config?client=antigravity").status_code == 401
    response = client.get(f"/api/mcp-config?client=antigravity&token={TOKEN}")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="mcp_config.json"'
    assert response.headers["cache-control"] == "no-store"
    entry = response.json()["mcpServers"]["midimcp"]
    assert entry["serverUrl"] == "http://nas.local:8765/mcp"  # the address the browser used
    assert entry["headers"] == {"Authorization": f"Bearer {TOKEN}"}
    via_header = client.get("/api/mcp-config?client=codex", headers=AUTH)
    assert 'url = "http://nas.local:8765/mcp"' in via_header.text
    bad = client.get("/api/mcp-config?client=nope", headers=AUTH)
    assert bad.status_code == 400 and bad.json()["code"] == "UNKNOWN_CLIENT"
    connect = client.get("/api/mcp-connect", headers=AUTH).json()
    assert connect["url"] == "http://nas.local:8765/mcp" and TOKEN in connect["claudeCommand"]


def test_tool_schema_listing(client: TestClient) -> None:  # noqa: F811
    assert client.get("/api/mcp-tools").status_code == 401
    listed = client.get("/api/mcp-tools", headers=AUTH)
    body = listed.json()
    assert body["transport"] == "streamable-http" and body["url"].endswith("/mcp")
    tools = {t["name"]: t for t in body["tools"]}
    assert {"create_project", "replace_notes", "humanize_notes", "add_to_collection"} <= set(tools)
    schema = tools["replace_notes"]["inputSchema"]
    assert schema["type"] == "object" and "project_id" in schema["properties"]
    assert "content-disposition" not in listed.headers
    download = client.get(f"/api/mcp-tools?download=1&token={TOKEN}")
    assert download.headers["content-disposition"] == 'attachment; filename="midimcp-tools.json"'
