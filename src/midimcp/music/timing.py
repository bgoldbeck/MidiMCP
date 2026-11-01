"""Integer tick / tempo math.

Canonical time is integer ticks at a fixed PPQ (pulses per quarter note).
Tempo is integer microseconds per quarter note. BPM always means quarter-note
beats per minute, including compound meters such as 6/8.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Final

DEFAULT_PPQ: Final = 960
MICROSECONDS_PER_MINUTE: Final = 60_000_000


def bpm_to_tempo_us(bpm: float) -> int:
    """Quarter-note BPM to integer microseconds per quarter (rounded half-up)."""
    if bpm <= 0:
        raise ValueError("bpm must be positive")
    return int(Fraction(MICROSECONDS_PER_MINUTE) / Fraction(bpm) + Fraction(1, 2))


def tempo_us_to_bpm(tempo_us: int) -> float:
    if tempo_us <= 0:
        raise ValueError("tempo must be positive")
    return MICROSECONDS_PER_MINUTE / tempo_us


def ticks_per_bar(ppq: int, numerator: int, denominator: int) -> int:
    """Ticks in one bar. 6/8 at 960 PPQ -> 2880."""
    ticks = Fraction(ppq * 4 * numerator, denominator)
    if ticks.denominator != 1:
        raise ValueError(f"{numerator}/{denominator} bar is not a whole number of ticks at {ppq}")
    return int(ticks)


def bar_start_tick(bar_number: int, ppq: int, numerator: int, denominator: int) -> int:
    """First tick of 1-based ``bar_number``."""
    if bar_number < 1:
        raise ValueError("bars are 1-based")
    return (bar_number - 1) * ticks_per_bar(ppq, numerator, denominator)


def bar_range(
    first_bar: int, last_bar: int, ppq: int, numerator: int, denominator: int
) -> tuple[int, int]:
    """Half-open tick range covering 1-based bars ``first_bar..last_bar`` inclusive."""
    if last_bar < first_bar:
        raise ValueError("last_bar must be >= first_bar")
    per_bar = ticks_per_bar(ppq, numerator, denominator)
    return (first_bar - 1) * per_bar, last_bar * per_bar


def tick_to_bar_position(tick: int, ppq: int, numerator: int, denominator: int) -> tuple[int, int]:
    """Return (1-based bar, tick offset within bar)."""
    if tick < 0:
        raise ValueError("tick must be >= 0")
    per_bar = ticks_per_bar(ppq, numerator, denominator)
    return tick // per_bar + 1, tick % per_bar


def ticks_to_microseconds(ticks: int, ppq: int, tempo_us: int) -> Fraction:
    """Exact duration of ``ticks`` at a constant tempo, as a Fraction of microseconds."""
    return Fraction(ticks * tempo_us, ppq)


def ticks_to_seconds(ticks: int, ppq: int, tempo_us: int, speed: float = 1.0) -> float:
    """Wall-clock seconds for ``ticks``. ``speed`` > 1 plays faster (pitch unchanged)."""
    if speed <= 0:
        raise ValueError("speed must be positive")
    return float(ticks_to_microseconds(ticks, ppq, tempo_us) / Fraction(speed) / 1_000_000)


def seconds_to_ticks(seconds: float, ppq: int, tempo_us: int) -> int:
    """Nearest tick for a wall-clock offset at normal speed."""
    exact = Fraction(seconds) * 1_000_000 * ppq / tempo_us
    return int(exact + Fraction(1, 2))
