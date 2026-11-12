# Composing playbook

How we design templates and write songs, collected from the owner's feedback so the ideas are not lost. Read this before you add or rework a template, or write a song. When feedback teaches us something new, add it here in the same PR.

## Owner preferences (hard rules)

- **Nothing shrill.** Every pitched part stays at or below **C6 (MIDI 84)**. Pitches like B-flat 6 on piccolo or high strings, or a flute up near G6, sounded harsh. Drum-kit keys are exempt. Prefer a lower instrument (ocarina or flute, not recorder or piccolo) before squeezing a part into a narrow top range.
- **Never echo a source.** When a template starts from an analysed MIDI file, keep only its style traits: ensemble, texture, feel and tempo range. Then change the **key, the chord loop and usually the meter**. If a section's chords match the source bar for bar, rewrite them. One song ("A Name Not Yet Spoken") sounded too close to its source because it kept the source's loop, its fixed pedal note, its key and its meter all at once.
- **No boring loops.** A bed that repeats the same arpeggio at one volume, with no tune until the middle, is boring. There must be something moving on top from the first bar of the tune.
- **Plucked notes ring.** Guitar, lute and harp notes sound for their real length: each one rings until the same pitch is plucked again or the bar ends, with at most four sounding at once. Short 400-tick plucks sound muted. Pizzicato stays short.
- **Originality.** Never copy or paraphrase a melody from an existing game. Templates describe genre traits only, and songs are always new.

## Template design checklist

Every built-in template should have:

1. **An intro (2–4 bars) before the tune.** The groove, drone or texture plays first and the melody rests. Name the section `Intro`.
2. **Layered sections, not blocks.** Use `layers` so parts `rest`, `enter` or `exit` by section. At least one part enters or leaves mid-section, at bar 2 or later.
3. **A break (4 bars) where the melody rests**, while a countermelody or colour instrument carries a fragment of the hook. The drums often drop out and come back with a fill.
4. **A short turnaround or coda (2 bars)** that leads back into bar 1 of the loop, for example IV–V, bVI–bVII or bVII–bII.
5. **Varied section lengths:** typically 4, 8, 8, 4, 8, 2 bars, about 34–42 bars in all. **No chord held for more than 4 bars** inside a section, or the bed stalls on one note.
6. **One melody part**, with every part's range inside its instrument's range and at or below 84.
7. **Patterns with exact tick positions** (`"name (ticks)"` keys), worked out for that meter's bar length. Cover:
   - a hook rhythm (for example dotted quarter, eighth, two quarters), answered at other pitches instead of repeated;
   - a walking bass that steps into each new chord in the last beat;
   - a fill at the end of every fourth bar;
   - the turnaround.
8. **Dos and don'ts** that state the arrangement:
   - B louder than A, with four-bar swells;
   - two tunes never at the same time;
   - no unison doubling between two leads;
   - the C6 rule;
   - the originality rule.
9. **Expression** guidance: humanize settings per part (seeds differ per part), `shape_expression` for sustained winds and strings, delayed vibrato via modulation on long chip leads, CC64 pedal rules for piano.
10. **Better sounds:**
    - The GM drum kit (`gm.drums`, keys 35–81) with named keys (kick 36, snare 38, hats 42/46, toms 45–50, crash 49, tambourine 54, bongos 60/61, conga 64) instead of the `synth_drum` patch.
    - Colour parts that come and go: music box, celesta, bells, harp, oboe, orchestra hits, taiko, sitar.
    - A second instrument that changes job each section, for example harmony, then an echo an eighth late, then arpeggios.

`tests/test_templates.py::test_refreshed_templates_carry_the_old_realm_lessons` checks the 8-bit, 16-bit and wayfarer families against this list. Old Realm templates are checked by `test_old_realm_forms_are_layered_not_blocks` and `test_old_realm_sections_never_park_on_one_chord`.

## Turning an owner's MIDI into a template

1. **Analyse** the file: tempo, meter, key and mode, instruments and their roles, each part's register, its texture (arpeggio, drone, canon, ostinato), its form and chord loop, and its percussion.
2. **Keep the style, change the material.** Pick a new key, usually a new meter, and a new progression and form, then compare them against the analysis before writing.
3. **Cap registers at C6** and choose parts whose ranges fit.
4. **Write the template** with the checklist above, add its id to `help.html` and add a ROADMAP row.
5. **Record which source produced which template** in the agent's private memory, not the repo, since templates never name their sources.
6. **Make a song from it** to prove it works.

## Writing a song from a template

1. **Create the project** with `create_project(template_id=...)`. Read `sectionPlans`, `harmony` and `partLimits`.
2. **Generate the notes with a script, one function per track,** that follows the chord chart and the layers. Check pitch range, note overlap within each one-voice track, and the song end before pushing. Useful helpers:
   - `ring()` for let-ring plucks;
   - `cap()` to keep at most 4 notes sounding;
   - a diatonic walk into the next root;
   - `swell()` for four-bar dynamics, louder in B.
3. **Push each track** with `replace_notes` over the whole bar range, chaining `expected_revision`.
4. **Humanize** the melody and countermelodies once; chip parts get velocity only. Add `shape_expression` to sustained parts.
5. **Run `validate_project`** and read every warning:
   - `NOTE_OUT_OF_KEY` is fine on borrowed chords (bVI, bVII, bII, harmonic-minor V).
   - Too many chromatic approach notes in the bass sound sour, so walk by scale step.
   - Fix `NOTE_OUTSIDE_INSTRUMENT_RANGE`, `POLYPHONY_EXCEEDED`, `UNISON_OVERLAP`, `BREATH_LENGTH`, `LOOP_ENERGY_JUMP` (fill the last bar) and `MELODY_MASKED` (keep accompaniment under the tune).
6. **Render** with `render_preview` and confirm `clippedSamples` is 0. Tell the owner what it should sound like and what is not yet heard.

**Revisions:** every mutation needs the latest `expected_revision`. On `REVISION_CONFLICT`, call `list_revisions` first: the owner may have changed an instrument or notes in the web UI. Build on their change; never overwrite it.

## Editor lessons (web UI)

- **Octave moves:**
  - Use **Octave down / up** or Shift+↑/↓; they keep the key.
  - "Move semitones" by anything other than ±12 changes the key; a move of −11 left a whole melody out of key.
  - Moves that would leave MIDI 0–127 are refused instead of squashed.
- **Revert must be hard to misuse:**
  - A long dropdown of raw revision summaries let the owner pick revision 1 (the empty song) and wipe every track.
  - The editor now uses **Revert song...**, a panel of plain-language versions, newest first, with "Just before the last change" preselected.
  - A revert is saved as a new revision, so Undo reverses it.
  - The owner wants revert to cover **all tracks at once**, not a single track.
- **When something breaks**, restore the last good revision over MCP. Then re-apply the owner's later choices, such as an instrument change, rather than asking them to dig through history.

## Process

- **Git:** follow the cycle in `CLAUDE.md`.
  - Branch from `origin/main` and push a start commit that sets the ROADMAP row to 🟨.
  - Before pushing, run ruff check, ruff format check and pytest.
  - Open a PR with a full description, merge it, then delete the branch.
- **Deploy:** after every merge, update the NAS (`midclt call cronjob.run 7` over SSH) and wait for the job to reach SUCCESS.
- **Owner feedback:** turn it into a rule here and, where possible, a test (the C6 cap, the source-distance check, the moving top line, the layered-form checks).
