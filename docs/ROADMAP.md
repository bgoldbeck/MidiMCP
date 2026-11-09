# Feature Roadmap

Ordered implementation plan. One feature = one branch = one PR, merged before the next starts. Each feature ships with tests and a usable slice.

Status legend: ⬜ not started · 🟨 in progress · ✅ merged

## Ordering rationale

The original design ordered work *engine → player → GUI → MCP*. The target platform is now a **Docker container on TrueNAS with a web UI** (see `reference/07-deployment-docker-truenas.md`). This roadmap moves **MCP ahead of the GUI** because MCP is the project's primary bridge: once the score engine, store, and offline WAV render exist, an agent can already compose a song and the owner can listen to the rendered file. That gives a real end-to-end loop (prompt → song → audio) weeks earlier, and every later UI feature is built against a proven, agent-tested service API instead of guesses.

Second change: the **composition service** (single mutation authority with locks + revisions) is its own feature before MCP and HTTP, so both adapters wrap the same tested core.

## Phase 1 — Deterministic core (no audio hardware needed)

| # | Feature | Branch | Delivers | Done when |
|---|---|---|---|---|
| 1 | ✅ Python project scaffold + local checks | `feature/python-project-scaffold-and-ci` | `pyproject.toml`, `src/` layout, pytest, ruff (no hosted CI — local checks are the merge gate) | Lint and tests pass locally |
| 2 | ✅ Score schema, models, music math | `feature/score-schema-models-and-tick-math` | Pydantic models for score/brief, JSON Schema export, tick⇄bar⇄seconds math, tempo µs/quarter, key/mode pitch-class sets, enharmonic display spelling | G# Ionian ⇒ PC 8 / A♭ major; 6/8 @ 84 ⇒ 2,880 ticks/bar, 32 bars ≈ 68.57 s |
| 3 | ✅ Validator (hard + advisory) | `feature/score-validation-hard-errors-and-advisories` | Structural checks, brief constraints (no percussion, track limits, strict key), advisory warnings | Matrix rows for invalid notes, forbidden percussion, out-of-key advisory pass |
| 4 | ✅ Project store with immutable revisions | `feature/project-store-immutable-revisions-atomic-writes` | Disk layout, atomic writes, revision snapshots, SQLite index, `expectedRevision` conflicts, schema-version rejection | Save/reopen round-trip identical; stale revision ⇒ conflict, nothing written |
| 5 | ✅ Composition service (mutation authority) | `feature/composition-service-locks-and-range-replace` | create/add_track/update_track/replace_notes/edit_notes/set_arrangement, locks, idempotent `operationId`, change summaries, undo/restore-as-new-head | Edit bars 9–16 leaves everything else untouched; locked edit rejected atomically |
| 6 | ✅ MIDI export + import | `feature/type1-midi-export-and-reimport` | Mido Type 1 export (tempo/meter/key meta, named tracks, programs, ch-10 rule), reimport | Export→reimport preserves timing/pitch/program; no-percussion song has zero ch-10 events |

## Phase 2 — Sound, the AI bridge, and the container (first end-to-end loop)

| # | Feature | Branch | Delivers | Done when |
|---|---|---|---|---|
| 7 | ✅ Soundbank registry + license audit | `feature/soundbank-registry-and-license-audit` | Registry with SHA-256, license/provenance, aliases (`retro.wooden_flute`, `retro.lute`, …), user banks in `/data/banks`; default FluidR3_GM (MIT, Debian `fluid-soundfont-gm`) | Default bank license documented; missing bank ⇒ explicit error |
| 8 | ✅ Deterministic offline render | `feature/fluidsynth-deterministic-offline-render` | Score ⇒ MIDI ⇒ FluidSynth WAV at 48 kHz, pinned render profile, speed-multiplier renders (pitch unchanged), render cache in `/data/renders` | Two renders of same revision ⇒ identical PCM hash |
| 9 | ✅ MCP server (Streamable HTTP + stdio) | `feature/mcp-http-server-composition-tools` | All tools from `reference/04-mcp-tools.md` over the service, resources (schema, guide, instruments), render + export, bearer-token auth | Agent creates "Lanterns of the Vale", edits flute bars 9–16 ⇒ revision 2, renders WAV |
| 10 | ✅ Docker image + TrueNAS deploy + agent setup | `feature/docker-image-truenas-deploy-and-agent-setup` | `Dockerfile`, `compose.yaml`, non-root user, `/data` volume, healthcheck, auto-generated token, one-YAML TrueNAS install from a self-published ghcr.io image; TrueNAS SCALE install guide; Claude Code / Codex / Antigravity connection guides | `docker compose up` serves `/mcp` + `/healthz`; agents connect over LAN |

**Milestone:** owner deploys on TrueNAS, asks an agent for a song, and gets a WAV. Core product promise proven.

## Phase 3 — The web app

