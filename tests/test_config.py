from __future__ import annotations

from pathlib import Path

import pytest

from midimcp.config import ConfigError, Settings


def settings(tmp_path: Path, **env: str) -> Settings:
    return Settings.from_env({"MIDIMCP_DATA_DIR": str(tmp_path), **env})


def test_env_token_wins(tmp_path: Path) -> None:
    resolved, how = settings(tmp_path, MIDIMCP_TOKEN="x" * 20).resolve_token()
    assert (how, resolved.token) == ("env", "x" * 20)
    assert not (tmp_path / "token.txt").exists()


def test_short_env_token_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        settings(tmp_path, MIDIMCP_TOKEN="short").resolve_token()


def test_token_generated_once_then_reused(tmp_path: Path) -> None:
    first, how = settings(tmp_path).resolve_token()
    assert how == "generated" and len(first.token) == 64
    again, how = settings(tmp_path).resolve_token()
    assert (how, again.token) == ("file", first.token)


def test_bad_token_file_rejected(tmp_path: Path) -> None:
    (tmp_path / "token.txt").write_text("tiny")
    with pytest.raises(ConfigError):
        settings(tmp_path).resolve_token()


def test_auth_can_be_disabled_explicitly(tmp_path: Path) -> None:
    resolved, how = settings(tmp_path, MIDIMCP_ALLOW_NO_AUTH="1").resolve_token()
    assert (how, resolved.token) == ("disabled", None)


def test_unwritable_data_dir(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    with pytest.raises(ConfigError, match="MIDIMCP_TOKEN"):
        Settings.from_env({"MIDIMCP_DATA_DIR": str(blocker / "data")}).resolve_token()
