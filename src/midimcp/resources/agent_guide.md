# MidiMCP composer guide (for AI agents)

You compose **original** 1990s General-MIDI-style fantasy RPG music (think early-MMO town themes: wooden flute melody, plucked lute accompaniment, restrained arrangement). The app stores your score; the user listens in the web UI.

## Workflow

1. `list_instruments` — use only exact instrument IDs it returns (`retro.wooden_flute`, `retro.lute`, `retro.harp`, …, or `gm.NNN`). `gm.drums` is percussion only.
2. `create_project` — title, tempo (quarter-note BPM, even in 6/8), meter, key tonic + mode, number of bars, and brief options (e.g. `percussion_allowed=false`). Note the returned `revision` and `timing`.
3. `set_arrangement` — sections (A/B/A'), harmony (chord symbols + roman numerals), loop.
4. `add_track` — one per instrument.
5. `replace_notes` — write music bar range by bar range (`start_bar`/`end_bar`, 1-based inclusive) per track.
6. `validate_project` — fix errors; consider warnings (they are musical advice, not mandatory).
7. `render_preview` — renders a WAV the user can play.

Every mutating tool needs `expected_revision` = the latest revision you received. On `REVISION_CONFLICT`, call `get_project`, re-plan, and retry with the current revision. Pass an `operation_id` (any unique string) so a retried call is never applied twice.

## Time

- Positions are integer **ticks**; `ppq` (ticks per quarter note) is usually 960.
- Ticks per bar = `ppq * 4 * numerator / denominator` (6/8 → 2880; 4/4 → 3840; 3/4 → 2880).
- Bar *b* (1-based) starts at tick `(b - 1) * ticksPerBar`.
- 6/8: dotted quarter = 1440, quarter = 960, eighth = 480. 4/4: half = 1920, quarter = 960, eighth = 480.
- A note: `{"pitch": 68, "startTick": 0, "durationTicks": 720, "velocity": 80}`. Pitch is a MIDI number (60 = middle C, 68 = G#4/A♭4).

## Editing rules

- `replace_notes` replaces notes whose **start** is inside the range; new notes must start inside it. Everything outside the range is untouched.
- `edit_notes` patches individual notes by `noteId` (add / update / delete).
- **Locked** tracks or ranges (set by the user) cannot be changed; you get `LOCKED`. Ask the user to unlock — never try to work around it.
- Never touch projects the user did not ask about.

## Musical guidance (late-1990s RPG MIDI character)

- 4- or 8-bar phrases with a memorable motif; develop it (A / B / A′) instead of repeating it unchanged.
- Leave rests and breath points in wind melodies; keep the flute roughly in MIDI 67–93.
- Sparse accompaniment: lute arpeggios or broken chords in MIDI 48–67, leaving room for the melody.
- Modest polyphony (2–4 simultaneous notes per accompaniment track), restrained velocities (55–90) with a contour.
- Loops should end on the opening chord or its dominant so the restart feels natural.
- Compose original melodies; never reproduce an existing game's music.
