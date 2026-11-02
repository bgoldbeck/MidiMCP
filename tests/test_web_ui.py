"""Browser tests for the web UI: JS unit tests (node --test) and a Playwright end-to-end run."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from midimcp.model import Brief
from midimcp.service import CompositionService
from midimcp.store import ProjectStore
from tests.test_mcp import free_port

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
HAS_AUDIO = (
    shutil.which("fluidsynth") is not None
    and Path("/usr/share/sounds/sf2/FluidR3_GM.sf2").is_file()
)


def has_playwright() -> bool:
    if NODE is None:
        return False
    probe = subprocess.run([NODE, "-e", "require('playwright')"], capture_output=True, cwd=ROOT)
    return probe.returncode == 0


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_js_unit_tests() -> None:
    tests = sorted(str(p) for p in (ROOT / "web-tests").glob("*.test.mjs"))
    completed = subprocess.run(
        [NODE, "--test", *tests], capture_output=True, text=True, cwd=ROOT, timeout=120
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def seed_song(data_dir: Path) -> None:
    service = CompositionService(ProjectStore(data_dir))
    service.create_project(
        brief=Brief(allowed_instrument_ids=["retro.wooden_flute", "retro.recorder"]),
        title="Browser Test Song",
        tempo_bpm=96,
        meter=(3, 4),
        tonic="D",
        mode="dorian",
        bars=4,
        project_id="browser-test-song",
    )
    service.add_track(
        "browser-test-song",
        expected_revision=1,
        instrument_id="retro.wooden_flute",
        name="Flute",
        track_id="flute",
    )
    notes = [
        {"pitch": 62 + (i % 4) * 2, "startTick": i * 960, "durationTicks": 900, "velocity": 80}
        for i in range(12)
    ]
    service.replace_notes(
        "browser-test-song",
        expected_revision=2,
        track_id="flute",
        start_tick=0,
        end_tick=4 * 2880,
        notes=notes,
    )
    service.create_project(
        title='<img src=x onerror="alert(1)"> Evil Title',
        tempo_bpm=90,
        meter=(4, 4),
        tonic="C",
        bars=2,
        project_id="evil-title",
    )


@pytest.fixture
def live_server(tmp_path: Path):
    data = tmp_path / "data"
    seed_song(data)
    port = free_port()
    token = "browser-test-token-0123456789"
    env = {
        **os.environ,
        "MIDIMCP_DATA_DIR": str(data),
        "MIDIMCP_TOKEN": token,
        "MIDIMCP_PORT": str(port),
        "MIDIMCP_HOST": "127.0.0.1",
        "MIDIMCP_LOG_LEVEL": "WARNING",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "midimcp", "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    yield base, token
    process.terminate()
    process.wait(timeout=10)


def test_ui_is_public_and_hardened(live_server) -> None:
    base, _ = live_server
    root = httpx.get(f"{base}/", follow_redirects=False)
    assert root.status_code == 307 and root.headers["location"] == "/ui/"
    page = httpx.get(f"{base}/ui/")
    assert page.status_code == 200 and "MidiMCP" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["referrer-policy"] == "no-referrer"
    assert httpx.get(f"{base}/ui/app.js").headers["content-type"].startswith("text/javascript")
    assert httpx.get(f"{base}/ui/editor.js").status_code == 200
    assert httpx.get(f"{base}/ui/editor-model.js").status_code == 200
    assert httpx.get(f"{base}/ui/editor.css").status_code == 200
    assert 'id="note-editor-panel"' in page.text
    assert httpx.get(f"{base}/ui/../token.txt").status_code == 401  # normalised, not public
    assert httpx.get(f"{base}/ui/..%2Ftoken.txt").status_code == 404  # traversal refused
    assert httpx.get(f"{base}/ui/missing.js").status_code == 404
    icon = httpx.get(f"{base}/ui/icon-512.png")  # public: TrueNAS loads it as the app icon
    assert icon.status_code == 200 and icon.headers["content-type"] == "image/png"
    assert icon.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert httpx.get(f"{base}/ui/icon.svg").headers["content-type"] == "image/svg+xml"
    help_page = httpx.get(f"{base}/ui/help.html")  # public, no data in it
    assert help_page.status_code == 200 and "peaceful-town" in help_page.text
    assert "script-src 'self'" in help_page.headers["content-security-policy"]
    setup_page = httpx.get(f"{base}/ui/setup.html")  # public install + developer guide
    assert setup_page.status_code == 200 and "publish-image.sh" in setup_page.text
    assert "auto-update.sh" in setup_page.text
    assert httpx.get(f"{base}/api/projects").status_code == 401  # data still needs the token


@pytest.mark.skipif(not (HAS_AUDIO and has_playwright()), reason="needs fluidsynth + playwright")
def test_web_ui_end_to_end_in_browser(live_server, tmp_path: Path) -> None:
    base, token = live_server
    shot = tmp_path / "ui.png"
    completed = subprocess.run(
        [NODE, str(ROOT / "web-tests" / "e2e-ui.mjs"), base, token, str(shot)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=240,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "E2E UI PASSED" in completed.stdout
