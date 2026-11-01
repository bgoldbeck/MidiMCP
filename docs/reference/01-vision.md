# 01 — Vision and Origin

Source: design conversation (ChatGPT, 2026) between the project owner and an AI assistant. This file is a distilled reference, not a transcript.

## The idea in one sentence

A local app that AI coding agents (Claude, Codex, Antigravity) drive over MCP to compose original, replayable, 1990s-MIDI-style fantasy RPG music — specifically evoking the flute-and-lute character of early Ultima Online — for use in the owner's game **Sparkfall** (Unity).

## Owner's original requirements

- App plays simple note data: "play E, C, B-flat" with selectable instrument styles.
- Old-school sounds are the core motivation: Ultima Online–style flute and lute.
- Interface must be easy to understand.
- **MCP is the main bridge.** The agent writes the music; the app reads it and plays it.
- Songs are **replayable identically every time** — playback reads stored notes and timings, not regenerated audio.
- Natural-language requests such as: *"a song in the style of X, flute + lute, no percussion, this tempo, Ionian, key of G#."*
- User clicks Play in the app. Editable controls, e.g. playback speed.

## Core architectural split

| Role | Who / what | Notes |
|---|---|---|
| Composer | AI agent via MCP | Creates melodies, harmony, arrangement |
| Composition | Structured JSON score | Source of truth: notes, ticks, instruments, key, tempo |
| Instrument engine | FluidSynth + SoundFont (SF2/SF3) | Turns notes into sound |

Same score + different soundbank = same notes, different timbre. No per-note audio files.

## Why the old UO sound is achievable

Early UO music was General MIDI, so its character came from the synth playing it (e.g. Roland SCC-1/Sound Canvas era). A carefully chosen retro GM SoundFont through FluidSynth gets the same *character*. Charm comes from: limited palette, simple arrangements, melodic phrasing, synthetic timbres. Avoid modern cinematic production.

## Decision taken

**Prioritize authentic 1990s General MIDI character** over realistic medieval samples. Bank-switching stays possible but is not the v1 focus.

## Legal/originality guardrails

- Compose original music; never copy recognizable melodies.
- Never bundle game-extracted audio, Roland ROMs, or unknown-license SoundFonts.
- Default bundled bank must pass a license audit (redistribution + commercial use).
