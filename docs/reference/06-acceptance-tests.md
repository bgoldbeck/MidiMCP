# 06 — Acceptance Tests and Definition of Done

## Acceptance matrix

| Test | Expected |
|---|---|
| G# Ionian, 6/8, 84 quarter-BPM | Tonic PC 8, mode ionian, 2,880 ticks/bar |
| 32 bars at that tempo | ≈ 68.57 s before tail |
| Play same revision twice | Same pitches and musical times |
| Offline render twice, same env | Identical decoded PCM bytes |
| Playback 125% | 80% duration, same pitches |
| No percussion requested | No drum track, no ch-10 events, no percussion samples |
| Edit flute bars 9–16 | Notes with onsets outside range and all lute notes unchanged |
| Edit locked melody | Rejected atomically; revision unchanged |
| Stale `expectedRevision` | Conflict error; nothing overwritten |
| Missing soundbank | Explicit error / remap prompt; no silent substitution |
| Change instrument preset | Timing/pitch unchanged; only timbre/mapping differ |
| Stop/seek during sustain | No stuck notes; controllers consistent |
| Loop render | No boundary click; exact loop sample metadata |
| UI + MCP edit simultaneously | One authoritative revision sequence; UI updates |
| Reopen after restart | Same score, bank identity, effects, loop, history |
| Export MIDI then reimport | Timing/pitch/program preserved within MIDI limits |
| Fresh install | Works offline with redistributable default bank |

## v1 definition of done

User can start the app on Windows, connect at least one MCP host, create an original two-instrument 1990s-style song by natural language, see and play it in the GUI, change tempo without pitch shift, make a track/measure-bounded AI revision without touching locked material, save and reopen, render repeatable offline audio, and export MIDI/WAV/OGG with project and loop metadata.

## Engineering rules for implementers

1. Read the design and repo before creating structure.
2. Work in roadmap order; every feature ends with passing tests and a usable slice.
3. No soundbank bundled or installed without license verification.
4. Schema, revision semantics, locks, reproducibility, and MCP behavior are contracts.
5. Write tests before changing transport timing or serialized formats.
6. Document Windows setup/run commands and verify them as actually run.
7. Unsupported features are absent or clearly labeled — no inert controls, no fake-success tools.
8. Music logic independent of agent hosts, UI, and Unity.
9. Working tested MVP beats premature DAW features.

## External references (recheck versions at implementation time)

- MCP spec: https://modelcontextprotocol.io/specification/
- MCP Python SDK: https://py.sdk.modelcontextprotocol.io/
- Claude Code MCP: https://docs.anthropic.com/en/docs/mcp
- Codex MCP: https://learn.chatgpt.com/docs/extend/mcp
- Antigravity MCP: https://antigravity.google/docs/mcp
- FluidSynth docs: https://www.fluidsynth.org/documentation/
- FluidSynth file renderer: https://www.fluidsynth.org/api/group__file__renderer.html
- Mido MIDI files: https://mido.github.io/mido/files/midi.html
