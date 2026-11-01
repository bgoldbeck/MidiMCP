"""Build tiny synthetic SoundFont files for tests (preset headers only)."""

from __future__ import annotations

import struct
from pathlib import Path


def _chunk(chunk_id: bytes, data: bytes) -> bytes:
    pad = b"\0" if len(data) % 2 else b""
    return chunk_id + struct.pack("<I", len(data)) + data + pad


def write_fake_sf2(path: Path, presets: list[tuple[str, int, int]]) -> Path:
    records = b"".join(
        struct.pack("<20sHHHIII", name.encode()[:20], program, bank, i, 0, 0, 0)
        for i, (name, bank, program) in enumerate(presets)
    )
    records += struct.pack("<20sHHHIII", b"EOP", 0, 0, len(presets), 0, 0, 0)
    info = _chunk(b"LIST", b"INFO" + _chunk(b"ifil", struct.pack("<HH", 2, 1)))
    sdta = _chunk(b"LIST", b"sdta" + _chunk(b"smpl", b"\0" * 16))
    pdta = _chunk(b"LIST", b"pdta" + _chunk(b"phdr", records))
    body = b"sfbk" + info + sdta + pdta
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def full_gm_presets() -> list[tuple[str, int, int]]:
    presets = [(f"GM {p}", 0, p) for p in range(128)]
    presets.append(("Standard", 128, 0))
    return presets
