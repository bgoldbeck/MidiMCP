from __future__ import annotations

import pytest

from midimcp.model import Brief, Score
from midimcp.validation import (
    MAX_NOTES,
    Severity,
    max_polyphony,
    validate_score,
)
from tests.conftest import BAR


def build(score_dict: dict) -> Score:
    return Score.model_validate(score_dict)


def note(nid: str, pitch: int, start: int, dur: int = 480, vel: int = 70) -> dict:
    return {"id": nid, "pitch": pitch, "startTick": start, "durationTicks": dur, "velocity": vel}


def add_track(score_dict: dict, tid: str, notes: list[dict], **extra: object) -> None:
    score_dict["tracks"].append(
        {"id": tid, "name": tid, "instrumentId": "retro.harp", "notes": notes} | extra
    )


def test_example_score_is_clean(score_dict: dict) -> None:
    report = validate_score(build(score_dict))
    assert report.ok
    assert report.issues == []
    assert report.summary["bars"] == 8
    assert report.summary["noteCount"] == 7
    assert report.summary["durationSeconds"] == pytest.approx(17.143, abs=0.001)


def test_report_serializes(score_dict: dict) -> None:
    score_dict["tracks"][0]["notes"][0]["pitch"] = 69  # A natural: out of Ab major
    data = validate_score(build(score_dict)).to_dict()
    assert data["ok"] is True
    assert data["warnings"][0] == {
        "code": "NOTE_OUT_OF_KEY",
        "severity": "warning",
        "message": "pitch 69 is outside the key",
        "trackId": "flute-1",
        "noteId": "f1",
        "tick": 0,
    }


def test_duplicate_ids(score_dict: dict) -> None:
    score_dict["tracks"][1]["id"] = "flute-1"
    score_dict["tracks"][1]["notes"][0]["id"] = "f1"
    score_dict["sections"][1]["id"] = "section-a"
    report = validate_score(build(score_dict))
    assert {"TRACK_ID_DUPLICATE", "NOTE_ID_DUPLICATE", "SECTION_ID_DUPLICATE"} <= report.codes(
        Severity.ERROR
    )


def test_note_past_end_of_timeline(score_dict: dict) -> None:
    score_dict["tracks"][0]["notes"].append(note("late", 68, 8 * BAR - 100, 200))
    report = validate_score(build(score_dict))
    assert not report.ok
    assert "NOTE_OUTSIDE_TIMELINE" in report.codes(Severity.ERROR)


def test_out_of_key_is_warning_unless_strict(score_dict: dict) -> None:
    score_dict["tracks"][0]["notes"][0]["pitch"] = 69
    score = build(score_dict)
    assert "NOTE_OUT_OF_KEY" in validate_score(score).codes(Severity.WARNING)
    strict = validate_score(score, Brief(harmonic_strictness="strict"))
    assert "NOTE_OUT_OF_KEY" in strict.codes(Severity.ERROR)
    assert not strict.ok
    assert validate_score(score, strict=False).ok


def test_g_sharp_ionian_notes_pass_strict(score_dict: dict) -> None:
    for i, pitch in enumerate([68, 70, 72, 73, 75, 77, 79, 80]):
        score_dict["tracks"][0]["notes"].append(note(f"s{i}", pitch, 2 * BAR + i * 240, 240))
    assert validate_score(build(score_dict), strict=True).ok


def test_percussion_forbidden(score_dict: dict) -> None:
    add_track(score_dict, "drums", [note("d1", 36, 0)], isPercussion=True, instrumentId="gm.drums")
    score = build(score_dict)
    assert validate_score(score).ok
    report = validate_score(score, Brief(percussion_allowed=False))
    assert "PERCUSSION_FORBIDDEN" in report.codes(Severity.ERROR)


def test_percussion_ignores_key(score_dict: dict) -> None:
    add_track(score_dict, "drums", [note("d1", 37, 0)], isPercussion=True, instrumentId="gm.drums")
    assert "NOTE_OUT_OF_KEY" not in validate_score(build(score_dict), strict=True).codes()


