"""Expression: automation model, humanize, expression curves, service, locks, MIDI, MCP."""

from __future__ import annotations

import asyncio
import io
import itertools
from pathlib import Path

import mido
import pytest
from mcp import Client

from midimcp.context import AppContext
from midimcp.mcp_server import build_mcp_server
from midimcp.midi import export_midi_bytes, import_midi_bytes
from midimcp.model import Brief, Note, Score, Track
from midimcp.model.score import AUTOMATION_LANES, SCORE_SCHEMA_VERSION
from midimcp.music.expression import (
    ExpressionSettings,
    HumanizeSettings,
    collapse,
    expression_curves,
    humanize,
    interpolate,
    noise,
)
from midimcp.service import CompositionService, InvalidOperation, InvalidRange, LockViolation
from midimcp.store import ProjectStore
from midimcp.validation import validate_score
from tests.conftest import lanterns_score_dict
from tests.test_mcp import call, call_error, ctx  # noqa: F401  (ctx is a fixture)

PPQ = 960
BAR = 4 * PPQ
PID = "song"


def grid_melody(bars: int = 8) -> list[dict]:
    """Typed-in melody: quarter notes on the grid, every velocity 80, a held note per 2 bars."""
    pitches = [60, 62, 64, 65, 67, 65, 64, 62]
    notes = []
    for bar in range(bars):
        start = bar * BAR
        if bar % 2:
            notes.append(
                {"pitch": 67, "startTick": start, "durationTicks": 3 * PPQ, "velocity": 80}
            )
            continue
        for beat in range(4):
            pitch = pitches[(bar * 4 + beat) % len(pitches)]
            notes.append(
                {
                    "pitch": pitch,
                    "startTick": start + beat * PPQ,
                    "durationTicks": PPQ,
                    "velocity": 80,
                }
            )
    # Chord under bar 1 beat 2 to check chords move together.
    notes.append({"pitch": 55, "startTick": PPQ, "durationTicks": PPQ, "velocity": 80})
    return notes


@pytest.fixture
def service(tmp_path: Path) -> CompositionService:
    svc = CompositionService(ProjectStore(tmp_path))
    svc.create_project(title="Song", tempo_bpm=96, meter=(4, 4), tonic="C", bars=8, project_id=PID)
    svc.add_track(
        PID,
        expected_revision=1,
        instrument_id="retro.wooden_flute",
        name="Flute",
        track_id="flute",
        role="melody",
    )
    svc.replace_notes(
        PID,
        expected_revision=2,
        track_id="flute",
        start_tick=0,
        end_tick=8 * BAR,
        notes=grid_melody(),
    )
    return svc


def notes_of(svc: CompositionService, track: str = "flute") -> list[Note]:
    return svc.get_project(PID).score.track(track).notes


# ---------------------------------------------------------------- algorithms


def test_noise_is_deterministic_and_bounded() -> None:
    values = [noise(7, f"n{i}", "velocity") for i in range(500)]
    assert values == [noise(7, f"n{i}", "velocity") for i in range(500)]
    assert all(-1 <= v < 1 for v in values)
    assert min(values) < -0.8 and max(values) > 0.8
    assert noise(7, "n1", "velocity") != noise(8, "n1", "velocity")


def test_interpolate_and_collapse() -> None:
    assert interpolate([(0, 0), (240, 120)], 60) == [
        (0, 0),
        (60, 30),
        (120, 60),
        (180, 90),
        (240, 120),
    ]
    assert collapse([(10, 5), (0, 5), (10, 7), (20, 7)]) == [(0, 5), (10, 7)]
    with pytest.raises(ValueError):
        interpolate([(0, 0), (10, 1)], 0)


def model_notes() -> list[Note]:
    return [
        Note(
            id=f"n{i}",
            **{
                "pitch": n["pitch"],
                "start_tick": n["startTick"],
                "duration_ticks": n["durationTicks"],
                "velocity": n["velocity"],
            },
        )
        for i, n in enumerate(grid_melody())
    ]


def run_humanize(notes: list[Note], **settings) -> list[Note]:
    return humanize(
        notes,
        ppq=PPQ,
        bar_ticks=BAR,
        beat_ticks=PPQ,
        start=0,
        end=8 * BAR,
        settings=HumanizeSettings(**settings),
    )


