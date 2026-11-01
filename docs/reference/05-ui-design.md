# 05 — UI Design

Target: between a simple MIDI player and a light DAW. Must make sense to someone with no DAW experience.

## Layout

- **Top transport:** Play / Pause / Stop / Loop, playhead, position / total, BPM, tempo multiplier, meter, key, output volume.
- **Left library:** projects, search/tags, soundbanks, instrument browser with single-note audition.
- **Center arrangement:** bar ruler, named tracks, note blocks or compact piano-roll lanes, track colors, zoom/scroll, playhead.
- **Right inspector:** selected track/note/section — instrument, velocity, gain, pan, mute, solo, lock, effects.
- **Bottom panel:** MCP connection health, AI-operation history, validation warnings, export jobs, versions.

## Beginner mode (default)

Open/Create, Play, Stop, Tempo, Loop, Export; track list with mute, volume, instrument picker; measure overview; AI revision status; one obvious **Edit Notes** button into advanced mode.

No inert "Ask AI" button in v1 — composition happens in the user's connected agent; the app shows activity and example prompts.

## Advanced mode

Piano roll (drag pitch/time, resize, velocity), select-and-regenerate measures, chord editor, lock track / lock range, (later) tempo changes and automation.

## Playback-only vs project mutation

| Control | Kind |
|---|---|
| Play / pause / stop / seek | Playback-only |
| Tempo multiplier 50–150% | Playback-only until user applies as project BPM |
| Master volume | Playback-only |
| Mute / solo while auditioning | Playback-only by default; optional save |
| Track instrument | Mutation, revisioned |
| Note move / length / velocity | Mutation, revisioned |
| Loop region | Mutation when saved |
| AI regenerate measures | Mutation after validation, revisioned |
| Undo / restore | New or navigated revision, history kept |

Label preview-only controls. Confirm before discarding unsaved changes.

## Agent-safe editing

- Selections expose exact measure/tick range, track ID, revision (copyable into a prompt).
- Locks visible and enforced by service.
- AI change summary, e.g. "Flute: 12 notes replaced in measures 9–16; lute unchanged."
- Before/after audition of last revision; one-click **Undo last AI change**.
- Preferences persist across restarts.

## Implemented (features 12–13)

Plain ES modules in `src/midimcp/web/` (no React/Vite build; nothing to compile in the image), served at `/ui/`:

- Token login (remembered in localStorage), live connection indicator (WebSocket).
- Library with search; updates live when songs are created or edited.
- Song header with last change (author, time, summary) and revision.
- Transport: play / pause / stop, loop, speed 50–150 % (server re-render, pitch unchanged), volume, bar/beat/time readout.
- Overview: mini piano roll per track with sections, loop region and moving playhead; click to seek.
- Tracks: instrument, volume (dB), mute — each saved as a new revision; locked tracks shown and not editable.
- Checks: validation errors and advisory warnings.
- Download: a prominent **⬇ Download song** button in the song header (format list: MP3 320/192/128 kbps, WAV, MIDI, Project JSON; choice remembered) and a Download card with one button per format. Each click exports the current revision into the project's exports folder and saves it to the computer; earlier files stay listed.
- Live updates: an agent edit reloads the song (or offers "Load new version" while playing).
- Not yet: revision history panel / A-B / undo (feature 14), piano-roll editing and lock controls (feature 16).

## Favorites and collections

The user's own organization of songs, stored in `<data>/collections.json` (format version 1), separate from song content: starring or filing a song creates no revision and never re-renders. Library: ☆/★ per song, filter chips (All / ★ Favorites / each collection with counts), sort (newest, A–Z, favorites first; filter and sort remembered per browser), **+ Collection**, rename/delete for the selected collection (deleting keeps the songs). Song header: ★ toggle and a *Collections* picker with checkboxes and "+ New collection…". Memberships of deleted songs are kept, so restoring from trash restores them. Changes broadcast `library.organized` so other open pages update live. API: `GET|POST /api/collections`, `PATCH|DELETE /api/collections/{id}`, `GET|PUT /api/projects/{id}/organization`. MCP: `list_projects` includes `favorite` and `collections`; `list_collections`; `add_to_collection` (existing collections only — agents cannot create, rename, delete, or star).

## Templates page

Header tab **Templates**: browse built-in and custom templates (ensemble with ranges, form with chord symbols in the default key, melody/accompaniment guidance, patterns, dos and don'ts, a copyable prompt). Built-ins (27: six classic RPG styles, nine `old-realm-*` styles in the spirit of late-90s online fantasy RPGs, twelve `retro-*` game-era styles) are read-only and each lists how to make the parts sound played (*Expression*); **Duplicate** creates a custom copy in `<data>/templates/<id>.json` that can be edited as JSON (validated on save: instruments, chords, ranges, tempo, meter, mode) or deleted. Custom templates are offered to agents through `list_templates` / `create_project(template_id=...)`.

## Help and Setup pages

Public (no token, no data): **Help** (`help.html`) has prompt recipes with Copy buttons; **Setup** (`setup.html`) covers installing on TrueNAS or plain Docker, settings, connecting AI clients, updating, data/backups, the developer environment and checks, building and publishing the image (`publish-image.cmd` / `.sh`), the nightly auto-update, and troubleshooting.
