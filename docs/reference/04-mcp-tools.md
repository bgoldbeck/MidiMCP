# 04 — MCP Tool Contract

MCP is a public adapter over the composition service, never a second data authority. All results carry: project ID (if applicable), success/error code, revision, warnings, summary.

## Tools

| Tool | Key inputs | Result |
|---|---|---|
| `list_capabilities` | — | Schema versions, limits, modes, audio engine status |
| `list_soundbanks` | filter? | Installed banks, IDs, licenses, availability |
| `list_instruments` | bankId / search | Exact instrument IDs, aliases, ranges |
| `list_projects` | search / tag | Project IDs + metadata |
| `create_project` | title, meter, tempo, key, profile, brief | New project, revision 1 |
| `get_project` | projectId, section/track filters | Score, locks, current revision |
| `set_arrangement` | projectId, expectedRevision, sections/harmony | New revision |
| `add_track` | projectId, expectedRevision, instrumentId, name | Empty track, new revision |
| `update_track` | projectId, expectedRevision, trackId, props | Instrument/mix/mute/pan, new revision |
| `replace_notes` | projectId, expectedRevision, trackId, range, notes | Atomic range replace |
| `edit_notes` | projectId, expectedRevision, note-ID patch ops | Targeted atomic edits |
| `validate_project` | projectId, strict/advisory | Errors, warnings, rhythm/harmony summary |
| `render_preview` | projectId, revision, range, profile | Render job ID |
| `get_render_status` | jobId | queued / running / completed / failed + asset ref |
| `export_project` | projectId, revision, format, loop policy | MIDI / WAV / OGG / JSON reference |
| `list_revisions` | projectId | History + change summaries |

Read-only **resources**: tool guide, composition schema, instrument registry, active project summary.

## Example edit

```json
{
  "projectId": "example-project",
  "expectedRevision": 4,
  "trackId": "flute-1",
  "range": { "startTick": 23040, "endTick": 46080 },
  "replacementNotes": [ { "pitch": 72, "startTick": 23040, "durationTicks": 960, "velocity": 70 } ]
}
```

## Every mutation must check, in order

1. `expectedRevision` matches head.
2. Project, track, note IDs, instruments, tick range exist.
3. No locked track/range touched.
4. New notes legal (pitch, velocity, duration).
5. Brief hard constraints still satisfied.
6. Whole resulting document validates.
7. Commit atomically, then notify UI subscribers.

Accept caller `operationId` for idempotency.

## Explicitly excluded

Shell commands, arbitrary disk paths, downloading assets, installing unknown banks, deleting other projects, silently changing a pinned sound profile. No stub tools that pretend to succeed.

## Hosts

Streamable HTTP first (`http://<nas>:<port>/mcp`, bearer token) because agents run on the owner's PC and the server runs on TrueNAS; stdio for local development. Document and test each supported release of:
- Claude Code
- OpenAI Codex CLI / IDE
- Google Antigravity IDE / CLI

Config syntax and protocol versions differ — test, don't assume. App gets a **Connections** page: per-host setup, backend health, tool list, last successful call, permission status.

## Reference end-to-end demo prompt

> Create an original 32-bar, loopable medieval town theme for Sparkfall in the character of late-1990s fantasy RPG MIDI music. Wooden flute melody, plucked lute-like accompaniment. No percussion. G# Ionian (A♭ major), 84 quarter-BPM, 6/8. I–vi–IV–V, A/B/A'/closing form, clear 4-bar phrases, rests, modest polyphony, restrained dynamics. Use the Retro GM 1997 profile and exact instrument IDs. Validate, save as "Lanterns of the Vale", render a preview. Don't modify other projects or copy an existing game's melody.

Follow-up: *"Simplify flute measures 9–16; leave lute untouched."* ⇒ bounded `replace_notes` on current revision ⇒ revision 2 with change summary and A/B audition.

## Music-quality guidance for agents

- 4- or 8-bar phrases with recognizable motifs.
- A / B / A' development, not static repetition.
- Rests, breath points, sensible range, velocity contour.
- Sparse accompaniment that leaves room for melody.
- Loops resolve back into the opening harmony.
- Real melodic contour, not random in-key notes.

Templates (character, never copied melodies): peaceful medieval town, forest exploration, ruined crypt, tavern/minstrel, sea travel, tense borderlands. Each gives tempo range, meter, palette, density, form, phrase length, register, typical harmony; user can override.

Preview WAV may be inspected by audio-capable hosts; never promise AI listening where the host can't.
