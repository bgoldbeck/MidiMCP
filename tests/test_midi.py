from __future__ import annotations

import io

import mido
import pytest

from midimcp.instruments import (
    UnknownInstrument,
    builtin_instruments,
    instrument_for_program,
    resolve_instrument,
)
from midimcp.midi import (
    MidiImportError,
    cc7_to_gain_db,
    cc10_to_pan,
    export_midi_bytes,
    gain_db_to_cc7,
    import_midi_bytes,
    midi_key_name,
    pan_to_cc10,
    score_to_midi,
)
from midimcp.model import Score
from midimcp.validation import validate_score


@pytest.fixture
def score(score_dict: dict) -> Score:
    return Score.model_validate(score_dict)


def note_tuples(score: Score) -> list[list[tuple[int, int, int, int]]]:
    return [
        sorted((n.pitch, n.start_tick, n.duration_ticks, n.velocity) for n in t.notes)
        for t in score.tracks
    ]


def test_instrument_resolution() -> None:
    flute = resolve_instrument("retro.wooden_flute")
    assert (flute.bank, flute.program, flute.is_percussion) == (0, 73, False)
    assert resolve_instrument("retro.lute").program == 24
    assert resolve_instrument("gm.73").id == "gm.073"
    assert resolve_instrument("gm.drums").is_percussion
    for bad in ("retro.kazoo", "gm.128", "flute"):
        with pytest.raises(UnknownInstrument):
            resolve_instrument(bad)
    assert instrument_for_program(73) == "retro.wooden_flute"
    assert instrument_for_program(3) == "gm.003"
    ids = [i.id for i in builtin_instruments()]
    assert "retro.lute" in ids and "gm.drums" in ids


def test_conversions() -> None:
    assert gain_db_to_cc7(0) == 127
    assert gain_db_to_cc7(-6) == 90
    assert cc7_to_gain_db(90) == pytest.approx(-6, abs=0.1)
    assert pan_to_cc10(0) == 64 and pan_to_cc10(-1) == 1 and pan_to_cc10(1) == 127
    assert cc10_to_pan(64) == 0


@pytest.mark.parametrize(
    ("tonic", "mode", "expected"),
    [(8, "ionian", "Ab"), (8, "aeolian", "G#m"), (2, "dorian", "C"), (10, "aeolian", "Bbm")],
)
def test_key_names(score_dict: dict, tonic: int, mode: str, expected: str) -> None:
    from midimcp.music.theory import practical_tonic_spelling

    score_dict["tonality"] = {
        "tonicPitchClass": tonic,
        "mode": mode,
        "displaySpelling": practical_tonic_spelling(tonic, mode),
    }
    assert midi_key_name(Score.model_validate(score_dict)) == expected


def test_export_structure(score: Score) -> None:
    midi = score_to_midi(score)
    assert midi.type == 1
    assert midi.ticks_per_beat == 960
    assert len(midi.tracks) == 3
    meta = {m.type: m for m in midi.tracks[0]}
    assert meta["set_tempo"].tempo == 714286
    assert (meta["time_signature"].numerator, meta["time_signature"].denominator) == (6, 8)
    assert meta["key_signature"].key == "Ab"
    markers = [m.text for m in midi.tracks[0] if m.type == "marker"]
    assert markers == ["A", "B"]
    flute = midi.tracks[1]
    assert [m.name for m in flute if m.type == "track_name"] == ["Wooden Flute"]
    programs = [(m.channel, m.program) for m in flute if m.type == "program_change"]
    assert programs == [(0, 73)]
    lute_programs = [(m.channel, m.program) for m in midi.tracks[2] if m.type == "program_change"]
    assert lute_programs == [(1, 24)]


def test_no_percussion_never_uses_channel_10(score_dict: dict) -> None:
    for i in range(12):
        score_dict["tracks"].append(
            {
                "id": f"x{i}",
                "name": f"x{i}",
                "instrumentId": "retro.harp",
                "notes": [
                    {
                        "id": f"x{i}n",
                        "pitch": 68,
                        "startTick": 0,
                        "durationTicks": 10,
                        "velocity": 9,
                    }
                ],
            }
        )
    midi = score_to_midi(Score.model_validate(score_dict))
    channels = {m.channel for t in midi.tracks for m in t if hasattr(m, "channel")}
    assert 9 not in channels
    assert len(channels) == 14


