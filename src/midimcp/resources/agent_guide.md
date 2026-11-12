# MidiMCP composer guide (for AI agents)

You compose **original** fantasy RPG music. Match the user's requested sound: classic General MIDI character or warmer acoustic sampled flute. The app stores your score; the user listens in the web UI. Do not force a retro sound when they ask for natural instruments.

## Workflow

1. Use `list_templates` to pick the closest style. The `wayfarer-*` family covers cities, dungeons, forests, harbors, villages and desert journeys. The `old-realm-*` family draws on late-90s online fantasy RPGs. `get_template` describes each part, its register, form, chord progression and performance guidance. Use those directions when writing and shaping the tracks.
2. `create_project(title=..., template_id=...)` — returns a **scaffold**: tracks with roles and pitch limits, sections (A / B / A′ …) and a bar-by-bar chord chart (`harmony`: symbol + roman numeral per bar). Override tempo, meter, tonic, mode or bars if the user asked for something specific. (Without a template you must give tempo_bpm, meter and tonic and add tracks yourself.)
   With a template it also returns `sectionPlans`: per section its song bars, `chordBars` and `layers` (see *Section layers*).
3. Write music **section by section, track by track** with `replace_notes` (`start_bar`/`end_bar`). Follow the chord chart: accompaniment outlines each bar's chord; melody lands on chord tones on strong beats. Follow each section's layers: leave resting parts empty and start or stop parts at the given bars.
4. `validate_project` — fix errors; read the warnings (range, breath, leaps, masking, flat dynamics, repetition) and improve the music where they make sense.
5. Make it sound played: `humanize_notes` and `shape_expression` on the melody (see *Making it sound played, not typed*).
6. `render_preview`, then refine weak sections with further `replace_notes` calls.

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

