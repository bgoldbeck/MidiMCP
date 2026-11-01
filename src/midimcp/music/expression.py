"""Expressive performance: humanized notes and controller curves.

Everything here is deterministic. "Random" variation is derived from SHA-256 of
(seed, note or onset, purpose), so the same call on the same notes always gives
the same result and offline renders stay byte-reproducible. Changing the seed
gives a different, equally reproducible performance.

Terms:

* line: the highest note at each onset (the melody a listener follows);
* phrase: line notes separated by a rest (> 1/32 note) or, after at least three
  notes, by a held note of two beats or more;
* arc: 0 at a phrase start, 1 at its highest note, 0.3 at its end (0.5 for a
  one-note phrase). Phrases rise toward their high point and relax afterwards.
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Sequence
from dataclasses import dataclass

from midimcp.model.score import Note

# ------------------------------------------------------------------ helpers


def noise(seed: int, key: str, purpose: str) -> float:
    """Deterministic value in [-1, 1) for (seed, key, purpose)."""
    digest = hashlib.sha256(f"{seed}:{key}:{purpose}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**63 - 1.0


def melodic_line(notes: Sequence[Note]) -> list[Note]:
    """Highest note at each onset, in time order."""
    line: list[Note] = []
    for note in sorted(notes, key=lambda n: (n.start_tick, -n.pitch, n.id)):
        if line and line[-1].start_tick == note.start_tick:
            continue
        line.append(note)
    return line


def phrases(line: Sequence[Note], ppq: int) -> list[list[Note]]:
    if not line:
        return []
    rest = ppq // 8
    held = 2 * ppq
    groups: list[list[Note]] = [[line[0]]]
    for prev, note in itertools.pairwise(line):
        breaks = note.start_tick - prev.end_tick > rest or (
            prev.duration_ticks >= held and len(groups[-1]) >= 3
        )
        if breaks:
            groups.append([note])
        else:
            groups[-1].append(note)
    return groups


def phrase_arc(index: int, count: int, apex: int) -> float:
    if count == 1:
        return 0.5
    if index <= apex:
        return index / apex if apex else 1.0
    return 1.0 - 0.7 * (index - apex) / (count - 1 - apex)


def apex_index(phrase: Sequence[Note]) -> int:
    top = max(n.pitch for n in phrase)
    return next(i for i, n in enumerate(phrase) if n.pitch == top)


def interpolate(points: Sequence[tuple[int, int]], resolution: int) -> list[tuple[int, int]]:
    """Linear ramps between consecutive points, one step every ``resolution`` ticks."""
    if resolution < 1:
        raise ValueError("resolution must be at least 1 tick")
    ordered = sorted(points)
    out: list[tuple[int, int]] = []
    for (t0, v0), (t1, v1) in itertools.pairwise(ordered):
        for tick in range(t0, t1, resolution):
            out.append((tick, round(v0 + (v1 - v0) * (tick - t0) / (t1 - t0))))
    if ordered:
        out.append(ordered[-1])
    return collapse(out)


def collapse(points: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort by tick (later writes win at equal ticks) and drop repeated values."""
    by_tick: dict[int, int] = {}
    for tick, value in points:
        by_tick[tick] = value
    out: list[tuple[int, int]] = []
    for tick in sorted(by_tick):
        if out and out[-1][1] == by_tick[tick]:
            continue
        out.append((tick, by_tick[tick]))
    return out


def _clamp(value: float, low: int, high: int) -> int:
    return max(low, min(high, round(value)))


# ----------------------------------------------------------------- humanize