def test_percussion_goes_to_channel_10(score_dict: dict) -> None:
    score_dict["tracks"].append(
        {
            "id": "drums",
            "name": "Drums",
            "instrumentId": "gm.drums",
            "isPercussion": True,
            "notes": [
                {"id": "d1", "pitch": 36, "startTick": 0, "durationTicks": 10, "velocity": 99}
            ],
        }
    )
    midi = score_to_midi(Score.model_validate(score_dict))
    drum_channels = {m.channel for m in midi.tracks[3] if hasattr(m, "channel")}
    assert drum_channels == {9}


def test_note_off_before_note_on_at_same_tick(score_dict: dict) -> None:
    score_dict["tracks"][0]["notes"] = [
        {"id": "a", "pitch": 68, "startTick": 0, "durationTicks": 480, "velocity": 70},
        {"id": "b", "pitch": 68, "startTick": 480, "durationTicks": 480, "velocity": 70},
    ]
    events = []
    tick = 0
    for message in score_to_midi(Score.model_validate(score_dict)).tracks[1]:
        tick += message.time
        if message.type in {"note_on", "note_off"}:
            events.append((tick, message.type))
    assert events == [(0, "note_on"), (480, "note_off"), (480, "note_on"), (960, "note_off")]


def test_export_is_deterministic(score: Score) -> None:
    assert export_midi_bytes(score) == export_midi_bytes(score)


def test_muted_tracks_skipped_unless_requested(score_dict: dict) -> None:
    score_dict["tracks"][1]["mute"] = True
    score = Score.model_validate(score_dict)
    assert len(score_to_midi(score).tracks) == 2
    assert len(score_to_midi(score, include_muted=True).tracks) == 3


def test_round_trip_preserves_music(score: Score) -> None:
    data = export_midi_bytes(score)
    back = import_midi_bytes(data, project_id="reimported")
    assert back.metadata.title == "Lanterns of the Vale"
    assert back.timeline.ppq == 960
    assert back.timeline.tempo_us_per_quarter == 714286
    assert (back.timeline.meter.numerator, back.timeline.meter.denominator) == (6, 8)
    assert back.timeline.total_ticks == score.timeline.total_ticks
    assert back.tonality.tonic_pitch_class == 8 and back.tonality.mode == "ionian"
    assert [t.instrument_id for t in back.tracks] == ["retro.wooden_flute", "retro.lute"]
    assert [t.name for t in back.tracks] == ["Wooden Flute", "Medieval Lute"]
    assert note_tuples(back) == note_tuples(score)
    assert back.tracks[0].gain_db == pytest.approx(-3, abs=0.1)
    assert back.tracks[1].pan == pytest.approx(-0.15, abs=0.02)
    assert [(s.label, s.start_tick, s.end_tick) for s in back.sections] == [
        (s.label, s.start_tick, s.end_tick) for s in score.sections
    ]
    assert validate_score(back).ok


def test_import_type0_multichannel() -> None:
    midi = mido.MidiFile(type=0, ticks_per_beat=480)
    track = mido.MidiTrack()
    track += [
        mido.Message("program_change", channel=0, program=73, time=0),
        mido.Message("note_on", channel=0, note=72, velocity=80, time=0),
        mido.Message("note_on", channel=9, note=36, velocity=100, time=0),
        mido.Message("note_off", channel=9, note=36, velocity=0, time=120),
        mido.Message("note_on", channel=0, note=72, velocity=0, time=360),
    ]
    midi.tracks.append(track)
    buffer = io.BytesIO()
    midi.save(file=buffer)
    score = import_midi_bytes(buffer.getvalue(), project_id="t0", title="T0")
    assert score.timeline.tempo_us_per_quarter == 500_000
    assert [(t.instrument_id, t.is_percussion) for t in score.tracks] == [
        ("retro.wooden_flute", False),
        ("gm.drums", True),
    ]
    assert note_tuples(score) == [[(72, 0, 480, 80)], [(36, 0, 120, 100)]]
    assert score.timeline.total_ticks == 1920


def test_import_rejects_garbage() -> None:
    with pytest.raises(MidiImportError):
        import_midi_bytes(b"not midi", project_id="x")
