# Track and phrase editing

The owner approved implementing the full editor proposal with “do all of it.”
Keep the current checkout, branch, plain JavaScript UI, immutable revisions, and
CompositionService as the only mutation authority. No branch creation or remote
publication is part of this work.

## User experience

Add an Edit Notes panel and per-track entry points. Provide a scrollable piano
roll with pitch/time axes, zoom, snap, a playhead, click/Shift-click/marquee
selection, group move, right-edge resize, and keyboard alternatives. A simpler
phrase mode selects a measure range and exposes the same controls.

The inspector edits pitch, start, duration, and velocity. Selected notes or a
whole track can be lengthened without moving starts, or time-stretched around
the first selected note. Preview changes before saving; save each gesture as one
atomic revision. Extensions grow the song to whole bars rather than clipping
notes. Explain any unsynchronized automation instead of silently promising to
stretch expressive controller curves. Selections can be loop-auditioned without
mutating the song loop, or saved as a bar-aligned song loop.

Undo and redo use immutable restore-as-new-head revisions for local note edits.
An external edit invalidates the local redo chain. Locks are explicit user
actions outside that chain: lock a track or passage, list protection, and unlock
only through user endpoints. Existing server lock checks protect source and
destination notes for all clients, including MCP.

Copy an AI refinement prompt containing project, revision, track, selected note
IDs, and exact ticks with instructions to preserve material outside the
selection. The connected agent performs refinement; there is no inert Ask AI
button or new autonomous model service.

## Approach

Extend the existing service/API and ES-module UI. A new editor component owns
selection and interaction; pure model helpers own geometry and transformations.
Use existing revision restoration for note undo. A new framework/DAW dependency
would add a build/deployment step and is unnecessary here. A phrase-only view
would omit the direct editing the user requested, so both views share one model.

## Verification

Meaningful unit tests cover transforms, group boundaries, snapping, selections,
locks, atomic extension, malformed requests, and conflicts. Player tests cover
selected-region playback and switching back to song playback. Browser tests
exercise note selection, edit/save, undo/redo, phrase controls, prompt copying,
lock/unlock, and reload. Broad local Python/lint/Node checks gate the final
local commit. No production songs are changed for testing.
