r"""Compose "My Old Realm: Deep Forest Theme" on a running MidiMCP server.

An original 24-bar loop from the "old-realm-forest" template (6/8, 74 BPM,
E dorian): flute theme (A), flute and oboe trading phrases (B), varied return
(A') that leads back to bar 1; rippling harp, soft pad, ringing contrabass.
Then the template's performance advice: humanize + expression on flute and
oboe, light humanize on harp/pad/bass, pad fade-in and easing down in B.
Finally validate and render a preview. Uses only the MCP tools, over HTTP.

Run it inside the MidiMCP container on the NAS (token read from /data/token.txt):

    cd /mnt/POOL/midimcp/src
    sudo docker exec -i $(sudo docker ps -qf name=midimcp) python - \
        < examples/old_realm_deep_forest.py

or from any PC with the `mcp` package installed:

    MIDIMCP_URL=http://NAS:8765 MIDIMCP_TOKEN=... python examples/old_realm_deep_forest.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

URL = os.environ.get("MIDIMCP_URL", "http://127.0.0.1:8765").rstrip("/")
TOKEN = os.environ.get("MIDIMCP_TOKEN") or (
    Path("/data/token.txt").read_text().strip() if Path("/data/token.txt").exists() else ""
)
TITLE = "My Old Realm: Deep Forest Theme"

BAR, E8 = 2880, 480  # 6/8: bar = 6 eighths of 480 ticks

# Note names -> MIDI
N = {
    "E2": 40,
    "F#2": 42,
    "G2": 43,
    "A2": 45,
    "B2": 47,
    "C3": 48,
    "D3": 50,
    "E3": 52,
    "F#3": 54,
    "G3": 55,
    "A3": 57,
    "B3": 59,
    "C#4": 61,
    "C4": 60,
    "D4": 62,
    "E4": 64,
    "F#4": 66,
    "G4": 67,
    "A4": 69,
    "B4": 71,
    "C5": 72,
    "C#5": 73,
    "D5": 74,
    "E5": 76,
    "F#5": 78,
    "G5": 79,
    "A5": 81,
    "B5": 83,
    "A1": 33,
    "B1": 35,
    "C2": 36,
    "D2": 38,
    "G1": 31,
}

# This piece's own chart (set with set_arrangement): one chord per bar.
CHART = [
    "Em",
    "A",
    "Em",
    "D",
    "Em",
    "A",
    "G",
    "D",
    "C",
    "D",
    "Em",
    "A",
    "C",
    "D",
    "Bm",
    "A",
    "Em",
    "A",
    "Em",
    "D",
    "G",
    "A",
    "D",
    "D",
]
CHORDS = {  # (bass root, harp root, third interval, pad voicing)
    "Em": ("E2", "E3", 3, ["E3", "G3", "B3"]),
    "A": ("A1", "A2", 4, ["E3", "A3", "C#4"]),
    "D": ("D2", "D3", 4, ["D3", "F#3", "A3"]),
    "G": ("G1", "G2", 4, ["D3", "G3", "B3"]),
    "C": ("C2", "C3", 4, ["E3", "G3", "C4"]),
    "Bm": ("B1", "B2", 3, ["D3", "F#3", "B3"]),
}


def line(phrases: list[tuple[int, list[tuple]]]) -> list[dict]:
    """(bar, [(eighth offset, length in eighths or ticks, pitch, velocity), ...])."""
    notes = []
    for bar, items in phrases:
        for off, length, pitch, vel in items:
            start = (bar - 1) * BAR + round(off * E8)
            dur = length if length > 50 else round(length * E8)
            notes.append(
                {
                    "pitch": N[pitch] if isinstance(pitch, str) else pitch,
                    "startTick": start,
                    "durationTicks": dur,
                    "velocity": vel,
                }
            )
    return notes


G = 90  # grace-note length in ticks

FLUTE_A = line(
    [
        (1, [(0, 3, "B4", 70), (3, 1, "D5", 74), (4, 2, "E5", 80)]),
        (2, [(0, 2, "F#5", 86), (2, 1, "E5", 80), (3, 3, "C#5", 78)]),  # raised 6th over A
        (
            3,
            [(0, G, "C#5", 64), (G / E8, 4 - G / E8, "B4", 74), (4, 1, "A4", 70), (5, 1, "G4", 68)],
        ),
        (
            4,
            [
                (0, 3, "F#4", 66),
            ],
        ),  # breath
        (5, [(0, 3, "B4", 72), (3, 1, "D5", 76), (4, 2, "E5", 82)]),
        (
            6,
            [(0, 2, "A5", 90), (2, 1, "G5", 84), (3, 2, "F#5", 82), (5, 1, "E5", 78)],
        ),  # leap of a 4th
        (
            7,
            [
                (0, 2, "D5", 78),
                (2, 1, "B4", 72),
                (3, 1, "D5", 74),
                (4, 0.5, "E5", 72),  # turn
                (4.5, 0.5, "D5", 70),
                (5, 1, "C#5", 70),
            ],
        ),
        (8, [(0, 4, "D5", 74)]),  # cadence, rest
    ]
)

FLUTE_B = line(
    [
        (9, [(0, 3, "G5", 80), (3, 1, "A5", 84), (4, 2, "B5", 88)]),  # higher register
        (10, [(0, 5, "A5", 86)]),
        # bars 11-12: flute rests, oboe answers
        (13, [(0, 3, "E5", 78), (3, 3, "G5", 82)]),
        (14, [(0, 2, "F#5", 84), (2, 1, "E5", 78), (3, 2, "D5", 76)]),
        # bar 15: oboe answers; flute re-enters on beat 2
        (15, [(3, 3, "D5", 72)]),
        (16, [(0, 4, "C#5", 74)]),
    ]
)

OBOE_B = line(
    [
        (11, [(0, 2, "B4", 70), (2, 1, "C#5", 72), (3, 3, "D5", 74)]),
        (12, [(0, 4, "C#5", 72)]),
        (15, [(0, 2, "F#4", 66), (2, 1, "A4", 68)]),
        (16, [(0, 3, "A4", 64), (3, 1, "G4", 62), (4, 2, "F#4", 60)]),  # lower than the flute
    ]
)

FLUTE_A2 = line(
    [
        (17, [(0, 3, "B4", 72), (3, 1, "D5", 76), (4, 2, "E5", 82)]),
        (18, [(0, 2, "F#5", 88), (2, 1, "E5", 82), (3, 2, "C#5", 78), (5, 1, "E5", 78)]),
        (
            19,
            [
                (0, 2, "B4", 74),
                (2, 1, "A4", 70),
                (3, 1, "G4", 68),
                (4, 1, "A4", 70),
                (5, 1, "B4", 72),
            ],
        ),
        (20, [(0, 3, "A4", 70), (3, 2, "F#4", 66)]),  # breath
        (21, [(0, 3, "B4", 76), (3, 2, "D5", 80), (5, 1, "G5", 84)]),
        (22, [(0, 3, "E5", 86), (3, 1, "C#5", 78), (4, 2, "E5", 80)]),
        (
            23,
            [(0, G, "G5", 70), (G / E8, 3 - G / E8, "F#5", 84), (3, 1, "E5", 76), (4, 2, "D5", 74)],
        ),
        (24, [(0, 4, "A4", 68)]),  # steps up to bar 1's B4
    ]
)


def harp() -> list[dict]:
    notes = []
    for bar, chord in enumerate(CHART, start=1):
        _, root, third, _ = CHORDS[chord]
        r = N[root]
        ripple = [r, r + 7, r + 12, r + 12 + third, r + 12, r + 7]
        for i, pitch in enumerate(ripple):
            if bar % 4 == 0 and i == 4:
                continue  # sometimes skip a note
            vel = (56 if i == 0 else 48) + (3 if i == 3 else 0)
            start = (bar - 1) * BAR + i * E8
            dur = 600 if i < 5 else E8  # let neighbours overlap slightly, end in the bar
            notes.append(
                {"pitch": pitch, "startTick": start, "durationTicks": dur, "velocity": vel}
            )
    return notes


def pad() -> list[dict]:
    notes = []
    for bar, chord in enumerate(CHART, start=1):
        for name in CHORDS[chord][3]:
            soft = 30 if 9 <= bar <= 16 else 36  # ease down while the winds speak in B
            notes.append(
                {
                    "pitch": N[name],
                    "startTick": (bar - 1) * BAR,
                    "durationTicks": BAR - 60,
                    "velocity": soft,
                }
            )
    return notes


def bass() -> list[dict]:
    notes = []
    for bar in range(1, 25, 2):  # every other bar, let it ring through two bars
        first, second = CHART[bar - 1], CHART[bar]
        root = N[CHORDS[first][0]]
        # Ring two bars only when the next chord shares the root; otherwise one bar.
        length = 2 * BAR - 120 if CHORDS[second][0] == CHORDS[first][0] else BAR - 60
        notes.append(
            {"pitch": root, "startTick": (bar - 1) * BAR, "durationTicks": length, "velocity": 58}
        )
        if length < BAR:
            continue
    for bar in range(2, 25, 2):  # light touch on the even bar when the harmony moved
        if CHORDS[CHART[bar - 1]][0] != CHORDS[CHART[bar - 2]][0]:
            notes.append(
                {
                    "pitch": N[CHORDS[CHART[bar - 1]][0]],
                    "startTick": (bar - 1) * BAR,
                    "durationTicks": BAR - 60,
                    "velocity": 50,
                }
            )
    return notes


class ToolFailed(RuntimeError):
    pass


async def call(client: Client, tool: str, **args):
    result = await client.call_tool(tool, args)
    if result.is_error:
        raise ToolFailed(f"{tool} failed: {result.content[0].text}")
    return result.structured_content


async def main() -> None:
    if not TOKEN:
        raise SystemExit("no token: set MIDIMCP_TOKEN (or run inside the container)")
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {TOKEN}"})
    async with http, Client(streamable_http_client(f"{URL}/mcp", http_client=http)) as c:
        made = await call(c, "create_project", title=TITLE, template_id="old-realm-forest", bars=24)
        pid, rev = made["projectId"], made["revision"]
        print(f"created {pid} (revision {rev})")

        async def step(tool: str, label: str, **args) -> None:
            nonlocal rev
            r = await call(c, tool, project_id=pid, expected_revision=rev, **args)
            rev = r["revision"]
            print(f"  {label:32s} -> revision {rev}")

        # This piece predates the template's layered form (intro, clearing, uneven
        # sections): keep its own A / B / A' plan and bar-by-bar chart.
        await step(
            "set_arrangement",
            "A / B / A' sections and chart",
            sections=[
                {"id": sid, "label": label, "startTick": a * BAR, "endTick": b * BAR}
                for sid, label, a, b in (
                    ("section-a", "A", 0, 8),
                    ("section-b", "B", 8, 16),
                    ("section-ap", "A'", 16, 24),
                )
            ],
            harmony=[
                {"startTick": i * BAR, "durationTicks": BAR, "symbol": symbol}
                for i, symbol in enumerate(CHART)
            ],
        )

        # Notes, section by section and track by track, following the chord chart.
        for first, last, part in ((1, 8, FLUTE_A), (9, 16, FLUTE_B), (17, 24, FLUTE_A2)):
            await step(
                "replace_notes",
                f"flute bars {first}-{last}",
                track_id="flute",
                start_bar=first,
                end_bar=last,
                notes=part,
            )
        await step(
            "replace_notes",
            "oboe answers bars 9-16",
            track_id="oboe",
            start_bar=9,
            end_bar=16,
            notes=OBOE_B,
        )
        await step(
            "replace_notes",
            "harp ripples bars 1-24",
            track_id="harp",
            start_bar=1,
            end_bar=24,
            notes=harp(),
        )
        await step(
            "replace_notes", "pad bars 1-24", track_id="pad", start_bar=1, end_bar=24, notes=pad()
        )
        await step(
            "replace_notes",
            "bass bars 1-24",
            track_id="bass",
            start_bar=1,
            end_bar=24,
            notes=bass(),
        )

        # Performance: the template's Expression advice.
        await step(
            "humanize_notes",
            "flute humanize",
            track_id="flute",
            legato=0.94,
            breath_ticks=240,
            timing_ticks=14,
            seed=3,
        )
        await step(
            "shape_expression",
            "flute expression + vibrato",
            track_id="flute",
            base=85,
            peak=109,
            swell=14,
            vibrato_depth=28,
        )
        await step(
            "humanize_notes",
            "oboe humanize",
            track_id="oboe",
            legato=0.94,
            breath_ticks=240,
            timing_ticks=14,
            seed=5,
        )
        await step(
            "shape_expression",
            "oboe expression (softer)",
            track_id="oboe",
            base=78,
            peak=100,
            swell=12,
            vibrato_depth=24,
        )
        await step(
            "humanize_notes",
            "harp humanize",
            track_id="harp",
            timing_ticks=10,
            phrase_dynamics=4,
            velocity_variation=4,
            seed=7,
        )
        await step(
            "humanize_notes",
            "pad humanize",
            track_id="pad",
            timing_ticks=6,
            phrase_dynamics=0,
            velocity_variation=3,
            seed=9,
        )
        await step(
            "set_automation",
            "pad fade-in bars 1-2",
            track_id="pad",
            lane="expression",
            start_bar=1,
            end_bar=2,
            interpolate=True,
            points=[{"tick": 0, "value": 40}, {"tick": 2 * BAR - 60, "value": 105}],
        )
        await step(
            "set_automation",
            "pad eases down in B",
            track_id="pad",
            lane="expression",
            start_bar=9,
            end_bar=16,
            interpolate=True,
            points=[
                {"tick": 8 * BAR, "value": 105},
                {"tick": 8 * BAR + 960, "value": 85},
                {"tick": 15 * BAR, "value": 85},
                {"tick": 16 * BAR - 60, "value": 105},
            ],
        )
        await step(
            "humanize_notes",
            "bass humanize",
            track_id="bass",
            timing_ticks=4,
            phrase_dynamics=0,
            velocity_variation=3,
            seed=11,
        )

        report = await call(c, "validate_project", project_id=pid)
        codes = sorted({w["code"] for w in report["warnings"]})
        print(f"validate: ok={report['ok']} warnings={codes}")
        print("  (NOTE_OUT_OF_KEY = the C major chord this chart uses in B: intended)")
        preview = await call(c, "render_preview", project_id=pid, wait_seconds=120)
        print(
            f"preview: {preview.get('status')} {preview.get('render', {}).get('durationSeconds')} s"
        )
        print(f'Open the web UI and pick "{TITLE}".')


try:
    asyncio.run(main())
except BaseException as exc:  # unwrap TaskGroup errors into one readable line
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    if isinstance(exc, (ToolFailed, SystemExit)):
        raise SystemExit(f"error: {exc}") from None
    raise SystemExit(
        f"error: {type(exc).__name__}: {exc}\nIs MidiMCP running at {URL}, and is the token right?"
    ) from None