def test_humanize_is_deterministic_and_keeps_pitches_and_downbeats() -> None:
    notes = model_notes()
    first, again = run_humanize(notes), run_humanize(notes)
    assert first == again
    assert first != run_humanize(notes, seed=2)
    by_id = {n.id: n for n in first}
    for old in notes:
        new = by_id[old.id]
        assert new.pitch == old.pitch
        assert new.end_tick <= old.end_tick  # releases never move later
        if old.start_tick % BAR == 0:
            assert new.start_tick == old.start_tick
        assert -0.4 * 12 - 1 <= new.start_tick - old.start_tick <= 12
    assert len({n.velocity for n in first}) >= 6  # no longer flat
    assert any(n.start_tick % 240 for n in first)  # no longer all on the grid
    chord = [n for n in first if n.id in {"n1", f"n{len(notes) - 1}"}]
    assert chord[0].start_tick == chord[1].start_tick  # chord tones move together


@pytest.mark.parametrize("seed", range(1, 30))
def test_humanize_keeps_a_monophonic_line_monophonic(seed: int) -> None:
    line = [n for n in model_notes() if n.pitch != 55]
    out = sorted(run_humanize(line, seed=seed, timing_ticks=40), key=lambda n: n.start_tick)
    for a, b in itertools.pairwise(out):
        assert a.end_tick <= b.start_tick, (a, b)
        assert a.duration_ticks >= 1


def test_humanize_respects_range_legato_and_breath() -> None:
    notes = model_notes()
    out = humanize(
        notes,
        ppq=PPQ,
        bar_ticks=BAR,
        beat_ticks=PPQ,
        start=2 * BAR,
        end=4 * BAR,
        settings=HumanizeSettings(),
    )
    for old, new in zip(notes, out, strict=True):
        if not 2 * BAR <= old.start_tick < 4 * BAR:
            assert new == old
    detached = run_humanize(notes, legato=0.6, timing_ticks=0)
    inner = [n for n in detached if n.start_tick % BAR not in (0, 3 * PPQ) and n.pitch != 55]
    assert inner and all(n.duration_ticks <= 0.62 * PPQ for n in inner)
    breathed = run_humanize(notes, breath_ticks=240, timing_ticks=0)
    held = [n for n in breathed if n.pitch == 67 and n.duration_ticks > PPQ]
    assert all(n.end_tick <= n.start_tick + 3 * PPQ for n in held)
    with pytest.raises(ValueError):
        run_humanize(notes, legato=1.5)


