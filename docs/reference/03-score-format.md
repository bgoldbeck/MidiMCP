# 03 — Score Format and Music Model

## Canonical units

- Positions and durations: **integer ticks**. Default PPQ = 960.
- Tempo: integer **microseconds per quarter note**. BPM is always quarter-note BPM (say so in UI, especially for 6/8).
- Meter: numerator + denominator.
- Ranges: inclusive start, exclusive end (half-open).
- Notes: MIDI pitch 0–127, velocity 1–127, duration > 0 ticks.
- Overlaps allowed (polyphony).
- Event ordering is deterministic: note-off before note-on at same tick/pitch; stable tiebreak by note ID.
- Track ID immutable; display name mutable.

### Worked example: 6/8 at 84 quarter-BPM

- Bar = 3 quarters = 2,880 ticks.
- 32 bars = 92,160 ticks ≈ 68.57 s.
- Tempo multiplier 1.25 ⇒ 80% duration, same pitches.
- 84 BPM ⇒ `tempoUsPerQuarter = 714286`.

## Key and mode

Store: tonic pitch class (0–11), mode ID, requested spelling, practical display spelling.

- "G# Ionian" ⇒ pitch class 8, mode `ionian`, display **A♭ major**.
- Scale pitch classes: 8, 10, 0, 1, 3, 5, 7.
- Mode ≠ progression. Progressions stored separately, e.g. I–vi–IV–V = A♭ / Fm / D♭ / E♭.
- Out-of-key notes are not structural errors; reported as advisory or strict-mode errors per brief.

## Document shape (schema 1.0.0)

```json
{
  "schemaVersion": "1.0.0",
  "projectId": "example-project",
  "revision": 4,
  "metadata": { "title": "Lanterns of the Vale", "usage": "sparkfall.town.day", "originality": "original" },
  "timeline": {
    "ppq": 960,
    "tempoUsPerQuarter": 714286,
    "meter": { "numerator": 6, "denominator": 8 },
    "totalTicks": 92160,
    "loop": { "enabled": true, "startTick": 0, "endTick": 92160 }
  },
  "tonality": { "tonicPitchClass": 8, "mode": "ionian", "requestedSpelling": "G#", "displaySpelling": "Ab" },
  "soundProfile": { "profileId": "retro-gm-1997-v1", "bankId": "retro-gm-default", "bankSha256": "<resolved at install>" },
  "tracks": [
    {
      "id": "flute-1", "name": "Wooden Flute", "instrumentId": "retro.wooden_flute",
      "gainDb": -3.0, "pan": 0.0, "mute": false,
      "notes": [
        { "id": "n1", "pitch": 68, "startTick": 0, "durationTicks": 720, "velocity": 80 }
      ]
    }
  ],
  "sections": [ { "id": "section-a", "label": "A", "startTick": 0, "endTick": 23040 } ],
  "harmony": [ { "startTick": 0, "durationTicks": 2880, "symbol": "Ab", "romanNumeral": "I" } ]
}
```

Future fields (reserve, don't build yet): articulation, controller automation, program changes, tempo map, track roles, humanization seed, regeneration metadata, adaptive stems.

## Brief (`brief.json`) — intent, constraints, locks

- Allowed instrument IDs, max tracks.
- Percussion allowed / forbidden.
- Key/mode, chord plan, tempo/meter, duration range.
- Per-part register and polyphony limits.
- Mood, setting, reference descriptors, loop requirement.
- Harmonic strictness (strict / advisory).
- **Locks:** whole track or disjoint tick ranges. Only an explicit user unlock releases them.

Service rejects prohibited operations; never silently reinterprets them.

## Sound profile

Default profile **Retro GM 1997**: pinned synth settings, friendly aliases ("Wooden Flute", "Lute", "Soft Harp", "Warm Strings").

GM has no dedicated lute program. `retro.lute` may map to a nylon/plucked preset; never claim otherwise.

### Soundbank registry entry
- Stable ID, display name, path (internal or user-imported).
- SHA-256 of bank bytes.
- License, author, provenance, redistribution permission.
- Bank/preset/program mappings and aliases; pitch-range guidance; audition samples.

### Persisted render-affecting settings
FluidSynth version, bank ID + checksum, sample rate (48 kHz), interpolation, gain, polyphony, program/bank assignments, pan, expression, velocity curve, reverb/chorus, output gain/limiter, master trim, tail policy.

New bank or engine version ⇒ new render profile. Never silently change a project's saved sound identity.

## Range replacement semantics

- `replace_notes` replaces notes whose **onset** lies in `[startTick, endTick)`.
- A note already sounding across the start boundary keeps its sustain unless explicitly selected.
- Inserted notes crossing a locked range are rejected.
- Result reports exactly what changed.

## Validation levels

**Hard errors (reject):** bad schema, missing bank, invalid pitch/velocity/time, locked-range change, forbidden percussion, track-count overflow.

**Advisory warnings (report, never auto-fix):** extreme range, excess simultaneous notes, out-of-key pitches when not strict, excessive repetition, voice collisions, abrupt loop harmony, impossible breath lengths for wind parts.
