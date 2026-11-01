# MidiMCP

AI-controlled retro MIDI composer for 1990s-style fantasy RPG music.
Claude, Codex, Antigravity (or any MCP-capable agent) compose structured scores through an MCP server; a local app validates, plays, edits, and exports them.

Runs as one Docker container (designed for TrueNAS SCALE): MCP over HTTP at `/mcp`, FluidSynth rendering, songs stored on a `/data` volume and downloadable as MIDI / WAV / JSON. A web UI is next on the roadmap.

- **Deploy on TrueNAS:** [`docs/deploy/truenas.md`](docs/deploy/truenas.md)
- **Connect Claude Code / Codex / Antigravity:** [`docs/agents/connect-agents.md`](docs/agents/connect-agents.md)
- Design reference: [`docs/reference/`](docs/reference/README.md)
- Build order: [`docs/ROADMAP.md`](docs/ROADMAP.md)

## Run with Docker (any host)

```bash
cp .env.example .env
```

Edit `.env` and set `MIDIMCP_TOKEN` (e.g. from `openssl rand -hex 32`), then:

```bash
docker compose up -d --build
```

```bash
curl http://localhost:8765/healthz
```

```bash
python scripts/smoke_test.py --url http://localhost:8765 --token YOUR_TOKEN
```

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

Tests that render audio need `fluidsynth` and the FluidR3 GM soundbank (Ubuntu/Debian: `sudo apt install fluidsynth fluid-soundfont-gm`); they are skipped when missing. Run the server locally without Docker:

```bash
MIDIMCP_TOKEN=dev-token-0123456789 MIDIMCP_DATA_DIR=./data python -m midimcp serve
```

There is no hosted CI (GitHub Actions is intentionally not used). Run the lint and test commands above before every pull request.
