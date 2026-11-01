"""Tests for scripts/auto-update.sh using a local git remote and stub tools."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("flock") is None, reason="needs bash and flock"
)

STUB_PUBLISH = """#!/usr/bin/env bash
set -euo pipefail
echo "publish called token_len=${#GHCR_TOKEN}" >> "$CALLS"
exit "${PUBLISH_EXIT:-0}"
"""

STUB_MIDCLT = """#!/usr/bin/env bash
echo "midclt $*" >> "$CALLS"
# Emulate TrueNAS 25.10: only `call -j` is accepted.
want="-j"; [ "${MIDCLT_OLD:-0}" = "1" ] && want="-job"
[ "$2" = "$want" ] || exit 2
exit "${MIDCLT_EXIT:-0}"
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def setup(tmp_path: Path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(work))
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    (work / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "auto-update.sh", work / "scripts" / "auto-update.sh")
    (work / "scripts" / "publish-image.sh").write_text(STUB_PUBLISH)
    git(work, "add", "-A")
    git(work, "commit", "-qm", "init")
    git(work, "push", "-q", "origin", "HEAD:main")

    base = tmp_path / "nas" / "midimcp"
    base.mkdir(parents=True)
    checkout = base / "src"
    git(tmp_path, "clone", "-q", str(origin), str(checkout))
    token = base / "ghcr-token"
    token.write_text("ghp_exampletoken123\n")
    token.chmod(0o600)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "midclt").write_text(STUB_MIDCLT)
    (bin_dir / "midclt").chmod(0o755)
    calls = tmp_path / "calls.txt"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(calls)}
    return work, checkout, base, env, calls


def run(checkout: Path, env: dict, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(checkout / "scripts" / "auto-update.sh")],
        env={**env, **extra},
        capture_output=True,
        text=True,
        timeout=60,
    )


def calls(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.exists() else []


def test_first_run_publishes_and_redeploys(setup) -> None:
    _, checkout, base, env, calls_file = setup
    result = run(checkout, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(calls_file) == [
        "publish called token_len=19",
        "midclt call -j app.redeploy midimcp",
    ]
    assert (base / "last-published-commit").read_text().strip() == git(
        checkout, "rev-parse", "HEAD"
    )
    assert "redeployed TrueNAS app 'midimcp'" in (base / "auto-update.log").read_text()


def test_nothing_new_does_nothing(setup) -> None:
    _, checkout, _, env, calls_file = setup
    run(checkout, env)
    calls_file.unlink()
    result = run(checkout, env)
    assert result.returncode == 0
    assert calls(calls_file) == []
    assert "nothing to do" in result.stdout


def test_new_commit_is_pulled_and_published(setup) -> None:
    work, checkout, _base, env, calls_file = setup
    run(checkout, env)
    calls_file.unlink()
    (work / "README.md").write_text("new")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "change")
    git(work, "push", "-q", "origin", "HEAD:main")
    result = run(checkout, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(checkout, "rev-parse", "HEAD") == git(work, "rev-parse", "HEAD")
    assert len(calls(calls_file)) == 2


def test_refuses_missing_or_open_token(setup) -> None:
    _, checkout, base, env, calls_file = setup
    (base / "ghcr-token").chmod(0o644)
    result = run(checkout, env)
    assert result.returncode == 1 and "must be mode 600" in result.stdout
    (base / "ghcr-token").unlink()
    result = run(checkout, env)
    assert result.returncode == 1 and "not found" in result.stdout
    assert calls(calls_file) == []


def test_refuses_dirty_checkout(setup) -> None:
    _, checkout, _, env, calls_file = setup
    (checkout / "scripts" / "publish-image.sh").write_text("# tampered\n")
    result = run(checkout, env)
    assert result.returncode == 1 and "local changes" in result.stdout
    assert calls(calls_file) == []


def test_publish_failure_does_not_mark_published(setup) -> None:
    _, checkout, base, env, _ = setup
    result = run(checkout, env, PUBLISH_EXIT="3")
    assert result.returncode == 1 and "publish failed" in result.stdout
    assert not (base / "last-published-commit").exists()


def test_redeploy_failure_reported(setup) -> None:
    _, checkout, base, env, _ = setup
    result = run(checkout, env, MIDCLT_EXIT="1")
    assert result.returncode == 1 and "redeploying app 'midimcp' failed" in result.stdout
    assert (base / "last-published-commit").exists()


def test_older_truenas_job_flag_fallback(setup) -> None:
    _, checkout, _, env, calls_file = setup
    result = run(checkout, env, MIDCLT_OLD="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(calls_file)[-2:] == [
        "midclt call -j app.redeploy midimcp",
        "midclt call -job app.redeploy midimcp",
    ]
