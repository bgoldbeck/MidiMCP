"""Deterministic offline rendering: score -> MIDI -> FluidSynth -> WAV.

The render profile pins every setting that affects the audio. Under the same
FluidSynth binary, soundbank bytes and profile, rendering the same score content
twice yields byte-identical PCM. Results are cached under ``<data>/renders`` by a
key covering all of those inputs.

Playback speed is applied by scaling the tempo before rendering, so a 125%
render is 80% as long with unchanged pitch.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import wave
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Final

from midimcp.midi import export_midi_bytes
from midimcp.model.score import Score
from midimcp.soundbanks import SoundbankRegistry, sound_profile_issues
from midimcp.store.files import canonical_json_bytes
from midimcp.validation import Issue

MIN_SPEED: Final = 0.25
MAX_SPEED: Final = 4.0
RENDER_TIMEOUT_SECONDS: Final = 600


class RenderError(RuntimeError):
    code = "RENDER_FAILED"

    def __init__(self, message: str, issues: list[Issue] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []

    def to_dict(self) -> dict:
        data = {"code": self.code, "message": str(self)}
        if self.issues:
            data["issues"] = [i.to_dict() for i in self.issues]
        return data


class RenderUnavailable(RenderError):
    code = "RENDERER_UNAVAILABLE"


class RenderBlocked(RenderError):
    code = "RENDER_BLOCKED"


@dataclass(frozen=True)
class RenderProfile:
    """Every render-affecting synth setting. Changing any value is a new profile."""

    id: str = "retro-gm-1997-v1"
    sample_rate: int = 48_000
    gain: float = 0.5
    interpolation: int = 4  # FluidSynth 4th-order interpolation
    polyphony: int = 256
    reverb: bool = True
    reverb_room_size: float = 0.35
    reverb_damp: float = 0.4
    reverb_width: float = 0.6
    reverb_level: float = 0.35
    chorus: bool = True
    chorus_voices: int = 3
    chorus_level: float = 1.0
    chorus_speed: float = 0.3
    chorus_depth: float = 6.0
    tail_seconds: float = 2.0

    def fluidsynth_settings(self) -> list[str]:
        settings = {
            "synth.sample-rate": self.sample_rate,
            "synth.gain": self.gain,
            "synth.polyphony": self.polyphony,
            "synth.cpu-cores": 1,
            "synth.reverb.active": int(self.reverb),
            "synth.reverb.room-size": self.reverb_room_size,
            "synth.reverb.damp": self.reverb_damp,
            "synth.reverb.width": self.reverb_width,
            "synth.reverb.level": self.reverb_level,
            "synth.chorus.active": int(self.chorus),
            "synth.chorus.nr": self.chorus_voices,
            "synth.chorus.level": self.chorus_level,
            "synth.chorus.speed": self.chorus_speed,
            "synth.chorus.depth": self.chorus_depth,
            "audio.file.type": "wav",
            "audio.file.format": "s16",
            "player.reset-synth": 1,
        }
        args = []
        for key, value in settings.items():
            args += ["-o", f"{key}={value}"]
        return args


DEFAULT_RENDER_PROFILE: Final = RenderProfile()


@dataclass(frozen=True)
class RenderResult:
    path: Path
    cache_key: str
    pcm_sha256: str
    sample_rate: int
    channels: int
    frames: int
    speed: float
    start_tick: int
    end_tick: int
    cached: bool

    @property
    def duration_seconds(self) -> float:
        return self.frames / self.sample_rate

    def to_dict(self) -> dict:
        return {
            "cacheKey": self.cache_key,
            "file": self.path.name,
            "pcmSha256": self.pcm_sha256,
            "sampleRate": self.sample_rate,
            "channels": self.channels,
            "frames": self.frames,
            "durationSeconds": round(self.duration_seconds, 3),
            "speed": self.speed,
            "startTick": self.start_tick,
            "endTick": self.end_tick,
            "cached": self.cached,
        }


def pcm_sha256(path: Path) -> str:
    with wave.open(str(path), "rb") as reader:
        return hashlib.sha256(reader.readframes(reader.getnframes())).hexdigest()


def tick_to_frame(tick: int, score: Score, speed: float, sample_rate: int) -> int:
    """Exact sample frame for a tick at the scaled tempo (rounded to nearest)."""
    t = score.timeline
    seconds = Fraction(tick * t.tempo_us_per_quarter, t.ppq * 1_000_000) / Fraction(speed)
    return int(seconds * sample_rate + Fraction(1, 2))


class Renderer:
    def __init__(
        self,
        registry: SoundbankRegistry,
        cache_dir: Path | str,
        *,
        profile: RenderProfile = DEFAULT_RENDER_PROFILE,
        fluidsynth: str | None = None,
    ) -> None:
        self.registry = registry
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.profile = profile
        self.fluidsynth = fluidsynth or os.environ.get("MIDIMCP_FLUIDSYNTH", "fluidsynth")
        self._version: str | None = None
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- info

    def engine_version(self) -> str:
        if self._version is None:
            binary = shutil.which(self.fluidsynth)
            if binary is None:
                raise RenderUnavailable(f"FluidSynth executable {self.fluidsynth!r} not found")
            output = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=30, check=False
            ).stdout
            self._version = output.splitlines()[0].strip() if output else "unknown"
        return self._version

    def status(self) -> dict:
        try:
            return {
                "available": True,
                "engine": self.engine_version(),
                "profile": asdict(self.profile),
            }
        except RenderError as exc:
            return {"available": False, "error": str(exc), "profile": asdict(self.profile)}

    # --------------------------------------------------------------- render

    def render(
        self,
        score: Score,
        *,
        speed: float = 1.0,
        start_tick: int | None = None,
        end_tick: int | None = None,
        include_muted: bool = False,
    ) -> RenderResult:
        if not MIN_SPEED <= speed <= MAX_SPEED:
            raise RenderError(f"speed must be between {MIN_SPEED} and {MAX_SPEED}")
        total = score.timeline.total_ticks
        start = 0 if start_tick is None else start_tick
        end = total if end_tick is None else end_tick
        if not 0 <= start < end <= total:
            raise RenderError(f"render range must satisfy 0 <= start < end <= {total}")
        issues = sound_profile_issues(score, self.registry)
        if issues:
            raise RenderBlocked("soundbank problems prevent rendering", issues)
        if not any(t.notes for t in score.tracks if include_muted or not t.mute):
            raise RenderBlocked("nothing to render: no audible notes")

        bank = self.registry.require(score.sound_profile.bank_id, score.sound_profile.bank_sha256)
        key = self._cache_key(score, bank.sha256 or "", speed, start, end, include_muted)
        target = self.cache_dir / f"{key}.wav"
        with self._lock:
            if target.is_file():
                return self._result(target, key, score, speed, start, end, cached=True)
            self._render_to(target, score, Path(bank.path), speed, start, end, include_muted)
            return self._result(target, key, score, speed, start, end, cached=False)

    def _cache_key(
        self, score: Score, bank_sha: str, speed: float, start: int, end: int, muted: bool
    ) -> str:
        content = score.to_json_dict()
        content.pop("revision", None)
        content.pop("metadata", None)  # title/tags do not change the audio
        payload = {
            "score": content,
            "bankSha256": bank_sha,
            "profile": asdict(self.profile),
            "engine": self.engine_version(),
            "speed": repr(float(speed)),
            "range": [start, end],
            "includeMuted": muted,
            "format": "wav-s16",
        }
        return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()[:40]

    def _render_to(
        self,
        target: Path,
        score: Score,
        bank_path: Path,
        speed: float,
        start: int,
        end: int,
        include_muted: bool,
    ) -> None:
        t = score.timeline
        scaled = score.model_copy(
            update={
                "timeline": t.model_copy(
                    update={"tempo_us_per_quarter": max(1, round(t.tempo_us_per_quarter / speed))}
                )
            }
        )
        tail_ticks = round(
            self.profile.tail_seconds * 1_000_000 * t.ppq / scaled.timeline.tempo_us_per_quarter
        )
        midi_bytes = export_midi_bytes(scaled, include_muted=include_muted, tail_ticks=tail_ticks)
        binary = shutil.which(self.fluidsynth)
        if binary is None:
            raise RenderUnavailable(f"FluidSynth executable {self.fluidsynth!r} not found")
        with tempfile.TemporaryDirectory(dir=self.cache_dir, prefix=".render-") as work:
            work_dir = Path(work)
            midi_path = work_dir / "song.mid"
            raw_path = work_dir / "full.wav"
            midi_path.write_bytes(midi_bytes)
            command = [
                binary, "-ni", "-q", "-F", str(raw_path),
                "-r", str(self.profile.sample_rate),
                *self.profile.fluidsynth_settings(),
                str(bank_path), str(midi_path),
            ]  # fmt: skip
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=RENDER_TIMEOUT_SECONDS,
                check=False,
                cwd=work_dir,
            )
            if completed.returncode != 0 or not raw_path.is_file():
                detail = (completed.stderr or completed.stdout).strip()[-500:]
                raise RenderError(f"FluidSynth failed (exit {completed.returncode}): {detail}")
            sliced = work_dir / "out.wav"
            self._slice(raw_path, sliced, score, speed, start, end, tail=end == t.total_ticks)
            os.replace(sliced, target)

    def _slice(
        self,
        source: Path,
        dest: Path,
        score: Score,
        speed: float,
        start: int,
        end: int,
        *,
        tail: bool,
    ) -> None:
        with wave.open(str(source), "rb") as reader:
            params = reader.getparams()
            rate = reader.getframerate()
            total_frames = reader.getnframes()
            first = min(tick_to_frame(start, score, speed, rate), total_frames)
            last = tick_to_frame(end, score, speed, rate)
            if tail:
                last += round(self.profile.tail_seconds * rate)
            last = min(max(last, first), total_frames)
            reader.setpos(first)
            frames = reader.readframes(last - first)
        with wave.open(str(dest), "wb") as writer:
            writer.setparams(params)
            writer.writeframes(frames)

    def _result(
        self,
        path: Path,
        key: str,
        score: Score,
        speed: float,
        start: int,
        end: int,
        *,
        cached: bool,
    ) -> RenderResult:
        with wave.open(str(path), "rb") as reader:
            rate, channels, frames = (
                reader.getframerate(),
                reader.getnchannels(),
                reader.getnframes(),
            )
        return RenderResult(
            path=path,
            cache_key=key,
            pcm_sha256=pcm_sha256(path),
            sample_rate=rate,
            channels=channels,
            frames=frames,
            speed=speed,
            start_tick=start,
            end_tick=end,
            cached=cached,
        )

    def write_metadata(self, result: RenderResult) -> Path:
        meta = result.path.with_suffix(".json")
        meta.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        return meta