def test_expression_curves_swell_phrases_and_vibrato_on_held_notes() -> None:
    curves = expression_curves(
        model_notes(), ppq=PPQ, start=0, end=8 * BAR, settings=ExpressionSettings()
    )
    expression, modulation = curves["expression"], curves["modulation"]
    assert all(0 <= v <= 127 for _, v in expression + modulation)
    assert all(0 <= t < 8 * BAR for t, _ in expression + modulation)
    assert [t for t, _ in expression] == sorted({t for t, _ in expression})
    assert min(v for _, v in expression) < max(v for _, v in expression)
    # Vibrato only inside held notes (bars 2, 4, 6, 8), never in the quarter-note bars.
    vibrato = [t for t, v in modulation if v > 0]
    assert vibrato and all((t // BAR) % 2 == 1 for t in vibrato)
    assert all(t % BAR >= 240 for t in vibrato)  # delayed start
    no_vib = expression_curves(
        model_notes(), ppq=PPQ, start=0, end=8 * BAR, settings=ExpressionSettings(vibrato_depth=0)
    )
    assert "modulation" not in no_vib


# ------------------------------------------------------------------- model


def test_automation_validation_and_schema_upgrade(service: CompositionService) -> None:
    with pytest.raises(ValueError):
        Track.model_validate(
            {
                "id": "a",
                "name": "A",
                "instrumentId": "retro.lute",
                "automation": {"expression": [{"tick": 5, "value": 9}, {"tick": 5, "value": 10}]},
            }
        )
    with pytest.raises(ValueError):
        Track.model_validate(
            {
                "id": "a",
                "name": "A",
                "instrumentId": "retro.lute",
                "automation": {"modulation": [{"tick": 0, "value": 128}]},
            }
        )
    old = Score.model_validate(lanterns_score_dict())  # a 1.0.0 document still loads
    assert old.schema_version == "1.0.0" and old.tracks[0].automation.is_empty
    assert service.get_project(PID).score.schema_version == SCORE_SCHEMA_VERSION


def test_old_documents_are_upgraded_on_next_change(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    data = lanterns_score_dict()
    store.create_project(Score.model_validate(data), Brief())
    svc = CompositionService(store)
    assert svc.get_project(data["projectId"]).score.schema_version == "1.0.0"
    svc.update_track(
        data["projectId"], expected_revision=1, track_id="flute-1", changes={"gain_db": -4.0}
    )
    assert svc.get_project(data["projectId"]).score.schema_version == SCORE_SCHEMA_VERSION


def test_automation_outside_timeline_is_an_error() -> None:
    data = lanterns_score_dict()
    data["tracks"][0]["automation"] = {"expression": [{"tick": 10**6, "value": 90}]}
    report = validate_score(Score.model_validate(data))
    assert "AUTOMATION_OUTSIDE_TIMELINE" in report.codes()


# ----------------------------------------------------------------- service


def test_mechanical_melody_advisory_clears_after_humanize_and_expression(
    service: CompositionService,
) -> None:
    assert "MECHANICAL_MELODY" in service.validate(PID).codes()
    result = service.humanize_notes(PID, expected_revision=3, track_id="flute")
    assert result.revision == 4
    assert "notes modified" in result.summary.text
    shaped = service.shape_expression(PID, expected_revision=4, track_id="flute")
    assert "expression curve" in shaped.summary.text and "modulation curve" in shaped.summary.text
    track = service.get_project(PID).score.track("flute")
    assert track.automation.expression and track.automation.modulation
    assert "MECHANICAL_MELODY" not in service.validate(PID).codes()


def test_shape_expression_only_replaces_points_in_range(service: CompositionService) -> None:
    service.set_automation(
        PID,
        expected_revision=3,
        track_id="flute",
        lane="expression",
        start_tick=0,
        end_tick=8 * BAR,
        points=[{"tick": 0, "value": 50}, {"tick": 7 * BAR, "value": 70}],
    )
    service.shape_expression(
        PID, expected_revision=4, track_id="flute", start_tick=2 * BAR, end_tick=4 * BAR
    )
    points = service.get_project(PID).score.track("flute").automation.expression
    assert (points[0].tick, points[0].value) == (0, 50)
    assert (points[-1].tick, points[-1].value) == (7 * BAR, 70)
    assert all(p.tick in (0, 7 * BAR) or 2 * BAR <= p.tick < 4 * BAR for p in points)


def test_set_automation_ramps_and_errors(service: CompositionService) -> None:
    service.set_automation(
        PID,
        expected_revision=3,
        track_id="flute",
        lane="pitchBend",
        start_tick=0,
        end_tick=BAR,
        interpolate_ramps=True,
        resolution_ticks=120,
        points=[{"tick": 0, "value": -4096}, {"tick": 480, "value": 0}],
    )
    bend = service.get_project(PID).score.track("flute").automation.pitch_bend
    assert [(p.tick, p.value) for p in bend] == [
        (0, -4096),
        (120, -3072),
        (240, -2048),
        (360, -1024),
        (480, 0),
    ]
    cases = [
        dict(lane="volume", points=[]),
        dict(lane="expression", points=[{"tick": 0, "value": 200}]),
        dict(lane="expression", points=[{"tick": 0, "value": 1}, {"tick": 0, "value": 2}]),
        dict(lane="expression", points=[{"tick": 0, "value": 1.5}]),
    ]
    for case in cases:
        with pytest.raises(InvalidOperation):
            service.set_automation(
                PID, expected_revision=4, track_id="flute", start_tick=0, end_tick=BAR, **case
            )
    with pytest.raises(InvalidRange):
        service.set_automation(
            PID,
            expected_revision=4,
            track_id="flute",
            lane="expression",
            start_tick=0,
            end_tick=BAR,
            points=[{"tick": BAR, "value": 1}],
        )
    with pytest.raises(InvalidOperation):
        service.humanize_notes(
            PID, expected_revision=4, track_id="flute", settings=HumanizeSettings(timing_ticks=999)
        )


def test_locks_protect_automation(service: CompositionService) -> None:
    service.lock(PID, expected_revision=3, track_id="flute", start_tick=0, end_tick=2 * BAR)
    with pytest.raises(LockViolation):
        service.set_automation(
            PID,
            expected_revision=4,
            track_id="flute",
            lane="modulation",
            start_tick=0,
            end_tick=BAR,
            points=[{"tick": 0, "value": 30}],
        )
    # Outside the locked bars is fine.
    service.set_automation(
        PID,
        expected_revision=4,
        track_id="flute",
        lane="modulation",
        start_tick=4 * BAR,
        end_tick=5 * BAR,
        points=[{"tick": 4 * BAR, "value": 30}],
    )
    with pytest.raises(LockViolation):
        service.shape_expression(PID, expected_revision=5, track_id="flute")


# ------------------------------------------------------------------- MIDI


def test_midi_writes_and_reads_automation(service: CompositionService) -> None:
    service.humanize_notes(PID, expected_revision=3, track_id="flute")
    service.shape_expression(PID, expected_revision=4, track_id="flute")
    service.set_automation(
        PID,
        expected_revision=5,
        track_id="flute",
        lane="pitchBend",
        start_tick=0,
        end_tick=BAR,
        points=[{"tick": 0, "value": -2000}, {"tick": 240, "value": 0}],
    )
    score = service.get_project(PID).score
    data = export_midi_bytes(score)
    assert data == export_midi_bytes(score)
    track = mido.MidiFile(file=io.BytesIO(data)).tracks[1]
    tick, order = 0, []
    for message in track:
        tick += message.time
        if tick == 0 and message.type in {"note_on", "pitchwheel"}:
            order.append(message.type)
    assert order == ["pitchwheel", "note_on"]  # bend applies to the note starting there
    imported = import_midi_bytes(data, project_id="copy").tracks[0].automation
    original = service.get_project(PID).score.track("flute").automation
    # Import drops leading points that only repeat the resting value (same sound).
    for lane, points in original.lanes().items():
        rest = AUTOMATION_LANES[lane][3]
        while points and points[0].value == rest:
            points = points[1:]
        assert imported.lanes()[lane] == points, lane
    assert imported.expression and imported.modulation and imported.pitch_bend


def test_tracks_without_automation_export_no_controller_curves(
    service: CompositionService,
) -> None:
    data = export_midi_bytes(service.get_project(PID).score)
    messages = list(mido.MidiFile(file=io.BytesIO(data)).tracks[1])
    controls = [(m.control, m.value) for m in messages if m.type == "control_change"]
    assert controls == [(7, 127), (10, 64), (11, 127)]  # setup only
    assert not any(m.type == "pitchwheel" for m in messages)
    assert import_midi_bytes(data, project_id="copy").tracks[0].automation.is_empty


# -------------------------------------------------------------------- MCP


def test_mcp_expression_tools(ctx: AppContext) -> None:  # noqa: F811
    ctx.service.create_project(
        title="Song", tempo_bpm=96, meter=(4, 4), tonic="C", bars=8, project_id=PID
    )
    ctx.service.add_track(
        PID,
        expected_revision=1,
        instrument_id="retro.wooden_flute",
        name="Flute",
        track_id="flute",
        role="melody",
    )
    ctx.service.replace_notes(
        PID,
        expected_revision=2,
        track_id="flute",
        start_tick=0,
        end_tick=8 * BAR,
        notes=grid_melody(),
    )

    async def go() -> None:
        async with Client(build_mcp_server(ctx)) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            assert {"humanize_notes", "shape_expression", "set_automation"} <= tools
            done = await call(
                client,
                "humanize_notes",
                project_id=PID,
                expected_revision=3,
                track_id="flute",
                start_bar=1,
                end_bar=4,
                legato=0.9,
            )
            assert done["revision"] == 4
            shaped = await call(
                client,
                "shape_expression",
                project_id=PID,
                expected_revision=4,
                track_id="flute",
                vibrato_depth=30,
            )
            assert shaped["revision"] == 5
            drawn = await call(
                client,
                "set_automation",
                project_id=PID,
                expected_revision=5,
                track_id="flute",
                lane="expression",
                start_bar=8,
                end_bar=8,
                interpolate=True,
                points=[{"tick": 7 * BAR, "value": 110}, {"tick": 8 * BAR - 60, "value": 40}],
            )
            assert drawn["revision"] == 6
            error = await call_error(
                client,
                "set_automation",
                project_id=PID,
                expected_revision=6,
                track_id="flute",
                lane="expression",
                start_bar=1,
                end_bar=1,
                points=[{"tick": 5 * BAR, "value": 10}],
            )
            assert error["code"] == "INVALID_RANGE"

    asyncio.run(go())
