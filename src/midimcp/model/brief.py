"""Composition brief (schema 1.0.0): intent, constraints, and locks.

Stored beside the score as ``brief.json``. Hard constraints here are enforced by
the validator; locks are enforced by the composition service on mutation.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field, field_validator, model_validator

from midimcp.model.score import (
    INSTRUMENT_ID_PATTERN,
    Identifier,
    NonNegativeTick,
    PositiveTick,
    ScoreModel,
)

BRIEF_SCHEMA_VERSION: Final = "1.0.0"
SUPPORTED_BRIEF_SCHEMA_VERSIONS: Final = frozenset({BRIEF_SCHEMA_VERSION})

MidiPitch = Annotated[int, Field(ge=0, le=127)]


class PartLimits(ScoreModel):
    """Register and polyphony guidance for one track."""

    track_id: Identifier
    lowest_pitch: MidiPitch | None = None
    highest_pitch: MidiPitch | None = None
    max_polyphony: Annotated[int, Field(ge=1, le=32)] | None = None

    @model_validator(mode="after")
    def _ordered(self) -> PartLimits:
        if (
            self.lowest_pitch is not None
            and self.highest_pitch is not None
            and self.lowest_pitch > self.highest_pitch
        ):
            raise ValueError("lowestPitch must be <= highestPitch")
        return self


class Lock(ScoreModel):
    """Protects a whole track (no range) or a half-open tick range of it."""

    id: Identifier
    track_id: Identifier
    start_tick: NonNegativeTick | None = None
    end_tick: PositiveTick | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _range_complete(self) -> Lock:
        if (self.start_tick is None) != (self.end_tick is None):
            raise ValueError("lock needs both startTick and endTick, or neither")
        if (
            self.start_tick is not None
            and self.end_tick is not None
            and self.end_tick <= self.start_tick
        ):
            raise ValueError("lock endTick must be > startTick")
        return self

    @property
    def whole_track(self) -> bool:
        return self.start_tick is None


class DurationRange(ScoreModel):
    min_seconds: Annotated[float, Field(ge=0)] | None = None
    max_seconds: Annotated[float, Field(gt=0)] | None = None


class Brief(ScoreModel):
    schema_version: str = BRIEF_SCHEMA_VERSION
    allowed_instrument_ids: list[Annotated[str, Field(pattern=INSTRUMENT_ID_PATTERN)]] | None = None
    max_tracks: Annotated[int, Field(ge=1, le=12)] | None = None
    percussion_allowed: bool = True
    harmonic_strictness: Literal["strict", "advisory"] = "advisory"
    chord_plan: list[str] = Field(default_factory=list)
    duration: DurationRange | None = None
    part_limits: list[PartLimits] = Field(default_factory=list)
    mood: str | None = None
    setting: str | None = None
    references: list[str] = Field(default_factory=list)
    loop_required: bool = False
    locks: list[Lock] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _supported_version(cls, value: str) -> str:
        if value not in SUPPORTED_BRIEF_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported brief schemaVersion {value!r}")
        return value

    def part_limits_for(self, track_id: str) -> PartLimits | None:
        return next((p for p in self.part_limits if p.track_id == track_id), None)
