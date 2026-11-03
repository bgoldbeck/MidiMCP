# Bundled sampler definitions and provisioned audio

VSCO 2 Community Edition, SFZ release 1.1.0:
https://github.com/sgossner/VSCO-2-CE/releases/tag/1.1.0
Pinned Git revision: `28092772094b2d9f1148d84cea97f4545b8c687d`.
Recorded by Sam Gossner and Simon Dalzell; sample cutting by Elan Hickler/Soundemote.
Upstream license: CC0-1.0; full text retained in LICENSE-VSCO.txt and provisioned LICENSE.

The manifest lists all upstream patch/sample dependencies, SHA-256 values, wrapper
files and capabilities. On 2026-11-03, all 36 original files were downloaded from
the pinned upstream raw URLs and verified byte-for-byte against the audition
subset. Only the two sustain patches and their samples are provisioned; randomized
staccato is excluded. No sample audio is stored in the Git checkout or downloaded
at playback. `scripts/provision-samplers.py DEST` downloads and verifies assets at
installation/build time; `--local-source DIR` can provision an offline source copy.
Set MIDIMCP_SAMPLER_DIR to DEST, otherwise assets are sought in DATA_DIR/samplers.

The controllable wrapper adds CC11 expression, +/-2 semitone bend, and CC1 pitch
vibrato at 5.2 Hz, maximum 35 cents, delayed 0.25 s with 0.3 s fade. The recorded
wrapper adds CC11 and bend; its vibrato is part of the waveform. Mapping, velocity
layers, envelope/release and recorded source files are retained. Both patches map
MIDI pitches 60-96; neither contains recorded legato transitions or infinite loops.
A documented `global_volume` source trim adds +3 dB to controlled and +8 dB to
recorded. Conservative trims preserve headroom for full-velocity, gain-0 dB,
CC11=127 monophonic chromatic playing across MIDI 60â€“96, including release overlap.
Both trims are verified by native output RMS ratios, fresh-process equality and
peak tests. Source levels still vary: the original comparison passage at restrained
velocities is quieter than GeneralUser, so track/mix balance remains an explicit
user choice. No velocity compression or automatic note normalization is applied.
`volume` is deliberately unchanged because upstream region values override it.
The source trim is included in each binding hash.
Wrappers use Unix path separators for Linux/Windows portability. Saving a source
pins its full manifest hash (names, per-file hashes, controller/wrapper settings).
The registry rechecks every dependency before every render/cache lookup.

sfizz offline renderer 1.2.3:
https://github.com/sfztools/sfizz/releases/tag/1.2.3
Pinned source commit: `4e70dc0bef53b41f2853ed46e26f5911114c92d0`, with recursive
dependencies pinned by its Gitlinks. Official release source archive SHA-256:
`a9339eac7620d7f0f6b44bdfe860680fab73e66efad4b5f15b21198dd9436822`.
The Docker builder uses the commit and retains upstream/dependency license and
author files under /usr/share/doc/sfizz. sfizz itself is BSD-2-Clause; dependency
notices are preserved with their source directory structure. The render client
statically links sfizz internals and uses the container runtime's C/C++ libraries.

sfizz_render exposes no seed/version option and ignores MIDI channel/program
selection, so each sampled track gets its own process. Settings are explicitly
48 kHz (profile configurable), 256-frame block, quality 8, 256 voices and --use-eot.
Cache identity includes release identity, executable SHA-256, profile, wrapper/sample
identity, score/controller content, range, speed and mixer version. Repeatability
is promised within the pinned image/environment, not across CPUs or platforms.
The two exposed patches use no random SFZ opcodes. Native Windows fresh-process
PCM equality was checked for both patches, plus CC11 RMS, CC1 waveform, CC7 gain
and CC10 pan response. The Linux image also passed real mixed FluidSynth/sfizz
fresh-process PCM equality, exact speed/region slicing, and sampled-only rendering
without an SF2 bank or FluidSynth. Both patch sources were rendered successfully.

GM-only rendering retains its existing code path. Mixed rendering uses one GM
stem and one stem per sampled track, all starting at song tick zero, retaining
prior controllers/notes for region previews. Each engine applies MIDI gain/pan
once. Stems are signed 16-bit stereo PCM; the mixer sums using wide integers,
then saturates once to [-32768,32767], pads short stems, and slices to the exact
requested frame count. `clippedSamples` reports mixer saturation (sample values,
not frames); it cannot count saturation already performed inside an engine.
There is no automatic normalization. The mix clipping count is cached alongside
its WAV and copied into render/export metadata. Tail duration is profile-pinned.
