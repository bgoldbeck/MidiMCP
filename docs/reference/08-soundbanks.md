# 08 — Soundbanks and License Audit

## Default bank: FluidR3 GM (`fluidr3-gm`)

| Field | Value |
|---|---|
| File | `FluidR3_GM.sf2` (≈148 MB), from Debian/Ubuntu package `fluid-soundfont-gm` |
| Author | Frank Wen and contributors |
| License | **MIT** — "I hereby release Fluid under the MIT license" (package `copyright` file, upstream README) |
| Redistribution / commercial use | Allowed under MIT (keep the copyright notice) |
| Presets | 189, full General MIDI program set in bank 0 plus drum kits (bank 128) |
| SHA-256 (Ubuntu 24.04 package) | `74594e8f4250680adf590507a306655a299935343583256f3b722c48a1bc1cb0` |

Installed into the container image by `apt-get install fluid-soundfont-gm`; the image does not copy the file into the repository.

### Is it "retro" enough?

FluidR3 is a clean general-purpose GM bank, not a vintage sound-card capture. It is the **safe, licensed default** so every feature works out of the box. The 1990s character comes mostly from what we control in the score: GM program choices (`retro.*` aliases), restrained arrangements, modest reverb/chorus. A bank that sounds closer to 1990s sound cards is still an open decision; it needs listening tests by the owner.

## Candidate banks for later (owner listening test + license check before bundling)

| Bank | Notes | Status |
|---|---|---|
| GeneralUser GS (S. Christian Collins) | Small, warm GM/GS bank; its license allows free use in music and redistribution — **verify the current license text before bundling** | Candidate |
| Other community "SC-55-style" banks | Many are built from Roland ROM samples | **Do not bundle.** User-import only, at owner's own discretion |
| Game-extracted banks/ROMs (incl. any Ultima Online assets) | Copyrighted | **Never bundle or distribute** |

## User-imported banks

- Owner copies an `.sf2`/`.sf3` into `/data/banks/` and registers it (web UI, feature 18) with name, license, author, provenance, redistributable flag.
- Imported banks are never included in exported project bundles; bundles carry only the bank ID and SHA-256.
- MCP agents can **list** banks and instruments but cannot install, import or remove them.

## Registry rules (`midimcp.soundbanks`)

- Every bank is identified by ID + SHA-256 of its bytes (hash cached by size/mtime).
- A project pins `soundProfile.bankId` (+ `bankSha256`). If the file is missing (`BANK_UNAVAILABLE`), unknown (`BANK_NOT_FOUND`) or changed (`BANK_CHECKSUM_MISMATCH`), rendering stops with an explicit error. It never silently substitutes another bank.
- Every instrument a score uses must exist as a preset (bank/program) in the bank, otherwise the result is `PRESET_MISSING`. FluidSynth's own fallback-to-piano is never relied on.
