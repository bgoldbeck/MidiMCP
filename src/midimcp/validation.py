"""Whole-document score validation.

Two levels (see ``docs/reference/03-score-format.md``):

* **errors** — hard failures. A score with errors must not be committed.
* **warnings** — musical advisories. Reported, never auto-corrected; chromaticism,
  dissonance and rhythmic surprise can be intentional.

Field-level structure (pitch range, positive durations, ID format, ...) is already
enforced by the Pydantic models; this module checks cross-field rules and brief
constraints. Soundbank availability is checked by the soundbank registry
(roadmap feature 7), not here. Lock enforcement happens at mutation time in the
composition service (feature 5).
"""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from midimcp.instruments import (
    UnknownInstrument,
    instrument_family,
    instrument_range,
    resolve_instrument,
)
from midimcp.model.brief import Brief
from midimcp.model.score import Note, Score, Track
from midimcp.music.theory import scale_pitch_classes
from midimcp.music.timing import ticks_per_bar, ticks_to_seconds

MAX_TRACKS: Final = 12
MAX_NOTES: Final = 20_000
MAX_DURATION_SECONDS: Final = 8 * 60
DEFAULT_POLYPHONY_WARNING: Final = 8
WIDE_RANGE_SEMITONES: Final = 36
REPEATED_BAR_RUN: Final = 4
LOOP_RESOLVING_NUMERALS: Final = frozenset(
    {"V", "V7", "v", "vii°", "viio", "vii", "bVII", "IV", "iv", "Vsus4", "bII"}
)


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    message: str
    track_id: str | None = None
    note_id: str | None = None
    tick: int | None = None

    def to_dict(self) -> dict:
        data = {"code": self.code, "severity": self.severity.value, "message": self.message}
        if self.track_id is not None:
            data["trackId"] = self.track_id
        if self.note_id is not None:
            data["noteId"] = self.note_id
        if self.tick is not None:
            data["tick"] = self.tick
        return data


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def codes(self, severity: Severity | None = None) -> set[str]:
        return {i.code for i in self.issues if severity is None or i.severity is severity}

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "summary": self.summary,
        }


def validate_score(
    score: Score, brief: Brief | None = None, *, strict: bool | None = None
) -> ValidationReport:
    """Validate ``score`` against built-in limits and the optional ``brief``.

    ``strict`` overrides ``brief.harmonicStrictness``: when strict, out-of-key
    notes are errors instead of warnings.
    """
    brief = brief or Brief()
    strict_key = strict if strict is not None else brief.harmonic_strictness == "strict"
    issues: list[Issue] = []
    issues += _check_identity(score)
    issues += _check_limits(score, brief)
    issues += _check_timeline(score, brief)
    issues += _check_brief_references(score, brief)
    issues += _check_tracks(score, brief, strict_key)
    issues += _check_loop_harmony(score)
    issues += _check_loop_seam(score)
    issues += _check_musicality(score)
    return ValidationReport(issues=issues, summary=_summary(score))


def _error(code: str, message: str, **where: object) -> Issue:
    return Issue(code, Severity.ERROR, message, **where)  # type: ignore[arg-type]


def _warning(code: str, message: str, **where: object) -> Issue:
    return Issue(code, Severity.WARNING, message, **where)  # type: ignore[arg-type]


def _duplicates(values: Iterable[str]) -> list[str]:
    return sorted(v for v, n in Counter(values).items() if n > 1)


def _bar_ticks(score: Score) -> int:
    t = score.timeline
    return ticks_per_bar(t.ppq, t.meter.numerator, t.meter.denominator)


def _duration_seconds(score: Score) -> float:
    t = score.timeline
    return ticks_to_seconds(t.total_ticks, t.ppq, t.tempo_us_per_quarter)


def _all_notes(score: Score) -> Iterator[tuple[Track, Note]]:
    for track in score.tracks:
        for note in track.notes:
            yield track, note