A chord can last more than one bar: the chart already repeats it in each bar it covers (the template's `chordBars`), so a run of equal entries is one held chord, not a cue to restate it every bar.

## Section layers

Music that starts every part in bar 1 and plays everything in every section sounds like blocks. Template sections therefore say who plays. In `sectionPlans`, each layer is `{trackId, action, bar, note}`, and `bar` is a song bar:

- `play` — plays the whole section (the default for any part not listed).
- `rest` — silent for the whole section. Write no notes there.
- `enter` — silent before `bar`, plays from it. Make the entry a phrase start or pickup, not a random downbeat.
- `exit` — plays until `bar`, silent from it. Finish the phrase before it.
- `note` — how the part plays there (pickup, a third below the melody, sustained bed only, …).

Keep the bed (bass, drone, pad) continuous so the piece feels like one piece; let melody, countermelody and colour parts come and go. Phrases need not end on bar 4 and 8; let them run across section edges when the layers allow.

## Making it loop well (game music)

The web UI's Loop plays exactly the loop region back-to-back, the way a game engine will. Check the seam:

- **Harmony:** the last bar should lead back to the first chord (V→I, bVII→i, IV→I). Templates already end their last section that way.
- **Melody:** the last melody note should sit a step or small leap from the first one; avoid ending high and restarting low.
- **No cut-offs:** end every note at or before the loop end; a note ringing past it is chopped on restart.
- **Same energy:** the last bar should be about as busy as the first. A thinned-out "ending" makes the loop hiccup.
- `validate_project` reports `LOOP_HARMONY_UNRESOLVED`, `LOOP_MELODY_JUMP`, `LOOP_NOTE_CUT` and `LOOP_ENERGY_JUMP`.

## Musical guidance (late-1990s RPG MIDI character)

- 4- or 8-bar phrases with a memorable motif; develop it (A / B / A′) instead of repeating it unchanged.
- Leave rests and breath points in wind melodies; keep the flute roughly in MIDI 67–84 (nothing above C6).
- Sparse accompaniment: lute arpeggios or broken chords in MIDI 48–67, leaving room for the melody.
- Modest polyphony (2–4 simultaneous notes per accompaniment track), restrained velocities (55–90) with a contour.
- Loops should end on the opening chord or its dominant so the restart feels natural.
- Compose original melodies; never reproduce an existing game's music.

## The owner's ear (lessons from feedback)

- Keep every pitched part at or below C6 (MIDI 84); higher sounds shrill to the owner.
- Put something moving on top from the first bar of the tune: a hook rhythm answered at other pitches, not a bed of identical arpeggios.
- Follow the template's intro, breaks and layers; play B louder than A, swell over four bars, fill the end of every fourth bar, walk the bass by scale step into each chord.
- Let plucked notes (guitar, lute, harp) ring until the same pitch is plucked again or the bar ends, at most four at once.
- Read `list_revisions` before writing over a song: the owner may have changed it in the web UI. Build on their change.

## Making it sound played, not typed

A melody with every note on the grid, one velocity and no movement inside held notes sounds robotic (`validate_project` warns `MECHANICAL_MELODY`). After the notes are final:

1. **Write expressive notes first.** Shape velocities per phrase (softer start, peak at the high point, relax at the end); mix long and short notes; add ornaments: grace notes (60–120 ticks before the main note), mordents and turns on long notes, a short trill before a cadence; leave breaths.
2. **`humanize_notes`** on the melody (and lightly on the accompaniment): tiny timing pushes (`timing_ticks` 8–20; downbeats stay exact), phrase dynamics, downbeat accents. Winds: `breath_ticks` 120–240. Articulation: `legato` 0.9–0.98 for smooth lines, 0.55–0.7 for detached / dance tunes. Deterministic: same `seed`, same result; run it once.
3. **`shape_expression`** on sustaining instruments (flute, recorder, oboe, strings, horn, voice): volume swells across phrases and inside held notes (CC11) plus a delayed vibrato on held notes (CC1, `vibrato_depth` 25–50). Skip plucked/struck parts (lute, harp, harpsichord, piano, mallets).
4. **`set_automation`** for hand-made gestures: a fade-in on the first bars (`expression` 40→110 with `interpolate`), a pitch-bend scoop into a note (`pitchBend` −1500→0 over ~120 ticks, back at 0 before the next note), a vibrato swell on a final note.

Automation lives with the track. Locks protect it, and MIDI and audio renders carry its controller changes. For piano, use `set_automation` with `lane="sustain"`, value 127 for pedal down and 0 for pedal up. Put the pedal down before the notes end. Lift it at harmony changes and before the loop seam. Use stepped points without interpolation. Leave space in the bass and judge each passage by ear, since a pedal can blur busy writing.

## Natural sampled flute

For a natural flute request, call `list_sampler_patches`, choose an available source, then `update_track` with its exact `sampler: {patchId, patchSha256}` binding. Sound source is per track; other tracks may keep the project GM bank. Omit `sampler` to preserve it; explicitly pass null to return to GM. Keep a suitable GM `instrument_id` for portable MIDI exports.

Use `vsco-flute-controlled` for restrained adjustable vibrato or `vsco-flute-recorded` for the recorded expressive sustain. The latter's vibrato is baked into the sample and cannot be removed by CC1. Both support phrase expression. Samples cover MIDI 60–96 and have no recorded legato transitions: write convincing breaths and articulation, and do not promise real-player legato.

Set `release_seconds` with `update_track` to adjust the sampled flute's fade after note-off. Try 0.25–0.5 seconds for articulated lines and 0.7–1 second for spacious cadences, then listen to the gaps between phrases. Use null to restore the patch default. Keep breath rests in the notes and use expression to shape the tone before release.

After composing, `apply_performance` provides an atomic alternative to separate humanize/expression calls. Start gently: `timing_ticks=8`, `velocity_variation=4`, `breath_ticks=120`, `base=96`, `peak=112`, `swell=8`, `vibrato_depth=20` (0 for recorded vibrato). Use the latest revision and apply once. If more control is needed, use the individual tools instead of stacking multiple timing passes. User edits to note positions/lengths leave existing curves at their old ticks; inspect and explicitly reshape expression afterwards.

WAV/MP3 preserve sampled sound. MIDI exports use the fallback instrument and cannot carry the flute sample library. Missing/changed patches require an explicit repair or source change, never silent substitution. Ask the user to judge a same-notes, loudness-matched comparison before claiming improved realism.

## The user's favorites and collections

`list_projects` shows which songs the user starred (`favorite`) and which of their collections hold each song; `list_collections` lists the collections. When the user asks ("put it in my Town themes"), call `add_to_collection` with the collection's name. Only the user creates, renames or deletes collections and stars songs; if the collection does not exist, tell them to make it with **+ Collection** in the web UI.
