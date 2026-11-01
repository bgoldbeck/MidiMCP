import pytest

from midimcp.music.timing import (
    bar_range,
    bar_start_tick,
    bpm_to_tempo_us,
    seconds_to_ticks,
    tempo_us_to_bpm,
    tick_to_bar_position,
    ticks_per_bar,
    ticks_to_seconds,
)


def test_84_bpm_tempo() -> None:
    assert bpm_to_tempo_us(84) == 714286
    assert tempo_us_to_bpm(714286) == pytest.approx(84, abs=1e-4)
    assert bpm_to_tempo_us(120) == 500_000


@pytest.mark.parametrize(
    ("num", "den", "ticks"),
    [(4, 4, 3840), (3, 4, 2880), (6, 8, 2880), (2, 2, 3840), (7, 8, 3360), (12, 8, 5760)],
)
def test_ticks_per_bar(num: int, den: int, ticks: int) -> None:
    assert ticks_per_bar(960, num, den) == ticks


def test_32_bars_of_six_eight_at_84() -> None:
    tempo = bpm_to_tempo_us(84)
    total = 32 * ticks_per_bar(960, 6, 8)
    assert total == 92_160
    assert ticks_to_seconds(total, 960, tempo) == pytest.approx(68.57, abs=0.01)


def test_speed_multiplier_scales_duration_only() -> None:
    tempo = bpm_to_tempo_us(84)
    normal = ticks_to_seconds(92_160, 960, tempo)
    fast = ticks_to_seconds(92_160, 960, tempo, speed=1.25)
    assert fast == pytest.approx(normal * 0.8)
    with pytest.raises(ValueError):
        ticks_to_seconds(1, 960, tempo, speed=0)


def test_bars_9_to_16_range() -> None:
    assert bar_start_tick(9, 960, 6, 8) == 23_040
    assert bar_range(9, 16, 960, 6, 8) == (23_040, 46_080)
    with pytest.raises(ValueError):
        bar_start_tick(0, 960, 6, 8)


def test_tick_to_bar_position() -> None:
    assert tick_to_bar_position(0, 960, 6, 8) == (1, 0)
    assert tick_to_bar_position(23_040, 960, 6, 8) == (9, 0)
    assert tick_to_bar_position(23_041, 960, 6, 8) == (9, 1)


def test_seconds_round_trip() -> None:
    tempo = bpm_to_tempo_us(84)
    assert seconds_to_ticks(ticks_to_seconds(23_040, 960, tempo), 960, tempo) == 23_040


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        bpm_to_tempo_us(0)
    with pytest.raises(ValueError):
        ticks_per_bar(1, 3, 32)
