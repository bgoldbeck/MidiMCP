# Natural flute implementation plan

> For agentic workers: use superpowers:subagent-driven-development. Root owns integration, review and commits; workers never spawn or commit. Work in the current checkout and branch.

**Goal:** Add reproducible per-track sampled flute and editable performance controls while preserving portable GM MIDI.
**Architecture:** An allowlisted SFZ registry feeds sfizz stems alongside the existing FluidSynth renderer. Optional track bindings select sources; existing service mutations enforce revisions and locks. The UI exposes source and performance choices.
**Tech stack:** Python/Pydantic/Starlette/MCP, plain JavaScript, sfizz offline renderer, FluidSynth, Docker.
**Spec:** ../specs/2026-11-03-natural-flute-design.md

## Global constraints

- Existing schema 1.0/1.1 scores load; new schema is 1.2.0.
- A binding is `sampler: {patchId, patchSha256} | null`. GM instrument remains the MIDI fallback.
- No silent substitutions, arbitrary caller paths or runtime sample downloads.
- Seeded performance, immutable revisions, server-enforced locks and pinned repeatable rendering.
- Retain notices and provenance; avoid new commercial dependencies.

## Review focus

Missing/changed sample dependencies must invalidate binding/cache; GM-only output stays unchanged; all-sampled songs need no SF2; previews retain earlier controller history; source/performance saves cannot cross songs during navigation.

## Task 1: Editor note-end handle (root)

- [x] Add a failing behavioral test for a distinct resize handle and off-grid end snapping.
- [x] Implement highlight/cursor, preview geometry and absolute end snapping; protect locked notes.
- [x] Focused DOM/model tests and real Edge gesture/undo test.
- [x] Commit after checks and independent review: `5654827`, 395 tests passed/21 environment skips, Edge gesture test passed.

## Task 2: Registry, renderer and deployment (audio worker)

Files: new `src/midimcp/sampler.py`, `render.py`, Dockerfile/docker scripts, audio tests and sample provenance assets only.
Interface: `SamplerRegistry(data_dir)`; `list_patches()` returns JSON dictionaries with `id,name,sha256,available,controllers,description`; `require(patch_id,sha256=None)` returns a descriptor with `path,sha256,id`; errors are explicit. `Renderer(...,samplers=None)` accepts this registry and detects optional `track.sampler`.

- [x] Write and observe failing registry/content-hash and mixed-render tests.
- [x] Add content-addressed allowlisted registry, flute wrapper/provisioning and pinned Linux sfizz build.
- [x] Render sampled tracks separately, mix deterministically, preserve exact ranges and GM-only path; key all dependencies.
- [x] Test focused cases, fresh-process PCM equality and real native sfizz flute/CC response. Root runs container smoke where available.
- [x] Return interface details, evidence and limitations for root review.

## Task 3: Model, service and transport (backend worker)

Files: `model/score.py`, schemas/model schema outputs, `service/composition.py`, `web_api.py`, `mcp_server.py`, `context.py`, backend tests only.
Consume Task 2 registry; expose `ctx.samplers`, wire it to Renderer. `GET /api/sampler-patches` => `{patches:[...]}`. Track PATCH/MCP update accepts optional sampler binding or explicit null. `POST /api/projects/{id}/tracks/{trackId}/performance` accepts `{expectedRevision,startTick?,endTick?,seed?,timingTicks?,velocityVariation?,breathTicks?,base?,peak?,swell?,vibratoDepth?}` and performs humanize + expression in one atomic undoable revision.

- [x] Write failing compatibility, binding validation/reset, lock/conflict and atomic performance tests.
- [x] Add optional typed binding with complete checksum pin; upgrade schema on mutation that introduces it.
- [x] Expose source listing/update/reset in HTTP and MCP using service-only mutation. Performance leaves other tracks/ranges intact; explicit full-track action by default.
- [x] Run focused schema/service/transport tests and return review package.

## Task 4: UI, integration and comparison (root)

Files: `web/app.js`, `api.js`, `editor.js`, CSS/help/README, browser tests and documentation.

- [x] Add API wrappers and tested per-track source selector/reset with unavailable-source explanations.
- [x] Add editable flute performance settings, explicit apply action and editor undo support.
- [x] Show sampler capability and MIDI fallback/legato limitations.
- [x] Integrate workers; independently review every diff, fix focused failures.
- [x] Test browser save/reload/reset/performance/undo, real renders and matched original comparison.
- [x] Run broad relevant suite once at integration, lint/format, commit the significant sampler feature.
- [x] Prepare commits, test evidence and listening comparison for delivery; live deployment follows the owner's standing TrueNAS update authorization.

## Ledger and rulings

- Upstream fetched and current main reconciled: 0 ahead/0 behind before coding.
- Owner explicitly approved the design; global instructions select delegation and current checkout, overriding skill worktree/branch defaults.
- Native registry wrappers and exact slider defaults are implementer decisions; recorded vibrato remains explicitly distinct from controllable vibrato.
- Ruling: conservative source trims of +3 dB controlled/+8 dB recorded, rather than matching a quiet passage at the cost of high-velocity clipping. Native chromatic 60-96, velocity 127, CC11 127 and gain 0 measured peaks 30607/28290, no saturation, with fresh-process equality. Libraries still require explicit track balancing.
- Independent review found two P2s, both fixed with regressions: adjacent-lock controller restoration and direct-export clipping warnings. Final review found no remaining P1/P2.
- Windows broad suite: 422 passed, 21 environment skips. After calibration changes, focused sampler suite including real engines: 29 passed. Both Edge editor and sampler workflow scripts passed.
- Final Linux image smoke: real mixed-engine fresh-process PCM equality, exact speed/region slicing, sample-only rendering without GM, both patches and zero mixer clipping passed. Local Docker HTTP mirror access failed; a temporary HTTPS/trusted-CA build variant enabled validation without changing production image networking. Temporary files are removed before delivery.
- Linux broad suite initially exposed missing Git in the runtime image, a checkout-schema path assumption, and an obsolete single-engine status assertion. Corrected the test-container setup and status test; final Linux suite: **444 passed, 2 browser skips**. Source and test code remained in the existing checkout. Added LF attributes for checksum-pinned SFZ definitions; staged Git blob hashes match their manifest pins.
- Deployment follow-up: the NAS HTTP Ubuntu mirror also failed before publication. Replaced the temporary bootstrap with a production HTTPS base using curl's dated Mozilla CA bundle, verified against its published SHA-256, explicit readable/traversable permissions and Ubuntu's maintained runtime CA package. Real bootstrap image build, `_apt` readability, complete HTTPS apt index update and required package availability checks passed. Partial apt updates now trigger the existing retry loop. Independent build-fix review found no material issues; application code is unchanged.
