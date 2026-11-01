"""MP3 encoding of rendered WAV files with the LAME command-line encoder."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Final

MP3_BITRATES: Final = (128, 192, 256, 320)
DEFAULT_MP3_BITRATE: Final = 192
ENCODE_TIMEOUT_SECONDS: Final = 600


class EncodeError(RuntimeError):
    code = "ENCODE_FAILED"

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self)}


class EncoderUnavailable(EncodeError):
    code = "ENCODER_UNAVAILABLE"


def lame_binary() -> str | None:
    return shutil.which(os.environ.get("MIDIMCP_LAME", "lame"))


def encoder_status() -> dict:
    binary = lame_binary()
    if binary is None:
        return {"mp3": False, "error": "LAME encoder not installed"}
    version = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, timeout=30, check=False
    ).stdout.splitlines()
    return {"mp3": True, "encoder": version[0].strip() if version else "lame"}


def encode_mp3(
    wav: Path,
    target: Path,
    *,
    bitrate: int = DEFAULT_MP3_BITRATE,
    title: str | None = None,
    comment: str | None = None,
) -> Path:
    """Encode ``wav`` to a constant-bitrate MP3 at ``target`` (written atomically)."""
    if bitrate not in MP3_BITRATES:
        raise EncodeError(f"bitrate must be one of {', '.join(map(str, MP3_BITRATES))} kbps")
    binary = lame_binary()
    if binary is None:
        raise EncoderUnavailable(
            "MP3 export needs the LAME encoder (install the 'lame' package; the Docker image "
            "includes it)"
        )
    # LAME happily encodes any bytes as raw PCM noise, so insist on a real WAV first.
    try:
        with wave.open(str(wav), "rb") as reader:
            if reader.getnframes() == 0 or reader.getsampwidth() != 2:
                raise EncodeError(f"{wav.name} is not a 16-bit PCM WAV with audio")
    except (wave.Error, EOFError, OSError) as exc:
        raise EncodeError(f"{wav.name} is not a readable WAV file: {exc}") from exc
    command = [binary, "--quiet", "--noreplaygain", "-b", str(bitrate), "--cbr"]
    if title:
        command += ["--tt", title[:120]]
    command += ["--ta", "MidiMCP"]
    if comment:
        command += ["--tc", comment[:120]]
    fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".enc-", suffix=".mp3")
    os.close(fd)
    temp = Path(temp_name)
    try:
        completed = subprocess.run(
            [*command, str(wav), str(temp)],
            capture_output=True,
            text=True,
            timeout=ENCODE_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0 or temp.stat().st_size == 0:
            detail = (completed.stderr or completed.stdout).strip()[-400:]
            raise EncodeError(f"LAME failed (exit {completed.returncode}): {detail}")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target
