# Track and Phrase Editor Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development. Remain on
> the current checkout and branch. Root owns integration and commits.

**Goal:** Let the owner refine generated tracks directly and protect edits.

**Architecture:** Revision-checked HTTP adapters wrap CompositionService. A
standalone NoteEditor ES module uses pure model transforms and the existing
server-rendered audio player.

**Tech Stack:** Python, Starlette, plain JavaScript ES modules, SVG, Node tests.

**Spec:** ../specs/2026-11-02-note-editor-design.md

## Global constraints

- Preserve user changes and current branch; no branch/worktree creation.
- Service owns mutations; integer ticks, atomic saves, immutable history.
- Lock checks, revision conflicts, and validation remain enforced server-side.
- No inert AI buttons, external dependencies in browser, or inline styles.

## Review focus

- Source/destination locks and invalid multi-note batches must remain atomic.
- Group transforms must preserve relative positions near MIDI/timeline limits.
- External revisions and navigation must not silently restore stale edits.
- Selected playback must re-render the exact tick range and preserve offsets.
- Pointer/keyboard gestures must not edit notes when typing in inspector fields.

## Tasks

- [x] Backend: RED tests for note edit/extension, locks, arrangement, exact tick
  rendering; add thin HTTP routes and optional atomic service extension; GREEN.
  Ownership: web_api.py, service/composition.py, new editor Python tests.
- [x] Editor: RED Node tests for selection/transforms/prompt math; implement
  editor-model.js and editor.js with editor.css; GREEN. Export NoteEditor with
  setView, selectTrack, setPosition, destroy, hasPendingWork.
- [x] Integration: add API wrappers, panel/track entry points, player selected
  region loading; RED/GREEN player tests; preserve own-revision notifications.
- [x] Browser verification: run against seeded local app; exercise editing,
  history, lock controls and conflicts; inspect screenshot; fix failures.
- [x] Review worker diffs and independent final review; run combined lint,
  formatting, Python and Node suites once ready; update roadmap and docs.
- [x] Stage intended files only and create descriptive local feature commit.
