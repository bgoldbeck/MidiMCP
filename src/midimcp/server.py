"""HTTP entry point: MCP (Streamable HTTP) + health + file downloads, behind a bearer token.

Routes:

* ``GET  /healthz``                          — public liveness/readiness
* ``POST /mcp``                              — MCP Streamable HTTP endpoint
* ``/api/...``                               — web API + downloads (see midimcp.web_api)
* ``WS   /api/events``                        — live project/render events

All routes except ``/healthz`` require ``Authorization: Bearer <MIDIMCP_TOKEN>``
(``?token=`` is also accepted on GET requests and WebSockets, which browsers cannot
give headers to).
"""

from __future__ import annotations

import argparse
import hmac
import logging
import sys
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from midimcp import __version__
from midimcp.config import ConfigError, Settings
from midimcp.context import AppContext
from midimcp.mcp_server import build_mcp_server
from midimcp.web_api import EventsDispatcher, register_api

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
        request = HTTPConnection(scope)
        supplied = None
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            supplied = header[7:].strip()
        elif scope["type"] == "websocket" or scope.get("method") == "GET":
            # Browsers cannot set headers on WebSockets, <audio> or download links.
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

    register_api(server, ctx)

    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(settings.allowed_hosts),
        allowed_hosts=list(settings.allowed_hosts),
        allowed_origins=[f"http://{h}" for h in settings.allowed_hosts]
        + [f"https://{h}" for h in settings.allowed_hosts],
    )
    app = server.streamable_http_app(
        streamable_http_path="/mcp", transport_security=security, host=settings.host
    )
    app = EventsDispatcher(app, ctx, settings.allowed_hosts)
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
        settings, how = settings.resolve_token()
    except ConfigError as exc:
        print(f"midimcp: {exc}", file=sys.stderr)
        return 2
    if how == "disabled":
        log.warning("authentication DISABLED (MIDIMCP_ALLOW_NO_AUTH=1)")
    elif how == "generated":
        banner = "=" * 72
        log.warning(
            "\n%s\nGenerated access token (saved to %s):\n\n    %s\n\n"
            "Give this token to your MCP clients (see docs/agents/connect-agents.md).\n%s",
            banner,
            settings.token_file,
            settings.token,
            banner,
        )
    elif how == "file":
        log.info("using access token from %s", settings.token_file)

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