def _check_identity(score: Score) -> list[Issue]:
    issues = []
    for track_id in _duplicates(t.id for t in score.tracks):
        issues.append(_error("TRACK_ID_DUPLICATE", f"track id {track_id!r} is used more than once"))
    for note_id in _duplicates(n.id for _, n in _all_notes(score)):
        issues.append(
            _error(
                "NOTE_ID_DUPLICATE",
                f"note id {note_id!r} is used more than once (note ids are project-wide)",
                note_id=note_id,
            )
        )
    for section_id in _duplicates(s.id for s in score.sections):
        issues.append(
            _error("SECTION_ID_DUPLICATE", f"section id {section_id!r} is used more than once")
        )
    return issues


def _check_limits(score: Score, brief: Brief) -> list[Issue]:
    issues = []
    track_count = len(score.tracks)
    if track_count > MAX_TRACKS:
        issues.append(
            _error("TOO_MANY_TRACKS", f"{track_count} tracks exceeds the limit of {MAX_TRACKS}")
        )
    if brief.max_tracks is not None and track_count > brief.max_tracks:
        issues.append(
            _error(
                "BRIEF_MAX_TRACKS_EXCEEDED",
                f"{track_count} tracks exceeds the brief's maxTracks of {brief.max_tracks}",
            )
        )
    note_count = sum(len(t.notes) for t in score.tracks)
    if note_count > MAX_NOTES:
        issues.append(
            _error("TOO_MANY_NOTES", f"{note_count} notes exceeds the limit of {MAX_NOTES}")
        )
    seconds = _duration_seconds(score)
    if seconds > MAX_DURATION_SECONDS:
        issues.append(
            _error(
                "SONG_TOO_LONG",
                f"song lasts {seconds:.1f}s; limit is {MAX_DURATION_SECONDS}s",
            )
        )
    if brief.duration is not None:
        low, high = brief.duration.min_seconds, brief.duration.max_seconds
        if low is not None and seconds < low:
            issues.append(
                _error("DURATION_OUT_OF_RANGE", f"song lasts {seconds:.1f}s; brief minimum {low}s")
            )
        if high is not None and seconds > high:
            issues.append(
                _error("DURATION_OUT_OF_RANGE", f"song lasts {seconds:.1f}s; brief maximum {high}s")
            )
    return issues


def _check_timeline(score: Score, brief: Brief) -> list[Issue]:
    issues = []
    total = score.timeline.total_ticks
    bar = _bar_ticks(score)
    if total % bar:
        issues.append(
            _warning(
                "TIMELINE_NOT_BAR_ALIGNED",
                f"totalTicks {total} is not a whole number of {bar}-tick bars",
            )
        )

    loop = score.timeline.loop
    if loop.enabled:
        if loop.end_tick <= loop.start_tick:
            issues.append(_error("LOOP_INVALID", "loop endTick must be greater than startTick"))
        if loop.end_tick > total:
            issues.append(
                _error("LOOP_INVALID", f"loop endTick {loop.end_tick} is past totalTicks {total}")
            )
    elif brief.loop_required:
        issues.append(_error("LOOP_REQUIRED", "the brief requires a loop but none is enabled"))

    issues += _check_spans(
        "SECTION",
        [(s.start_tick, s.end_tick, s.label) for s in score.sections],
        total,
    )
    issues += _check_spans(
        "HARMONY",
        [(h.start_tick, h.start_tick + h.duration_ticks, h.symbol) for h in score.harmony],
        total,
    )
    return issues


def _check_spans(kind: str, spans: list[tuple[int, int, str]], total: int) -> list[Issue]:
    issues = []
    for start, end, label in spans:
        if end <= start:
            issues.append(
                _error(f"{kind}_INVALID", f"{kind.lower()} {label!r} ends before it starts")
            )
        elif end > total:
            issues.append(
                _error(
                    f"{kind}_OUTSIDE_TIMELINE",
                    f"{kind.lower()} {label!r} ends at {end}, past totalTicks {total}",
                    tick=start,
                )
            )
    ordered = sorted(spans)
    for (_, prev_end, prev_label), (start, _, label) in itertools.pairwise(ordered):
        if start < prev_end:
            issues.append(
                _error(
                    f"{kind}_OVERLAP",
                    f"{kind.lower()} {label!r} overlaps {prev_label!r}",
                    tick=start,
                )
            )
    return issues


