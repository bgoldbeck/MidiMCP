"""Canonical score document (schema 1.1.0; 1.0.0 documents load unchanged).

The score is the project's source of truth. Field names serialize as camelCase
to match ``docs/reference/03-score-format.md``. Models enforce per-field
structure; cross-field rules (unique IDs, notes inside the timeline, brief
constraints) live in :mod:`midimcp.validation`.
"""

from __future__ import annotations

import itertools
import re
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from midimcp.music.theory import MODES, normalize_mode, parse_note_name

# 1.1.0 added per-track ``automation`` (expression / vibrato / pitch-bend curves).
SCORE_SCHEMA_VERSION: Final = "1.1.0"
SUPPORTED_SCORE_SCHEMA_VERSIONS: Final = frozenset({"1.0.0", SCORE_SCHEMA_VERSION})

ID_PATTERN: Final = r"^[a-z0-9][a-z0-9_-]{0,63}$"
TRACK_ROLES: Final = (
    "melody",
    "countermelody",
    "accompaniment",
    "bass",
    "pad",
    "percussion",
)
INSTRUMENT_ID_PATTERN: Final = r"^[a-z0-9][a-z0-9_.-]{0,127}$"
_ID_RE: Final = re.compile(ID_PATTERN)

Identifier = Annotated[str, Field(pattern=ID_PATTERN)]
NonNegativeTick = Annotated[int, Field(ge=0)]
PositiveTick = Annotated[int, Field(ge=1)]


def is_valid_identifier(value: str) -> bool:
    return bool(_ID_RE.match(value))