| # | Feature | Branch | Delivers | Done when |
|---|---|---|---|---|
| 11 | ✅ Web API + live events + downloads | `feature/web-api-websocket-events-and-downloads` | Starlette `/api` routes beside `/mcp` in the same app (no FastAPI dependency needed), token auth, WebSocket revision/render events, download endpoints (MIDI/WAV/project bundle) | MCP edit appears as an event; browser downloads exports |
| 12 | ✅ Browser playback | `feature/browser-playback-of-rendered-audio` | Play/pause/stop/seek/loop over rendered audio, speed multiplier via cached re-render, playhead sync | 125% ⇒ 80% duration, same pitch |
| 13 | ✅ Web UI — beginner mode | `feature/react-web-ui-library-transport-and-tracks` | Plain-JS UI (no build step) served by the container: library, transport, tracks (mute/solo/volume/instrument), measure overview, MCP status, export buttons | All core song tasks work in the browser with no agent connected |
| 14 | ⬜ Revision history + AI change review | `feature/revision-history-ai-change-summary-and-ab` | History panel, change summaries, A/B audition, undo last AI change | Undo restores prior notes as new head revision |
| 15 | ⬜ Loops, OGG, export metadata, bundle import | `feature/loop-export-ogg-metadata-and-bundle-import` | Straight + tail-aware loop, OGG encode, export metadata JSON, project bundle `.zip` import | Clean loop with exact sample metadata; bundle round-trips |

## Added on request

| # | Feature | Branch | Delivers |
|---|---|---|---|
| 24 | ✅ MP3 export | `feature/mp3-export` | MP3 download (LAME, 128-320 kbps, ID3 title tags) from the web UI, web API and MCP |
| 25 | ✅ Expression + humanize + style templates | `feature/expression-and-humanize` | Score schema 1.1.0 automation (CC11 expression, CC1 vibrato, pitch bend) with MIDI export/import and lock protection; MCP `humanize_notes` (seeded), `shape_expression`, `set_automation`; `MECHANICAL_MELODY` advisory; 9 `old-realm-*` templates (late-90s online fantasy RPG spirit: title/login, town, forest, sailing, dungeon, battle, castle, shrine, wilderness) and 12 `retro-*` game-era templates; per-template expression guidance; help page section |
| 26 | ✅ Favorites + collections | `feature/favorites-and-collections` | Star songs, user-made collections (create/rename/delete, multi-membership), library filter chips and sorting, `collections.json` outside song revisions, live updates, MCP `list_collections` / `add_to_collection` |
| 27 | ✅ Natural sampled flute | `main` (current checkout) | Per-track sfizz/GM source selection, pinned licensed VSCO flute patches, atomic performance controls, portable MIDI fallback, mixed rendering and clipping reports; native/browser and Linux mixed-render/determinism checks passed |
| 28 | 🟨 Layered template sections | `feature/template-section-layers` | Per-section part layers (play / rest / enter / exit with bar and playing note), chord length in bars, layers in scaffolds, charts, MCP and the template editor; Old Realm forms reworked so parts enter and leave instead of four equal blocks |

## Phase 4 — Editing depth and quality

| # | Feature | Branch | Delivers |
|---|---|---|---|
| 16 | ✅ Piano roll + locks UI | `feature/piano-roll-note-editor-and-lock-ranges` | Click/Shift/marquee selection, group move/resize, velocity, snap/zoom, phrase sliders, length/time scaling with atomic timeline extension, selection audition/saved loop, revision-safe undo/redo, track/range protection, exact AI selection prompts; highlighted note-end grip with absolute grid snapping added in `5654827` |
| 17 | ✅ Composition templates + theory advisories | `feature/rpg-composition-templates-and-theory-advisories` | Town/forest/crypt/tavern/sea/borderlands templates that scaffold tracks, roles, ranges, form and chord chart; range/breath/leap/masking/dynamics/repetition advisories (example songs deferred) |
| 18 | ⬜ Connections page + diagnostics | `feature/connections-page-and-diagnostics` | Per-host setup, health, last MCP call, missing-bank diagnostics, user SoundFont upload |
| 19 | ⬜ TrueNAS hardening | `feature/truenas-app-hardening-and-backups` | Upgrade/migration path, snapshot-friendly backups, resource limits, fresh-install test |

## Phase 5 — Sparkfall / game workflow (post-v1)

| # | Feature | Branch |
|---|---|---|
| 20 | ⬜ Instrument stems export | `feature/instrument-stem-export` |
| 21 | ⬜ Linked mood variations (day / night / danger) | `feature/linked-mood-variations` |
| 22 | ⬜ Unity import presets + bar-quantized transitions | `feature/unity-import-and-adaptive-transitions` |
| 23 | ⬜ Tempo map (articulation + humanization done in 25) | `feature/tempo-map-articulation-humanization` |

## Open decisions (owner input welcome, safe defaults used meanwhile)

- Default SoundFont — needs listening test + license audit (feature 7).
- Final product name (default: "Retro MIDI Composer" / repo MidiMCP).
- Desktop shell for packaging (deferred to feature 19).