def _check_brief_references(score: Score, brief: Brief) -> list[Issue]:
    issues = []
    track_ids = {t.id for t in score.tracks}
    for limits in brief.part_limits:
        if limits.track_id not in track_ids:
            issues.append(
                _warning(
                    "PART_LIMITS_UNKNOWN_TRACK",
                    f"brief part limits reference missing track {limits.track_id!r}",
                    track_id=limits.track_id,
                )
            )
    for lock in brief.locks:
        if lock.track_id not in track_ids:
            issues.append(
                _warning(
                    "LOCK_UNKNOWN_TRACK",
                    f"lock {lock.id!r} references missing track {lock.track_id!r}",
                    track_id=lock.track_id,
                )
            )
        elif lock.end_tick is not None and lock.end_tick > score.timeline.total_ticks:
            issues.append(
                _warning(
                    "LOCK_OUTSIDE_TIMELINE",
                    f"lock {lock.id!r} extends past totalTicks",
                    track_id=lock.track_id,
                )
            )
    return issues


def _check_tracks(score: Score, brief: Brief, strict_key: bool) -> list[Issue]:
    issues = []
    key_pcs = set(scale_pitch_classes(score.tonality.tonic_pitch_class, score.tonality.mode))
    allowed = set(brief.allowed_instrument_ids) if brief.allowed_instrument_ids else None
    total = score.timeline.total_ticks

    for track in score.tracks:
        tid = track.id
        if track.is_percussion and not brief.percussion_allowed:
            issues.append(
                _error(
                    "PERCUSSION_FORBIDDEN",
                    f"track {tid!r} is percussion but the brief forbids percussion",
                    track_id=tid,
                )
            )
        try:
            instrument = resolve_instrument(track.instrument_id)
        except UnknownInstrument:
            issues.append(
                _error(
                    "UNKNOWN_INSTRUMENT",
                    f"instrument {track.instrument_id!r} is not known; use list_instruments",
                    track_id=tid,
                )
            )
        else:
            if instrument.is_percussion != track.is_percussion:
                issues.append(
                    _error(
                        "PERCUSSION_INSTRUMENT_MISMATCH",
                        f"track {tid!r}: isPercussion must be "
                        f"{str(instrument.is_percussion).lower()} for {track.instrument_id!r}",
                        track_id=tid,
                    )
                )
        if allowed is not None and track.instrument_id not in allowed:
            issues.append(
                _error(
                    "INSTRUMENT_NOT_ALLOWED",
                    f"instrument {track.instrument_id!r} is not in the brief's allowed list",
                    track_id=tid,
                )
            )
        if not track.notes:
            issues.append(_warning("EMPTY_TRACK", f"track {tid!r} has no notes", track_id=tid))
            continue

        limits = brief.part_limits_for(tid)
        for note in track.notes:
            where = {"track_id": tid, "note_id": note.id, "tick": note.start_tick}
            if note.end_tick > total:
                issues.append(
                    _error(
                        "NOTE_OUTSIDE_TIMELINE",
                        f"note ends at {note.end_tick}, past totalTicks {total}",
                        **where,
                    )
                )
            if not track.is_percussion and note.pitch % 12 not in key_pcs:
                make = _error if strict_key else _warning
                issues.append(
                    make("NOTE_OUT_OF_KEY", f"pitch {note.pitch} is outside the key", **where)
                )
            if limits is not None:
                if limits.lowest_pitch is not None and note.pitch < limits.lowest_pitch:
                    issues.append(
                        _warning(
                            "NOTE_BELOW_REGISTER",
                            f"pitch {note.pitch} is below the part's lowest {limits.lowest_pitch}",
                            **where,
                        )
                    )
                if limits.highest_pitch is not None and note.pitch > limits.highest_pitch:
                    issues.append(
                        _warning(
                            "NOTE_ABOVE_REGISTER",
                            f"pitch {note.pitch} is above the part's highest "
                            f"{limits.highest_pitch}",
                            **where,
                        )
                    )

        issues += _check_polyphony(track, limits.max_polyphony if limits else None)
        issues += _check_unison_overlaps(track)
        if not track.is_percussion:
            pitches = [n.pitch for n in track.notes]
            span = max(pitches) - min(pitches)
            if span > WIDE_RANGE_SEMITONES:
                issues.append(
                    _warning(
                        "WIDE_RANGE",
                        f"track {tid!r} spans {span} semitones (over {WIDE_RANGE_SEMITONES})",
                        track_id=tid,
                    )
                )
        issues += _check_repetition(track, _bar_ticks(score))
    return issues


