# 07 — Deployment: Docker on TrueNAS with Web UI

**Decision (owner, 2026-11-01):** the app ships as a single Docker container, deployed on the owner's **TrueNAS SCALE** server, with a **web interface** reached from a browser. This replaces the original Windows-desktop plan. Everything else in the design (score format, revisions, locks, deterministic rendering, MCP tool contract) is unchanged.

## What runs where

```
Your PC / laptop                               TrueNAS SCALE
┌──────────────────────────────┐   LAN    ┌────────────────────────────────────────┐
│ Claude Code / Codex /         │──HTTP──►│  midimcp container (one process)        │
│ Antigravity  (MCP client)     │  /mcp   │   ├─ MCP server  (Streamable HTTP)      │
│                               │         │   ├─ Web API + WebSocket events         │
│ Browser                       │──HTTP──►│   ├─ Web UI (static React build)        │
│  - web UI, plays audio        │   /     │   ├─ Composition service + ProjectStore │
│  - downloads exports          │         │   └─ FluidSynth offline renderer        │
└──────────────────────────────┘          │  /data  ◄── TrueNAS dataset (volume)    │
                                          └────────────────────────────────────────┘
```

- One container, one Python process: MCP endpoint, web API, and UI share the same composition service and store — still a single mutation authority.
- **MCP transport: Streamable HTTP** at `http://<nas>:<port>/mcp`. Agents run on the owner's PC, so stdio cannot reach the container. stdio remains available for local development (`python -m midimcp.mcp --stdio`).
- **Audio is rendered in the container and played in the browser.** The NAS has no speakers; FluidSynth renders WAV (later OGG) and the browser plays it. Playback speed = re-render at a different tempo (pitch unchanged, deterministic, cached).
- **No sound card, no realtime synth on the server.** The "realtime transport" feature becomes a browser audio player over rendered files with playhead sync.

## Data and exports

- Persistent volume mounted at **`/data`** (TrueNAS dataset, e.g. `/mnt/<pool>/apps/midimcp`):
  ```
  /data/projects/...      songs + immutable revisions (source of truth)
  /data/library.sqlite    search index (rebuildable)
  /data/banks/            user-imported SoundFonts
  /data/renders/          render cache (safe to delete)
  ```
- Songs live on the NAS by default. **Export is optional and user-initiated**: download from the web UI as `.mid`, `.wav`, `.ogg`, or a **project bundle** (`.zip` with score, brief, revisions, manifest — never third-party bank bytes). Bundles can be re-imported.
- The dataset is covered by normal TrueNAS snapshots/replication — the recommended backup path.

## Security (container is reachable on the LAN)

- The old "loopback only" rule no longer applies; replace with:
  - **Bearer token required** for `/mcp` and `/api` (`MIDIMCP_TOKEN` env var; container refuses to start without one unless `MIDIMCP_ALLOW_NO_AUTH=1` is set explicitly).
  - Web UI login uses the same token (stored in the browser session).
  - Origin checks on WebSocket; CORS closed by default.
  - **Do not expose the port to the internet.** For remote use, put it behind the owner's VPN/reverse proxy with TLS.
- Container runs as non-root (UID/GID configurable to match the dataset owner, TrueNAS default `apps` = 568).
- No MCP tool accepts arbitrary paths, URLs, or shell commands.

## Image

- Base: Ubuntu 24.04 + `fluidsynth` + `fluid-soundfont-gm` + `lame` (MP3 encoder) (FluidR3_GM, MIT license — redistributable default bank; final retro bank choice still pending listening tests).
- Single exposed port (default `8765`), healthcheck at `/healthz`.
- Config via env: `MIDIMCP_TOKEN`, `MIDIMCP_DATA_DIR=/data`, `MIDIMCP_PORT`, `PUID`/`PGID`.
- No hosted CI: the image is built locally (`docker compose build`) on the NAS or on the owner's PC and pushed to a registry of their choice. TrueNAS install via **Apps → Discover → Custom App → Install via YAML** using the repo's `compose.yaml`.

## Changes to earlier docs

| Earlier statement | Now |
|---|---|
| Windows desktop, local only | Docker container on TrueNAS, LAN web UI |
| MCP stdio first, loopback HTTP later | Streamable HTTP first (token auth), stdio for dev |
| Bind 127.0.0.1, launcher session token | Bind 0.0.0.0 in container, required bearer token |
| Realtime FluidSynth playback to sound card | Server renders audio, browser plays it |
| Windows packaging/installer | Docker image + compose + TrueNAS guide |
