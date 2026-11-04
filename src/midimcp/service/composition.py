"""Composition service: the single mutation authority for projects.

The web UI and MCP adapters call this service; nothing else writes projects.
Every mutation:

1. names ``expected_revision`` (stale ⇒ ``RevisionConflict``, nothing written),
2. resolves tracks / notes / ranges (missing ⇒ explicit error),
3. builds the complete new document,
4. rejects any change to locked material (checked on the result, so it holds
   for every operation),
5. validates the whole document (hard errors ⇒ ``ValidationFailed``),
6. commits atomically as a new immutable revision with a change summary.

Optional ``operation_id`` makes a mutation idempotent (safe agent retries).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import ValidationError

from midimcp.model.brief import Brief, Lock
from midimcp.model.score import (
    AUTOMATION_LANES,
    LANE_FIELDS,
    SCORE_SCHEMA_VERSION,
    Automation,
    ControlPoint,
    HarmonyEvent,
    LoopRegion,
    Metadata,
    Meter,
    Note,
    SamplerBinding,
    Score,
    Section,
    SoundProfile,
    Timeline,
    Track,
    is_valid_identifier,
    make_tonality,
)
from midimcp.music.expression import (
    ExpressionSettings,
    HumanizeSettings,
    expression_curves,
    humanize,
    interpolate,
)
from midimcp.music.timing import DEFAULT_PPQ, bpm_to_tempo_us, ticks_per_bar
from midimcp.service.diff import ChangeSummary, check_locks, summarize_changes
from midimcp.service.errors import (
    InvalidOperation,
    InvalidRange,
    NoteNotFound,
    TrackNotFound,
)
from midimcp.store import CommitResult, ProjectSnapshot, ProjectStore
from midimcp.store.errors import RevisionConflict
from midimcp.validation import ValidationReport, validate_score

if TYPE_CHECKING:
    from midimcp.sampler import SamplerRegistry

Author = Literal["user", "agent", "system"]

DEFAULT_PROFILE_ID = "retro-gm-1997-v1"
DEFAULT_BANK_ID = "fluidr3-gm"

_GENERATED_NOTE_ID = re.compile(r"^n(\d+)$")
_TRACK_PROPERTIES = {
    "name",
    "instrument_id",
    "gain_db",
    "pan",
    "mute",
    "is_percussion",
    "role",
    "sampler",
    "release_seconds",
}


@dataclass(frozen=True)
class OperationResult:
    project_id: str
    revision: int
    summary: ChangeSummary | None
    validation: ValidationReport
    replayed: bool = False
    created_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "projectId": self.project_id,
            "revision": self.revision,
            "replayed": self.replayed,
            "changes": self.summary.to_dict() if self.summary else None,
            "createdIds": list(self.created_ids),
            "warnings": [w.to_dict() for w in self.validation.warnings],
            "summary": self.validation.summary,
        }


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:56].strip("-")
    return slug or "song"


class CompositionService:
    def __init__(self, store: ProjectStore, *, samplers: SamplerRegistry | None = None) -> None:
        self.store = store
        self.samplers = samplers

    # ------------------------------------------------------------------ reads

    def get_project(self, project_id: str) -> ProjectSnapshot:
        return self.store.load(project_id)

    def list_projects(self, search: str | None = None) -> list[dict]:
        return [p.to_dict() for p in self.store.list_projects(search)]

    def list_revisions(self, project_id: str) -> list[dict]:
        return [r.to_dict() for r in self.store.list_revisions(project_id)]

    def validate(self, project_id: str, *, strict: bool | None = None) -> ValidationReport:
        snapshot = self.store.load(project_id)
        return validate_score(snapshot.score, snapshot.brief, strict=strict)

    # --------------------------------------------------------------- creation

    def create_project(
        self,
        *,
        title: str,
        tempo_bpm: float,
        meter: tuple[int, int],
        tonic: str,
        mode: str = "ionian",
        bars: int,
        project_id: str | None = None,
        ppq: int = DEFAULT_PPQ,
        usage: str | None = None,
        tags: Sequence[str] = (),
        loop: bool = True,
        profile_id: str = DEFAULT_PROFILE_ID,
        bank_id: str = DEFAULT_BANK_ID,
        bank_sha256: str | None = None,
        brief: Brief | None = None,
        author: Author = "agent",
        operation_id: str | None = None,
        tracks: Sequence[dict[str, Any]] = (),
        sections: Sequence[dict[str, Any]] = (),
        harmony: Sequence[dict[str, Any]] = (),
        summary: str | None = None,
    ) -> OperationResult:
        """Create a project from musical parameters (optionally with a track/form scaffold)."""
        if bars < 1:
            raise InvalidOperation("bars must be >= 1")
        numerator, denominator = meter
        try:
            total = bars * ticks_per_bar(ppq, numerator, denominator)
        except ValueError as exc:
            raise InvalidOperation(str(exc)) from exc
        if project_id is None:
            project_id, replay = self._free_project_id(slugify(title), operation_id)
            if replay is not None:
                return self._result(replay, None)
        elif operation_id is not None and self.store.exists(project_id):
            replay = self.store.find_operation(project_id, operation_id)
            if replay is not None:
                return self._result(replay, None)
        if not is_valid_identifier(project_id):
            raise InvalidOperation(f"invalid project id {project_id!r}")
        score = self._build(
            Score,
            project_id=project_id,
            metadata=Metadata(title=title, usage=usage, tags=list(tags)),
            timeline=Timeline(
                ppq=ppq,
                tempo_us_per_quarter=bpm_to_tempo_us(tempo_bpm),
                meter=Meter(numerator=numerator, denominator=denominator),  # type: ignore[arg-type]
                total_ticks=total,
                loop=LoopRegion(enabled=loop, start_tick=0, end_tick=total if loop else 0),
            ),
            tonality=make_tonality(tonic, mode),
            sound_profile=SoundProfile(
                profile_id=profile_id, bank_id=bank_id, bank_sha256=bank_sha256
            ),
            tracks=[self._build(Track, **t) for t in tracks],
            sections=[self._build(Section, **x) for x in sections],
            harmony=[self._build(HarmonyEvent, **h) for h in harmony],
        )
        for track in score.tracks:
            if track.sampler is not None:
                self._require_sampler(track.sampler)
        result = self.store.create_project(
            score,
            brief or Brief(),
            summary=summary or f"Created project {title!r}",
            author=author,
            operation_id=operation_id,
        )
        return self._result(result, None)

    def create_from_template(
        self,
        *,
        template_id: str,
        title: str,
        tonic: str | None = None,
        mode: str | None = None,
        tempo_bpm: float | None = None,
        meter: tuple[int, int] | None = None,
        bars: int | None = None,
        project_id: str | None = None,
        usage: str | None = None,
        tags: Sequence[str] = (),
        bank_id: str = DEFAULT_BANK_ID,
        bank_sha256: str | None = None,
        brief_overrides: dict[str, Any] | None = None,
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Create a project scaffolded from a composition template (one revision):
        tracks with roles, part limits, sections and a bar-by-bar chord chart."""
        from midimcp.music.theory import parse_key
        from midimcp.templates import TemplateLibrary, build_scaffold, resolve_key

        template = TemplateLibrary(self.store.root).get(template_id)
        tonic_name, mode_name = resolve_key(template, tonic, mode)
        meter = meter or template.meter
        bars = bars or template.form_bars
        if bars < 1:
            raise InvalidOperation("bars must be >= 1")
        scaffold = build_scaffold(
            template,
            tonic_pc=parse_key(tonic_name, mode_name).tonic_pitch_class,
            mode=mode_name,
            meter=meter,
            bars=bars,
        )
        brief_data: dict[str, Any] = {
            "percussionAllowed": template.percussion_allowed,
            "partLimits": scaffold.part_limits,
            "mood": template.mood,
            "setting": template.setting,
            "templateId": template.id,
            "loopRequired": template.loop,
            "chordPlan": [h["romanNumeral"] for h in scaffold.harmony],
        }
        for key, value in (brief_overrides or {}).items():
            brief_data[_camel(key)] = value
        return self.create_project(
            title=title,
            tempo_bpm=tempo_bpm or template.default_tempo,
            meter=meter,
            tonic=tonic_name,
            mode=mode_name,
            bars=bars,
            project_id=project_id,
            usage=usage,
            tags=tags,
            loop=template.loop,
            bank_id=bank_id,
            bank_sha256=bank_sha256,
            brief=self._build(Brief, **brief_data),
            author=author,
            operation_id=operation_id,
            tracks=scaffold.tracks,
            sections=scaffold.sections,
            harmony=scaffold.harmony,
            summary=f"Created {title!r} from template {template.name!r}",
        )

    def _free_project_id(
        self, base: str, operation_id: str | None
    ) -> tuple[str, CommitResult | None]:
        candidate, n = base, 2
        while self.store.exists(candidate):
            if operation_id is not None:
                replay = self.store.find_operation(candidate, operation_id)
                if replay is not None:
                    return candidate, replay
            candidate = f"{base}-{n}"
            n += 1
        return candidate, None

    # ---------------------------------------------------------------- tracks

    def add_track(
        self,
        project_id: str,
        *,
        expected_revision: int,
        instrument_id: str,
        name: str,
        track_id: str | None = None,
        is_percussion: bool = False,
        gain_db: float = 0.0,
        pan: float = 0.0,
        role: str | None = None,
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            new_id = track_id or self._free_track_id(score, slugify(name))
            if score.track(new_id) is not None:
                raise InvalidOperation(f"track {new_id!r} already exists")
            track = self._build(
                Track,
                id=new_id,
                name=name,
                instrument_id=instrument_id,
                is_percussion=is_percussion,
                gain_db=float(gain_db),
                pan=float(pan),
                role=role,
            )
            return _with(score, tracks=[*score.tracks, track]), brief, (new_id,)

        return self._mutate(
            project_id, expected_revision, change, author, operation_id, f"Added track {name!r}"
        )

    def update_track(
        self,
        project_id: str,
        *,
        expected_revision: int,
        track_id: str,
        changes: dict[str, Any],
        allow_instrument: bool = False,
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Change track properties: name, instrument_id, gain_db, pan, mute, is_percussion.

        ``allow_instrument=True`` also adds a new ``instrument_id`` to the brief's
        allowed-instruments list (when the brief has one) in the same revision.
        """
        unknown = set(changes) - _TRACK_PROPERTIES
        if unknown:
            raise InvalidOperation(f"cannot update track fields: {', '.join(sorted(unknown))}")

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            track = _require_track(score, track_id)
            values = {k: float(v) if k in {"gain_db", "pan"} else v for k, v in changes.items()}
            if "sampler" in values and values["sampler"] is None:
                values.setdefault("release_seconds", None)
            updated = self._build(Track, **{**track.model_dump(), **values})
            new_instrument = values.get("instrument_id")
            allowed = brief.allowed_instrument_ids
            if (
                allow_instrument
                and new_instrument
                and allowed is not None
                and new_instrument not in allowed
            ):
                brief = _with(brief, allowed_instrument_ids=[*allowed, new_instrument])
            return _replace_track(score, updated), brief, ()

        return self._mutate(
            project_id,
            expected_revision,
            change,
            author,
            operation_id,
            f"Updated track {track_id!r}",
        )

    RESETTABLE: ClassVar[dict[str, str]] = {  # API field -> track attribute
        "instrument": "instrument_id",
        "volume": "gain_db",
        "pan": "pan",
        "mute": "mute",
        "sampler": "sampler",
    }

    def track_defaults(self, project_id: str) -> dict[str, dict[str, Any]]:
        """Each current track's settings in the revision where it first appeared.

        For a template song that is the template's choice. Revisions are immutable,
        so the answer only grows as tracks are added.
        """
        wanted = {t.id for t in self.store.load(project_id).score.tracks}
        defaults: dict[str, dict[str, Any]] = {}
        for info in self.store.list_revisions(project_id):
            if not wanted - defaults.keys():
                break
            score = self.store.load_revision(project_id, info.revision).score
            for track in score.tracks:
                if track.id in wanted and track.id not in defaults:
                    defaults[track.id] = {
                        "revision": info.revision,
                        "instrumentId": track.instrument_id,
                        "isPercussion": track.is_percussion,
                        "gainDb": track.gain_db,
                        "pan": track.pan,
                        "mute": track.mute,
                        "sampler": track.sampler.to_json_dict() if track.sampler else None,
                    }
        return defaults

    def reset_track(
        self,
        project_id: str,
        *,
        expected_revision: int,
        track_id: str,
        fields: Sequence[str] = ("instrument", "volume", "pan", "mute"),
        author: Author = "user",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Put chosen track settings back to their defaults (see ``track_defaults``)."""
        unknown = set(fields) - self.RESETTABLE.keys()
        if unknown or not fields:
            raise InvalidOperation(
                f"fields must be some of {', '.join(self.RESETTABLE)}; got {sorted(fields)}"
            )
        default = self.track_defaults(project_id).get(track_id)
        if default is None:
            raise TrackNotFound(f"track {track_id!r} not found")
        source = {
            "instrument_id": default["instrumentId"],
            "gain_db": default["gainDb"],
            "pan": default["pan"],
            "mute": default["mute"],
            "sampler": default["sampler"],
        }
        changes = {self.RESETTABLE[f]: source[self.RESETTABLE[f]] for f in fields}
        if "instrument_id" in changes:
            changes["is_percussion"] = default["isPercussion"]
        return self.update_track(
            project_id,
            expected_revision=expected_revision,
            track_id=track_id,
            changes=changes,
            allow_instrument=True,
            author=author,
            operation_id=operation_id,
        )

    def remove_track(
        self,
        project_id: str,
        *,
        expected_revision: int,
        track_id: str,
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            _require_track(score, track_id)
            tracks = [t for t in score.tracks if t.id != track_id]
            return _with(score, tracks=tracks), brief, ()

        return self._mutate(
            project_id,
            expected_revision,
            change,
            author,
            operation_id,
            f"Removed track {track_id!r}",
        )

    # ----------------------------------------------------------------- notes

    def replace_notes(
        self,
        project_id: str,
        *,
        expected_revision: int,
        track_id: str,
        start_tick: int,
        end_tick: int,
        notes: Sequence[dict[str, Any]],
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Replace every note whose onset is in ``[start_tick, end_tick)``.

        Notes that start before the range keep their full sustain. Replacement
        notes must start inside the range; they may ring past ``end_tick``.
        Notes without an ``id`` get a generated one.
        """
        if start_tick < 0 or end_tick <= start_tick:
            raise InvalidRange("range must satisfy 0 <= startTick < endTick")

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            track = _require_track(score, track_id)
            if end_tick > score.timeline.total_ticks:
                raise InvalidRange(f"endTick {end_tick} is past totalTicks")
            ids = _NoteIds(score)
            new_notes = []
            for raw in notes:
                note = self._note(raw, ids)
                if not start_tick <= note.start_tick < end_tick:
                    raise InvalidRange(
                        f"note {note.id!r} starts at {note.start_tick}, outside "
                        f"[{start_tick}, {end_tick})"
                    )
                new_notes.append(note)
            kept = [n for n in track.notes if not start_tick <= n.start_tick < end_tick]
            updated = _with(track, notes=_sorted(kept + new_notes))
            return _replace_track(score, updated), brief, tuple(ids.created)

        return self._mutate(
            project_id,
            expected_revision,
            change,
            author,
            operation_id,
            f"Replaced notes in {track_id!r} [{start_tick}, {end_tick})",
        )

    def edit_notes(
        self,
        project_id: str,
        *,
        expected_revision: int,
        operations: Sequence[dict[str, Any]],
        extend_to_tick: int | None = None,
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Apply note patches atomically, optionally growing to a bar boundary.

        ``extend_to_tick`` never shrinks the timeline. A loop ending at the old
        song end follows growth; a custom loop retains its bounds.

        Each operation is one of::

            {"op": "add", "trackId": ..., "note": {pitch, startTick, durationTicks, velocity}}
            {"op": "update", "noteId": ..., "pitch"?, "startTick"?, "durationTicks"?, "velocity"?}
            {"op": "delete", "noteId": ...}
        """
        if extend_to_tick is not None and (
            isinstance(extend_to_tick, bool)
            or not isinstance(extend_to_tick, int)
            or not 0 <= extend_to_tick <= 1_000_000_000
        ):
            raise InvalidOperation("extendToTick must be an integer in 0..1000000000")
        if not operations:
            raise InvalidOperation("operations must not be empty")

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            timeline = score.timeline
            if extend_to_tick is not None and extend_to_tick > timeline.total_ticks:
                bar = ticks_per_bar(
                    timeline.ppq, timeline.meter.numerator, timeline.meter.denominator
                )
                total = ((extend_to_tick + bar - 1) // bar) * bar
                loop = timeline.loop
                if loop.end_tick == timeline.total_ticks:
                    loop = _with(loop, end_tick=total)
                score = _with(score, timeline=_with(timeline, total_ticks=total, loop=loop))
            # Keep the index synchronized after each operation so later patches
            # see earlier adds/deletes without scanning every note in the song.
            tracks = {t.id: {n.id: n for n in t.notes} for t in score.tracks}
            note_tracks = {n.id: t.id for t in score.tracks for n in t.notes}
            ids = _NoteIds(score)
            for index, op in enumerate(operations):
                kind = op.get("op")
                if kind == "add":
                    track_id = op.get("trackId")
                    if track_id not in tracks:
                        raise TrackNotFound(f"operation {index}: track {track_id!r} not found")
                    note = self._note(op.get("note") or {}, ids)
                    tracks[track_id][note.id] = note
                    note_tracks[note.id] = track_id
                elif kind in {"update", "delete"}:
                    note_id = op.get("noteId")
                    track_id = note_tracks.get(note_id) if isinstance(note_id, str) else None
                    if track_id is None:
                        raise NoteNotFound(f"operation {index}: note {note_id!r} not found")
                    if kind == "delete":
                        del tracks[track_id][note_id]
                        del note_tracks[note_id]
                        continue
                    allowed = {"pitch", "startTick", "durationTicks", "velocity"}
                    extra = set(op) - allowed - {"op", "noteId"}
                    if extra:
                        raise InvalidOperation(
                            f"operation {index}: unknown fields {', '.join(sorted(extra))}"
                        )
                    current = tracks[track_id][note_id].to_json_dict()
                    patch = {k: op[k] for k in allowed if k in op}
                    tracks[track_id][note_id] = self._build(Note, **{**current, **patch})
                else:
                    raise InvalidOperation(f"operation {index}: unknown op {kind!r}")
            new_tracks = [_with(t, notes=_sorted(tracks[t.id].values())) for t in score.tracks]
            return _with(score, tracks=new_tracks), brief, tuple(ids.created)

        return self._mutate(
            project_id,
            expected_revision,
            change,
            author,
            operation_id,
            f"Edited notes ({len(operations)} operations)",
        )

    # ------------------------------------------------------------- expression

    def _require_sampler(self, binding: SamplerBinding) -> None:
        if self.samplers is None:
            raise InvalidOperation(
                "sampled sources are unavailable: no sampler registry configured"
            )
        self.samplers.require(binding.patch_id, binding.patch_sha256)

    def apply_performance(
        self,
        project_id: str,
        *,
        expected_revision: int,
        track_id: str,
        start_tick: int = 0,
        end_tick: int | None = None,
        seed: int = 1,
        timing_ticks: int = 8,
        velocity_variation: int = 4,
        breath_ticks: int = 120,
        base: int = 96,
        peak: int = 112,
        swell: int = 8,
        vibrato_depth: int = 20,
        author: Author = "user",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Apply seeded note performance and expression in one undoable revision."""
        values = (
            seed,
            timing_ticks,
            velocity_variation,
            breath_ticks,
            base,
            peak,
            swell,
            vibrato_depth,
            start_tick,
        )
        if any(type(value) is not int for value in values) or (
            end_tick is not None and type(end_tick) is not int
        ):
            raise InvalidOperation("performance settings and range must be integers")
        human = HumanizeSettings(
            seed=seed,
            timing_ticks=timing_ticks,
            velocity_variation=velocity_variation,
            breath_ticks=breath_ticks,
        )
        expression = ExpressionSettings(
            base=base, peak=peak, swell=swell, vibrato_depth=vibrato_depth
        )
        _check_settings(human)
        _check_settings(expression)

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            track = _require_track(score, track_id)
            lo, hi = _bounded_range(score, start_tick, end_tick)
            timeline = score.timeline
            notes = humanize(
                track.notes,
                ppq=timeline.ppq,
                bar_ticks=ticks_per_bar(
                    timeline.ppq, timeline.meter.numerator, timeline.meter.denominator
                ),
                beat_ticks=_beat_ticks(score),
                start=lo,
                end=hi,
                settings=human,
            )
            # Keep edited onsets inside the selected interval. Releases remain anchored.
            target_ids = {note.id for note in track.notes if lo <= note.start_tick < hi}
            notes = [
                _with(
                    note,
                    start_tick=max(lo, min(hi - 1, note.start_tick)),
                    duration_ticks=max(1, note.end_tick - max(lo, min(hi - 1, note.start_tick))),
                )
                if note.id in target_ids
                else note
                for note in notes
            ]
            curves = expression_curves(
                notes, ppq=timeline.ppq, start=lo, end=hi, settings=expression
            )
            if vibrato_depth == 0:
                curves["modulation"] = [(lo, 0)]
            automation = track.automation
            for lane, points in curves.items():
                automation = _replace_lane(automation, lane, lo, hi, points)
                # Restore the original held value on the final editable tick. This
                # preserves the following range without writing into an adjacent lock.
                original = track.automation.lanes()[lane]
                if hi < timeline.total_ticks and not any(p.tick == hi for p in original):
                    resting = AUTOMATION_LANES[lane][3]
                    held = next((p.value for p in reversed(original) if p.tick <= hi), resting)
                    automation = _replace_lane(automation, lane, hi - 1, hi, [(hi - 1, held)])
            updated = _with(track, notes=_sorted(notes), automation=automation)
            return _replace_track(score, updated), brief, ()

        return self._mutate(
            project_id,
            expected_revision,
            change,
            author,
            operation_id,
            f"Applied performance to {track_id!r}",
        )

    def humanize_notes(
        self,
        project_id: str,
        *,
        expected_revision: int,
        track_id: str,
        start_tick: int = 0,
        end_tick: int | None = None,
        settings: HumanizeSettings | None = None,
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Make notes starting in ``[start_tick, end_tick)`` sound performed, not typed.

        Seeded and deterministic (see :mod:`midimcp.music.expression`): small timing
        pushes, phrase-shaped velocities with metric accents, optional legato and
        breaths. Pitches never change.
        """
        settings = settings or HumanizeSettings()
        _check_settings(settings)

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            track = _require_track(score, track_id)
            lo, hi = _bounded_range(score, start_tick, end_tick)
            t = score.timeline
            notes = humanize(
                track.notes,
                ppq=t.ppq,
                bar_ticks=ticks_per_bar(t.ppq, t.meter.numerator, t.meter.denominator),
                beat_ticks=_beat_ticks(score),
                start=lo,
                end=hi,
                settings=settings,
            )
            return _replace_track(score, _with(track, notes=_sorted(notes))), brief, ()

        return self._mutate(
            project_id,
            expected_revision,
            change,
            author,
            operation_id,
            f"Humanized {track_id!r}",
        )

    def shape_expression(
        self,
        project_id: str,
        *,
        expected_revision: int,
        track_id: str,
        start_tick: int = 0,
        end_tick: int | None = None,
        settings: ExpressionSettings | None = None,
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Write phrase swells (expression) and delayed vibrato on held notes (modulation).

        Replaces the track's expression points, and its modulation points unless
        ``vibrato_depth`` is 0, inside ``[start_tick, end_tick)``.
        """
        settings = settings or ExpressionSettings()
        _check_settings(settings)

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            track = _require_track(score, track_id)
            lo, hi = _bounded_range(score, start_tick, end_tick)
            curves = expression_curves(
                track.notes, ppq=score.timeline.ppq, start=lo, end=hi, settings=settings
            )
            automation = track.automation
            for lane, points in curves.items():
                automation = _replace_lane(automation, lane, lo, hi, points)
            return _replace_track(score, _with(track, automation=automation)), brief, ()

        return self._mutate(
            project_id,
            expected_revision,
            change,
            author,
            operation_id,
            f"Shaped expression of {track_id!r}",
        )

    def set_automation(
        self,
        project_id: str,
        *,
        expected_revision: int,
        track_id: str,
        lane: str,
        start_tick: int,
        end_tick: int,
        points: Sequence[dict[str, Any]],
        interpolate_ramps: bool = False,
        resolution_ticks: int = 60,
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Replace one lane's points inside ``[start_tick, end_tick)``.

        ``points`` are ``{"tick", "value"}``; an empty list clears the range. With
        ``interpolate_ramps`` the points are joined by straight ramps.
        Sustain range edits restore the previous pedal setting at the end boundary.
        """
        if lane not in AUTOMATION_LANES:
            raise InvalidOperation(f"lane must be one of {', '.join(AUTOMATION_LANES)}")
        if start_tick < 0 or end_tick <= start_tick:
            raise InvalidRange("range must satisfy 0 <= startTick < endTick")
        pairs = []
        for index, raw in enumerate(points):
            tick, value = raw.get("tick"), raw.get("value")
            extra = set(raw) - {"tick", "value"}
            if type(tick) is not int or type(value) is not int or extra:
                raise InvalidOperation(f"point {index}: needs integer 'tick' and 'value' only")
            if not start_tick <= tick < end_tick:
                raise InvalidRange(
                    f"point {index}: tick {tick} is outside [{start_tick}, {end_tick})"
                )
            pairs.append((tick, value))
        if len({t for t, _ in pairs}) != len(pairs):
            raise InvalidOperation("two points share a tick")
        if interpolate_ramps:
            if not 10 <= resolution_ticks <= 480:
                raise InvalidOperation("resolutionTicks must be 10-480")
            pairs = interpolate(pairs, resolution_ticks)
        else:
            pairs = sorted(pairs)

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            track = _require_track(score, track_id)
            if end_tick > score.timeline.total_ticks:
                raise InvalidRange(f"endTick {end_tick} is past totalTicks")
            automation = _replace_lane(track.automation, lane, start_tick, end_tick, pairs)
            if lane == "sustain" and end_tick < score.timeline.total_ticks:
                # Range edits must not change the pedal setting in later bars.
                old_value = next(
                    (p.value for p in reversed(track.automation.sustain) if p.tick <= end_tick), 0
                )
                new_value = next(
                    (p.value for p in reversed(automation.sustain) if p.tick <= end_tick), 0
                )
                if old_value != new_value:
                    automation = _replace_lane(
                        automation, lane, end_tick, end_tick + 1, [(end_tick, old_value)]
                    )
            return _replace_track(score, _with(track, automation=automation)), brief, ()

        return self._mutate(
            project_id,
            expected_revision,
            change,
            author,
            operation_id,
            f"Set {lane} of {track_id!r} [{start_tick}, {end_tick})",
        )

    # ------------------------------------------------------------- structure

    def set_arrangement(
        self,
        project_id: str,
        *,
        expected_revision: int,
        sections: Sequence[dict[str, Any]] | None = None,
        harmony: Sequence[dict[str, Any]] | None = None,
        bars: int | None = None,
        loop: dict[str, Any] | None = None,
        loop_enabled: bool | None = None,
        loop_start_bar: int | None = None,
        loop_end_bar: int | None = None,
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Replace form, resize the song, or set the loop.

        Bar loop fields are one-based inclusive and converted after the revision
        guard using this score's meter. They cannot combine with ``loop``.
        """
        bar_loop = any(v is not None for v in (loop_enabled, loop_start_bar, loop_end_bar))
        if loop is not None and bar_loop:
            raise InvalidOperation("give loop or loop bar fields, not both")
        for name, value in (
            ("bars", bars),
            ("loopStartBar", loop_start_bar),
            ("loopEndBar", loop_end_bar),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100_000
            ):
                raise InvalidOperation(f"{name} must be an integer in 1..100000")
        if loop_enabled is not None and not isinstance(loop_enabled, bool):
            raise InvalidOperation("loopEnabled must be a boolean")
        if sections is None and harmony is None and bars is None and loop is None and not bar_loop:
            raise InvalidOperation("nothing to change")

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            updates: dict[str, Any] = {}
            if sections is not None:
                updates["sections"] = [self._build(Section, **s) for s in sections]
            if harmony is not None:
                updates["harmony"] = [self._build(HarmonyEvent, **h) for h in harmony]
            timeline = score.timeline
            if bars is not None:
                if bars < 1:
                    raise InvalidOperation("bars must be >= 1")
                t = score.timeline
                total = bars * ticks_per_bar(t.ppq, t.meter.numerator, t.meter.denominator)
                old_loop = timeline.loop
                if old_loop.end_tick == timeline.total_ticks:
                    old_loop = _with(old_loop, end_tick=total)
                timeline = _with(timeline, total_ticks=total, loop=old_loop)
            if loop is not None:
                timeline = _with(timeline, loop=self._build(LoopRegion, **loop))
            if bar_loop:
                bar = ticks_per_bar(
                    timeline.ppq, timeline.meter.numerator, timeline.meter.denominator
                )
                current_loop = timeline.loop
                start = (
                    (loop_start_bar - 1) * bar
                    if loop_start_bar is not None
                    else current_loop.start_tick
                )
                end = (
                    loop_end_bar * bar
                    if loop_end_bar is not None
                    else current_loop.end_tick or timeline.total_ticks
                )
                if not 0 <= start < end <= timeline.total_ticks:
                    raise InvalidRange("loop bars must define a nonempty range within the song")
                timeline = _with(
                    timeline,
                    loop=self._build(
                        LoopRegion,
                        enabled=(
                            loop_enabled if loop_enabled is not None else current_loop.enabled
                        ),
                        start_tick=start,
                        end_tick=end,
                    ),
                )
            updates["timeline"] = timeline
            return _with(score, **updates), brief, ()

        return self._mutate(
            project_id, expected_revision, change, author, operation_id, "Updated arrangement"
        )

    def update_brief(
        self,
        project_id: str,
        *,
        expected_revision: int,
        changes: dict[str, Any],
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Change brief fields (camelCase or snake_case). Locks change via lock/unlock."""

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            data = brief.to_json_dict()
            for key, value in changes.items():
                if key in {"locks", "schemaVersion", "schema_version"}:
                    raise InvalidOperation(f"{key} cannot be changed with update_brief")
                data[_camel(key)] = value
            return score, self._build(Brief, **data), ()

        return self._mutate(
            project_id, expected_revision, change, author, operation_id, "Updated brief"
        )

    # ----------------------------------------------------------------- locks

    def lock(
        self,
        project_id: str,
        *,
        expected_revision: int,
        track_id: str,
        start_tick: int | None = None,
        end_tick: int | None = None,
        reason: str | None = None,
        author: Author = "user",
        operation_id: str | None = None,
    ) -> OperationResult:
        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            _require_track(score, track_id)
            existing = {lock.id for lock in brief.locks}
            n = 1
            while f"lock-{n}" in existing:
                n += 1
            new_lock = self._build(
                Lock,
                id=f"lock-{n}",
                track_id=track_id,
                start_tick=start_tick,
                end_tick=end_tick,
                reason=reason,
            )
            return score, _with(brief, locks=[*brief.locks, new_lock]), (new_lock.id,)

        return self._mutate(
            project_id, expected_revision, change, author, operation_id, f"Locked {track_id!r}"
        )

    def unlock(
        self,
        project_id: str,
        *,
        expected_revision: int,
        lock_id: str,
        author: Author = "user",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Remove a lock. Only users may unlock; agents are refused."""
        if author != "user":
            raise InvalidOperation("only the user can remove locks")

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            if lock_id not in {lock.id for lock in brief.locks}:
                raise InvalidOperation(f"lock {lock_id!r} not found")
            locks = [lock for lock in brief.locks if lock.id != lock_id]
            return score, _with(brief, locks=locks), ()

        return self._mutate(
            project_id, expected_revision, change, author, operation_id, f"Unlocked {lock_id!r}"
        )

    # --------------------------------------------------------------- history

    def restore_revision(
        self,
        project_id: str,
        *,
        expected_revision: int,
        revision: int,
        author: Author = "user",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Make an old revision's score the new head. History is kept; locks still apply."""
        old = self.store.load_revision(project_id, revision)

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            return old.score, brief, ()

        return self._mutate(
            project_id,
            expected_revision,
            change,
            author,
            operation_id,
            f"Restored revision {revision}",
        )

    def undo(
        self,
        project_id: str,
        *,
        expected_revision: int,
        author: Author = "user",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Restore the revision before the head (as a new head revision)."""
        if expected_revision <= 1:
            raise InvalidOperation("nothing to undo")
        return self.restore_revision(
            project_id,
            expected_revision=expected_revision,
            revision=expected_revision - 1,
            author=author,
            operation_id=operation_id,
        )

    # -------------------------------------------------------------- plumbing

    def _mutate(
        self,
        project_id: str,
        expected_revision: int,
        change: Callable[[Score, Brief], tuple[Score, Brief, tuple[str, ...]]],
        author: Author,
        operation_id: str | None,
        default_summary: str,
    ) -> OperationResult:
        if operation_id is not None:
            replay = self.store.find_operation(project_id, operation_id)
            if replay is not None:
                return self._result(replay, None)
        current = self.store.load(project_id)
        if expected_revision != current.revision:
            raise RevisionConflict(project_id, expected_revision, current.revision)
        score, brief, created = change(current.score, current.brief)
        if score.schema_version != SCORE_SCHEMA_VERSION:
            score = _with(score, schema_version=SCORE_SCHEMA_VERSION)
        check_locks(current.score, score, current.brief)
        for track in score.tracks:
            previous = current.score.track(track.id)
            if track.sampler is not None and (
                previous is None or track.sampler != previous.sampler
            ):
                self._require_sampler(track.sampler)
        summary = summarize_changes(current.score, score)
        text = summary.text if summary.text != "No changes" else default_summary
        result = self.store.commit(
            project_id,
            expected_revision=expected_revision,
            score=score,
            brief=brief,
            summary=text,
            author=author,
            operation_id=operation_id,
        )
        return self._result(result, None if result.replayed else summary, created)

    @staticmethod
    def _result(
        result: CommitResult, summary: ChangeSummary | None, created: tuple[str, ...] = ()
    ) -> OperationResult:
        return OperationResult(
            project_id=result.snapshot.project_id,
            revision=result.revision,
            summary=summary,
            validation=result.validation,
            replayed=result.replayed,
            created_ids=created,
        )

    @staticmethod
    def _build(model: type, **values: Any) -> Any:
        try:
            return model.model_validate(values)
        except ValidationError as exc:
            raise InvalidOperation(_validation_message(exc)) from exc

    def _note(self, raw: dict[str, Any], ids: _NoteIds) -> Note:
        data = {_camel(k): v for k, v in raw.items()}
        if "id" not in data or data["id"] is None:
            data["id"] = ids.next()
        else:
            ids.claim(data["id"])
        return self._build(Note, **data)

    @staticmethod
    def _free_track_id(score: Score, base: str) -> str:
        base = base[:56] or "track"
        candidate, n = base, 2
        while score.track(candidate) is not None:
            candidate = f"{base}-{n}"
            n += 1
        return candidate


class _NoteIds:
    """Allocates project-wide note IDs ``n<k>`` that never collide."""

    def __init__(self, score: Score) -> None:
        self.used = {n.id for t in score.tracks for n in t.notes}
        numbers = [
            int(m.group(1)) for i in self.used if (m := _GENERATED_NOTE_ID.match(i)) is not None
        ]
        self.counter = max(numbers, default=0)
        self.created: list[str] = []

    def next(self) -> str:
        while True:
            self.counter += 1
            candidate = f"n{self.counter}"
            if candidate not in self.used:
                self.used.add(candidate)
                self.created.append(candidate)
                return candidate

    def claim(self, note_id: str) -> None:
        if note_id in self.used:
            raise InvalidOperation(f"note id {note_id!r} already exists")
        self.used.add(note_id)
        self.created.append(note_id)


def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(part.title() for part in rest)


def _with(model: Any, **updates: Any) -> Any:
    data = {**model.model_dump(), **updates}
    return type(model).model_validate(data)


def _sorted(notes: list[Note]) -> list[Note]:
    return sorted(notes, key=lambda n: (n.start_tick, n.pitch, n.id))


def _check_settings(settings: HumanizeSettings | ExpressionSettings) -> None:
    try:
        settings.check()
    except ValueError as exc:
        raise InvalidOperation(str(exc)) from exc


def _bounded_range(score: Score, start_tick: int, end_tick: int | None) -> tuple[int, int]:
    total = score.timeline.total_ticks
    end = total if end_tick is None else end_tick
    if start_tick < 0 or end <= start_tick or end > total:
        raise InvalidRange(f"range must satisfy 0 <= startTick < endTick <= {total}")
    return start_tick, end


def _beat_ticks(score: Score) -> int:
    """Felt beat: a quarter in 4/4, a dotted quarter in 6/8, 9/8 and 12/8."""
    t = score.timeline
    unit = t.ppq * 4 // t.meter.denominator
    if t.meter.denominator == 8 and t.meter.numerator % 3 == 0 and t.meter.numerator > 3:
        return unit * 3
    return unit


def _replace_lane(
    automation: Automation, lane: str, start: int, end: int, points: Sequence[tuple[int, int]]
) -> Automation:
    field = LANE_FIELDS[lane]
    kept = [p for p in getattr(automation, field) if not start <= p.tick < end]
    added = [ControlPoint(tick=t, value=v) for t, v in points]
    merged = sorted(kept + added, key=lambda p: p.tick)
    try:
        return Automation.model_validate(
            {**automation.model_dump(), field: [p.model_dump() for p in merged]}
        )
    except ValidationError as exc:
        raise InvalidOperation(_validation_message(exc)) from exc


def _require_track(score: Score, track_id: str) -> Track:
    track = score.track(track_id)
    if track is None:
        raise TrackNotFound(f"track {track_id!r} not found")
    return track


def _replace_track(score: Score, track: Track) -> Score:
    return _with(score, tracks=[track if t.id == track.id else t for t in score.tracks])


def _find_note(tracks: dict[str, list[Note]], note_id: Any, index: int) -> tuple[str, int]:
    for track_id, notes in tracks.items():
        for position, note in enumerate(notes):
            if note.id == note_id:
                return track_id, position
    raise NoteNotFound(f"operation {index}: note {note_id!r} not found")


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(p) for p in error["loc"])
        parts.append(f"{location}: {error['msg']}" if location else error["msg"])
    return "; ".join(parts)
