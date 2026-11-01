"""Ready-to-use MCP client configuration files for this server.

The web UI offers them as downloads so nobody has to type the URL or token. The
token in a file is the one the browser already used for the request, so a
download never reveals anything the caller did not already have.

Formats follow each client's documented remote (Streamable HTTP) server entry:

* Google Antigravity: ``mcp_config.json`` with ``mcpServers.<name>.serverUrl``
  and ``headers``;
* Claude Code: a project ``.mcp.json`` with ``type: "http"``, ``url``, ``headers``;
* OpenAI Codex: ``config.toml`` ``[mcp_servers.<name>]`` with ``url`` and
  ``bearer_token_env_var``;
* generic: the common ``mcpServers`` shape with ``url`` and ``headers``.
"""

from __future__ import annotations

import json
from typing import Final

SERVER_NAME: Final = "midimcp"
CLIENTS: Final = ("antigravity", "claude", "codex", "generic")


class UnknownClient(ValueError):
    code = "UNKNOWN_CLIENT"


def _headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _json(data: dict) -> str:
    return json.dumps(data, indent=2) + "\n"


def client_config(client: str, url: str, token: str | None) -> tuple[str, str, str]:
    """Return ``(filename, media_type, content)`` for ``client``."""
    if client == "antigravity":
        entry: dict = {"serverUrl": url}
        if token:
            entry["headers"] = _headers(token)
        return "mcp_config.json", "application/json", _json({"mcpServers": {SERVER_NAME: entry}})
    if client == "claude":
        entry = {"type": "http", "url": url}
        if token:
            entry["headers"] = _headers(token)
        return ".mcp.json", "application/json", _json({"mcpServers": {SERVER_NAME: entry}})
    if client == "generic":
        entry = {"url": url}
        if token:
            entry["headers"] = _headers(token)
        return "mcp.json", "application/json", _json({"mcpServers": {SERVER_NAME: entry}})
    if client == "codex":
        lines = [
            "# MidiMCP for OpenAI Codex: add this to ~/.codex/config.toml",
        ]
        if token:
            lines.append("# and set the token where Codex runs:  export MIDIMCP_TOKEN=" + token)
        lines += ["", f"[mcp_servers.{SERVER_NAME}]", f'url = "{url}"']
        if token:
            lines.append('bearer_token_env_var = "MIDIMCP_TOKEN"')
        return "config.toml", "text/plain; charset=utf-8", "\n".join(lines) + "\n"
    raise UnknownClient(f"client must be one of {', '.join(CLIENTS)}")


def claude_command(url: str, token: str | None) -> str:
    header = f' --header "Authorization: Bearer {token}"' if token else ""
    return f"claude mcp add --transport http --scope user {SERVER_NAME} {url}{header}"