def test_instrument_allow_list(score_dict: dict) -> None:
    brief = Brief(allowed_instrument_ids=["retro.wooden_flute"])
    report = validate_score(build(score_dict), brief)
    assert [i.track_id for i in report.errors] == ["lute-1"]
    assert report.errors[0].code == "INSTRUMENT_NOT_ALLOWED"


def test_track_limits(score_dict: dict) -> None:
    assert "BRIEF_MAX_TRACKS_EXCEEDED" in validate_score(
        build(score_dict), Brief(max_tracks=1)
    ).codes(Severity.ERROR)
    for i in range(11):
        add_track(score_dict, f"extra-{i}", [note(f"x{i}", 68, 0)])
    assert "TOO_MANY_TRACKS" in validate_score(build(score_dict)).codes(Severity.ERROR)


def test_note_count_limit(score_dict: dict) -> None:
    score_dict["timeline"]["totalTicks"] = 1_000_000
    score_dict["timeline"]["tempoUsPerQuarter"] = 100_000
    score_dict["timeline"]["loop"]["enabled"] = False
    notes = [note(f"m{i}", 68, i * 48, 48) for i in range(MAX_NOTES + 1)]
    add_track(score_dict, "busy", notes)
    assert "TOO_MANY_NOTES" in validate_score(build(score_dict)).codes(Severity.ERROR)


def test_song_length_limits(score_dict: dict) -> None:
    score_dict["timeline"]["totalTicks"] = 300 * BAR  # ~643 s at 84 BPM
    score_dict["timeline"]["loop"]["enabled"] = False
    assert "SONG_TOO_LONG" in validate_score(build(score_dict)).codes(Severity.ERROR)


def test_brief_duration_range(score_dict: dict) -> None:
    score = build(score_dict)  # ~17.1 s
    brief = Brief.model_validate({"duration": {"minSeconds": 60}})
    assert "DURATION_OUT_OF_RANGE" in validate_score(score, brief).codes(Severity.ERROR)
    brief = Brief.model_validate({"duration": {"minSeconds": 10, "maxSeconds": 20}})
    assert validate_score(score, brief).ok


def test_loop_rules(score_dict: dict) -> None:
    score_dict["timeline"]["loop"] = {"enabled": True, "startTick": 100, "endTick": 100}
    assert "LOOP_INVALID" in validate_score(build(score_dict)).codes(Severity.ERROR)
    score_dict["timeline"]["loop"] = {"enabled": True, "startTick": 0, "endTick": 9 * BAR}
    assert "LOOP_INVALID" in validate_score(build(score_dict)).codes(Severity.ERROR)
    score_dict["timeline"]["loop"] = {"enabled": False, "startTick": 0, "endTick": 0}
    report = validate_score(build(score_dict), Brief(loop_required=True))
    assert "LOOP_REQUIRED" in report.codes(Severity.ERROR)


def test_sections_and_harmony_spans(score_dict: dict) -> None:
    score_dict["sections"][1]["startTick"] = 3 * BAR
    score_dict["harmony"].append({"startTick": 7 * BAR, "durationTicks": 2 * BAR, "symbol": "Eb"})
    codes = validate_score(build(score_dict)).codes(Severity.ERROR)
    assert {"SECTION_OVERLAP", "HARMONY_OUTSIDE_TIMELINE", "HARMONY_OVERLAP"} <= codes


def test_section_ending_before_start(score_dict: dict) -> None:
    score_dict["sections"][0]["endTick"] = 0 + 1
    score_dict["sections"][0]["startTick"] = 5
    assert "SECTION_INVALID" in validate_score(build(score_dict)).codes(Severity.ERROR)


def test_timeline_not_bar_aligned(score_dict: dict) -> None:
    score_dict["timeline"]["totalTicks"] = 8 * BAR + 10
    report = validate_score(build(score_dict))
    assert report.ok
    assert "TIMELINE_NOT_BAR_ALIGNED" in report.codes(Severity.WARNING)


