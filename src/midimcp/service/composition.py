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
from typing import Any, Literal

from pydantic import ValidationError

from midimcp.model.brief import Brief, Lock
from midimcp.model.score import (
    HarmonyEvent,
    LoopRegion,
    Metadata,
    Meter,
    Note,
    Score,
    Section,
    SoundProfile,
    Timeline,
    Track,
    is_valid_identifier,
    make_tonality,
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

Author = Literal["user", "agent", "system"]

DEFAULT_PROFILE_ID = "retro-gm-1997-v1"
DEFAULT_BANK_ID = "fluidr3-gm"

_GENERATED_NOTE_ID = re.compile(r"^n(\d+)$")
_TRACK_PROPERTIES = {"name", "instrument_id", "gain_db", "pan", "mute", "is_percussion"}


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
    def __init__(self, store: ProjectStore) -> None:
        self.store = store

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
    ) -> OperationResult:
        """Create an empty project from musical parameters (no tracks yet)."""
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
        )
        result = self.store.create_project(
            score,
            brief or Brief(),
            summary=f"Created project {title!r}",
            author=author,
            operation_id=operation_id,
        )
        return self._result(result, None)

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
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Change track properties: name, instrument_id, gain_db, pan, mute, is_percussion."""
        unknown = set(changes) - _TRACK_PROPERTIES
        if unknown:
            raise InvalidOperation(f"cannot update track fields: {', '.join(sorted(unknown))}")

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            track = _require_track(score, track_id)
            values = {k: float(v) if k in {"gain_db", "pan"} else v for k, v in changes.items()}
            updated = self._build(Track, **{**track.model_dump(), **values})
            return _replace_track(score, updated), brief, ()

        return self._mutate(
            project_id,
            expected_revision,
            change,
            author,
            operation_id,
            f"Updated track {track_id!r}",
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
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Apply note patches atomically.

        Each operation is one of::

            {"op": "add", "trackId": ..., "note": {pitch, startTick, durationTicks, velocity}}
            {"op": "update", "noteId": ..., "pitch"?, "startTick"?, "durationTicks"?, "velocity"?}
            {"op": "delete", "noteId": ...}
        """
        if not operations:
            raise InvalidOperation("operations must not be empty")

        def change(score: Score, brief: Brief) -> tuple[Score, Brief, tuple[str, ...]]:
            tracks = {t.id: list(t.notes) for t in score.tracks}
            ids = _NoteIds(score)
            for index, op in enumerate(operations):
                kind = op.get("op")
                if kind == "add":
                    track_id = op.get("trackId")
                    if track_id not in tracks:
                        raise TrackNotFound(f"operation {index}: track {track_id!r} not found")
                    tracks[track_id].append(self._note(op.get("note") or {}, ids))
                elif kind in {"update", "delete"}:
                    note_id = op.get("noteId")
                    track_id, position = _find_note(tracks, note_id, index)
                    if kind == "delete":
                        tracks[track_id].pop(position)
                        continue
                    allowed = {"pitch", "startTick", "durationTicks", "velocity"}
                    extra = set(op) - allowed - {"op", "noteId"}
                    if extra:
                        raise InvalidOperation(
                            f"operation {index}: unknown fields {', '.join(sorted(extra))}"
                        )
                    current = tracks[track_id][position].to_json_dict()
                    patch = {k: op[k] for k in allowed if k in op}
                    tracks[track_id][position] = self._build(Note, **{**current, **patch})
                else:
                    raise InvalidOperation(f"operation {index}: unknown op {kind!r}")
            new_tracks = [_with(t, notes=_sorted(tracks[t.id])) for t in score.tracks]
            return _with(score, tracks=new_tracks), brief, tuple(ids.created)

        return self._mutate(
            project_id,
            expected_revision,
            change,
            author,
            operation_id,
            f"Edited notes ({len(operations)} operations)",
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
        author: Author = "agent",
        operation_id: str | None = None,
    ) -> OperationResult:
        """Replace sections and/or harmony, resize the song, or set the loop."""
        if sections is None and harmony is None and bars is None and loop is None:
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
                timeline = _with(timeline, total_ticks=total)
            if loop is not None:
                timeline = _with(timeline, loop=self._build(LoopRegion, **loop))
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
        check_locks(current.score, score, current.brief)
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
