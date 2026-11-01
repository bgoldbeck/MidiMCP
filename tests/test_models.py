import json

import pytest
from pydantic import ValidationError

from midimcp.model import Brief, Lock, Score, make_tonality
from midimcp.model.schema import SCHEMA_DIR, render, schema_files


def test_example_score_parses_and_round_trips(score_dict: dict) -> None:
    score = Score.model_validate(score_dict)
    assert score.track("flute-1").notes[0].end_tick == 720
    dumped = score.to_json_dict()
    assert Score.model_validate_json(json.dumps(dumped)) == score
    assert dumped["timeline"]["tempoUsPerQuarter"] == 714286
    assert dumped["tracks"][0]["instrumentId"] == "retro.wooden_flute"


def test_defaults_are_filled(score_dict: dict) -> None:
    score = Score.model_validate(score_dict)
    flute = score.track("flute-1")
    assert flute.pan == 0.0
    assert flute.mute is False
    assert flute.is_percussion is False
    assert score.metadata.originality == "original"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("tracks", 0, "notes", 0, "pitch"), 128),
        (("tracks", 0, "notes", 0, "velocity"), 0),
        (("tracks", 0, "notes", 0, "durationTicks"), 0),
        (("tracks", 0, "notes", 0, "startTick"), -1),
        (("tracks", 0, "notes", 0, "startTick"), 1.5),
        (("timeline", "meter", "denominator"), 3),
        (("tonality", "mode"), "bebop"),
        (("tonality", "displaySpelling"), "A"),
        (("projectId",), "../escape"),
        (("schemaVersion",), "9.9.9"),
        (("tracks", 0, "id"), "Has Spaces"),
    ],
)
def test_invalid_fields_rejected(score_dict: dict, path: tuple, value: object) -> None:
    target = score_dict
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        Score.model_validate(score_dict)


def test_unknown_fields_rejected(score_dict: dict) -> None:
    score_dict["tracks"][0]["notes"][0]["colour"] = "red"
    with pytest.raises(ValidationError):
        Score.model_validate(score_dict)


def test_make_tonality_from_user_text() -> None:
    tonality = make_tonality("G#", "Ionian")
    assert tonality.tonic_pitch_class == 8
    assert tonality.display_spelling == "Ab"
    assert tonality.requested_spelling == "G#"


def test_brief_parses_and_validates_locks() -> None:
    brief = Brief.model_validate(
        {
            "allowedInstrumentIds": ["retro.wooden_flute", "retro.lute"],
            "maxTracks": 2,
            "percussionAllowed": False,
            "harmonicStrictness": "strict",
            "chordPlan": ["I", "vi", "IV", "V"],
            "partLimits": [{"trackId": "flute-1", "lowestPitch": 60, "highestPitch": 96}],
            "locks": [{"id": "lock-1", "trackId": "lute-1"}],
        }
    )
    assert brief.locks[0].whole_track
    with pytest.raises(ValidationError):
        Lock(id="x", track_id="t", start_tick=10)
    with pytest.raises(ValidationError):
        Lock(id="x", track_id="t", start_tick=10, end_tick=10)
    with pytest.raises(ValidationError):
        Brief.model_validate(
            {"partLimits": [{"trackId": "a", "lowestPitch": 80, "highestPitch": 60}]}
        )
    with pytest.raises(ValidationError):
        Brief.model_validate({"maxTracks": 13})


def test_checked_in_json_schemas_are_current() -> None:
    for name, schema in schema_files().items():
        path = SCHEMA_DIR / name
        assert path.exists(), f"missing {path}; run python -m midimcp.model.schema"
        assert path.read_text(encoding="utf-8") == render(schema), (
            f"{name} is stale; run python -m midimcp.model.schema"
        )
