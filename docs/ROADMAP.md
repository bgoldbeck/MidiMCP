# Feature Roadmap

Ordered implementation plan. One feature = one branch = one PR, merged before the next starts. Each feature ships with tests and a usable slice.

Status legend: ⬜ not started · 🟨 in progress · ✅ merged

## Ordering rationale

The original design ordered work *engine → player → GUI → MCP*. This roadmap moves **MCP ahead of the GUI** because MCP is the project's primary bridge: once the score engine, store, and offline WAV render exist, an agent can already compose a song and the owner can listen to the rendered file. That gives a real end-to-end loop (prompt → song → audio) weeks earlier, and every later UI feature is built against a proven, agent-tested service API instead of guesses.

Second change: the **composition service** (single mutation authority with locks + revisions) is its own feature before MCP and HTTP, so both adapters wrap the same tested core.

## Phase 1 — Deterministic core (no audio hardware needed)

| # | Feature | Branch | Delivers | Done when |
|---|---|---|---|---|
| 1 | ✅ Python project scaffold + CI | `feature/python-project-scaffold-and-ci` | `pyproject.toml`, `src/` layout, pytest, ruff, GitHub Actions on Windows + Linux | CI green on empty test suite |
| 2 | ✅ Score schema, models, music math | `feature/score-schema-models-and-tick-math` | Pydantic models for score/brief, JSON Schema export, tick⇄bar⇄seconds math, tempo µs/quarter, key/mode pitch-class sets, enharmonic display spelling | G# Ionian ⇒ PC 8 / A♭ major; 6/8 @ 84 ⇒ 2,880 ticks/bar, 32 bars ≈ 68.57 s |
| 3 | ✅ Validator (hard + advisory) | `feature/score-validation-hard-errors-and-advisories` | Structural checks, brief constraints (no percussion, track limits, strict key), advisory warnings | Matrix rows for invalid notes, forbidden percussion, out-of-key advisory pass |
| 4 | 🟨 Project store with immutable revisions | `feature/project-store-immutable-revisions-atomic-writes` | Disk layout, atomic writes, revision snapshots, SQLite index, `expectedRevision` conflicts, schema-version rejection | Save/reopen round-trip identical; stale revision ⇒ conflict, nothing written |
| 5 | ⬜ Composition service (mutation authority) | `feature/composition-service-locks-and-range-replace` | create/add_track/update_track/replace_notes/edit_notes/set_arrangement, locks, idempotent `operationId`, change summaries, undo/restore-as-new-head | Edit bars 9–16 leaves everything else untouched; locked edit rejected atomically |
| 6 | ⬜ MIDI export + import | `feature/type1-midi-export-and-reimport` | Mido Type 1 export (tempo/meter/key meta, named tracks, programs, ch-10 rule), reimport | Export→reimport preserves timing/pitch/program; no-percussion song has zero ch-10 events |

## Phase 2 — Sound and the AI bridge (first end-to-end loop)

| # | Feature | Branch | Delivers | Done when |
|---|---|---|---|---|
| 7 | ⬜ Soundbank registry + license audit | `feature/soundbank-registry-and-license-audit` | Registry with SHA-256, license/provenance, aliases (`retro.wooden_flute`, `retro.lute`, …), user import; written audit choosing default retro GM bank | Default bank chosen with documented redistributable license; missing bank ⇒ explicit error |
| 8 | ⬜ Deterministic offline WAV render | `feature/fluidsynth-deterministic-offline-render` | Shared event compiler, headless FluidSynth render at 48 kHz, pinned render profile, render cache key | Two renders of same revision ⇒ identical PCM hash |
| 9 | ⬜ MCP server (stdio) | `feature/mcp-stdio-server-composition-tools` | All tools from `reference/04-mcp-tools.md` over the service, resources (schema, guide, instruments), render jobs, exports | Demo prompt in Claude Code produces "Lanterns of the Vale" + WAV; follow-up bar 9–16 edit yields revision 2 |
| 10 | ⬜ Agent host setup guides | `docs/mcp-host-setup-claude-codex-antigravity` | Tested config for Claude Code, Codex, Antigravity; tool usage guide + composition templates text | Each host lists tools and completes the demo |

**Milestone:** owner can ask an agent for a song and listen to the WAV. Core product promise proven.

## Phase 3 — The app

| # | Feature | Branch | Delivers | Done when |
|---|---|---|---|---|
| 11 | ⬜ Local API + live events | `feature/local-fastapi-and-websocket-events` | FastAPI on 127.0.0.1, session token, origin checks, WebSocket revision/render events; MCP adapter attaches to running service | MCP edit appears as event to a connected client |
| 12 | ⬜ Realtime playback transport | `feature/realtime-playback-transport` | Play/pause/stop/seek/loop, tempo multiplier without pitch shift, all-notes-off on stop/seek, playhead events | 125% ⇒ 80% duration; no stuck notes on seek |
| 13 | ⬜ React app — beginner mode | `feature/react-ui-library-transport-and-tracks` | Vite+TS app: library, transport, track list (mute/solo/volume/instrument), measure overview, MCP status | All core song tasks work with no agent connected |
| 14 | ⬜ Revision history + AI change review | `feature/revision-history-ai-change-summary-and-ab` | History panel, change summaries, A/B audition, undo last AI change | Undo restores prior notes as new head revision |
| 15 | ⬜ Exports: loops, OGG, metadata | `feature/loop-export-ogg-and-export-metadata` | Straight + tail-aware loop, OGG encode, export metadata JSON, export UI | Clean loop with exact sample metadata |

## Phase 4 — Editing depth and quality

| # | Feature | Branch | Delivers |
|---|---|---|---|
| 16 | ⬜ Piano roll + locks UI | `feature/piano-roll-note-editor-and-lock-ranges` | Drag/resize/velocity edit, lock track/range, copy selection ranges for prompts |
| 17 | ⬜ Composition templates + theory advisories | `feature/rpg-composition-templates-and-theory-advisories` | Town/forest/crypt/tavern/sea/borderlands templates, richer advisories, original example songs |
| 18 | ⬜ Connections page + diagnostics | `feature/connections-page-and-diagnostics` | Per-host setup, health, last call, missing-bank/audio-driver diagnostics |
| 19 | ⬜ Windows packaging | `feature/windows-packaging-and-fresh-install` | Launcher, bundled redistributable bank, fresh-machine install/uninstall/backup tests |

## Phase 5 — Sparkfall / game workflow (post-v1)

| # | Feature | Branch |
|---|---|---|
| 20 | ⬜ Instrument stems export | `feature/instrument-stem-export` |
| 21 | ⬜ Linked mood variations (day / night / danger) | `feature/linked-mood-variations` |
| 22 | ⬜ Unity import presets + bar-quantized transitions | `feature/unity-import-and-adaptive-transitions` |
| 23 | ⬜ Tempo map, articulation, humanization seed | `feature/tempo-map-articulation-humanization` |

## Open decisions (owner input welcome, safe defaults used meanwhile)

- Default SoundFont — needs listening test + license audit (feature 7).
- Final product name (default: "Retro MIDI Composer" / repo MidiMCP).
- Desktop shell for packaging (deferred to feature 19).
