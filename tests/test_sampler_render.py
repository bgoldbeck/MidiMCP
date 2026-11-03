import array
import wave
from pathlib import Path

import pytest

from midimcp.model import Score
from midimcp.model.score import SamplerBinding
from midimcp.render import Renderer, RenderProfile, tick_to_frame
from midimcp.sampler import SamplerPatch
from midimcp.soundbanks import SoundbankRegistry


def write_wave(path, samples, rate=48000):
    with wave.open(str(path), "wb") as writer:
        writer.setparams((2, 2, rate, 0, "NONE", "not compressed"))
        writer.writeframes(array.array("h", samples).tobytes())


class Registry:
    def require(self, patch_id, sha256=None):
        return SamplerPatch(patch_id, Path("fake.sfz"), "a" * 64)


def sampled_score(score_dict):
    score = Score.model_validate(score_dict)
    binding = SamplerBinding(patch_id="vsco-flute-controlled", patch_sha256="a" * 64)
    score.tracks[0] = score.tracks[0].model_copy(update={"sampler": binding})
    return score


def test_sampled_without_bank_or_fluidsynth_exact_range(tmp_path, score_dict, monkeypatch):
    score = sampled_score(score_dict)
    score.tracks = score.tracks[:1]
    renderer = Renderer(
        SoundbankRegistry(tmp_path),
        tmp_path / "r",
        samplers=Registry(),
        fluidsynth="missing",
        profile=RenderProfile(tail_seconds=0.1),
    )
    monkeypatch.setattr(renderer, "sampler_engine_identity", lambda: "fake-sfizz")
    monkeypatch.setattr(renderer, "_sampled_cache_key", lambda *args: "sample-key")

    def sample(path, stem_score, patch, speed):
        assert len(stem_score.tracks) == 1
        assert len(stem_score.tracks[0].automation.expression) == len(
            score.tracks[0].automation.expression
        )
        write_wave(path, [100, -100] * 100)

    monkeypatch.setattr(renderer, "_render_sample", sample)
    result = renderer.render(score, start_tick=960, end_tick=1920, speed=1.25, tail=False)
    assert result.frames == tick_to_frame(1920, score, 1.25, 48000) - tick_to_frame(
        960, score, 1.25, 48000
    )
    assert renderer.render(score, start_tick=960, end_tick=1920, speed=1.25, tail=False).cached


def test_mix_accumulates_then_saturates_and_reports_clipping(tmp_path):
    renderer = Renderer(SoundbankRegistry(tmp_path), tmp_path / "r")
    paths = [tmp_path / f"{i}.wav" for i in range(3)]
    for path, samples in zip(
        paths,
        [[30000, -30000, 10, 20], [30000, -30000, 30, 40], [-30000, 30000, 50, 60]],
        strict=True,
    ):
        write_wave(path, samples)
    out = tmp_path / "out.wav"
    assert renderer._mix_stems(paths, out, first=0, frames=3) == 0
    with wave.open(str(out), "rb") as reader:
        assert array.array("h", reader.readframes(3)).tolist() == [30000, -30000, 90, 120, 0, 0]
    assert renderer._mix_stems(paths[:2], out, first=0, frames=2) == 2
    with wave.open(str(out), "rb") as reader:
        assert array.array("h", reader.readframes(2)).tolist() == [32767, -32768, 40, 60]


def test_mixed_stems_gm_group_sample_separate_and_controller_history(
    tmp_path, score_dict, monkeypatch
):
    from midimcp.model.score import Automation, ControlPoint

    score = sampled_score(score_dict)
    track = score.tracks[0]
    track.automation = Automation(expression=[ControlPoint(tick=0, value=40)])
    score.tracks.append(track.model_copy(update={"id": "flute-2"}))
    renderer = Renderer(SoundbankRegistry(tmp_path), tmp_path / "r", samplers=Registry())
    monkeypatch.setattr(renderer, "_sampled_cache_key", lambda *args: "mixed-key")
    monkeypatch.setattr("midimcp.render.sound_profile_issues", lambda *args: [])
    monkeypatch.setattr(
        renderer.registry,
        "require",
        lambda *args: type("Bank", (), {"sha256": "b", "path": "fake.sf2"})(),
    )
    calls = []

    def gm(path, stem_score, *args):
        assert [t.id for t in stem_score.tracks] == ["lute-1"]
        calls.append("gm")
        write_wave(path, [10, 20] * 100000)

    def sample(path, stem_score, patch, speed):
        assert len(stem_score.tracks) == 1
        assert stem_score.tracks[0].automation.expression[0].tick == 0
        assert stem_score.tracks[0].gain_db == track.gain_db
        calls.append(stem_score.tracks[0].id)
        write_wave(path, [30, 40] * 100000)

    monkeypatch.setattr(renderer, "_render_to", gm)
    monkeypatch.setattr(renderer, "_render_sample", sample)
    result = renderer.render(score, start_tick=960, end_tick=1920, tail=False)
    assert calls == ["gm", "flute-1", "flute-2"]
    with wave.open(str(result.path), "rb") as reader:
        assert array.array("h", reader.readframes(1)).tolist() == [70, 100]


