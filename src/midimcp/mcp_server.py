"""MCP adapter: typed tools over the composition service, renderer and registry.

The adapter owns no data. Every mutation goes through ``CompositionService``
with ``author="agent"``. Agents cannot install soundbanks, unlock material, read
arbitrary files, or run commands.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Callable
from importlib import resources
from typing import Annotated, Any, Literal, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from midimcp import __version__
from midimcp.context import AppContext
from midimcp.instruments import UnknownInstrument
from midimcp.midi import MidiExportError, export_midi_bytes
from midimcp.model.brief import Brief
from midimcp.model.schema import brief_json_schema, score_json_schema
from midimcp.model.score import Score
from midimcp.music.theory import TheoryError
from midimcp.music.timing import bar_range, tempo_us_to_bpm, ticks_per_bar, ticks_to_seconds
from midimcp.render import RenderError
from midimcp.soundbanks import DEFAULT_BANK_ID, SoundbankError, sound_profile_issues
from midimcp.store.errors import StoreError
from midimcp.validation import MAX_DURATION_SECONDS, MAX_NOTES, MAX_TRACKS, validate_score

INSTRUCTIONS = """\
MidiMCP composes original 1990s General-MIDI-style fantasy RPG music. Read the
resource midimcp://guide first. Workflow: list_instruments -> create_project ->
set_arrangement -> add_track -> replace_notes (by bar range) -> validate_project
-> render_preview. Every mutation needs expected_revision (the latest revision
you received). Locked material is protected: never try to bypass LOCKED errors.
"""

F = TypeVar("F", bound=Callable[..., Any])


class NoteIn(BaseModel):
    """A note to write. Ticks are absolute positions in the song."""

    pitch: Annotated[int, Field(ge=0, le=127, description="MIDI pitch, 60 = middle C")]
    startTick: Annotated[int, Field(ge=0)]
    durationTicks: Annotated[int, Field(ge=1)]
    velocity: Annotated[int, Field(ge=1, le=127)] = 80
    id: str | None = Field(default=None, description="Optional; generated when omitted")


class NoteEdit(BaseModel):
    op: Literal["add", "update", "delete"]
    noteId: str | None = Field(default=None, description="Required for update/delete")
    trackId: str | None = Field(default=None, description="Required for add")
    note: NoteIn | None = Field(default=None, description="Required for add")
    pitch: int | None = None
    startTick: int | None = None
    durationTicks: int | None = None
    velocity: int | None = None


class SectionIn(BaseModel):
    id: str
    label: str
    startTick: int
    endTick: int


class HarmonyIn(BaseModel):
    startTick: int
    durationTicks: int
    symbol: str = Field(description="Chord symbol, e.g. Ab, Fm, Db, Eb7")
    romanNumeral: str | None = Field(default=None, description="e.g. I, vi, IV, V")


def _tool_errors(func: F) -> F:
    """Turn domain errors into MCP tool errors carrying a JSON {code, message, ...} body."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except (StoreError, SoundbankError, RenderError, MidiExportError) as exc:
            raise ToolError(json.dumps(exc.to_dict())) from exc
        except (UnknownInstrument, TheoryError, ValueError) as exc:
            code = getattr(exc, "code", "INVALID_ARGUMENT")
            raise ToolError(json.dumps({"code": code, "message": str(exc)})) from exc

    return wrapper  # type: ignore[return-value]


def _timing(score: Score) -> dict[str, Any]:
    t = score.timeline
    per_bar = ticks_per_bar(t.ppq, t.meter.numerator, t.meter.denominator)
    return {
        "ppq": t.ppq,
        "ticksPerBar": per_bar,
        "bars": t.total_ticks / per_bar,
        "totalTicks": t.total_ticks,
        "quarterNoteBpm": round(tempo_us_to_bpm(t.tempo_us_per_quarter), 3),
        "meter": f"{t.meter.numerator}/{t.meter.denominator}",
        "durationSeconds": round(ticks_to_seconds(t.total_ticks, t.ppq, t.tempo_us_per_quarter), 3),
    }


