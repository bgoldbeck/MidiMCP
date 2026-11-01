"""Web API for the browser UI: JSON routes under ``/api`` and live events over WebSocket.

All routes sit behind the bearer-token middleware in :mod:`midimcp.server`.
Mutations go through :class:`CompositionService` with ``author="user"`` and need
``expectedRevision``, exactly like MCP tools.

Routes::

    GET   /api/status
    GET   /api/instruments?bankId=&search=
    GET   /api/templates                          (built-in + custom)
    GET|PUT|DELETE /api/templates/{id}          (PUT/DELETE: custom templates only)
    POST  /api/templates/{id}/duplicate        {newId, name?}
    GET   /api/projects?search=
    GET   /api/projects/{id}?revision=
    DELETE /api/projects/{id}                  (moves the song to <data>/trash)
    GET   /api/projects/{id}/revisions
    PATCH /api/projects/{id}/tracks/{trackId}   {expectedRevision, name?, instrumentId?, allowInstrument?, gainDb?, pan?, mute?}
    POST  /api/projects/{id}/tracks/{trackId}/reset {expectedRevision, fields?: instrument|volume|pan|mute}
    POST  /api/projects/{id}/restore            {expectedRevision, revision}
    POST  /api/projects/{id}/render             {revision?, speed?, startBar?, endBar?, loop?}
    GET   /api/jobs/{jobId}
    GET   /api/projects/{id}/exports
    POST  /api/projects/{id}/exports            {format: midi|wav|mp3|json, revision?, speed?, bitrate?}
    GET   /api/projects/{id}/exports/{file}     (download)
    GET   /api/renders/{file}                   (download)
    WS    /api/events?token=                    (project.updated, render.queued, render.finished)
"""  # noqa: E501

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mcp.server.mcpserver import MCPServer
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket, WebSocketDisconnect

from midimcp import __version__
from midimcp.context import AppContext
from midimcp.encode import DEFAULT_MP3_BITRATE, MP3_BITRATES, EncodeError, encoder_status
from midimcp.instruments import UnknownInstrument, resolve_instrument
from midimcp.music.timing import bar_range
from midimcp.render import MAX_SPEED, MIN_SPEED, RenderError
from midimcp.soundbanks import DEFAULT_BANK_ID, SoundbankError
from midimcp.store.errors import StoreError
from midimcp.views import export_project as export_project_files
from midimcp.views import list_exports, media_type, project_view

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"
_WEB_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}
SECURITY_HEADERS = {
    # Everything is served from this origin; the token must never leak via Referer.
    "Content-Security-Policy": (
        "default-src 'self'; connect-src 'self' ws: wss:; media-src 'self' blob:; "
        "img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-cache",
}

_STATUS_BY_CODE = {
    "PROJECT_NOT_FOUND": 404,
    "REVISION_NOT_FOUND": 404,
    "TRACK_NOT_FOUND": 404,
    "NOTE_NOT_FOUND": 404,
    "BANK_NOT_FOUND": 404,
    "JOB_NOT_FOUND": 404,
    "UNKNOWN_TEMPLATE": 404,
    "INVALID_TEMPLATE": 422,
    "NOT_FOUND": 404,
    "REVISION_CONFLICT": 409,
    "PROJECT_EXISTS": 409,
    "OPERATION_ID_REUSED": 409,
    "LOCKED": 423,
    "VALIDATION_FAILED": 422,
    "RENDER_BLOCKED": 422,
    "RENDERER_UNAVAILABLE": 503,
    "ENCODER_UNAVAILABLE": 503,
    "CORRUPT_PROJECT": 500,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.status = code, status

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self)}


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, ApiError):
        return JSONResponse(exc.to_dict(), status_code=exc.status)
    if isinstance(exc, (StoreError, SoundbankError, RenderError, EncodeError)):
        body = exc.to_dict()
        return JSONResponse(body, status_code=_STATUS_BY_CODE.get(body["code"], 400))
    if isinstance(exc, (UnknownInstrument, ValueError)):
        code = getattr(exc, "code", "INVALID_ARGUMENT")
        status = _STATUS_BY_CODE.get(code, 400)
        return JSONResponse({"code": code, "message": str(exc)}, status_code=status)
    log.exception("unexpected API error")
    return JSONResponse({"code": "INTERNAL_ERROR", "message": str(exc)}, status_code=500)