def test_native_flute_fresh_process_equality_and_controllers(tmp_path, score_dict):
    import json
    import math
    import os
    import subprocess
    import sys

    binary = os.environ.get("MIDIMCP_TEST_SFIZZ")
    if not binary or not os.environ.get("MIDIMCP_SAMPLER_DIR"):
        pytest.skip("set MIDIMCP_TEST_SFIZZ and MIDIMCP_SAMPLER_DIR for native sampler test")
    from midimcp.sampler import SamplerRegistry

    registry = SamplerRegistry(tmp_path)
    patch = registry.require("vsco-flute-controlled")
    score_dict["schemaVersion"] = "1.2.0"
    score_dict["sections"] = []
    score_dict["timeline"].update(totalTicks=5760, loop={"enabled": False})
    score_dict["tracks"] = [score_dict["tracks"][0]]
    track = score_dict["tracks"][0]
    track["sampler"] = {"patchId": patch.id, "patchSha256": patch.sha256}
    track["gainDb"] = 0
    track["notes"] = [
        {"id": "held", "pitch": 74, "startTick": 0, "durationTicks": 4800, "velocity": 70}
    ]
    script = """
import json,sys
from pathlib import Path
from midimcp.model import Score
from midimcp.render import Renderer
from midimcp.sampler import SamplerRegistry
from midimcp.soundbanks import SoundbankRegistry
root=Path(sys.argv[2])
r=Renderer(SoundbankRegistry(root),root, samplers=SamplerRegistry(root),
           sfizz=sys.argv[3],fluidsynth='missing')
print(r.render(Score.model_validate(json.loads(Path(sys.argv[1]).read_text())),
               **json.loads(sys.argv[4])).path)
"""

    def render(name, expression=127, modulation=0, gain=0, pan=0, recorded=False, **options):
        selected = registry.require("vsco-flute-recorded" if recorded else patch.id)
        track["sampler"] = {"patchId": selected.id, "patchSha256": selected.sha256}
        track["gainDb"] = gain
        track["pan"] = pan
        track["automation"] = {
            "expression": [{"tick": 0, "value": expression}],
            "modulation": [{"tick": 0, "value": modulation}],
        }
        source = tmp_path / f"{name}.json"
        source.write_text(json.dumps(score_dict))
        out = subprocess.check_output(
            [
                sys.executable,
                "-c",
                script,
                str(source),
                str(tmp_path / name),
                binary,
                json.dumps(options),
            ],
            text=True,
        )
        path = Path(out.strip().splitlines()[-1])
        with wave.open(str(path), "rb") as reader:
            samples = array.array("h", reader.readframes(reader.getnframes()))
        return samples

    a, b = render("first"), render("second")
    assert a == b
    score = Score.model_validate(score_dict)
    expected = tick_to_frame(5760, score, 1.0, 48000) + 2 * 48000
    assert len(a) == expected * 2
    low = render("quiet", expression=30)
    vibrato = render("vibrato", modulation=127)

    def rms(samples):
        return math.sqrt(sum(x * x for x in samples) / len(samples))

    assert rms(a) > 50
    assert rms(low) < rms(a) * 0.5
    assert a != vibrato
    gain = render("gain", gain=-6)
    assert 0.35 < rms(gain) / rms(a) < 0.65
    left = render("left", pan=-1)
    assert rms(left[::2]) > 10 * rms(left[1::2])
    recorded_a = render("recorded-first", recorded=True)
    recorded_b = render("recorded-second", recorded=True)
    assert recorded_a == recorded_b
    assert rms(recorded_a) > 50
    speedy = render("speedy", speed=1.25, tail=False)
    region = render("region", speed=1.25, start_tick=960, end_tick=3840, tail=False)
    first = tick_to_frame(960, score, 1.25, 48000)
    last = tick_to_frame(3840, score, 1.25, 48000)
    assert region == speedy[first * 2 : last * 2]