class ScoreModel(BaseModel):
    """Base: camelCase JSON, strict types, unknown fields rejected."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        strict=True,
        extra="forbid",
        validate_assignment=True,
    )

    def to_json_dict(self) -> dict:
        return self.model_dump(mode="json", by_alias=True)


class Note(ScoreModel):
    id: Identifier
    pitch: Annotated[int, Field(ge=0, le=127)]
    start_tick: NonNegativeTick
    duration_ticks: PositiveTick
    velocity: Annotated[int, Field(ge=1, le=127)]

    @property
    def end_tick(self) -> int:
        return self.start_tick + self.duration_ticks


# Automation lanes: JSON name -> (MIDI meaning, lowest value, highest value, resting value).
AUTOMATION_LANES: Final[dict[str, tuple[str, int, int, int]]] = {
    "expression": ("CC11 expression (127 = full volume)", 0, 127, 127),
    "modulation": ("CC1 modulation (vibrato depth, 0 = none)", 0, 127, 0),
    "pitchBend": ("pitch bend (8191 = +2 semitones, -8192 = -2)", -8192, 8191, 0),
}


class ControlPoint(ScoreModel):
    """A controller value that holds from ``tick`` until the next point of its lane."""

    tick: NonNegativeTick
    value: Annotated[int, Field(ge=-8192, le=8191)]


class Automation(ScoreModel):
    """Per-track controller curves (step points; tools add ramps as dense points)."""

    expression: list[ControlPoint] = Field(default_factory=list)
    modulation: list[ControlPoint] = Field(default_factory=list)
    pitch_bend: list[ControlPoint] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ordered_and_in_range(self) -> Automation:
        for lane, points in self.lanes().items():
            _, low, high, _ = AUTOMATION_LANES[lane]
            for point in points:
                if not low <= point.value <= high:
                    raise ValueError(f"{lane} value {point.value} must be {low}..{high}")
            for a, b in itertools.pairwise(points):
                if b.tick <= a.tick:
                    raise ValueError(f"{lane} points must have strictly increasing ticks")
        return self

    def lanes(self) -> dict[str, list[ControlPoint]]:
        return {
            "expression": self.expression,
            "modulation": self.modulation,
            "pitchBend": self.pitch_bend,
        }

    @property
    def is_empty(self) -> bool:
        return not (self.expression or self.modulation or self.pitch_bend)


LANE_FIELDS: Final = {
    "expression": "expression",
    "modulation": "modulation",
    "pitchBend": "pitch_bend",
}


class Track(ScoreModel):
    id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=100)]
    instrument_id: Annotated[str, Field(pattern=INSTRUMENT_ID_PATTERN)]
    is_percussion: bool = False
    gain_db: Annotated[float, Field(ge=-60.0, le=12.0)] = 0.0
    pan: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    mute: bool = False
    role: Literal[TRACK_ROLES] | None = None  # type: ignore[valid-type]
    notes: list[Note] = Field(default_factory=list)
    automation: Automation = Field(default_factory=Automation)


class Meter(ScoreModel):
    numerator: Annotated[int, Field(ge=1, le=32)]
    denominator: Literal[1, 2, 4, 8, 16, 32]


class LoopRegion(ScoreModel):
    enabled: bool = False
    start_tick: NonNegativeTick = 0
    end_tick: NonNegativeTick = 0


class Timeline(ScoreModel):
    ppq: Annotated[int, Field(ge=24, le=15360)] = 960
    tempo_us_per_quarter: Annotated[int, Field(ge=100_000, le=6_000_000)]
    meter: Meter
    total_ticks: PositiveTick
    loop: LoopRegion = Field(default_factory=LoopRegion)


class Tonality(ScoreModel):
    tonic_pitch_class: Annotated[int, Field(ge=0, le=11)]
    mode: Annotated[str, Field(json_schema_extra={"enum": list(MODES)})]
    requested_spelling: str | None = None
    display_spelling: str

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, value: str) -> str:
        if value not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        return value

    @model_validator(mode="after")
    def _spellings_match_tonic(self) -> Tonality:
        for label, spelling in (
            ("displaySpelling", self.display_spelling),
            ("requestedSpelling", self.requested_spelling),
        ):
            if spelling is not None and parse_note_name(spelling) != self.tonic_pitch_class:
                raise ValueError(f"{label} {spelling!r} does not match tonicPitchClass")
        return self


class SoundProfile(ScoreModel):
    profile_id: Annotated[str, Field(min_length=1, max_length=128)]
    bank_id: Annotated[str, Field(min_length=1, max_length=128)]
    bank_sha256: str | None = None


class Metadata(ScoreModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    usage: str | None = None
    originality: Literal["original"] = "original"
    tags: list[str] = Field(default_factory=list)


class Section(ScoreModel):
    id: Identifier
    label: Annotated[str, Field(min_length=1, max_length=50)]
    start_tick: NonNegativeTick
    end_tick: PositiveTick


class HarmonyEvent(ScoreModel):
    start_tick: NonNegativeTick
    duration_ticks: PositiveTick
    symbol: Annotated[str, Field(min_length=1, max_length=20)]
    roman_numeral: str | None = None


class Score(ScoreModel):
    schema_version: str = SCORE_SCHEMA_VERSION
    project_id: Identifier
    revision: Annotated[int, Field(ge=0)] = 0
    metadata: Metadata
    timeline: Timeline
    tonality: Tonality
    sound_profile: SoundProfile
    tracks: list[Track] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    harmony: list[HarmonyEvent] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _supported_version(cls, value: str) -> str:
        if value not in SUPPORTED_SCORE_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported score schemaVersion {value!r}")
        return value

    def track(self, track_id: str) -> Track | None:
        return next((t for t in self.tracks if t.id == track_id), None)


def make_tonality(tonic: str, mode: str) -> Tonality:
    """Build a Tonality from user text such as ``("G#", "ionian")``."""
    from midimcp.music.theory import parse_key

    key = parse_key(tonic, normalize_mode(mode))
    return Tonality(
        tonic_pitch_class=key.tonic_pitch_class,
        mode=key.mode,
        requested_spelling=key.requested_spelling,
        display_spelling=key.display_spelling,
    )
