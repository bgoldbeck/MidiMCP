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
from midimcp.midi import MidiExportError
from midimcp.model.brief import Brief
from midimcp.model.schema import brief_json_schema, score_json_schema
from midimcp.model.score import Score
from midimcp.music.theory import TheoryError
from midimcp.music.timing import bar_range
from midimcp.render import RenderError
from midimcp.soundbanks import DEFAULT_BANK_ID, SoundbankError, sound_profile_issues
from midimcp.store.errors import StoreError
from midimcp.templates import get_template as get_template_data
from midimcp.templates import list_templates as list_templates_data
from midimcp.validation import MAX_DURATION_SECONDS, MAX_NOTES, MAX_TRACKS, validate_score
from midimcp.views import export_project as export_project_files
from midimcp.views import timing

INSTRUCTIONS = """\
MidiMCP composes original 1990s General-MIDI-style fantasy RPG music. Read the
resource midimcp://guide first. Workflow: list_templates -> create_project with
template_id (gives tracks, sections and a chord chart) -> replace_notes (by bar
range, following the chords) -> validate_project -> render_preview. Every
mutation needs expected_revision (the latest revision you received). Locked
material is protected: never try to bypass LOCKED errors.
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


_timing = timing


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
        "midimcp://templates", name="Composition templates", mime_type="application/json"
    )
    def templates_resource() -> str:
        return json.dumps({"templates": list_templates_data()})

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
    def list_templates() -> dict[str, Any]:
        """Composition templates (peaceful town, forest, crypt, tavern, sea, borderlands):
        tempo, meter, mode, ensemble and form. Pass template_id to create_project."""
        return {"templates": list_templates_data()}

    @server.tool()
    @_tool_errors
    def get_template(template_id: str) -> dict[str, Any]:
        """Full template guidance: parts (role, instrument, register, what to play), form with
        chord progressions per section, accompaniment patterns, dos and don'ts."""
        return get_template_data(template_id).to_dict()

    @server.tool()
    @_tool_errors
    def create_project(
        title: str,
        template_id: Annotated[
            str | None,
            Field(
                description="Recommended. Scaffolds tracks (with roles and pitch ranges), "
                "sections and a bar-by-bar chord chart; other musical fields become optional "
                "overrides. See list_templates."
            ),
        ] = None,
        tempo_bpm: Annotated[float | None, Field(description="Quarter-note BPM")] = None,
        meter_numerator: int | None = None,
        meter_denominator: int | None = None,
        tonic: Annotated[str | None, Field(description="Key tonic, e.g. G#, Ab, D, Bb")] = None,
        mode: Annotated[
            str | None,
            Field(
                description="ionian/major, dorian, phrygian, lydian, "
                "mixolydian, aeolian/minor, locrian"
            ),
        ] = None,
        bars: Annotated[int | None, Field(ge=1, description="Song length in bars")] = None,
        loop: bool | None = None,
        usage: str | None = None,
        tags: list[str] | None = None,
        bank_id: str = DEFAULT_BANK_ID,
        percussion_allowed: bool | None = None,
        allowed_instrument_ids: list[str] | None = None,
        max_tracks: int | None = None,
        harmonic_strictness: Literal["strict", "advisory"] | None = None,
        chord_plan: list[str] | None = None,
        mood: str | None = None,
        setting: str | None = None,
        references: list[str] | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a song. With template_id you get a ready scaffold (fill it with replace_notes);
        without it, give tempo_bpm, meter and tonic and add tracks yourself.
        Returns projectId, revision, timing (ticksPerBar...) and the key."""
        bank = ctx.registry.require(bank_id)
        brief_fields = {
            "percussionAllowed": percussion_allowed,
            "allowedInstrumentIds": allowed_instrument_ids,
            "maxTracks": max_tracks,
            "harmonicStrictness": harmonic_strictness,
            "chordPlan": chord_plan,
            "mood": mood,
            "setting": setting,
            "references": references,
            "loopRequired": loop,
        }
        given = {k: v for k, v in brief_fields.items() if v is not None}
        meter = (
            (meter_numerator, meter_denominator) if meter_numerator and meter_denominator else None
        )
        if template_id is not None:
            result = service.create_from_template(
                template_id=template_id,
                title=title,
                tonic=tonic,
                mode=mode,
                tempo_bpm=tempo_bpm,
                meter=meter,
                bars=bars,
                usage=usage,
                tags=tags or [],
                bank_id=bank.id,
                bank_sha256=bank.sha256,
                brief_overrides=given,
                author="agent",
                operation_id=operation_id,
            )
        else:
            missing = [
                name
                for name, value in (("tempo_bpm", tempo_bpm), ("meter", meter), ("tonic", tonic))
                if value is None
            ]
            if missing:
                raise ToolError(
                    json.dumps(
                        {
                            "code": "MISSING_ARGUMENT",
                            "message": f"without template_id, give {', '.join(missing)} "
                            "(meter = meter_numerator + meter_denominator)",
                        }
                    )
                )
            loop_value = True if loop is None else loop
            brief = Brief.model_validate(
                {"percussionAllowed": True, "loopRequired": loop_value, **given}
            )
            result = service.create_project(
                title=title,
                tempo_bpm=tempo_bpm,
                meter=meter,
                tonic=tonic,
                mode=mode or "ionian",
                bars=bars or 32,
                usage=usage,
                tags=tags or [],
                loop=loop_value,
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
            "tracks": [
                {"id": t.id, "name": t.name, "role": t.role, "instrumentId": t.instrument_id}
                for t in snap.score.tracks
            ],
            "sections": [s.to_json_dict() for s in snap.score.sections],
            "harmony": [h.to_json_dict() for h in snap.score.harmony],
            "partLimits": [p.to_json_dict() for p in snap.brief.part_limits],
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
        role: Literal["melody", "countermelody", "accompaniment", "bass", "pad", "percussion"]
        | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Add an empty instrument track. Percussion is detected from the instrument ID.
        Give a role so the music checks know which part is the melody."""
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
            role=role,
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
        return export_project_files(ctx, project_id, format, revision=revision, speed=speed)

    return server
