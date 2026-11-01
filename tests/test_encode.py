from __future__ import annotations

import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from midimcp.encode import (
    EncodeError,
    EncoderUnavailable,
    encode_mp3,
    encoder_status,
)

HAS_LAME = shutil.which("lame") is not None


def sine_wav(path: Path, seconds: float = 1.0, rate: int = 48_000) -> Path:
    frames = b"".join(
        struct.pack("<hh", s, s)
        for s in (
            int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(int(rate * seconds))
        )
    )
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(frames)
    return path


@pytest.mark.skipif(not HAS_LAME, reason="lame not installed")
def test_encode_mp3_with_tags_and_bitrate(tmp_path: Path) -> None:
    wav = sine_wav(tmp_path / "in.wav", seconds=2)
    small = encode_mp3(wav, tmp_path / "a.mp3", bitrate=128, title="Lanterns", comment="revision 3")
    big = encode_mp3(wav, tmp_path / "b.mp3", bitrate=320)
    data = small.read_bytes()
    assert data[:3] == b"ID3" and b"TIT2" in data[:256]
    assert "Lanterns".encode("utf-16-le") in data[:256] or b"Lanterns" in data[:256]
    assert big.stat().st_size > small.stat().st_size * 2  # constant bitrate scales size
    assert not list(tmp_path.glob(".enc-*"))  # temp files cleaned up
    assert encoder_status()["mp3"] is True


def test_invalid_bitrate(tmp_path: Path) -> None:
    with pytest.raises(EncodeError):
        encode_mp3(tmp_path / "x.wav", tmp_path / "x.mp3", bitrate=96)


def test_missing_encoder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIDIMCP_LAME", "no-such-lame-binary")
    with pytest.raises(EncoderUnavailable) as caught:
        encode_mp3(sine_wav(tmp_path / "in.wav", 0.1), tmp_path / "x.mp3")
    assert caught.value.to_dict()["code"] == "ENCODER_UNAVAILABLE"
    assert encoder_status()["mp3"] is False


def test_rejects_non_wav_input(tmp_path: Path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wav file at all")
    with pytest.raises(EncodeError):
        encode_mp3(bad, tmp_path / "out.mp3")
    assert not (tmp_path / "out.mp3").exists()
