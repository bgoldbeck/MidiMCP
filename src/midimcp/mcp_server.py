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
from midimcp.encode import EncodeError
from midimcp.instruments import UnknownInstrument
from midimcp.midi import MidiExportError
from midimcp.model.brief import Brief
from midimcp.model.schema import brief_json_schema, score_json_schema
from midimcp.model.score import Score
from midimcp.music.expression import ExpressionSettings, HumanizeSettings
from midimcp.music.theory import TheoryError
from midimcp.music.timing import bar_range
from midimcp.render import RenderError
from midimcp.soundbanks import DEFAULT_BANK_ID, SoundbankError, sound_profile_issues
from midimcp.store.errors import StoreError
from midimcp.validation import MAX_DURATION_SECONDS, MAX_NOTES, MAX_TRACKS, validate_score
from midimcp.views import export_project as export_project_files
from midimcp.views import timing

INSTRUCTIONS = """\
MidiMCP composes original 1990s General-MIDI-style fantasy RPG music. Read the
resource midimcp://guide first. Workflow: list_templates -> create_project with
template_id (gives tracks, sections and a chord chart) -> replace_notes (by bar
range, following the chords) -> humanize_notes + shape_expression on the melody
(so it sounds played, not typed) -> validate_project -> render_preview. Every
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


class PointIn(BaseModel):
    tick: Annotated[
        int, Field(ge=0, description="Absolute tick; the value holds until the next point")
    ]
    value: Annotated[
        int,
        Field(
            ge=-8192,
            le=8191,
            description="expression/modulation 0-127; pitchBend -8192..8191 (+-2 semitones)",
        ),
    ]


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
        except (StoreError, SoundbankError, RenderError, MidiExportError, EncodeError) as exc:
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
        return json.dumps({"templates": ctx.templates.summaries()})

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
            "exportFormats": ["midi", "wav", "mp3", "json"],
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
        """Projects (songs) with title, usage, tags, head revision, and the user's
        organization: favorite (starred) and the ids of collections holding the song."""
        return {"projects": ctx.organizer.annotate(service.list_projects(search))}

    @server.tool()
    @_tool_errors
    def list_collections() -> dict[str, Any]:
        """The user's song collections (their own categories, e.g. "Town themes") with
        the songs in each, plus their favorites. Read-only except add_to_collection."""
        return ctx.organizer.snapshot()

    @server.tool()
    @_tool_errors
    def add_to_collection(project_id: str, collection: str) -> dict[str, Any]:
        """Put a song into one of the user's EXISTING collections (by name or id), e.g. when
        asked "add it to my Town themes". Does not create collections or change the song
        itself; only the user creates, renames or deletes collections and stars songs."""
        target = ctx.organizer.find(collection)
        ctx.organizer.add_to_collection(project_id, target["id"])
        return {
            "ok": True,
            "projectId": project_id,
            "collection": target["name"],
            **ctx.organizer.for_project(project_id),
        }

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
        return {"templates": ctx.templates.summaries()}

    @server.tool()
    @_tool_errors
    def get_template(template_id: str) -> dict[str, Any]:
        """Full template guidance: parts (role, instrument, register, what to play), form with
        chord progressions per section, accompaniment patterns, dos and don'ts."""
        return ctx.templates.detail(template_id)

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

    def _optional_range(project_id, start_bar, end_bar, start_tick, end_tick):
        if start_bar is None and end_bar is None and start_tick is None and end_tick is None:
            return 0, None
        return _range(
            service.get_project(project_id).score, start_bar, end_bar, start_tick, end_tick
        )

    @server.tool()
    @_tool_errors
    def humanize_notes(
        project_id: str,
        expected_revision: int,
        track_id: str,
        start_bar: Annotated[
            int | None, Field(description="1-based, inclusive; omit = whole song")
        ] = None,
        end_bar: Annotated[int | None, Field(description="1-based, inclusive")] = None,
        start_tick: int | None = None,
        end_tick: int | None = None,
        seed: Annotated[
            int, Field(description="Same seed = same result; change it for a different take")
        ] = 1,
        timing_ticks: Annotated[
            int, Field(ge=0, le=240, description="Max late push (960 = quarter); 8-20 is subtle")
        ] = 12,
        velocity_variation: Annotated[int, Field(ge=0, le=30, description="+- per note")] = 5,
        phrase_dynamics: Annotated[
            int, Field(ge=0, le=40, description="Velocity rise toward each phrase's high note")
        ] = 10,
        accent_downbeats: bool = True,
        keep_downbeats: Annotated[
            bool, Field(description="Notes on a bar line stay exactly on it")
        ] = True,
        legato: Annotated[
            float | None,
            Field(
                ge=0.3,
                le=1.0,
                description="Inner notes last this share of the gap to the next note "
                "(0.95 smooth, 0.6 detached); omit = keep lengths",
            ),
        ] = None,
        breath_ticks: Annotated[
            int, Field(ge=0, le=1920, description="Silence before each new phrase (winds: 120-240)")
        ] = 0,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Make a track sound performed instead of typed in: tiny timing pushes, phrase-shaped
        velocities with downbeat accents, optional legato/detached articulation and breaths.
        Pitches never change. Deterministic: the same arguments always give the same result.
        Run it once after the notes are final (running it again adds more variation)."""
        lo, hi = _optional_range(project_id, start_bar, end_bar, start_tick, end_tick)
        return service.humanize_notes(
            project_id,
            expected_revision=expected_revision,
            track_id=track_id,
            start_tick=lo,
            end_tick=hi,
            settings=HumanizeSettings(
                seed=seed,
                timing_ticks=timing_ticks,
                velocity_variation=velocity_variation,
                phrase_dynamics=phrase_dynamics,
                accent_downbeats=accent_downbeats,
                keep_downbeats=keep_downbeats,
                legato=legato,
                breath_ticks=breath_ticks,
            ),
            author="agent",
            operation_id=operation_id,
        ).to_dict()

    @server.tool()
    @_tool_errors
    def shape_expression(
        project_id: str,
        expected_revision: int,
        track_id: str,
        start_bar: Annotated[
            int | None, Field(description="1-based, inclusive; omit = whole song")
        ] = None,
        end_bar: Annotated[int | None, Field(description="1-based, inclusive")] = None,
        start_tick: int | None = None,
        end_tick: int | None = None,
        base: Annotated[int, Field(ge=0, le=127, description="Expression at phrase starts")] = 96,
        peak: Annotated[
            int, Field(ge=0, le=127, description="Expression at each phrase's high point")
        ] = 120,
        swell: Annotated[
            int, Field(ge=0, le=40, description="Extra rise/fall inside held notes")
        ] = 10,
        long_note_ticks: Annotated[
            int,
            Field(
                ge=1, description="Notes this long swell and get vibrato (1440 = dotted quarter)"
            ),
        ] = 1440,
        vibrato_depth: Annotated[
            int,
            Field(
                ge=0,
                le=127,
                description="Vibrato (CC1) on held notes; 0 = leave vibrato alone. 25-50 natural",
            ),
        ] = 40,
        vibrato_delay_ticks: Annotated[
            int, Field(ge=0, description="Straight tone before vibrato starts")
        ] = 240,
        resolution_ticks: Annotated[int, Field(ge=10, le=480)] = 60,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Give a melody life inside its notes: volume swells across each phrase and within held
        notes (CC11 expression) and a delayed vibrato that fades in on held notes (CC1). Replaces
        the track's expression (and vibrato) curves in the range. Best for flutes, strings,
        brass, voices; skip plucked or struck instruments (lute, harp, piano)."""
        lo, hi = _optional_range(project_id, start_bar, end_bar, start_tick, end_tick)
        return service.shape_expression(
            project_id,
            expected_revision=expected_revision,
            track_id=track_id,
            start_tick=lo,
            end_tick=hi,
            settings=ExpressionSettings(
                base=base,
                peak=peak,
                swell=swell,
                long_note_ticks=long_note_ticks,
                vibrato_depth=vibrato_depth,
                vibrato_delay_ticks=vibrato_delay_ticks,
                resolution_ticks=resolution_ticks,
            ),
            author="agent",
            operation_id=operation_id,
        ).to_dict()

    @server.tool()
    @_tool_errors
    def set_automation(
        project_id: str,
        expected_revision: int,
        track_id: str,
        lane: Literal["expression", "modulation", "pitchBend"],
        points: list[PointIn],
        start_bar: Annotated[int | None, Field(description="1-based, inclusive")] = None,
        end_bar: Annotated[int | None, Field(description="1-based, inclusive")] = None,
        start_tick: int | None = None,
        end_tick: int | None = None,
        interpolate: Annotated[
            bool, Field(description="Join the points with straight ramps")
        ] = False,
        resolution_ticks: Annotated[int, Field(ge=10, le=480)] = 60,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Hand-draw one controller curve of a track in a bar/tick range (replaces the points
        there; empty list clears). expression = CC11 volume inside the track (fade in/out,
        swells); modulation = CC1 vibrato depth; pitchBend = slides (+-8191 = +-2 semitones;
        return to 0 before the next note)."""
        snap = service.get_project(project_id)
        lo, hi = _range(snap.score, start_bar, end_bar, start_tick, end_tick)
        return service.set_automation(
            project_id,
            expected_revision=expected_revision,
            track_id=track_id,
            lane=lane,
            start_tick=lo,
            end_tick=hi,
            points=[p.model_dump() for p in points],
            interpolate_ramps=interpolate,
            resolution_ticks=resolution_ticks,
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
        format: Literal["midi", "wav", "mp3", "json"],
        revision: int | None = None,
        speed: Annotated[float, Field(ge=0.25, le=4.0)] = 1.0,
        bitrate: Annotated[
            Literal[128, 192, 256, 320], Field(description="MP3 kbps (mp3 only)")
        ] = 192,
    ) -> dict[str, Any]:
        """Write an export into the project's exports folder; the user downloads it from the
        web UI (downloadPath). json = score + brief; mp3 = rendered audio encoded with LAME."""
        return export_project_files(
            ctx, project_id, format, revision=revision, speed=speed, bitrate=bitrate
        )

    return server
