# Natural flute and note-end resizing

Status: approved by the owner on 2026-11-03. The precisely requested editor gesture is a separate, independently deliverable improvement.

## Intent and approaches

Make MidiMCP capable of warmer acoustic performances, starting with one flute track. The owner accepted the recommended approach: add sfizz sampled instruments alongside FluidSynth, with a source choice per track. Changing General MIDI banks alone leaves the present performance limitations; a commercial plugin host would add substantially more deployment and licensing complexity. Keep FluidSynth and the installed banks available.

## First release

- Each track gains a Sound source selector: Project GM bank, Sampled flute (controllable vibrato), or Sampled flute (recorded vibrato). Retain its existing GM instrument as the MIDI export fallback. Changing that fallback does not silently change its chosen sound source. Reset source is a separate explicit action.
- Use the already auditioned CC0 VSCO Community Edition flute subset, verified against its pinned upstream release. The controllable version wraps the non-vibrato sustain patch with documented expression, delayed CC1 vibrato and a two-semitone pitch-bend range. The recorded-vibrato version clearly states that vibrato is baked into the recording. Do not expose randomized staccato patches until repeatability is proven.
- Add flute performance controls for phrase dynamics, held-note swell, breath spacing and restrained timing/velocity variation. Reuse existing expression/humanize service logic and seeded settings. Applying performance is explicit and undoable, with expected-revision checks and server-enforced locks. Expression can be reapplied after note edits; dragging notes does not silently rewrite existing automation.
- Provide a loudness-matched GeneralUser versus sampled-flute audition of the same original passage, including exposed long notes and transitions. The owner judges the sound; passing render tests is not proof that it sounds natural. These samples have no recorded legato transitions, and the UI/help must say so.

## Saved data and rendering

Add an optional per-track sampler binding containing a registered patch ID and complete-content hash. Introduce score schema 1.2 while loading existing 1.0/1.1 songs unchanged. Older application versions cannot read sampler-enabled scores. Native exports retain the binding; MIDI exports use GM fallback and explain the difference. WAV/MP3 retain the rendered sampled sound.

A dedicated allowlisted patch registry records provenance, license, controller capabilities and hashes of patch definitions, includes, samples and wrapper settings. No arbitrary file paths or download URLs from MCP. Missing or changed assets produce explicit errors without silent substitution.

Keep the existing GM render path unchanged for GM-only songs. For mixed songs, render GM tracks together and each sampled track separately, align stems from song start, then mix and slice. Respect mute, gain, pan, speed, controller history, loops and exact preview ranges. Never apply gain or pan twice. Use a wide accumulator with a documented final saturating conversion; report clipping rather than silently normalize the mix. An entirely sampled song does not require a working SF2 bank.

Cache keys cover source bindings, complete asset hashes, pinned engine identities/settings and mixer version. Two fresh renders must produce identical PCM in the pinned environment. Build the offline sfizz renderer in a pinned Linux container stage, retain required license notices, and provision the licensed flute subset with a verified manifest. No runtime downloads during playback.

## Note-end gesture

Hovering the right end of an editable note highlights a dedicated end handle and shows a horizontal resize cursor. Dragging it extends or shortens the note with live preview, snapping its end to the selected step grid, including initially off-grid notes. The start and pitch stay fixed. Selected notes resize together by the same duration delta; keep all durations positive. Preserve existing lock checks, undo and explicit timeline extension. Short notes retain a usable end target. Cancel restores the original geometry.

## Verification and scope

Test schema compatibility, source persistence/reset, API/MCP parity, conflicts/locks, missing assets, content-hash cache invalidation and portable MIDI fallback. Verify mixed audio alignment, mute/gain/pan, controller response, region/speed/tail and fresh-process determinism. Run a Linux container smoke render and browser checks for source switching and resizing.

The implementer may choose internal module boundaries and exact slider defaults. This release does not include a plugin host, new paid libraries, automatic composition rewrites, reference-MP3 transcription or a full automation-lane editor. Push and live container deployment require the owner's authorization for this update.
