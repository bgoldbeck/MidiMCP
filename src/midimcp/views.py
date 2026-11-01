"""Shared read models and file operations for the MCP tools and the web API."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from midimcp.encode import DEFAULT_MP3_BITRATE, MP3_BITRATES, encode_mp3
from midimcp.midi import export_midi_bytes
from midimcp.model.score import Score
from midimcp.music.timing import tempo_us_to_bpm, ticks_per_bar, ticks_to_seconds
from midimcp.soundbanks import sound_profile_issues
from midimcp.validation import validate_score

if TYPE_CHECKING:
    from midimcp.context import AppContext

EXPORT_FORMATS = ("midi", "wav", "mp3", "json")
_EXPORT_NAME = re.compile(r"[^a-z0-9-]+")
_MEDIA_TYPES = {
    ".mid": "audio/midi",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".json": "application/json",
}


def timing(score: Score) -> dict[str, Any]:
    t = score.timeline
    per_bar = ticks_per_bar(t.ppq, t.meter.numerator, t.meter.denominator)
    return {
        "ppq": t.ppq,
        "ticksPerBar": per_bar,
        "bars": t.total_ticks / per_bar,
        "totalTicks": t.total_ticks,
        "tempoUsPerQuarter": t.tempo_us_per_quarter,
        "quarterNoteBpm": round(tempo_us_to_bpm(t.tempo_us_per_quarter), 3),
        "meter": f"{t.meter.numerator}/{t.meter.denominator}",
        "durationSeconds": round(ticks_to_seconds(t.total_ticks, t.ppq, t.tempo_us_per_quarter), 3),
    }


def project_view(ctx: AppContext, project_id: str, revision: int | None = None) -> dict[str, Any]:
    """Everything the UI needs to show one project."""
    snap = (
        ctx.store.load_revision(project_id, revision)
        if revision is not None
        else ctx.store.load(project_id)
    )
    report = validate_score(snap.score, snap.brief)
    report.issues += sound_profile_issues(snap.score, ctx.registry)
    return {
        "projectId": project_id,
        "revision": snap.revision,
        "timing": timing(snap.score),
        "score": snap.score.to_json_dict(),
        "brief": snap.brief.to_json_dict(),
        "validation": report.to_dict(),
        "lastChange": snap.info.to_dict(),
        "trackDefaults": ctx.service.track_defaults(project_id) if revision is None else {},
    }


def export_project(
    ctx: AppContext,
    project_id: str,
    fmt: str,
    *,
    revision: int | None = None,
    speed: float = 1.0,
    bitrate: int = DEFAULT_MP3_BITRATE,
) -> dict[str, Any]:
    """Write an export into the project's exports folder and describe it."""
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"format must be one of {', '.join(EXPORT_FORMATS)}")
    snap = (
        ctx.store.load_revision(project_id, revision)
        if revision is not None
        else ctx.store.load(project_id)
    )
    base = _EXPORT_NAME.sub("-", snap.score.metadata.title.lower()).strip("-") or "song"
    stem = f"{base[:60]}-r{snap.revision}"
    exports = ctx.store.project_dir(project_id) / "exports"
    exports.mkdir(exist_ok=True)
    if fmt == "midi":
        path = exports / f"{stem}.mid"
        path.write_bytes(export_midi_bytes(snap.score))
    elif fmt == "json":
        path = exports / f"{stem}.json"
        payload = {"score": snap.score.to_json_dict(), "brief": snap.brief.to_json_dict()}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        if fmt == "mp3" and bitrate not in MP3_BITRATES:
            raise ValueError(f"bitrate must be one of {', '.join(map(str, MP3_BITRATES))}")
        result = ctx.renderer.render(snap.score, speed=speed)
        suffix = "" if speed == 1.0 else f"-x{speed:g}"
        if fmt == "wav":
            path = exports / f"{stem}{suffix}.wav"
            path.write_bytes(result.path.read_bytes())
        else:
            path = encode_mp3(
                result.path,
                exports / f"{stem}{suffix}-{bitrate}k.mp3",
                bitrate=bitrate,
                title=snap.score.metadata.title,
                comment=f"revision {snap.revision}",
            )
    return export_entry(project_id, path, revision=snap.revision, fmt=fmt)


def export_entry(
    project_id: str, path, *, revision: int | None = None, fmt: str | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "projectId": project_id,
        "file": path.name,
        "sizeBytes": path.stat().st_size,
        "downloadPath": f"/api/projects/{project_id}/exports/{path.name}",
        "mediaType": media_type(path.name),
    }
    if revision is not None:
        data["revision"] = revision
    if fmt is not None:
        data["format"] = fmt
    return data


def list_exports(ctx: AppContext, project_id: str) -> list[dict[str, Any]]:
    directory = ctx.store.project_dir(project_id) / "exports"
    if not directory.is_dir():
        return []
    files = sorted(
        (p for p in directory.iterdir() if p.is_file() and p.suffix in _MEDIA_TYPES),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [export_entry(project_id, p) for p in files]


def media_type(name: str) -> str:
    for suffix, media in _MEDIA_TYPES.items():
        if name.endswith(suffix):
            return media
    return "application/octet-stream"