def test_part_limits_register_and_polyphony(score_dict: dict) -> None:
    brief = Brief.model_validate(
        {
            "partLimits": [
                {"trackId": "flute-1", "lowestPitch": 69, "highestPitch": 72},
                {"trackId": "lute-1", "maxPolyphony": 2},
                {"trackId": "ghost", "maxPolyphony": 1},
            ]
        }
    )
    report = validate_score(build(score_dict), brief)
    assert report.ok
    assert {
        "NOTE_BELOW_REGISTER",
        "NOTE_ABOVE_REGISTER",
        "POLYPHONY_EXCEEDED",
        "PART_LIMITS_UNKNOWN_TRACK",
    } <= report.codes(Severity.WARNING)


def test_default_high_polyphony(score_dict: dict) -> None:
    chord = [note(f"c{i}", 56 + i, 0, 960) for i in range(9)]
    add_track(score_dict, "cluster", chord)
    assert "HIGH_POLYPHONY" in validate_score(build(score_dict)).codes(Severity.WARNING)


def test_max_polyphony_note_off_before_note_on(score_dict: dict) -> None:
    score = build(score_dict)
    assert max_polyphony(score.track("lute-1").notes) == (3, 0)
    # Back-to-back notes do not overlap.
    assert max_polyphony(score.track("flute-1").notes)[0] == 1


def test_unison_overlap_and_wide_range(score_dict: dict) -> None:
    score_dict["tracks"][0]["notes"] += [
        note("u1", 70, 1000, 100),  # overlaps f2 (960-1440) on pitch 70
        note("hi", 106, 3 * BAR, 100),  # 106 - 68 = 38 semitones
    ]
    codes = validate_score(build(score_dict)).codes(Severity.WARNING)
    assert {"UNISON_OVERLAP", "WIDE_RANGE"} <= codes


def test_excessive_repetition(score_dict: dict) -> None:
    riff = [note(f"r{b}", 68, b * BAR, 960) for b in range(4)]
    add_track(score_dict, "riff", riff)
    assert "EXCESSIVE_REPETITION" in validate_score(build(score_dict)).codes(Severity.WARNING)
    varied = [dict(n, id=n["id"] + "b") for n in riff]
    varied[2]["pitch"] = 70
    add_track(score_dict, "riff2", varied)
    issues = [
        i for i in validate_score(build(score_dict)).issues if i.code == "EXCESSIVE_REPETITION"
    ]
    assert [i.track_id for i in issues] == ["riff"]


def test_empty_track_warning(score_dict: dict) -> None:
    add_track(score_dict, "silent", [])
    assert "EMPTY_TRACK" in validate_score(build(score_dict)).codes(Severity.WARNING)


def test_loop_harmony(score_dict: dict) -> None:
    score_dict["harmony"][1]["romanNumeral"] = "V"
    score_dict["harmony"][1]["symbol"] = "Eb"
    assert validate_score(build(score_dict)).issues == []
    score_dict["harmony"][1]["romanNumeral"] = "ii"
    score_dict["harmony"][1]["symbol"] = "Bbm"
    assert "LOOP_HARMONY_UNRESOLVED" in validate_score(build(score_dict)).codes(Severity.WARNING)


def test_lock_references(score_dict: dict) -> None:
    brief = Brief.model_validate(
        {
            "locks": [
                {"id": "a", "trackId": "nope"},
                {"id": "b", "trackId": "flute-1", "startTick": 0, "endTick": 99 * BAR},
            ]
        }
    )
    codes = validate_score(build(score_dict), brief).codes(Severity.WARNING)
    assert {"LOCK_UNKNOWN_TRACK", "LOCK_OUTSIDE_TIMELINE"} <= codes


def test_instrument_resolution(score_dict: dict) -> None:
    score_dict["tracks"][0]["instrumentId"] = "retro.kazoo"
    score_dict["tracks"][1]["instrumentId"] = "gm.drums"
    codes = validate_score(build(score_dict)).codes(Severity.ERROR)
    assert {"UNKNOWN_INSTRUMENT", "PERCUSSION_INSTRUMENT_MISMATCH"} <= codes
