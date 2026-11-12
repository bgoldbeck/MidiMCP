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
| 28 | ✅ Layered template sections | `feature/template-section-layers` | Per-section part layers (play / rest / enter / exit with bar and playing note), chord length in bars, layers in scaffolds, charts, MCP and the template editor; Old Realm forms reworked so parts enter and leave instead of four equal blocks |
| 29 | ✅ Old Realm woodland glade template | `feature/old-realm-glade-template` | `old-realm-glade`: 3/4 wandering theme built on section layers — never-stopping harp ostinato, anticipated bass, two-bar chords, a second ocarina in thirds, a melody-free clearing and a late guitar colour |
| 30 | ✅ Old Realm lament template | `feature/old-realm-lament-template` | `old-realm-lament`: slow 6/8 minor lament for ruins and memorials — harp flourish melody, choir that opens alone, rolled nylon-guitar chords in two blocks, low-harp arpeggios only at the edges, rare pizzicato punctuation, a melody-silent stretch before the coda |
| 31 | ✅ Old Realm mining town template | `feature/old-realm-mining-town-template` | `old-realm-mining-town`: 4/4 mixolydian town theme — galloping open-fifth guitar, horn, flute and oboe taking turns on the tune, decaying woodblock rolls and a taiko pair mid-phrase; new `retro.woodblock` alias |
| 32 | ✅ Old Realm elven town template | `feature/old-realm-elven-town-template` | `old-realm-elven-town`: brisk 4/4 D-minor town theme — harp root-fifth pendulum, music-box ostinato, flute tune with a harp answer, a drone dance with woodblock, a tolling-bell bridge through the flat II and an ocarina strain over harp arpeggios |
| 33 | ✅ Old Realm character creation template | `feature/old-realm-character-creation-template` | `old-realm-character-creation`: quiet 3/4 E-minor fingerpicked guitar for character creation and menus — a held low bass under a rolling arpeggio with every note left to ring, a second guitar doubling a few ticks late on the other side, and a sparse singing top line in the middle (reworked in `fix/character-creation-distinct-from-source` to move further from its source) |
| 34 | ✅ Old Realm bazaar template | `feature/old-realm-bazaar-template` | `old-realm-bazaar`: brisk 3/4 G-minor market theme with chromatic neighbour-note ornaments — pizzicato tonic pulse, tremolo drone, choir and high strings in open fifths, flute tune handed to the horn, piccolo echoes, tolling bells and a tambourine shaking on beats 2 and 3; `gm.drums` gets the GM percussion key range |
| 35 | ✅ Old Realm noble city template | `feature/old-realm-noble-city-template` | `old-realm-noble-city`: stately 3/4 A-minor waltz for a proud walled city — rolled nylon-guitar chords with a harpsichord's broken eighths, an ocarina tune of long notes and quick pickups answered by flute and oboe, falling harp sequences, a bright dorian section on the major IV with congas, and a tambourine shake into every other downbeat; every part kept at or below C6 |
| 36 | ✅ Old Realm island town template | `feature/old-realm-island-town-template` | `old-realm-island-town`: driving 4/4 A-harmonic-minor theme for a mystic island town — two harps in canon on a rising three-note figure, a high ocarina call, bells on the downbeat, low string drones, a timpani ostinato over tonic and subdominant pedals, a flute side tune and bongo eighths in the outro; every part at or below C6 |
| 37 | ✅ Octave transpose in the note editor | `feature/octave-transpose-controls` | **Octave down** / **Octave up** buttons and Shift + up/down arrow move the selection (or the whole track when nothing is selected) by whole octaves in one revision; refuses moves that would push a note outside MIDI 0-127 |
| 38 | ✅ Revert button in the note editor | `feature/editor-revert-button`, `fix/editor-revert-panel` | **Revert song...** beside Undo opens a panel listing earlier versions of the song, newest first, in plain words (who, when, what changed; unchanged tracks left out); pick one and **Revert song** puts every track back as a new revision, so Undo reverses it |
| 39 | ✅ Refresh the 8-bit and 16-bit templates | `feature/retro-templates-refresh` | The two 8-bit and five 16-bit templates get the Old Realm lessons: an intro before the tune, layered sections (parts rest, enter and leave), a break and a turnaround into the loop, every pitched part at or below C6, tick patterns for hooks, walking bass and fills, GM drum kits instead of the synth-drum patch, ringing harps, and new colours (oboe, music box, orchestra hits, bells, taiko, flute) |
| 40 | ✅ Refresh the wayfarer templates and write the composing playbook | `feature/wayfarer-refresh-and-playbook` | The six wayfarer templates get intros, layered sections, a break where the melody rests, a turnaround, every pitched part at or below C6 (the village recorder becomes an ocarina), tick patterns and new colours (fiddle, tambourine, voices, timpani, celesta, music box, ship's bell, sitar, hand drums); `docs/reference/09-composing-playbook.md` records owner preferences, the template checklist and the song-writing process, and the agent guide gains "The owner's ear" |

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