def max_polyphony(notes: Iterable[Note]) -> tuple[int, int]:
    """Peak simultaneous notes and the first tick it occurs (note-offs sort first)."""
    events = []
    for note in notes:
        events.append((note.start_tick, 1))
        events.append((note.end_tick, -1))
    events.sort(key=lambda e: (e[0], e[1]))
    current = peak = 0
    peak_tick = 0
    for tick, delta in events:
        current += delta
        if current > peak:
            peak, peak_tick = current, tick
    return peak, peak_tick


def _check_polyphony(track: Track, limit: int | None) -> list[Issue]:
    peak, tick = max_polyphony(track.notes)
    if limit is not None and peak > limit:
        return [
            _warning(
                "POLYPHONY_EXCEEDED",
                f"track {track.id!r} plays {peak} simultaneous notes; part limit is {limit}",
                track_id=track.id,
                tick=tick,
            )
        ]
    if limit is None and peak > DEFAULT_POLYPHONY_WARNING:
        return [
            _warning(
                "HIGH_POLYPHONY",
                f"track {track.id!r} plays {peak} simultaneous notes",
                track_id=track.id,
                tick=tick,
            )
        ]
    return []


def _check_unison_overlaps(track: Track) -> list[Issue]:
    issues = []
    by_pitch: dict[int, list[Note]] = {}
    for note in track.notes:
        by_pitch.setdefault(note.pitch, []).append(note)
    for notes in by_pitch.values():
        notes.sort(key=lambda n: (n.start_tick, n.id))
        for prev, cur in itertools.pairwise(notes):
            if cur.start_tick < prev.end_tick:
                issues.append(
                    _warning(
                        "UNISON_OVERLAP",
                        f"notes {prev.id!r} and {cur.id!r} overlap on pitch {cur.pitch}",
                        track_id=track.id,
                        note_id=cur.id,
                        tick=cur.start_tick,
                    )
                )
    return issues


def _check_repetition(track: Track, bar: int) -> list[Issue]:
    bars: dict[int, list[tuple[int, int, int, int]]] = {}
    for note in track.notes:
        index, offset = divmod(note.start_tick, bar)
        bars.setdefault(index, []).append((offset, note.pitch, note.duration_ticks, note.velocity))
    if not bars:
        return []
    signatures = {i: tuple(sorted(v)) for i, v in bars.items()}
    issues = []
    run_start, run_len, prev = 0, 0, None
    for index in range(max(signatures) + 2):
        sig = signatures.get(index)
        if sig is not None and sig == prev:
            run_len += 1
        else:
            if prev is not None and run_len >= REPEATED_BAR_RUN:
                issues.append(
                    _warning(
                        "EXCESSIVE_REPETITION",
                        f"track {track.id!r} repeats the same bar {run_len} times from bar "
                        f"{run_start + 1}",
                        track_id=track.id,
                        tick=run_start * bar,
                    )
                )
            run_start, run_len, prev = index, 1, sig
    return issues


def _check_loop_harmony(score: Score) -> list[Issue]:
    loop = score.timeline.loop
    if not loop.enabled or not score.harmony:
        return []
    first = next((h for h in score.harmony if h.start_tick <= loop.start_tick), None)
    covering_end = [h for h in score.harmony if h.start_tick < loop.end_tick]
    last = max(covering_end, key=lambda h: h.start_tick) if covering_end else None
    if first is None or last is None or not first.roman_numeral or not last.roman_numeral:
        return []
    if last.roman_numeral == first.roman_numeral or last.roman_numeral in LOOP_RESOLVING_NUMERALS:
        return []
    return [
        _warning(
            "LOOP_HARMONY_UNRESOLVED",
            f"loop ends on {last.roman_numeral} and restarts on {first.roman_numeral}; "
            "consider ending on the opening chord or its dominant",
            tick=last.start_tick,
        )
    ]