@dataclass(frozen=True)
class HumanizeSettings:
    seed: int = 1
    timing_ticks: int = 12  # largest late push; early pushes are up to 40 % of this
    velocity_variation: int = 5  # +- per note
    phrase_dynamics: int = 10  # velocity rise from phrase start to its high point
    accent_downbeats: bool = True  # bar starts +4, other beats +1
    keep_downbeats: bool = True  # notes on a bar line stay exactly on it
    legato: float | None = None  # inner notes last this share of the gap to the next onset
    breath_ticks: int = 0  # silence before each new phrase (wind players breathe)

    def check(self) -> None:
        if not 0 <= self.timing_ticks <= 240:
            raise ValueError("timing_ticks must be 0-240")
        if not 0 <= self.velocity_variation <= 30:
            raise ValueError("velocity_variation must be 0-30")
        if not 0 <= self.phrase_dynamics <= 40:
            raise ValueError("phrase_dynamics must be 0-40")
        if self.legato is not None and not 0.3 <= self.legato <= 1.0:
            raise ValueError("legato must be between 0.3 and 1.0")
        if not 0 <= self.breath_ticks <= 1920:
            raise ValueError("breath_ticks must be 0-1920")


def humanize(
    notes: Sequence[Note],
    *,
    ppq: int,
    bar_ticks: int,
    beat_ticks: int,
    start: int,
    end: int,
    settings: HumanizeSettings,
) -> list[Note]:
    """Return ``notes`` with those starting in ``[start, end)`` performed more naturally.

    Notes sharing an onset (chords) move together and get the same dynamic shape.
    Pitches never change and note order is preserved.
    """
    settings.check()
    targets = [n for n in notes if start <= n.start_tick < end]
    if not targets:
        return list(notes)
    seed = settings.seed
    target_ids = {n.id for n in targets}
    line = melodic_line(targets)
    onsets = [n.start_tick for n in line]
    position = {onset: i for i, onset in enumerate(onsets)}

    # Dynamic shape per onset: phrase arc + metric accent.
    offset: dict[int, int] = {}
    phrase_end: set[int] = set()
    phrase_of: dict[int, int] = {}
    for number, phrase in enumerate(phrases(line, ppq)):
        apex = apex_index(phrase)
        for index, note in enumerate(phrase):
            arc = phrase_arc(index, len(phrase), apex)
            value = settings.phrase_dynamics * (arc - 0.4)
            if settings.accent_downbeats:
                if note.start_tick % bar_ticks == 0:
                    value += 4
                elif note.start_tick % beat_ticks == 0:
                    value += 1
            offset[note.start_tick] = round(value)
            phrase_of[note.start_tick] = number
        phrase_end.add(phrase[-1].start_tick)

    # Timing per onset; keeps onsets in order and never past the note end.
    moved: dict[int, int] = {}
    previous = -1
    shortest: dict[int, int] = {}
    for n in targets:
        shortest[n.start_tick] = min(shortest.get(n.start_tick, n.end_tick), n.end_tick)
    for onset in onsets:
        shift = 0
        if settings.timing_ticks and not (settings.keep_downbeats and onset % bar_ticks == 0):
            u = (noise(seed, f"onset{onset}", "timing") + 1) / 2
            shift = round(settings.timing_ticks * (u * 1.4 - 0.4))
        new = max(0, onset + shift, previous + 1)
        if new >= shortest[onset]:
            new = onset
        moved[onset] = new
        previous = new

    result: list[Note] = []
    for note in notes:
        if note.id not in target_ids:
            result.append(note)
            continue
        onset = note.start_tick
        new_start = moved[onset]
        new_end = note.end_tick  # releases stay put; a late start just shortens the note
        index = position[onset]
        following = moved[onsets[index + 1]] if index + 1 < len(onsets) else None
        same_phrase = (
            following is not None
            and phrase_of.get(onsets[index + 1]) == phrase_of.get(onset)
            and onset not in phrase_end
        )
        if settings.legato is not None and same_phrase:
            share = settings.legato * (1 + 0.03 * noise(seed, note.id, "legato"))
            new_end = new_start + max(ppq // 16, round((following - new_start) * min(share, 1.0)))
        if settings.breath_ticks and onset in phrase_end and following is not None:
            limit = following - settings.breath_ticks
            floor = new_start + max(ppq // 8, (new_end - new_start) // 2)
            if new_end > limit:
                new_end = max(limit, floor)
        jitter = settings.velocity_variation * noise(seed, note.id, "velocity")
        velocity = _clamp(note.velocity + offset.get(onset, 0) + jitter, 1, 127)
        result.append(
            Note(
                id=note.id,
                pitch=note.pitch,
                start_tick=new_start,
                duration_ticks=max(1, new_end - new_start),
                velocity=velocity,
            )
        )
    return result


# ------------------------------------------------------------ curves


@dataclass(frozen=True)
class ExpressionSettings:
    base: int = 96  # CC11 at phrase starts (127 = full volume)
    peak: int = 120  # CC11 at each phrase's high point
    swell: int = 10  # extra rise and fall inside held notes
    long_note_ticks: int = 960  # notes at least this long swell and get vibrato
    vibrato_depth: int = 40  # CC1 reached on held notes; 0 = leave vibrato alone
    vibrato_delay_ticks: int = 240  # straight tone before vibrato starts
    resolution_ticks: int = 60  # spacing of ramp steps

    def check(self) -> None:
        if not 0 <= self.base <= 127 or not 0 <= self.peak <= 127:
            raise ValueError("base and peak must be 0-127")
        if not 0 <= self.swell <= 40:
            raise ValueError("swell must be 0-40")
        if not 0 <= self.vibrato_depth <= 127:
            raise ValueError("vibrato_depth must be 0-127")
        if self.long_note_ticks < 1 or self.vibrato_delay_ticks < 0:
            raise ValueError("long_note_ticks must be >= 1 and vibrato_delay_ticks >= 0")
        if not 10 <= self.resolution_ticks <= 480:
            raise ValueError("resolution_ticks must be 10-480")


def expression_curves(
    notes: Sequence[Note],
    *,
    ppq: int,
    start: int,
    end: int,
    settings: ExpressionSettings,
) -> dict[str, list[tuple[int, int]]]:
    """Expression (CC11) and, unless ``vibrato_depth`` is 0, modulation (CC1) points.

    Every point lies in ``[start, end)``. Phrases swell toward their high point; held
    notes add their own swell and a delayed vibrato that fades in and stops at the
    next note.
    """
    settings.check()
    line = melodic_line([n for n in notes if start <= n.start_tick < end])
    expression: list[tuple[int, int]] = []
    modulation: list[tuple[int, int]] = []
    step = settings.resolution_ticks
    onsets = [n.start_tick for n in line]
    order = {onset: i for i, onset in enumerate(onsets)}
    for phrase in phrases(line, ppq):
        apex = apex_index(phrase)
        for index, note in enumerate(phrase):
            level = settings.base + (settings.peak - settings.base) * phrase_arc(
                index, len(phrase), apex
            )
            position = order[note.start_tick]
            next_onset = onsets[position + 1] if position + 1 < len(onsets) else None
            seg_end = min(note.end_tick, next_onset or note.end_tick, end)
            span = seg_end - note.start_tick
            held = note.duration_ticks >= settings.long_note_ticks and span >= step * 2
            if not held:
                expression.append((note.start_tick, _clamp(level, 0, 127)))
                modulation.append((note.start_tick, 0))
                continue
            low = level - settings.swell / 2
            high = level + settings.swell
            top = note.start_tick + round(span * 0.45)
            ramp = [(note.start_tick, low), (top, high), (seg_end - 1, low)]
            expression += [
                (t, _clamp(v, 0, 127))
                for t, v in interpolate([(t, round(v)) for t, v in ramp], step)
            ]
            vib_start = note.start_tick + settings.vibrato_delay_ticks
            modulation.append((note.start_tick, 0))
            if settings.vibrato_depth and vib_start < seg_end - step:
                full = vib_start + max(step, round((seg_end - vib_start) * 0.5))
                modulation += interpolate(
                    [(vib_start, 0), (min(full, seg_end - 1), settings.vibrato_depth)], step
                )
                if seg_end < end and seg_end != next_onset:
                    modulation.append((seg_end, 0))
    curves = {"expression": collapse(expression)}
    if settings.vibrato_depth:
        curves["modulation"] = collapse(modulation)
    return curves
