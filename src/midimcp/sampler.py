"""Allowlisted, fully content-addressed SFZ patches; playback never downloads assets."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

MANIFEST_PATH = Path(__file__).with_name("sampler_assets") / "manifest.json"


class SamplerError(ValueError):
    code = "SAMPLER_ERROR"

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self)}


@dataclass(frozen=True)
class SamplerPatch:
    id: str
    path: Path
    sha256: str


class SamplerRegistry:
    def __init__(self, data_dir: Path | str) -> None:
        self.root = Path(os.environ.get("MIDIMCP_SAMPLER_DIR", Path(data_dir) / "samplers"))
        self._patches = {
            p["id"]: p for p in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["patches"]
        }

    @staticmethod
    def _hash(patch: dict) -> str:
        # Include names as well as bytes; controller/wrapper settings are manifest inputs.
        return hashlib.sha256(
            json.dumps(patch, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def require(self, patch_id: str, sha256: str | None = None) -> SamplerPatch:
        if patch_id not in self._patches:
            raise SamplerError(f"unknown sampler patch {patch_id!r}")
        patch = self._patches[patch_id]
        digest = self._hash(patch)
        for name, expected in patch["files"].items():
            path = (self.root / name).resolve()
            if not path.is_relative_to(self.root.resolve()):
                raise SamplerError("sampler manifest contains an unsafe dependency path")
            if not path.is_file():
                raise SamplerError(f"sampler {patch_id}: missing dependency {name}")
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected:
                raise SamplerError(f"sampler {patch_id}: changed dependency {name}")
        if sha256 is not None and sha256 != digest:
            raise SamplerError(f"sampler {patch_id}: checksum differs from saved binding")
        return SamplerPatch(patch_id, self.root / patch["path"], digest)

    def list_patches(self) -> list[dict]:
        result = []
        for patch in self._patches.values():
            error = None
            try:
                self.require(patch["id"])
            except SamplerError as exc:
                error = str(exc)
            result.append(
                {key: patch[key] for key in ("id", "name", "controllers", "description")}
                | {"sha256": self._hash(patch), "available": error is None, "error": error}
            )
        return result
