# MidiMCP

AI-controlled retro MIDI composer for 1990s-style fantasy RPG music.
Claude, Codex, Antigravity (or any MCP-capable agent) compose structured scores through an MCP server; a local app validates, plays, edits, and exports them.

- Design reference: [`docs/reference/`](docs/reference/README.md)
- Build order: [`docs/ROADMAP.md`](docs/ROADMAP.md)

## Development

Requires Python 3.11+.

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

There is no hosted CI (GitHub Actions is intentionally not used). Run the lint and test commands above before every pull request.