def test_muted_and_empty_sources_do_not_require_engines_or_assets(
    tmp_path, score_dict, monkeypatch
):
    score = sampled_score(score_dict)
    score.tracks[0].mute = True
    renderer = Renderer(SoundbankRegistry(tmp_path), tmp_path / "r", sfizz="missing")
    monkeypatch.setattr("midimcp.render.sound_profile_issues", lambda *args: [])
    monkeypatch.setattr(
        renderer.registry,
        "require",
        lambda *args: type("Bank", (), {"sha256": "b", "path": "fake.sf2"})(),
    )
    monkeypatch.setattr(renderer, "engine_version", lambda: "fake-gm")

    def gm(path, *args):
        write_wave(path, [10, 20] * 100)

    monkeypatch.setattr(renderer, "_render_to", gm)
    assert renderer.render(score, end_tick=960, tail=False).frames > 0
    # An empty GM track in an otherwise sampled song must not trigger bank validation.
    score.tracks[0].mute = False
    score.tracks[1].notes = []
    renderer.samplers = Registry()
    monkeypatch.setattr(renderer, "sampler_engine_identity", lambda: "fake-sfizz")
    monkeypatch.setattr(renderer.registry, "require", lambda *args: pytest.fail("bank lookup"))

    def sample(path, *args):
        write_wave(path, [30, 40] * 100)

    monkeypatch.setattr(renderer, "_render_sample", sample)
    assert renderer.render(score, end_tick=960, tail=False).frames > 0


def test_sample_cache_includes_engine_assets_settings_and_range(tmp_path, score_dict, monkeypatch):
    score = sampled_score(score_dict)
    renderer = Renderer(SoundbankRegistry(tmp_path), tmp_path / "r", samplers=Registry())
    monkeypatch.setattr(renderer, "sampler_engine_identity", lambda: "engine-one")
    args = [score, {"flute-1": "a" * 64}, None, 1.0, 0, 960, False, False]
    first = renderer._sampled_cache_key(*args)
    args[1] = {"flute-1": "b" * 64}
    assert first != renderer._sampled_cache_key(*args)
    args[1] = {"flute-1": "a" * 64}
    monkeypatch.setattr(renderer, "sampler_engine_identity", lambda: "engine-two")
    assert first != renderer._sampled_cache_key(*args)
    monkeypatch.setattr(renderer, "sampler_engine_identity", lambda: "engine-one")
    args[3] = 1.25
    assert first != renderer._sampled_cache_key(*args)


@pytest.mark.parametrize(
    "patch_id,original,trim",
    [
        ("vsco-flute-controlled", "FluteSusNV.sfz", 3),
        ("vsco-flute-recorded", "FluteExpVib.sfz", 8),
    ],
)
def test_native_source_trim_and_full_velocity_mono_headroom(
    tmp_path, score_dict, patch_id, original, trim
):
    import math
    import os

    from midimcp.sampler import SamplerRegistry

    binary = os.environ.get("MIDIMCP_TEST_SFIZZ")
    if not binary or not os.environ.get("MIDIMCP_SAMPLER_DIR"):
        pytest.skip("set native sampler test environment")
    registry = SamplerRegistry(tmp_path)
    patch = registry.require(patch_id)
    score_dict["schemaVersion"] = "1.2.0"
    score_dict["sections"] = []
    score_dict["timeline"].update(
        totalTicks=38 * 960, tempoUsPerQuarter=500000, loop={"enabled": False}
    )
    score_dict["tracks"] = [score_dict["tracks"][0]]
    track = score_dict["tracks"][0]
    track.update(gainDb=0, pan=0, sampler={"patchId": patch.id, "patchSha256": patch.sha256})
    track["notes"] = [
        {
            "id": f"n{pitch}",
            "pitch": pitch,
            "startTick": (pitch - 60) * 960,
            "durationTicks": 960,
            "velocity": 127,
        }
        for pitch in range(60, 97)
    ]
    score = Score.model_validate(score_dict)
    renderer = Renderer(
        SoundbankRegistry(tmp_path), tmp_path / "r", samplers=registry, sfizz=binary
    )
    calibrated = renderer.render(score)
    raw_path = tmp_path / "original.wav"
    renderer._render_sample(
        raw_path, score, SamplerPatch("original", patch.path.parent / original, ""), 1
    )

    def samples(path):
        with wave.open(str(path), "rb") as reader:
            return array.array("h", reader.readframes(reader.getnframes()))

    calibrated_again = Renderer(
        SoundbankRegistry(tmp_path), tmp_path / "fresh", samplers=registry, sfizz=binary
    ).render(score)
    adjusted, raw = samples(calibrated.path), samples(raw_path)
    assert adjusted == samples(calibrated_again.path)
    ratio_db = 10 * math.log10(sum(x * x for x in adjusted) / sum(x * x for x in raw))
    assert abs(ratio_db - trim) < 0.05
    assert max(abs(x) for x in adjusted) < 32767
    assert calibrated.clipped_samples == 0