def _summary(score: Score) -> dict:
    bar = _bar_ticks(score)
    t = score.timeline
    return {
        "bars": t.total_ticks / bar,
        "durationSeconds": round(_duration_seconds(score), 3),
        "trackCount": len(score.tracks),
        "noteCount": sum(len(tr.notes) for tr in score.tracks),
        "tracks": [
            {"id": tr.id, "instrumentId": tr.instrument_id, "noteCount": len(tr.notes)}
            for tr in score.tracks
        ],
    }


# ------------------------------------------------------------- musicality
# Advisory only: these describe common reasons a part sounds amateurish. They
# never block saving, and deliberate choices may trigger them.

BREATH_SECONDS: Final = 10.0
LARGE_LEAP_SEMITONES: Final = 12
MASKED_SHARE: Final = 0.3


def _melody_track(score: Score) -> Track | None:
    """The track with role 'melody', else (no roles at all) the highest-sounding part."""
    tracks = [t for t in score.tracks if not t.is_percussion and t.notes]
    explicit = [t for t in tracks if t.role == "melody"]
    if explicit:
        return explicit[0]
    if any(t.role for t in score.tracks):
        return None
    candidates = [t for t in tracks if len(t.notes) >= 8]
    if not candidates:
        return None
    return max(candidates, key=lambda t: sum(n.pitch for n in t.notes) / len(t.notes))


def _check_musicality(score: Score) -> list[Issue]:
    issues: list[Issue] = []
    t = score.timeline
    seconds_per_tick = t.tempo_us_per_quarter / 1e6 / t.ppq
    for track in score.tracks:
        if not track.notes or track.is_percussion:
            continue
        span = instrument_range(track.instrument_id)
        if span is not None:
            outside = [n for n in track.notes if not span[0] <= n.pitch <= span[1]]
            if outside:
                issues.append(
                    _warning(
                        "NOTE_OUTSIDE_INSTRUMENT_RANGE",
                        f"{len(outside)} note(s) outside the practical range of "
                        f"{track.instrument_id} ({span[0]}-{span[1]}); they will sound unnatural",
                        track_id=track.id,
                        note_id=outside[0].id,
                        tick=outside[0].start_tick,
                    )
                )
        if instrument_family(track.instrument_id) in {"wind", "brass"}:
            issues += _check_breath(track, t.ppq, seconds_per_tick)
        velocities = {n.velocity for n in track.notes}
        if len(track.notes) >= 16 and len(velocities) == 1:
            issues.append(
                _warning(
                    "FLAT_DYNAMICS",
                    f"all {len(track.notes)} notes use velocity {velocities.pop()}; "
                    "vary velocity to shape phrases",
                    track_id=track.id,
                )
            )
    melody = _melody_track(score)
    if melody is not None:
        issues += _check_melody(score, melody)
    return issues


def _check_breath(track: Track, ppq: int, seconds_per_tick: float) -> list[Issue]:
    notes = sorted(track.notes, key=lambda n: (n.start_tick, n.id))
    gap = ppq // 8  # anything shorter than a 32nd note is not a breath
    phrase_start, phrase_end = notes[0].start_tick, notes[0].end_tick
    for note in [*notes[1:], None]:
        if note is not None and note.start_tick - phrase_end <= gap:
            phrase_end = max(phrase_end, note.end_tick)
            continue
        length = (phrase_end - phrase_start) * seconds_per_tick
        if length > BREATH_SECONDS:
            return [
                _warning(
                    "BREATH_LENGTH",
                    f"wind phrase plays {length:.0f}s without a rest; leave breathing gaps "
                    f"(under {BREATH_SECONDS:.0f}s)",
                    track_id=track.id,
                    tick=phrase_start,
                )
            ]
        if note is not None:
            phrase_start, phrase_end = note.start_tick, note.end_tick
    return []


