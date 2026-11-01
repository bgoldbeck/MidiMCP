"""Runtime configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    pass


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str = "0.0.0.0"
    port: int = 8765
    token: str | None = None
    allow_no_auth: bool = False
    allowed_hosts: tuple[str, ...] = ()
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        hosts = tuple(
            h.strip() for h in env.get("MIDIMCP_ALLOWED_HOSTS", "").split(",") if h.strip()
        )
        return cls(
            data_dir=Path(env.get("MIDIMCP_DATA_DIR", "./data")),
            host=env.get("MIDIMCP_HOST", "0.0.0.0"),
            port=int(env.get("MIDIMCP_PORT", "8765")),
            token=env.get("MIDIMCP_TOKEN") or None,
            allow_no_auth=_flag(env.get("MIDIMCP_ALLOW_NO_AUTH")),
            allowed_hosts=hosts,
            log_level=env.get("MIDIMCP_LOG_LEVEL", "INFO").upper(),
        )

    def require_auth_config(self) -> None:
        """The HTTP server is reachable on the LAN: refuse to start without a token."""
        if self.token is None and not self.allow_no_auth:
            raise ConfigError(
                "MIDIMCP_TOKEN is not set. Set a long random token (e.g. `openssl rand -hex 32`), "
                "or set MIDIMCP_ALLOW_NO_AUTH=1 to run without authentication (not recommended)."
            )
        if self.token is not None and len(self.token) < 16:
            raise ConfigError("MIDIMCP_TOKEN must be at least 16 characters")
