# Design Reference

Distilled from the original design conversation. Authoritative for implementation; update via PR when decisions change.

| File | Contents |
|---|---|
| [01-vision.md](01-vision.md) | Original idea, owner requirements, sound goal, legal guardrails |
| [02-architecture.md](02-architecture.md) | Stack, process boundary, storage, revisions, audio, exports, limits |
| [03-score-format.md](03-score-format.md) | Ticks/tempo/key model, JSON schema, brief, locks, validation levels |
| [04-mcp-tools.md](04-mcp-tools.md) | MCP tool contract, mutation checks, hosts, demo prompt, music guidance |
| [05-ui-design.md](05-ui-design.md) | Layout, beginner/advanced modes, playback vs mutation controls |
| [06-acceptance-tests.md](06-acceptance-tests.md) | Acceptance matrix, v1 definition of done, implementer rules, links |
| [07-deployment-docker-truenas.md](07-deployment-docker-truenas.md) | **Current platform:** Docker on TrueNAS, web UI, HTTP MCP, data volume, exports, security |
| [08-soundbanks.md](08-soundbanks.md) | Default bank license audit, candidate banks, registry rules |
| [09-composing-playbook.md](09-composing-playbook.md) | Owner preferences, template checklist, MIDI-to-template and song-writing process, editor lessons |

Build order lives in [../ROADMAP.md](../ROADMAP.md).
