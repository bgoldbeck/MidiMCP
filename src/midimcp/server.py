"""HTTP entry point: MCP (Streamable HTTP) + health + file downloads, behind a bearer token.

Routes:

* ``GET  /healthz``                          — public liveness/readiness
* ``POST /mcp``                              — MCP Streamable HTTP endpoint
* ``GET  /api/renders/<key>.wav``            — rendered previews
* ``GET  /api/projects/<id>/exports/<file>`` — exported files

All routes except ``/healthz`` require ``Authorization: Bearer <MIDIMCP_TOKEN>``
(``?token=`` is also accepted on GET downloads so links work in a browser).
"""

from __future__ import annotations

import argparse
import hmac
import logging
import sys
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from midimcp import __version__
from midimcp.config import ConfigError, Settings
from midimcp.context import AppContext
from midimcp.mcp_server import build_mcp_server

log = logging.getLogger("midimcp")

PUBLIC_PATHS = frozenset({"/healthz"})


class BearerAuthMiddleware:
    """Require ``Authorization: Bearer <token>`` (or ``?token=`` on GET) for non-public paths."""

    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"} or self.token is None:
            await self.app(scope, receive, send)
            return
        if scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        supplied = None
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            supplied = header[7:].strip()
        elif scope["type"] == "http" and request.method == "GET":
            supplied = request.query_params.get("token")
        if supplied is None or not hmac.compare_digest(supplied.encode(), self.token.encode()):
            response = JSONResponse(
                {"code": "UNAUTHORIZED", "message": "missing or invalid bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def build_app(settings: Settings, ctx: AppContext | None = None) -> ASGIApp:
    ctx = ctx or AppContext(settings.data_dir)
    server = build_mcp_server(ctx)

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> Response:
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "audio": ctx.renderer.status()["available"],
                "auth": settings.token is not None,
            }
        )

    @server.custom_route("/api/renders/{name}", methods=["GET"])
    async def render_download(request: Request) -> Response:
        path = ctx.render_file(request.path_params["name"])
        if path is None:
            return JSONResponse({"code": "NOT_FOUND"}, status_code=404)
        return FileResponse(path, media_type="audio/wav")

    @server.custom_route("/api/projects/{project_id}/exports/{name}", methods=["GET"])
    async def export_download(request: Request) -> Response:
        path = ctx.export_file(request.path_params["project_id"], request.path_params["name"])
        if path is None:
            return JSONResponse({"code": "NOT_FOUND"}, status_code=404)
        media = {
            ".mid": "audio/midi",
            ".wav": "audio/wav",
            ".json": "application/json",
        }.get(path.suffix, "application/octet-stream")
        return FileResponse(path, media_type=media, filename=path.name)

    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(settings.allowed_hosts),
        allowed_hosts=list(settings.allowed_hosts),
        allowed_origins=[f"http://{h}" for h in settings.allowed_hosts]
        + [f"https://{h}" for h in settings.allowed_hosts],
    )
    app = server.streamable_http_app(
        streamable_http_path="/mcp", transport_security=security, host=settings.host
    )
    return BearerAuthMiddleware(app, settings.token)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="midimcp", description="MidiMCP retro composer server")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the HTTP server (MCP at /mcp)")
    sub.add_parser("stdio", help="run MCP over stdio (local development, no auth)")
    args = parser.parse_args(argv)
    command = args.command or "serve"

    settings = Settings.from_env()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(message)s")

    if command == "stdio":
        ctx = AppContext(settings.data_dir)
        build_mcp_server(ctx).run("stdio")
        return 0

    try:
        settings.require_auth_config()
    except ConfigError as exc:
        print(f"midimcp: {exc}", file=sys.stderr)
        return 2
    if settings.token is None:
        log.warning("authentication DISABLED (MIDIMCP_ALLOW_NO_AUTH=1)")

    import uvicorn

    app = build_app(settings)
    uvicorn_args: dict[str, Any] = {
        "host": settings.host,
        "port": settings.port,
        "log_level": settings.log_level.lower(),
        "proxy_headers": True,
    }
    log.info(
        "MidiMCP %s on http://%s:%s (MCP at /mcp, data %s)",
        __version__,
        settings.host,
        settings.port,
        settings.data_dir,
    )
    uvicorn.run(app, **uvicorn_args)
    return 0
