from __future__ import annotations

import array
import shutil
import wave
from pathlib import Path

import pytest

from midimcp.model import Score
from midimcp.render import (
    RenderBlocked,
    Renderer,
    RenderError,
    RenderUnavailable,
    tick_to_frame,
)
from midimcp.soundbanks import DEFAULT_BANK_ID, SoundbankRegistry
from tests.sf2 import full_gm_presets, write_fake_sf2

FLUIDR3 = Path("/usr/share/sounds/sf2/FluidR3_GM.sf2")
needs_fluidsynth = pytest.mark.skipif(
    shutil.which("fluidsynth") is None or not FLUIDR3.is_file(),
    reason="fluidsynth and FluidR3_GM.sf2 required",
)


@pytest.fixture
def score(score_dict: dict) -> Score:
    score_dict["soundProfile"]["bankId"] = DEFAULT_BANK_ID
    return Score.model_validate(score_dict)


@pytest.fixture
def fake_registry(tmp_path: Path) -> SoundbankRegistry:
    system = tmp_path / "system"
    system.mkdir()
    write_fake_sf2(system / "FluidR3_GM.sf2", full_gm_presets())
    return SoundbankRegistry(tmp_path / "data", system_dir=system)


def peak(path: Path) -> int:
    with wave.open(str(path), "rb") as reader:
        samples = array.array("h", reader.readframes(reader.getnframes()))
    return max(abs(s) for s in samples)


def test_tick_to_frame(score: Score) -> None:
    # 6/8 @ 84 BPM: one bar (2880 ticks) = 2.142857 s.
    assert tick_to_frame(2880, score, 1.0, 48_000) == 102_857
    assert tick_to_frame(2880, score, 1.25, 48_000) == 82_286
    assert tick_to_frame(0, score, 1.0, 48_000) == 0


def test_blocked_by_soundbank_problems(tmp_path: Path, score_dict: dict) -> None:
    sparse = tmp_path / "sparse"
    sparse.mkdir()
    write_fake_sf2(sparse / "FluidR3_GM.sf2", [("Flute", 0, 73)])
    renderer = Renderer(SoundbankRegistry(tmp_path / "d", system_dir=sparse), tmp_path / "r")
    score_dict["soundProfile"]["bankId"] = DEFAULT_BANK_ID
    with pytest.raises(RenderBlocked) as caught:
        renderer.render(Score.model_validate(score_dict))
    assert [i.code for i in caught.value.issues] == ["PRESET_MISSING"]
    assert caught.value.to_dict()["code"] == "RENDER_BLOCKED"

    score_dict["soundProfile"]["bankId"] = "missing"
    with pytest.raises(RenderBlocked) as caught:
        renderer.render(Score.model_validate(score_dict))
    assert caught.value.issues[0].code == "BANK_NOT_FOUND"


def test_argument_checks(fake_registry: SoundbankRegistry, tmp_path: Path, score: Score) -> None:
    renderer = Renderer(fake_registry, tmp_path / "r")
    with pytest.raises(RenderError):
        renderer.render(score, speed=10)
    with pytest.raises(RenderError):
        renderer.render(score, start_tick=100, end_tick=100)
    muted = score.model_copy(
        update={"tracks": [t.model_copy(update={"mute": True}) for t in score.tracks]}
    )
    with pytest.raises(RenderBlocked):
        renderer.render(muted)


def test_missing_engine(fake_registry: SoundbankRegistry, tmp_path: Path, score: Score) -> None:
    renderer = Renderer(
        fake_registry,
        tmp_path / "r",
        fluidsynth="no-such-fluidsynth-binary",
        sfizz="no-such-sfizz-binary",
    )
    with pytest.raises(RenderUnavailable):
        renderer.render(score)
    assert renderer.status()["available"] is False


def test_sampler_only_status_is_available(fake_registry, tmp_path, monkeypatch):
    renderer = Renderer(fake_registry, tmp_path / "r")

    def missing_fluidsynth():
        raise RenderUnavailable("FluidSynth unavailable")

    monkeypatch.setattr(renderer, "engine_version", missing_fluidsynth)
    monkeypatch.setattr(renderer, "sampler_engine_identity", lambda: "test-sfizz")
    status = renderer.status()
    assert status["available"] is True
    assert status["engine"] is None
    assert status["samplerAvailable"] is True
    assert status["samplerEngine"] == "test-sfizz"


@needs_fluidsynth
def test_render_is_deterministic_and_audible(tmp_path: Path, score: Score) -> None:
    registry = SoundbankRegistry(tmp_path / "data")
    first = Renderer(registry, tmp_path / "a").render(score)
    second = Renderer(registry, tmp_path / "b").render(score)
    assert not first.cached and not second.cached
    assert first.pcm_sha256 == second.pcm_sha256
    assert first.sample_rate == 48_000 and first.channels == 2
    # 8 bars (17.143 s) + 2 s tail.
    assert first.duration_seconds == pytest.approx(19.143, abs=0.01)
    assert peak(first.path) > 1000


@needs_fluidsynth
def test_cache_hit(tmp_path: Path, score: Score) -> None:
    renderer = Renderer(SoundbankRegistry(tmp_path / "data"), tmp_path / "r")
    first = renderer.render(score)
    again = renderer.render(score.model_copy(update={"revision": 99}))
    assert again.cached and again.cache_key == first.cache_key
    assert renderer.write_metadata(again).is_file()


@needs_fluidsynth
def test_speed_changes_duration_not_pitch(tmp_path: Path, score: Score) -> None:
    renderer = Renderer(SoundbankRegistry(tmp_path / "data"), tmp_path / "r")
    normal = renderer.render(score)
    fast = renderer.render(score, speed=1.25)
    tail = renderer.profile.tail_seconds
    assert (fast.duration_seconds - tail) == pytest.approx(
        (normal.duration_seconds - tail) * 0.8, abs=0.001
    )
    assert fast.cache_key != normal.cache_key


@needs_fluidsynth
def test_region_render(tmp_path: Path, score: Score) -> None:
    renderer = Renderer(SoundbankRegistry(tmp_path / "data"), tmp_path / "r")
    region = renderer.render(score, start_tick=2880, end_tick=4 * 2880)
    assert region.frames == tick_to_frame(4 * 2880, score, 1.0, 48_000) - tick_to_frame(
        2880, score, 1.0, 48_000
    )


@needs_fluidsynth
def test_loop_render_has_exact_length_and_no_tail(tmp_path: Path, score: Score) -> None:
    renderer = Renderer(SoundbankRegistry(tmp_path / "data"), tmp_path / "r")
    loop = score.timeline.loop
    seamless = renderer.render(
        score, start_tick=loop.start_tick, end_tick=loop.end_tick, tail=False
    )
    expected = tick_to_frame(loop.end_tick, score, 1.0, 48_000) - tick_to_frame(
        loop.start_tick, score, 1.0, 48_000
    )
    assert seamless.frames == expected  # exactly the loop: repeats with no gap
    with_tail = renderer.render(score)
    assert with_tail.frames == expected + 2 * 48_000
    assert seamless.cache_key != with_tail.cache_key
