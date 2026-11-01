"""Runtime configuration from environment variables."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, replace
from pathlib import Path

TOKEN_FILE_NAME = "token.txt"


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

    @property
    def token_file(self) -> Path:
        return self.data_dir / TOKEN_FILE_NAME

    def resolve_token(self) -> tuple[Settings, str]:
        """Settle authentication before serving. Returns (settings, how).

        ``how`` is ``"env"`` (MIDIMCP_TOKEN), ``"file"`` (existing ``<data>/token.txt``),
        ``"generated"`` (new random token written to ``<data>/token.txt``) or
        ``"disabled"`` (MIDIMCP_ALLOW_NO_AUTH=1). The server never runs open by accident.
        """
        if self.token is not None:
            if len(self.token) < 16:
                raise ConfigError("MIDIMCP_TOKEN must be at least 16 characters")
            return self, "env"
        if self.allow_no_auth:
            return self, "disabled"
        path = self.token_file
        try:
            if path.is_file():
                stored = path.read_text(encoding="utf-8").strip()
                if len(stored) < 16:
                    raise ConfigError(f"{path} must contain a token of at least 16 characters")
                return replace(self, token=stored), "file"
            self.data_dir.mkdir(parents=True, exist_ok=True)
            generated = secrets.token_hex(32)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(generated + "\n")
            return replace(self, token=generated), "generated"
        except OSError as exc:
            raise ConfigError(
                f"cannot read or create {path} ({exc}); set MIDIMCP_TOKEN or fix permissions "
                "on the data folder (it must be writable by the container user, UID 568)"
            ) from exc
