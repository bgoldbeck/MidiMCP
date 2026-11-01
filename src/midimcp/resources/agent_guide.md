# MidiMCP composer guide (for AI agents)

You compose **original** 1990s General-MIDI-style fantasy RPG music (think early-MMO town themes: wooden flute melody, plucked lute accompaniment, restrained arrangement). The app stores your score; the user listens in the web UI.

## Workflow

1. `list_templates` → pick the closest style (peaceful-town, forest-exploration, ruined-crypt, tavern, sea-voyage, tense-borderlands). `get_template` gives the full guidance: what each part plays, registers, form, chord progressions, patterns, dos and don'ts.
2. `create_project(title=..., template_id=...)` — returns a **scaffold**: tracks with roles and pitch limits, sections (A / B / A′ …) and a bar-by-bar chord chart (`harmony`: symbol + roman numeral per bar). Override tempo, meter, tonic, mode or bars if the user asked for something specific. (Without a template you must give tempo_bpm, meter and tonic and add tracks yourself.)
3. Write music **section by section, track by track** with `replace_notes` (`start_bar`/`end_bar`). Follow the chord chart: accompaniment outlines each bar's chord; melody lands on chord tones on strong beats.
4. `validate_project` — fix errors; read the warnings (range, breath, leaps, masking, flat dynamics, repetition) and improve the music where they make sense.
5. `render_preview`, then refine weak sections with further `replace_notes` calls.

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

## Reading the chord chart

`harmony` has one entry per bar, e.g. `{"startTick": 23040, "symbol": "Em", "romanNumeral": "vi"}`. Roman numerals count on the tonic's major scale: in minor/modal keys `bIII`, `bVI`, `bVII` are the flattened degrees; upper case = major chord, lower case = minor, `°` = diminished.

## Musical guidance (late-1990s RPG MIDI character)

- 4- or 8-bar phrases with a memorable motif; develop it (A / B / A′) instead of repeating it unchanged.
- Leave rests and breath points in wind melodies; keep the flute roughly in MIDI 67–93.
- Sparse accompaniment: lute arpeggios or broken chords in MIDI 48–67, leaving room for the melody.
- Modest polyphony (2–4 simultaneous notes per accompaniment track), restrained velocities (55–90) with a contour.
- Loops should end on the opening chord or its dominant so the restart feels natural.
- Compose original melodies; never reproduce an existing game's music.
