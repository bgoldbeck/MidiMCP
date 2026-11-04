"""Example song scripts keep working against a real HTTP server."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_mcp import HAS_AUDIO, http_server  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not HAS_AUDIO, reason="render_preview needs fluidsynth + FluidR3")
def test_old_realm_deep_forest_example(http_server: tuple[str, str]) -> None:  # noqa: F811
    base, token = http_server
    script = (ROOT / "examples" / "old_realm_deep_forest.py").read_text()
    done = subprocess.run(
        [sys.executable, "-"],
        input=script,
        text=True,
        capture_output=True,
        timeout=240,
        env={"MIDIMCP_URL": base, "MIDIMCP_TOKEN": token, "PATH": "/usr/bin:/bin"},
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "revision 17" in done.stdout
    assert "validate: ok=True warnings=['NOTE_OUT_OF_KEY']" in done.stdout
    assert "preview: completed" in done.stdout
