"""Score comparison: lock enforcement and human-readable change summaries."""

from __future__ import annotations

from dataclasses import dataclass, field

from midimcp.model.brief import Brief, Lock
from midimcp.model.score import Note, Score, Track
from midimcp.music.timing import tick_to_bar_position
from midimcp.service.errors import LockViolation

NoteKey = tuple[str, int, int, int, int]


def _note_key(note: Note) -> NoteKey:
    return (note.id, note.pitch, note.start_tick, note.duration_ticks, note.velocity)


def _track_props(track: Track) -> dict:
    data = track.to_json_dict()
    data.pop("notes")
    data.pop("automation")
    return data


def _lanes_touching(track: Track | None, start: int, end: int) -> dict[str, list[tuple[int, int]]]:
    if track is None:
        return {}
    return {
        lane: [(p.tick, p.value) for p in points if start <= p.tick < end]
        for lane, points in track.automation.lanes().items()
    }


def _changed_lanes(old: Track, new: Track) -> list[str]:
    before, after = old.automation.lanes(), new.automation.lanes()
    return [f"{lane} curve" for lane in before if before[lane] != after[lane]]


def _notes_touching(track: Track | None, start: int, end: int) -> set[NoteKey]:
    if track is None:
        return set()
    return {_note_key(n) for n in track.notes if n.start_tick < end and n.end_tick > start}


def check_locks(before: Score, after: Score, brief: Brief) -> None:
    """Raise LockViolation if ``after`` changes anything protected by ``brief.locks``.

    Whole-track lock: the track (properties, every note and every automation point)
    must be identical and must not be removed. Range lock: the set of notes sounding
    anywhere inside the range, and the automation points inside it, must be identical.
    This is checked on the resulting document, so it holds for every kind of operation.
    """
    violated: list[str] = []
    for lock in brief.locks:
        old_track, new_track = before.track(lock.track_id), after.track(lock.track_id)
        if old_track is None:
            continue
        if _lock_broken(lock, old_track, new_track):
            violated.append(lock.id)
    if violated:
        raise LockViolation(
            f"change would modify locked material ({', '.join(violated)})", violated
        )


def _lock_broken(lock: Lock, old: Track, new: Track | None) -> bool:
    if new is None:
        return True
    if lock.whole_track:
        return (
            _track_props(old) != _track_props(new)
            or old.automation != new.automation
            or {_note_key(n) for n in old.notes} != {_note_key(n) for n in new.notes}
        )
    assert lock.start_tick is not None and lock.end_tick is not None
    start, end = lock.start_tick, lock.end_tick
    return _notes_touching(old, start, end) != _notes_touching(new, start, end) or (
        _lanes_touching(old, start, end) != _lanes_touching(new, start, end)
    )


@dataclass
class TrackChange:
    track_id: str
    name: str
    added: int = 0
    removed: int = 0
    modified: int = 0
    properties: list[str] = field(default_factory=list)
    created: bool = False
    deleted: bool = False
    first_bar: int | None = None
    last_bar: int | None = None

    @property
    def changed(self) -> bool:
        return (
            bool(self.added or self.removed or self.modified or self.properties)
            or self.created
            or self.deleted
        )

    def to_dict(self) -> dict:
        return {
            "trackId": self.track_id,
            "name": self.name,
            "notesAdded": self.added,
            "notesRemoved": self.removed,
            "notesModified": self.modified,
            "propertiesChanged": self.properties,
            "created": self.created,
            "deleted": self.deleted,
            "bars": [self.first_bar, self.last_bar] if self.first_bar else None,
        }

    def describe(self) -> str:
        if self.created:
            return f"{self.name}: track added with {self.added} notes"
        if self.deleted:
            return f"{self.name}: track removed"
        parts = []
        if self.added and self.removed and not self.modified:
            parts.append(f"{self.removed} notes replaced with {self.added}")
        else:
            if self.added:
                parts.append(f"{self.added} notes added")
            if self.removed:
                parts.append(f"{self.removed} notes removed")
            if self.modified:
                parts.append(f"{self.modified} notes modified")
        if self.properties:
            parts.append(f"{', '.join(self.properties)} changed")
        text = f"{self.name}: " + "; ".join(parts)
        if self.first_bar:
            bars = (
                f"measure {self.first_bar}"
                if self.first_bar == self.last_bar
                else f"measures {self.first_bar}-{self.last_bar}"
            )
            text += f" in {bars}"
        return text


@dataclass
class ChangeSummary:
    tracks: list[TrackChange]
    other: list[str]

    @property
    def text(self) -> str:
        changed = [t.describe() for t in self.tracks if t.changed]
        unchanged = [t.name for t in self.tracks if not t.changed]
        parts = changed + self.other
        if not parts:
            return "No changes"
        if unchanged and changed:
            parts.append(f"{', '.join(unchanged)} unchanged")
        return "; ".join(parts)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "tracks": [t.to_dict() for t in self.tracks],
            "other": self.other,
        }


def summarize_changes(before: Score, after: Score) -> ChangeSummary:
    t = after.timeline
    old_tracks = {tr.id: tr for tr in before.tracks}
    new_tracks = {tr.id: tr for tr in after.tracks}
    changes: list[TrackChange] = []

    for track_id in list(old_tracks) + [i for i in new_tracks if i not in old_tracks]:
        old, new = old_tracks.get(track_id), new_tracks.get(track_id)
        change = TrackChange(track_id, (new or old).name)  # type: ignore[union-attr]
        old_notes = {n.id: n for n in old.notes} if old else {}
        new_notes = {n.id: n for n in new.notes} if new else {}
        touched: list[int] = []
        for nid, note in new_notes.items():
            prev = old_notes.get(nid)
            if prev is None:
                change.added += 1
                touched.append(note.start_tick)
            elif _note_key(prev) != _note_key(note):
                change.modified += 1
                touched += [prev.start_tick, note.start_tick]
        for nid, note in old_notes.items():
            if nid not in new_notes:
                change.removed += 1
                touched.append(note.start_tick)
        if old is None:
            change.created = True
        elif new is None:
            change.deleted = True
        else:
            old_props, new_props = _track_props(old), _track_props(new)
            change.properties = sorted(k for k in new_props if old_props.get(k) != new_props[k])
            change.properties += _changed_lanes(old, new)
        if touched:
            change.first_bar = tick_to_bar_position(min(touched), t.ppq, *_meter(after))[0]
            change.last_bar = tick_to_bar_position(max(touched), t.ppq, *_meter(after))[0]
        changes.append(change)

    other = []
    if before.timeline != after.timeline:
        other.append("timeline changed")
    if before.sections != after.sections:
        other.append("sections changed")
    if before.harmony != after.harmony:
        other.append("harmony changed")
    if before.metadata != after.metadata:
        other.append("metadata changed")
    if before.tonality != after.tonality:
        other.append("key changed")
    if before.sound_profile != after.sound_profile:
        other.append("sound profile changed")
    return ChangeSummary(changes, other)


def _meter(score: Score) -> tuple[int, int]:
    return score.timeline.meter.numerator, score.timeline.meter.denominator