def _range(score: Score, start_bar, end_bar, start_tick, end_tick) -> tuple[int, int]:
    if start_bar is not None or end_bar is not None:
        if start_bar is None or end_bar is None:
            raise ToolError(
                json.dumps({"code": "INVALID_RANGE", "message": "give both start_bar and end_bar"})
            )
        t = score.timeline
        return bar_range(start_bar, end_bar, t.ppq, t.meter.numerator, t.meter.denominator)
    if start_tick is None or end_tick is None:
        raise ToolError(
            json.dumps(
                {
                    "code": "INVALID_RANGE",
                    "message": "give start_bar/end_bar or start_tick/end_tick",
                }
            )
        )
    return start_tick, end_tick


_EXPORT_NAME = re.compile(r"[^a-z0-9-]+")


def build_mcp_server(ctx: AppContext) -> MCPServer:
    server = MCPServer(
        name="midimcp",
        title="MidiMCP Retro Composer",
        version=__version__,
        instructions=INSTRUCTIONS,
    )
    service = ctx.service

    # ------------------------------------------------------------ resources

    @server.resource("midimcp://guide", name="Composer guide", mime_type="text/markdown")
    def guide() -> str:
        return resources.files("midimcp.resources").joinpath("agent_guide.md").read_text("utf-8")

    @server.resource(
        "midimcp://schema/score", name="Score JSON Schema", mime_type="application/json"
    )
    def score_schema() -> str:
        return json.dumps(score_json_schema())

    @server.resource(
        "midimcp://schema/brief", name="Brief JSON Schema", mime_type="application/json"
    )
    def brief_schema() -> str:
        return json.dumps(brief_json_schema())

    # ------------------------------------------------------------ discovery

    @server.tool()
    @_tool_errors
    def list_capabilities() -> dict[str, Any]:
        """Versions, limits, supported modes/meters, and audio engine status."""
        from midimcp.model.score import SCORE_SCHEMA_VERSION
        from midimcp.music.theory import MODES

        return {
            "serverVersion": __version__,
            "scoreSchemaVersion": SCORE_SCHEMA_VERSION,
            "limits": {
                "maxTracks": MAX_TRACKS,
                "maxNotes": MAX_NOTES,
                "maxDurationSeconds": MAX_DURATION_SECONDS,
            },
            "modes": list(MODES),
            "meterDenominators": [1, 2, 4, 8, 16, 32],
            "defaultBankId": DEFAULT_BANK_ID,
            "audio": ctx.renderer.status(),
            "exportFormats": ["midi", "wav", "json"],
        }

    @server.tool()
    @_tool_errors
    def list_soundbanks() -> dict[str, Any]:
        """Installed soundbanks with license and availability. Agents cannot install banks."""
        return {"banks": [b.to_dict() for b in ctx.registry.list_banks()]}

    @server.tool()
    @_tool_errors
    def list_instruments(
        bank_id: str = DEFAULT_BANK_ID, search: str | None = None
    ) -> dict[str, Any]:
        """Exact instrument IDs usable in tracks, with GM program and availability in the bank."""
        return {"bankId": bank_id, "instruments": ctx.registry.instruments(bank_id, search)}

    @server.tool()
    @_tool_errors
    def list_projects(search: str | None = None) -> dict[str, Any]:
        """Projects (songs) with title, usage, tags and head revision."""
        return {"projects": service.list_projects(search)}

    @server.tool()
    @_tool_errors
    def get_project(
        project_id: str,
        track_ids: list[str] | None = None,
        start_bar: int | None = None,
        end_bar: int | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        """Score, brief (incl. locks) and timing. Optionally filter tracks and a bar range
        (notes whose start is inside the bars)."""
        snap = (
            ctx.store.load_revision(project_id, revision)
            if revision is not None
            else service.get_project(project_id)
        )
        score = snap.score.to_json_dict()
        if track_ids is not None:
            score["tracks"] = [t for t in score["tracks"] if t["id"] in track_ids]
        if start_bar is not None or end_bar is not None:
            lo, hi = _range(snap.score, start_bar or 1, end_bar or start_bar or 1, None, None)
            for track in score["tracks"]:
                track["notes"] = [n for n in track["notes"] if lo <= n["startTick"] < hi]
        return {
            "projectId": project_id,
            "revision": snap.revision,
            "timing": _timing(snap.score),
            "score": score,
            "brief": snap.brief.to_json_dict(),
        }

    @server.tool()
    @_tool_errors
    def list_revisions(project_id: str) -> dict[str, Any]:
        """Revision history with authors and change summaries."""
        return {"projectId": project_id, "revisions": service.list_revisions(project_id)}

    # ------------------------------------------------------------- mutation

    @server.tool()
    @_tool_errors
    def create_project(
        title: str,
        tempo_bpm: Annotated[float, Field(description="Quarter-note beats per minute")],
        meter_numerator: int,
        meter_denominator: int,
        tonic: Annotated[str, Field(description="Key tonic, e.g. G#, Ab, D, Bb")],
        mode: Annotated[
            str,
            Field(
                description="ionian/major, dorian, phrygian, lydian, "
                "mixolydian, aeolian/minor, locrian"
            ),
        ] = "ionian",
        bars: Annotated[int, Field(ge=1, description="Song length in bars")] = 32,
        loop: bool = True,
        usage: str | None = None,
        tags: list[str] | None = None,
        bank_id: str = DEFAULT_BANK_ID,
        percussion_allowed: bool = True,
        allowed_instrument_ids: list[str] | None = None,
        max_tracks: int | None = None,
        harmonic_strictness: Literal["strict", "advisory"] = "advisory",
        chord_plan: list[str] | None = None,
        mood: str | None = None,
        setting: str | None = None,
        references: list[str] | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Create an empty song. Returns projectId, revision (1) and timing (ticksPerBar...)."""
        bank = ctx.registry.require(bank_id)
        brief = Brief.model_validate(
            {
                "percussionAllowed": percussion_allowed,
                "allowedInstrumentIds": allowed_instrument_ids,
                "maxTracks": max_tracks,
                "harmonicStrictness": harmonic_strictness,
                "chordPlan": chord_plan or [],
                "mood": mood,
                "setting": setting,
                "references": references or [],
                "loopRequired": loop,
            }
        )
        result = service.create_project(
            title=title,
            tempo_bpm=tempo_bpm,
            meter=(meter_numerator, meter_denominator),
            tonic=tonic,
            mode=mode,
            bars=bars,
            usage=usage,
            tags=tags or [],
            loop=loop,
            bank_id=bank.id,
            bank_sha256=bank.sha256,
            brief=brief,
            author="agent",
            operation_id=operation_id,
        )
        snap = service.get_project(result.project_id)
        return {
            **result.to_dict(),
            "timing": _timing(snap.score),
            "key": snap.score.tonality.to_json_dict(),
        }

    @server.tool()
    @_tool_errors
    def set_arrangement(
        project_id: str,
        expected_revision: int,
        sections: list[SectionIn] | None = None,
        harmony: list[HarmonyIn] | None = None,
        bars: int | None = None,
        loop_start_bar: int | None = None,
        loop_end_bar: int | None = None,
        loop_enabled: bool | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Replace sections and/or harmony, change length in bars, or set the loop (bars,
        1-based inclusive)."""
        snap = service.get_project(project_id)
        loop = None
        if loop_enabled is not None or loop_start_bar is not None or loop_end_bar is not None:
            current = snap.score.timeline.loop
            start, end = current.start_tick, current.end_tick
            if loop_start_bar is not None or loop_end_bar is not None:
                start, end = _range(snap.score, loop_start_bar, loop_end_bar, None, None)
            loop = {
                "enabled": current.enabled if loop_enabled is None else loop_enabled,
                "startTick": start,
                "endTick": end,
            }
        return service.set_arrangement(
            project_id,
            expected_revision=expected_revision,
            sections=[s.model_dump() for s in sections] if sections is not None else None,
            harmony=[h.model_dump(exclude_none=True) for h in harmony]
            if harmony is not None
            else None,
            bars=bars,
            loop=loop,
            author="agent",
            operation_id=operation_id,
        ).to_dict()

    @server.tool()
    @_tool_errors
    def update_brief(
        project_id: str,
        expected_revision: int,
        changes: Annotated[
            dict[str, Any],
            Field(
                description='Brief fields to change, e.g. {"mood": "melancholy"}; locks excluded'
            ),
        ],
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Change composition-brief fields (mood, chordPlan, partLimits, ...)."""
        return service.update_brief(
            project_id,
            expected_revision=expected_revision,
            changes=changes,
            author="agent",
            operation_id=operation_id,
        ).to_dict()

    @server.tool()
    @_tool_errors
    def add_track(
        project_id: str,
        expected_revision: int,
        instrument_id: str,
        name: str,
        track_id: str | None = None,
        gain_db: float = 0.0,
        pan: Annotated[float, Field(ge=-1, le=1)] = 0.0,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Add an empty instrument track. Percussion is detected from the instrument ID."""
        from midimcp.instruments import resolve_instrument

        instrument = resolve_instrument(instrument_id)
        return service.add_track(
            project_id,
            expected_revision=expected_revision,
            instrument_id=instrument.id,
            name=name,
            track_id=track_id,
            is_percussion=instrument.is_percussion,
            gain_db=gain_db,
            pan=pan,
            author="agent",
            operation_id=operation_id,
        ).to_dict()

    @server.tool()
    @_tool_errors
    def update_track(
        project_id: str,
        expected_revision: int,
        track_id: str,
        name: str | None = None,
        instrument_id: str | None = None,
        gain_db: float | None = None,
        pan: float | None = None,
        mute: bool | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Change a track's name, instrument, gain, pan or mute. Notes are unchanged."""
        changes: dict[str, Any] = {
            k: v
            for k, v in {"name": name, "gain_db": gain_db, "pan": pan, "mute": mute}.items()
            if v is not None
        }
        if instrument_id is not None:
            from midimcp.instruments import resolve_instrument

            instrument = resolve_instrument(instrument_id)
            changes["instrument_id"] = instrument.id
            changes["is_percussion"] = instrument.is_percussion
        return service.update_track(
            project_id,
            expected_revision=expected_revision,
            track_id=track_id,
            changes=changes,
            author="agent",
            operation_id=operation_id,
        ).to_dict()

    @server.tool()
    @_tool_errors
    def remove_track(
        project_id: str, expected_revision: int, track_id: str, operation_id: str | None = None
    ) -> dict[str, Any]:
        """Delete a track and its notes."""
        return service.remove_track(
            project_id,
            expected_revision=expected_revision,
            track_id=track_id,
            author="agent",
            operation_id=operation_id,
        ).to_dict()

    @server.tool()
    @_tool_errors
    def replace_notes(
        project_id: str,
        expected_revision: int,
        track_id: str,
        notes: list[NoteIn],
        start_bar: Annotated[int | None, Field(description="1-based, inclusive")] = None,
        end_bar: Annotated[int | None, Field(description="1-based, inclusive")] = None,
        start_tick: int | None = None,
        end_tick: int | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Replace all notes of one track whose start falls in the bar (or tick) range with
        `notes`. Use an empty list to clear. Notes outside the range are untouched."""
        snap = service.get_project(project_id)
        lo, hi = _range(snap.score, start_bar, end_bar, start_tick, end_tick)
        return service.replace_notes(
            project_id,
            expected_revision=expected_revision,
            track_id=track_id,
            start_tick=lo,
            end_tick=hi,
            notes=[n.model_dump(exclude_none=True) for n in notes],
            author="agent",
            operation_id=operation_id,
        ).to_dict()

    @server.tool()
    @_tool_errors
    def edit_notes(
        project_id: str,
        expected_revision: int,
        operations: list[NoteEdit],
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomically add/update/delete individual notes by noteId."""
        ops = []
        for op in operations:
            data = op.model_dump(exclude_none=True)
            if "note" in data:
                data["note"] = {k: v for k, v in data["note"].items() if v is not None}
            ops.append(data)
        return service.edit_notes(
            project_id,
            expected_revision=expected_revision,
            operations=ops,
            author="agent",
            operation_id=operation_id,
        ).to_dict()

    @server.tool()
    @_tool_errors
    def restore_revision(
        project_id: str, expected_revision: int, revision: int, operation_id: str | None = None
    ) -> dict[str, Any]:
        """Make an earlier revision's music the new head (history is kept; locks apply)."""
        return service.restore_revision(
            project_id,
            expected_revision=expected_revision,
            revision=revision,
            author="agent",
            operation_id=operation_id,
        ).to_dict()

    # ------------------------------------------------- validation and audio

    @server.tool()
    @_tool_errors
    def validate_project(project_id: str, strict: bool | None = None) -> dict[str, Any]:
        """Errors (must fix), warnings (musical advice), summary, and soundbank checks."""
        snap = service.get_project(project_id)
        report = validate_score(snap.score, snap.brief, strict=strict)
        report.issues += sound_profile_issues(snap.score, ctx.registry)
        return {"projectId": project_id, "revision": snap.revision, **report.to_dict()}

    @server.tool()
    @_tool_errors
    def render_preview(
        project_id: str,
        revision: int | None = None,
        start_bar: int | None = None,
        end_bar: int | None = None,
        speed: Annotated[float, Field(ge=0.25, le=4.0, description="1.25 = 125% speed")] = 1.0,
        wait_seconds: Annotated[float, Field(ge=0, le=120)] = 60,
    ) -> dict[str, Any]:
        """Render a WAV preview with the project's soundbank. Waits up to wait_seconds;
        otherwise poll get_render_status with the jobId."""
        snap = (
            ctx.store.load_revision(project_id, revision)
            if revision is not None
            else service.get_project(project_id)
        )
        kwargs: dict[str, Any] = {"speed": speed}
        if start_bar is not None or end_bar is not None:
            kwargs["start_tick"], kwargs["end_tick"] = _range(
                snap.score, start_bar, end_bar, None, None
            )
        job = ctx.jobs.submit(snap.score, **kwargs)
        ctx.jobs.wait(job, wait_seconds)
        return job.to_dict()

    @server.tool()
    @_tool_errors
    def get_render_status(job_id: str) -> dict[str, Any]:
        """Status of a render job: queued, running, completed (with downloadPath) or failed."""
        job = ctx.jobs.get(job_id)
        if job is None:
            raise ToolError(json.dumps({"code": "JOB_NOT_FOUND", "message": job_id}))
        return job.to_dict()

    @server.tool()
    @_tool_errors
    def export_project(
        project_id: str,
        format: Literal["midi", "wav", "json"],
        revision: int | None = None,
        speed: Annotated[float, Field(ge=0.25, le=4.0)] = 1.0,
    ) -> dict[str, Any]:
        """Write an export into the project's exports folder; the user downloads it from the
        web UI (downloadPath). json = score + brief."""
        snap = (
            ctx.store.load_revision(project_id, revision)
            if revision is not None
            else service.get_project(project_id)
        )
        base = _EXPORT_NAME.sub("-", snap.score.metadata.title.lower()).strip("-") or "song"
        stem = f"{base[:60]}-r{snap.revision}"
        exports = ctx.store.project_dir(project_id) / "exports"
        exports.mkdir(exist_ok=True)
        if format == "midi":
            path = exports / f"{stem}.mid"
            path.write_bytes(export_midi_bytes(snap.score))
        elif format == "json":
            path = exports / f"{stem}.json"
            payload = {"score": snap.score.to_json_dict(), "brief": snap.brief.to_json_dict()}
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        else:
            result = ctx.renderer.render(snap.score, speed=speed)
            suffix = "" if speed == 1.0 else f"-x{speed:g}"
            path = exports / f"{stem}{suffix}.wav"
            path.write_bytes(result.path.read_bytes())
        return {
            "projectId": project_id,
            "revision": snap.revision,
            "format": format,
            "file": path.name,
            "sizeBytes": path.stat().st_size,
            "downloadPath": f"/api/projects/{project_id}/exports/{path.name}",
        }

    return server