def _check_melody(score: Score, melody: Track) -> list[Issue]:
    issues: list[Issue] = []
    line = sorted(melody.notes, key=lambda n: (n.start_tick, -n.pitch))
    # Melodic line = highest note at each onset.
    tops: list[Note] = []
    for note in line:
        if tops and tops[-1].start_tick == note.start_tick:
            continue
        tops.append(note)
    leaps = [
        b for a, b in itertools.pairwise(tops) if abs(b.pitch - a.pitch) > LARGE_LEAP_SEMITONES
    ]
    if leaps:
        issues.append(
            _warning(
                "LARGE_LEAP",
                f"melody leaps more than an octave {len(leaps)} time(s); keep leaps rare "
                "and follow them with stepwise motion back",
                track_id=melody.id,
                note_id=leaps[0].id,
                tick=leaps[0].start_tick,
            )
        )
    if len(tops) >= 8 and len({n.pitch % 12 for n in tops}) < 4:
        issues.append(
            _warning(
                "MONOTONOUS_MELODY",
                "melody uses fewer than 4 different pitches; give it a clearer shape",
                track_id=melody.id,
            )
        )
    if len(tops) >= 16 and len({n.duration_ticks for n in tops}) == 1:
        issues.append(
            _warning(
                "UNIFORM_RHYTHM",
                "every melody note has the same length; mix long and short notes",
                track_id=melody.id,
            )
        )
    others = [
        t
        for t in score.tracks
        if t is not melody and not t.is_percussion and t.role not in {"bass"} and not t.mute
    ]
    if others and tops:
        masked = 0
        for note in tops:
            for other in others:
                if any(
                    o.start_tick <= note.start_tick < o.end_tick and o.pitch > note.pitch
                    for o in other.notes
                ):
                    masked += 1
                    break
        if masked / len(tops) > MASKED_SHARE:
            issues.append(
                _warning(
                    "MELODY_MASKED",
                    f"{masked} of {len(tops)} melody notes have another part sounding above them; "
                    "keep accompaniment below the melody",
                    track_id=melody.id,
                )
            )
    return issues


# ---------------------------------------------------------------- loop seam

LOOP_JUMP_SEMITONES: Final = 7
LOOP_ENERGY_RATIO: Final = 3.0


def _check_loop_seam(score: Score) -> list[Issue]:
    """How the loop end joins the loop start: cut-off notes, melodic jump, energy jump."""
    loop = score.timeline.loop
    if not loop.enabled or loop.end_tick <= loop.start_tick:
        return []
    issues: list[Issue] = []
    start, end = loop.start_tick, loop.end_tick
    cut = [
        (t, n)
        for t in score.tracks
        if not t.mute and not t.is_percussion
        for n in t.notes
        if n.start_tick < end < n.end_tick
    ]
    if cut:
        track, note = cut[0]
        issues.append(
            _warning(
                "LOOP_NOTE_CUT",
                f"{len(cut)} note(s) ring past the loop end and will be cut off when the "
                "loop restarts; end them at the loop point",
                track_id=track.id,
                note_id=note.id,
                tick=note.start_tick,
            )
        )
    melody = _melody_track(score)
    if melody is not None:
        before = [n for n in melody.notes if start <= n.start_tick < end]
        if before:
            last = max(before, key=lambda n: (n.start_tick, n.pitch))
            first = min(before, key=lambda n: (n.start_tick, -n.pitch))
            jump = abs(first.pitch - last.pitch)
            if jump > LOOP_JUMP_SEMITONES:
                issues.append(
                    _warning(
                        "LOOP_MELODY_JUMP",
                        f"melody jumps {jump} semitones from the loop's last note back to its "
                        "first; approach the opening note by step or a small leap",
                        track_id=melody.id,
                        tick=last.start_tick,
                    )
                )
    t = score.timeline
    bar = ticks_per_bar(t.ppq, t.meter.numerator, t.meter.denominator)
    if end - start >= 2 * bar:
        audible = [n for tr in score.tracks if not tr.mute for n in tr.notes]
        first_bar = sum(1 for n in audible if start <= n.start_tick < start + bar)
        last_bar = sum(1 for n in audible if end - bar <= n.start_tick < end)
        low, high = sorted((first_bar, last_bar))
        if high >= 6 and (low == 0 or high / low > LOOP_ENERGY_RATIO):
            issues.append(
                _warning(
                    "LOOP_ENERGY_JUMP",
                    f"the loop's last bar has {last_bar} notes and its first bar {first_bar}; "
                    "match the density so the restart is not abrupt",
                    tick=end - bar,
                )
            )
    return issues