async def _call(func, *args: Any, **kwargs: Any) -> Response:
    """Run blocking service code off the event loop; map domain errors to HTTP."""
    try:
        result = await run_in_threadpool(func, *args, **kwargs)
    except Exception as exc:
        return _error_response(exc)
    if isinstance(result, Response):
        return result
    return JSONResponse(result)


async def _body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApiError("INVALID_JSON", "request body must be JSON") from exc
    if not isinstance(data, dict):
        raise ApiError("INVALID_JSON", "request body must be a JSON object")
    return data


def _int(data: dict, key: str, *, required: bool = False) -> int | None:
    value = data.get(key)
    if value is None:
        if required:
            raise ApiError("MISSING_FIELD", f"{key} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("INVALID_FIELD", f"{key} must be an integer")
    return value


def register_web_ui(server: MCPServer) -> None:
    """Serve the static browser UI (public: it holds no data; the API needs the token)."""

    @server.custom_route("/", methods=["GET"])
    async def index(request: Request) -> Response:
        return RedirectResponse("/ui/", status_code=307)

    @server.custom_route("/ui/{path:path}", methods=["GET"])
    async def ui(request: Request) -> Response:
        name = request.path_params["path"] or "index.html"
        path = (WEB_DIR / name).resolve()
        if path.parent != WEB_DIR or path.suffix not in _WEB_TYPES or not path.is_file():
            return JSONResponse({"code": "NOT_FOUND", "message": "no such file"}, status_code=404)
        return FileResponse(path, media_type=_WEB_TYPES[path.suffix], headers=SECURITY_HEADERS)


def register_api(server: MCPServer, ctx: AppContext) -> None:
    service = ctx.service

    def route(path: str, methods: list[str]):
        return server.custom_route(path, methods=methods)

    @route("/api/status", ["GET"])
    async def status(request: Request) -> Response:
        def build() -> dict:
            return {
                "version": __version__,
                "audio": ctx.renderer.status(),
                "banks": [b.to_dict() for b in ctx.registry.list_banks()],
                "mcpPath": "/mcp",
                "speedRange": [MIN_SPEED, MAX_SPEED],
                "encoders": encoder_status(),
                "mp3Bitrates": list(MP3_BITRATES),
            }

        return await _call(build)

    @route("/api/instruments", ["GET"])
    async def instruments(request: Request) -> Response:
        bank = request.query_params.get("bankId", DEFAULT_BANK_ID)
        search = request.query_params.get("search")
        return await _call(
            lambda: {"bankId": bank, "instruments": ctx.registry.instruments(bank, search)}
        )

    @route("/api/templates", ["GET"])
    async def templates(request: Request) -> Response:
        return await _call(lambda: {"templates": ctx.templates.summaries()})

    @route("/api/templates/{template_id}", ["GET", "PUT", "DELETE"])
    async def template(request: Request) -> Response:
        template_id = request.path_params["template_id"]
        if request.method == "GET":
            return await _call(ctx.templates.detail, template_id)
        if request.method == "DELETE":

            def delete() -> dict:
                ctx.templates.delete(template_id)
                return {"ok": True, "templateId": template_id}

            return await _call(delete)
        try:
            data = await _body(request)
        except Exception as exc:
            return _error_response(exc)

        def save() -> dict:
            ctx.templates.save(template_id, data)
            return ctx.templates.detail(template_id)

        return await _call(save)

    @route("/api/templates/{template_id}/duplicate", ["POST"])
    async def duplicate_template(request: Request) -> Response:
        template_id = request.path_params["template_id"]
        try:
            data = await _body(request)
            new_id = data.get("newId")
            if not isinstance(new_id, str):
                raise ApiError("MISSING_FIELD", "newId is required")
            name = data.get("name")
        except Exception as exc:
            return _error_response(exc)

        def duplicate() -> dict:
            ctx.templates.duplicate(template_id, new_id, name if isinstance(name, str) else None)
            return ctx.templates.detail(new_id)

        return await _call(duplicate)

    @route("/api/projects", ["GET"])
    async def projects(request: Request) -> Response:
        search = request.query_params.get("search") or None
        return await _call(lambda: {"projects": service.list_projects(search)})

    @route("/api/projects/{project_id}", ["GET", "DELETE"])
    async def project(request: Request) -> Response:
        project_id = request.path_params["project_id"]
        if request.method == "DELETE":

            def delete() -> dict:
                trash = ctx.store.delete_project(project_id)
                return {"ok": True, "projectId": project_id, "trash": trash.name}

            return await _call(delete)
        raw = request.query_params.get("revision")
        try:
            revision = int(raw) if raw else None
        except ValueError:
            return _error_response(ApiError("INVALID_FIELD", "revision must be an integer"))
        return await _call(project_view, ctx, project_id, revision)

    @route("/api/projects/{project_id}/revisions", ["GET"])
    async def revisions(request: Request) -> Response:
        project_id = request.path_params["project_id"]
        return await _call(
            lambda: {"projectId": project_id, "revisions": service.list_revisions(project_id)}
        )

    @route("/api/projects/{project_id}/tracks/{track_id}", ["PATCH"])
    async def update_track(request: Request) -> Response:
        project_id = request.path_params["project_id"]
        track_id = request.path_params["track_id"]
        try:
            data = await _body(request)
            expected = _int(data, "expectedRevision", required=True)
            changes: dict[str, Any] = {}
            for key, field in (("name", "name"), ("gainDb", "gain_db"), ("pan", "pan"),
                               ("mute", "mute")):  # fmt: skip
                if key in data:
                    changes[field] = data[key]
            if "instrumentId" in data:
                instrument = resolve_instrument(str(data["instrumentId"]))
                changes["instrument_id"] = instrument.id
                changes["is_percussion"] = instrument.is_percussion
            if not changes:
                raise ApiError("NOTHING_TO_CHANGE", "no track fields given")
        except Exception as exc:
            return _error_response(exc)
        return await _call(
            lambda: service.update_track(
                project_id, expected_revision=expected, track_id=track_id, changes=changes,
                allow_instrument=bool(data.get("allowInstrument", False)), author="user",
            ).to_dict()
        )  # fmt: skip

    @route("/api/projects/{project_id}/tracks/{track_id}/reset", ["POST"])
    async def reset_track(request: Request) -> Response:
        project_id = request.path_params["project_id"]
        track_id = request.path_params["track_id"]
        try:
            data = await _body(request)
            expected = _int(data, "expectedRevision", required=True)
            fields = data.get("fields") or ["instrument", "volume", "pan", "mute"]
            if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
                raise ApiError("INVALID_FIELD", "fields must be a list of strings")
        except Exception as exc:
            return _error_response(exc)
        return await _call(
            lambda: service.reset_track(
                project_id, expected_revision=expected, track_id=track_id, fields=fields,
                author="user",
            ).to_dict()
        )  # fmt: skip

    @route("/api/projects/{project_id}/restore", ["POST"])
    async def restore(request: Request) -> Response:
        project_id = request.path_params["project_id"]
        try:
            data = await _body(request)
            expected = _int(data, "expectedRevision", required=True)
            revision = _int(data, "revision", required=True)
        except Exception as exc:
            return _error_response(exc)
        return await _call(
            lambda: service.restore_revision(
                project_id, expected_revision=expected, revision=revision, author="user"
            ).to_dict()
        )

    @route("/api/projects/{project_id}/render", ["POST"])
    async def render(request: Request) -> Response:
        project_id = request.path_params["project_id"]
        try:
            data = await _body(request)
            revision = _int(data, "revision")
            start_bar, end_bar = _int(data, "startBar"), _int(data, "endBar")
            loop = bool(data.get("loop", False))
            speed = data.get("speed", 1.0)
            if isinstance(speed, bool) or not isinstance(speed, (int, float)):
                raise ApiError("INVALID_FIELD", "speed must be a number")
        except Exception as exc:
            return _error_response(exc)

        def submit() -> dict:
            snap = (
                ctx.store.load_revision(project_id, revision)
                if revision is not None
                else ctx.store.load(project_id)
            )
            kwargs: dict[str, Any] = {"speed": float(speed)}
            if start_bar is not None or end_bar is not None:
                if start_bar is None or end_bar is None:
                    raise ApiError("INVALID_RANGE", "give both startBar and endBar")
                t = snap.score.timeline
                kwargs["start_tick"], kwargs["end_tick"] = bar_range(
                    start_bar, end_bar, t.ppq, t.meter.numerator, t.meter.denominator
                )
            if loop:
                timeline = snap.score.timeline
                if timeline.loop.enabled:
                    lo, hi = timeline.loop.start_tick, timeline.loop.end_tick
                else:
                    lo, hi = 0, timeline.total_ticks
                kwargs.update(start_tick=lo, end_tick=hi, tail=False)
            if not MIN_SPEED <= kwargs["speed"] <= MAX_SPEED:
                raise ApiError("INVALID_FIELD", f"speed must be {MIN_SPEED}-{MAX_SPEED}")
            return ctx.jobs.submit(snap.score, **kwargs).to_dict()

        return await _call(submit)

    @route("/api/jobs/{job_id}", ["GET"])
    async def job(request: Request) -> Response:
        found = ctx.jobs.get(request.path_params["job_id"])
        if found is None:
            return _error_response(ApiError("JOB_NOT_FOUND", "no such render job", 404))
        return JSONResponse(found.to_dict())

    @route("/api/projects/{project_id}/exports", ["GET", "POST"])
    async def exports(request: Request) -> Response:
        project_id = request.path_params["project_id"]
        if request.method == "GET":
            return await _call(
                lambda: {"projectId": project_id, "exports": list_exports(ctx, project_id)}
            )
        try:
            data = await _body(request)
            fmt = data.get("format")
            revision = _int(data, "revision")
            speed = float(data.get("speed", 1.0))
            bitrate = _int(data, "bitrate") or DEFAULT_MP3_BITRATE
        except Exception as exc:
            return _error_response(exc)
        return await _call(
            export_project_files,
            ctx,
            project_id,
            str(fmt),
            revision=revision,
            speed=speed,
            bitrate=bitrate,
        )

    @route("/api/renders/{name}", ["GET"])
    async def render_download(request: Request) -> Response:
        path = ctx.render_file(request.path_params["name"])
        if path is None:
            return _error_response(ApiError("NOT_FOUND", "no such render", 404))
        return FileResponse(path, media_type="audio/wav")

    @route("/api/projects/{project_id}/exports/{name}", ["GET"])
    async def export_download(request: Request) -> Response:
        path = ctx.export_file(request.path_params["project_id"], request.path_params["name"])
        if path is None:
            return _error_response(ApiError("NOT_FOUND", "no such export", 404))
        return FileResponse(path, media_type=media_type(path.name), filename=path.name)


class EventsDispatcher:
    """Serve ``WS /api/events`` in front of the MCP/HTTP app; pass everything else through."""

    path = "/api/events"

    def __init__(self, app: ASGIApp, ctx: AppContext, allowed_hosts: tuple[str, ...]) -> None:
        self.app = app
        self.ctx = ctx
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "websocket" or scope["path"] != self.path:
            await self.app(scope, receive, send)
            return
        websocket = WebSocket(scope, receive, send)
        if not self._origin_ok(websocket):
            await websocket.close(code=4403)
            return
        await websocket.accept()
        async with self.ctx.events.subscribe() as queue:
            await websocket.send_json({"type": "hello", "version": __version__})
            receiver = asyncio.create_task(self._drain(websocket))
            try:
                while not receiver.done():
                    getter = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait(
                        {getter, receiver}, timeout=25, return_when=asyncio.FIRST_COMPLETED
                    )
                    if getter in done:
                        await websocket.send_json(getter.result())
                    else:
                        getter.cancel()
                        if not done:
                            await websocket.send_json({"type": "ping"})
            except (WebSocketDisconnect, RuntimeError):
                pass
            finally:
                receiver.cancel()

    @staticmethod
    async def _drain(websocket: WebSocket) -> None:
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            return

    def _origin_ok(self, websocket: WebSocket) -> bool:
        """Browsers send Origin; it must match the Host (same origin) or an allowed host."""
        origin = websocket.headers.get("origin")
        if not origin:
            return True  # non-browser client (still token-authenticated)
        origin_host = urlsplit(origin).netloc
        return origin_host == websocket.headers.get("host") or origin_host in self.allowed_hosts
