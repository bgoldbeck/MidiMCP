# MidiMCP — Agent Instructions

AI-controlled retro (1990s General MIDI) RPG music composer. Agents compose via MCP; local app validates, plays, exports.

- Design reference: `docs/reference/` (read before structural changes).
- Build order: `docs/ROADMAP.md`. Implement features in order unless the owner says otherwise.

## Git workflow (owner requirement — always follow)

For every feature or change, the agent handles the full cycle without asking:

1. Start from latest `main`: `git fetch origin main && git checkout -B <branch> origin/main`.
2. Branch name describes the feature: `feature/<descriptive-kebab-name>`, `fix/...`, or `docs/...` (use the name listed in `docs/ROADMAP.md` when one exists).
3. **Start commit before any work.** First commit on the branch marks the feature as started — set its `docs/ROADMAP.md` status to 🟨 (or, for work not on the roadmap, an empty commit `git commit --allow-empty -m "Start: <feature>"`) — and push it immediately so the branch is visible on GitHub as in progress.
4. Commit work with clear messages. Before pushing, run `python -m ruff check .`, `python -m ruff format --check .`, and `python -m pytest` locally — all must pass. **No GitHub Actions**: the owner does not use hosted CI; local checks are the merge gate.
5. `git push -u origin <branch>`.
6. Open a PR into `main` with a full description (summary, what changed, how tested, roadmap item).
7. Merge the PR once local checks pass (state the results in the PR's Testing section), then delete the remote branch.
8. Set the feature's status in `docs/ROADMAP.md` to ✅ as part of the feature PR.

## Engineering rules

- Composition service is the only mutation authority; MCP and UI are adapters.
- Integer ticks (PPQ 960), tempo in µs/quarter, half-open ranges.
- Every mutation takes `expectedRevision`; locks enforced server-side; revisions immutable.
- Offline render must be byte-reproducible in a pinned environment.
- Never bundle unlicensed soundbanks or copy existing game melodies.
- No inert UI controls or fake-success MCP tools.
- Tests before changing transport timing or serialized formats.
