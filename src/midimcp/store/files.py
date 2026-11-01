"""Durable file primitives: canonical JSON, hashing, atomic and exclusive writes."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def canonical_json_bytes(data: Any) -> bytes:
    """Compact, key-sorted UTF-8 JSON used for content hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def pretty_json_bytes(data: Any) -> bytes:
    """Human-readable JSON written to disk (stable key order, LF newlines)."""
    text = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    return text.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(score: dict, brief: dict) -> str:
    """Hash of a project's semantic content, independent of file formatting."""
    return sha256_hex(canonical_json_bytes({"brief": brief, "score": score}))


def read_json(path: Path) -> Any:
    with path.open("rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def _fsync_directory(directory: Path) -> None:
    if sys.platform == "win32":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_temp(directory: Path, data: bytes) -> Path:
    fd, name = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise
    return Path(name)


def atomic_write(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` so readers see the old or new file, never a mix."""
    temp = _write_temp(path.parent, data)
    try:
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise
    _fsync_directory(path.parent)


def write_exclusive(path: Path, data: bytes) -> None:
    """Atomically create ``path``; raise ``FileExistsError`` if it already exists.

    The file appears fully written or not at all, and two writers racing for the
    same path cannot both succeed. POSIX uses ``link`` (fails on existing target);
    Windows ``rename`` already refuses to overwrite.
    """
    temp = _write_temp(path.parent, data)
    try:
        if sys.platform == "win32":
            os.rename(temp, path)
        else:
            os.link(temp, path)
            os.unlink(temp)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise
    _fsync_directory(path.parent)
