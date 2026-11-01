# 02 — Architecture

## Stack (v1)

| Layer | Choice | Why |
|---|---|---|
| UI | React + TypeScript + Vite | Owner familiar; desktop-like UI |
| Local API | Python + FastAPI | Single authority for UI and agents |
| MCP | Official Python MCP SDK, stdio transport first | Structured tool calls; all three hosts can spawn stdio servers |
| Synth | libFluidSynth + SF2/SF3 | GM-era sampled synthesis, realtime and offline |
| MIDI I/O | Mido | Standard MIDI File read/write |
| Storage | JSON per project + SQLite index | Readable source of truth; fast library listing |
| Live status | WebSocket | Playhead, render jobs, revision changes |
| Platform | Windows, local, offline | Packaging deferred until MVP stable |

## Process boundary

```
Claude / Codex / Antigravity
   └─ MCP adapter (stdio; optional loopback HTTP later)
        └─ Composition service  ◄── React UI (HTTP + WebSocket)
             ├─ schema validator / musical constraints / revision manager
             ├─ immutable revision files + SQLite index
             ├─ realtime playback (FluidSynth)
             └─ offline render (FluidSynth)
```

## Hard rules

1. **One mutation authority.** GUI and MCP both go through the composition service. Agents never touch project JSON directly.
2. MCP adapter discovers the already-running service; if absent, return a friendly "app not running" error. No per-agent private stores.
3. Bind to `127.0.0.1` only. Launcher issues a random session token to UI and MCP adapter. Validate request origin.
4. No arbitrary file paths, shell execution, URL downloads, or soundbank installs via MCP.
5. Music logic stays independent of any agent host, the UI, and Unity.

## Project layout on disk

```
RetroMIDI/
  bank-registry.json
  banks/
  projects/<project-id>/
    manifest.json   # bank identity, render profile, version, timestamps
    score.json      # current canonical composition
    brief.json      # composition intent, constraints, locks
    revisions/000001.json ...   # immutable snapshots
    previews/
    exports/
  library.sqlite    # index only, never canonical
```

- Atomic writes: temp sibling file + fsync + replace.
- Schema migrations, corruption detection, backups.
- Never rewrite an existing revision snapshot.

## Concurrency and history

- Every mutation carries `expectedRevision`. Mismatch returns a machine-readable conflict (current revision + retry hint). No last-writer-wins.
- Optional caller `operationId` for idempotency; duplicate requests do not duplicate notes or tracks.
- Revision auto-created before any AI replacement and on explicit save.
- Undo/redo over mutations; restoring an old revision creates a new head (history never deleted).

## Audio

### Realtime transport
- Backend owns musical time; FluidSynth owns voices. Never schedule notes from React timers.
- Play, pause, resume, stop, seek, loop, tempo multiplier (no pitch change).
- Stop/seek: all-notes-off + controller reset; restore program/controller state after seek.
- Playhead pushed to UI over WebSocket; UI lag must not affect audio.

### Offline render
- Shares event compilation and instrument config with realtime; separate synth instance.
- 48 kHz stereo default.
- Render cache key: score content hash, bank SHA-256, synth version + settings, sample rate, tempo override, mute state, effects, region, loop/tail params.
- **Guarantee:** same binary + platform + bank + settings ⇒ byte-identical PCM. No promise across OSes, synth versions, or OGG encodes.

### Loops
1. Straight loop — exact tick range to exact sample boundaries, click-free.
2. Tail-aware loop — wrap/crossfade reverb tails into the start without lengthening.
3. Full song — natural decay tail, no loop.

v1: straight loop + one tested tail strategy, chosen explicitly.

### MIDI export
- Type 1 SMF, default PPQ 960, tempo + meter + key-signature meta, one named track per instrument, program/bank, note on/off, velocity, pan, expression.
- Channel 10 used only when percussion is allowed. "No percussion" ⇒ zero drum events, no melodic track on channel 10.

## Exports (v1)

- Native project bundle (score + brief + bank *reference*, never bank bytes of third-party banks).
- `.mid`, 48 kHz stereo `.wav`, `.ogg` with quality options.
- Export metadata JSON: tempo, key, meter, loop start/end samples, tracks, render settings.
- Missing bank ⇒ explicit error / remap workflow. Never silently substitute presets.

## Default limits

- Single user, local only, Windows first.
- 12 melodic tracks max; percussion channel reserved.
- 8 minutes max song length; 20,000 notes max.
- One global tempo per song in v1 (tempo map = later schema extension).
- Large replace operations bounded and transactional.
- Unknown schema versions rejected.
