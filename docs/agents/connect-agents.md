# Connect Claude Code, Codex, or Antigravity

MidiMCP speaks **MCP over Streamable HTTP** at `http://<nas>:8765/mcp` and requires the header `Authorization: Bearer <MIDIMCP_TOKEN>`. Replace `truenas.local` and `YOUR_TOKEN` below (the token is in the app logs or `token.txt` in the dataset).

> Client configuration formats change between releases. The snippets below follow each client's documented HTTP-server format at the time of writing; if your version differs, check its MCP docs (links at the end). The server side was verified with the official MCP Python client over HTTP.

## Easiest: download a ready-made config

Open the web UI, log in, and use the **Connect an AI client** card on the Songs page (or *Setup → Connect AI clients*): it downloads a config with your NAS address and token already filled in.

| Button | File | Endpoint |
|---|---|---|
| Antigravity | `mcp_config.json` | `GET /api/mcp-config?client=antigravity` |
| Claude Code | `.mcp.json` (+ a *Copy command* button) | `GET /api/mcp-config?client=claude` |
| Codex | `config.toml` lines | `GET /api/mcp-config?client=codex` |
| Tool list with schemas | `midimcp-tools.json`: every tool's JSON input schema | `GET /api/mcp-tools?download=1` |

The files contain your token: keep them private. The endpoints need the token too (`?token=` works for downloads).

## Claude Code

```bash
claude mcp add --transport http --scope user midimcp http://truenas.local:8765/mcp --header "Authorization: Bearer YOUR_TOKEN"
```

Check with `claude mcp list`, or `/mcp` inside a session.

## OpenAI Codex (CLI / IDE)

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.midimcp]
url = "http://truenas.local:8765/mcp"
bearer_token_env_var = "MIDIMCP_TOKEN"
```

and export the token where Codex runs:

```bash
export MIDIMCP_TOKEN=YOUR_TOKEN
```

Older Codex releases needed `experimental_use_rmcp_client = true` at the top level for HTTP servers.

## Google Antigravity

Agent panel → **…** → **MCP Servers** → **Manage MCP Servers** → **View raw config**, then add to `mcp_config.json` (or download it, see above; the file usually lives at `~/.gemini/antigravity/mcp_config.json`). Antigravity requires `serverUrl` (not `url`) for remote servers; if you already have servers, merge only the `midimcp` entry into `mcpServers`:

```json
{
  "mcpServers": {
    "midimcp": {
      "serverUrl": "http://truenas.local:8765/mcp",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

## Fallback for clients without HTTP MCP support

Bridge stdio to HTTP with `mcp-remote` (needs Node.js):

```json
{
  "command": "npx",
  "args": ["-y", "mcp-remote", "http://truenas.local:8765/mcp", "--allow-http",
           "--header", "Authorization: Bearer YOUR_TOKEN"]
}
```

## First prompt to try

> Using the midimcp tools, read the midimcp://guide resource, then create an original 16-bar loopable medieval town theme in the character of late-1990s fantasy RPG MIDI music: wooden flute melody, lute accompaniment, no percussion, G# Ionian, 84 BPM, 6/8, I–vi–IV–V. Validate it and render a preview.

Follow-up:

> Simplify the flute in bars 9–16 and leave the lute untouched.

The preview WAV and exports are downloadable at the `downloadPath` the tools return, e.g. `http://truenas.local:8765/api/projects/<id>/exports/<file>?token=YOUR_TOKEN` (the web UI, coming next, will make this a click).

## References

- Claude Code MCP: https://docs.anthropic.com/en/docs/claude-code/mcp
- Codex MCP: https://developers.openai.com/codex/mcp
- Antigravity MCP: https://antigravity.google/docs/mcp
