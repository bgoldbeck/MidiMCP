from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import Client

from midimcp.context import AppContext
from midimcp.mcp_server import build_mcp_server
from midimcp.service import CompositionService
from midimcp.soundbanks import SoundbankRegistry
from tests.sf2 import full_gm_presets, write_fake_sf2

HAS_AUDIO = (
    shutil.which("fluidsynth") is not None
    and Path("/usr/share/sounds/sf2/FluidR3_GM.sf2").is_file()
)


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppContext:
    if not HAS_AUDIO:
        system = tmp_path / "system"
        system.mkdir()
        write_fake_sf2(system / "FluidR3_GM.sf2", full_gm_presets())
        monkeypatch.setattr(
            "midimcp.context.SoundbankRegistry",
            lambda data: SoundbankRegistry(data, system_dir=system),
        )
    return AppContext(tmp_path / "data")


def run(coro: Any) -> Any:
    return asyncio.run(coro)


async def call(client: Client, tool: str, **args: Any) -> dict:
    result = await client.call_tool(tool, args)
    if result.is_error:
        raise AssertionError(result.content[0].text)
    return result.structured_content


async def call_error(client: Client, tool: str, **args: Any) -> dict:
    result = await client.call_tool(tool, args)
    assert result.is_error, f"{tool} unexpectedly succeeded"
    text = result.content[0].text
    return json.loads(text[text.index("{") :])


def phrase(bar: int, base: int) -> list[dict]:
    start = (bar - 1) * 2880
    return [
        {"pitch": base, "startTick": start, "durationTicks": 1440, "velocity": 76},
        {"pitch": base + 4, "startTick": start + 1440, "durationTicks": 960, "velocity": 70},
    ]


async def build_song(client: Client) -> None:
    created = await call(
        client,
        "create_project",
        title="Lanterns of the Vale",
        tempo_bpm=84,
        meter_numerator=6,
        meter_denominator=8,
        tonic="G#",
        mode="ionian",
        bars=16,
        percussion_allowed=False,
    )
    assert created["projectId"] == "lanterns-of-the-vale"
    assert created["timing"]["ticksPerBar"] == 2880
    assert created["key"]["displaySpelling"] == "Ab"
    pid = created["projectId"]
    r = await call(
        client,
        "add_track",
        project_id=pid,
        expected_revision=1,
        instrument_id="retro.wooden_flute",
        name="Flute",
        track_id="flute",
    )
    r = await call(
        client,
        "add_track",
        project_id=pid,
        expected_revision=r["revision"],
        instrument_id="retro.lute",
        name="Lute",
        track_id="lute",
    )
    flute = [n for b in range(1, 17) for n in phrase(b, 68)]
    lute = [n for b in range(1, 17) for n in phrase(b, 56)]
    r = await call(
        client,
        "replace_notes",
        project_id=pid,
        expected_revision=r["revision"],
        track_id="flute",
        start_bar=1,
        end_bar=16,
        notes=flute,
    )
    r = await call(
        client,
        "replace_notes",
        project_id=pid,
        expected_revision=r["revision"],
        track_id="lute",
        start_bar=1,
        end_bar=16,
        notes=lute,
    )
    assert r["revision"] == 5


def test_tools_and_resources_listed(ctx: AppContext) -> None:
    async def go() -> None:
        async with Client(build_mcp_server(ctx)) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert {
                "create_project",
                "replace_notes",
                "edit_notes",
                "render_preview",
                "export_project",
                "validate_project",
                "list_instruments",
            } <= names
            assert not {"unlock", "lock", "register_soundbank", "delete_project"} & names
            guide = await client.read_resource("midimcp://guide")
            assert "expected_revision" in guide.contents[0].text
            caps = await call(client, "list_capabilities")
            assert caps["limits"]["maxTracks"] == 12
            instruments = await call(client, "list_instruments", search="dulcimer")
            assert [i["id"] for i in instruments["instruments"]] == ["retro.dulcimer"]

    run(go())


def test_compose_and_edit_bars_9_to_16(ctx: AppContext) -> None:
    async def go() -> None:
        async with Client(build_mcp_server(ctx)) as client:
            await build_song(client)
            pid = "lanterns-of-the-vale"
            before = await call(client, "get_project", project_id=pid)
            edit = await call(
                client,
                "replace_notes",
                project_id=pid,
                expected_revision=5,
                track_id="flute",
                start_bar=9,
                end_bar=16,
                notes=[{"pitch": 75, "startTick": 23040, "durationTicks": 2880}],
            )
            assert edit["revision"] == 6
            assert edit["changes"]["text"].startswith("Flute: 16 notes replaced with 1")
            after = await call(client, "get_project", project_id=pid)
            assert after["score"]["tracks"][1] == before["score"]["tracks"][1]
            early_before = await call(
                client,
                "get_project",
                project_id=pid,
                revision=5,
                track_ids=["flute"],
                start_bar=1,
                end_bar=8,
            )
            early_after = await call(
                client, "get_project", project_id=pid, track_ids=["flute"], start_bar=1, end_bar=8
            )
            assert early_before["score"]["tracks"] == early_after["score"]["tracks"]
            report = await call(client, "validate_project", project_id=pid)
            assert report["ok"] is True
            history = await call(client, "list_revisions", project_id=pid)
            assert [r["author"] for r in history["revisions"]] == ["agent"] * 6

    run(go())


def test_errors_are_structured(ctx: AppContext) -> None:
    async def go() -> None:
        async with Client(build_mcp_server(ctx)) as client:
            await build_song(client)
            pid = "lanterns-of-the-vale"
            stale = await call_error(
                client,
                "add_track",
                project_id=pid,
                expected_revision=1,
                instrument_id="retro.harp",
                name="Harp",
            )
            assert stale["code"] == "REVISION_CONFLICT" and stale["currentRevision"] == 5
            drums = await call_error(
                client,
                "add_track",
                project_id=pid,
                expected_revision=5,
                instrument_id="gm.drums",
                name="Drums",
            )
            assert drums["code"] == "VALIDATION_FAILED"
            unknown = await call_error(
                client,
                "add_track",
                project_id=pid,
                expected_revision=5,
                instrument_id="retro.kazoo",
                name="Kazoo",
            )
            assert unknown["code"] == "UNKNOWN_INSTRUMENT"
            # User locks the lute in the web UI; the agent cannot change it.
            CompositionService(ctx.store).lock(pid, expected_revision=5, track_id="lute")
            locked = await call_error(
                client,
                "replace_notes",
                project_id=pid,
                expected_revision=6,
                track_id="lute",
                start_bar=1,
                end_bar=1,
                notes=[],
            )
            assert locked["code"] == "LOCKED"
            bad_range = await call_error(
                client,
                "replace_notes",
                project_id=pid,
                expected_revision=6,
                track_id="flute",
                notes=[],
            )
            assert bad_range["code"] == "INVALID_RANGE"

    run(go())


def test_operation_id_retry(ctx: AppContext) -> None:
    async def go() -> None:
        async with Client(build_mcp_server(ctx)) as client:
            await build_song(client)
            args = dict(
                project_id="lanterns-of-the-vale",
                expected_revision=5,
                instrument_id="retro.harp",
                name="Harp",
                operation_id="op-1",
            )
            first = await call(client, "add_track", **args)
            again = await call(client, "add_track", **args)
            assert again["replayed"] and again["revision"] == first["revision"] == 6

    run(go())


def test_export_midi_and_json(ctx: AppContext) -> None:
    async def go() -> None:
        async with Client(build_mcp_server(ctx)) as client:
            await build_song(client)
            midi = await call(
                client, "export_project", project_id="lanterns-of-the-vale", format="midi"
            )
            assert midi["file"] == "lanterns-of-the-vale-r5.mid"
            assert midi["downloadPath"].endswith("/exports/lanterns-of-the-vale-r5.mid")
            assert ctx.export_file("lanterns-of-the-vale", midi["file"]) is not None
            data = await call(
                client, "export_project", project_id="lanterns-of-the-vale", format="json"
            )
            assert data["file"].endswith(".json")

    run(go())


@pytest.mark.skipif(not HAS_AUDIO, reason="fluidsynth and FluidR3 required")
def test_render_preview_and_wav_export(ctx: AppContext) -> None:
    async def go() -> None:
        async with Client(build_mcp_server(ctx)) as client:
            await build_song(client)
            job = await call(
                client, "render_preview", project_id="lanterns-of-the-vale", start_bar=1, end_bar=4
            )
            assert job["status"] == "completed", job
            assert job["render"]["durationSeconds"] == pytest.approx(8.571, abs=0.01)
            status = await call(client, "get_render_status", job_id=job["jobId"])
            assert status["downloadPath"] == job["downloadPath"]
            wav = await call(
                client,
                "export_project",
                project_id="lanterns-of-the-vale",
                format="wav",
                speed=1.25,
            )
            assert wav["file"] == "lanterns-of-the-vale-r5-x1.25.wav"

    run(go())


# ------------------------------------------------------------------ HTTP e2e


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def http_server(tmp_path: Path):
    port = free_port()
    token = "test-token-0123456789abcdef"
    env = {
        **os.environ,
        "MIDIMCP_DATA_DIR": str(tmp_path / "data"),
        "MIDIMCP_TOKEN": token,
        "MIDIMCP_PORT": str(port),
        "MIDIMCP_HOST": "127.0.0.1",
        "MIDIMCP_LOG_LEVEL": "WARNING",
    }
    if not HAS_AUDIO:
        system = tmp_path / "system"
        system.mkdir()
        write_fake_sf2(system / "FluidR3_GM.sf2", full_gm_presets())
        env["MIDIMCP_SYSTEM_SF2_DIR"] = str(system)
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
    else:
        process.kill()
        raise AssertionError(process.stdout.read().decode())
    yield base, token
    process.terminate()
    process.wait(timeout=10)


def test_http_server_requires_token(http_server: tuple[str, str]) -> None:
    base, _token = http_server
    health = httpx.get(f"{base}/healthz").json()
    assert health["status"] == "ok" and health["auth"] is True
    assert httpx.post(f"{base}/mcp", json={}).status_code == 401
    assert (
        httpx.post(f"{base}/mcp", json={}, headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )
    assert httpx.get(f"{base}/api/renders/x.wav").status_code == 401


def test_http_mcp_session_and_download(http_server: tuple[str, str]) -> None:
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    base, token = http_server

    async def go() -> None:
        http = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
        async with http, Client(streamable_http_client(f"{base}/mcp", http_client=http)) as client:
            await build_song(client)
            export = await call(
                client, "export_project", project_id="lanterns-of-the-vale", format="midi"
            )
        response = httpx.get(f"{base}{export['downloadPath']}", params={"token": token})
        assert response.status_code == 200
        assert response.content.startswith(b"MThd")
        assert "attachment" in response.headers["content-disposition"]

    run(go())


def test_server_generates_token_when_unset(tmp_path: Path) -> None:
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("MIDIMCP_")}
    env.update(MIDIMCP_DATA_DIR=str(tmp_path), MIDIMCP_PORT=str(port), MIDIMCP_HOST="127.0.0.1")
    if not HAS_AUDIO:
        system = tmp_path / "system"
        system.mkdir()
        write_fake_sf2(system / "FluidR3_GM.sf2", full_gm_presets())
        env["MIDIMCP_SYSTEM_SF2_DIR"] = str(system)
    process = subprocess.Popen(
        [sys.executable, "-m", "midimcp", "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        token = (tmp_path / "token.txt").read_text().strip()
        assert len(token) == 64
        assert httpx.post(f"{base}/mcp", json={}).status_code == 401
        export_404 = httpx.get(f"{base}/api/renders/missing.wav", params={"token": token})
        assert export_404.status_code == 404  # authenticated, file simply absent
        if sys.platform != "win32":
            assert (tmp_path / "token.txt").stat().st_mode & 0o777 == 0o600
    finally:
        process.terminate()
        output = process.communicate(timeout=10)[0]
    assert "Generated access token" in output and token in output


def test_stdio_transport(tmp_path: Path) -> None:
    from mcp import StdioServerParameters

    env = {**os.environ, "MIDIMCP_DATA_DIR": str(tmp_path / "data")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "midimcp", "stdio"], env=env)

    async def go() -> None:
        async with Client(params) as client:
            projects = await call(client, "list_projects")
            assert projects == {"projects": []}

    run(go())


def test_smoke_script_against_server(http_server: tuple[str, str], tmp_path: Path) -> None:
    base, token = http_server
    script = Path(__file__).resolve().parents[1] / "scripts" / "smoke_test.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--url",
            base,
            "--token",
            token,
            "--out",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "SMOKE TEST PASSED" in completed.stdout
    assert (tmp_path / "out" / "midimcp-smoke-test-r5.mid").is_file()


def test_templates_via_mcp(ctx: AppContext) -> None:
    async def go() -> None:
        async with Client(build_mcp_server(ctx)) as client:
            listed = await call(client, "list_templates")
            assert len(listed["templates"]) == 6
            detail = await call(client, "get_template", template_id="tavern")
            assert detail["form"][0]["progression"][1] == "bVII"
            created = await call(
                client, "create_project", title="Inn Song", template_id="tavern", tonic="G"
            )
            assert created["revision"] == 1
            assert [t["role"] for t in created["tracks"]] == [
                "melody",
                "countermelody",
                "accompaniment",
                "bass",
            ]
            assert created["harmony"][1]["symbol"] == "F"  # bVII in G mixolydian
            assert len(created["partLimits"]) == 4
            missing = await call_error(client, "create_project", title="Bare")
            assert missing["code"] == "MISSING_ARGUMENT"
            unknown = await call_error(client, "create_project", title="X", template_id="disco")
            assert unknown["code"] == "UNKNOWN_TEMPLATE"
            resource = await client.read_resource("midimcp://templates")
            assert "peaceful-town" in resource.contents[0].text

    run(go())


@pytest.mark.skipif(not (HAS_AUDIO and shutil.which("lame")), reason="fluidsynth + lame required")
def test_mp3_export_via_mcp(ctx: AppContext) -> None:
    async def go() -> None:
        async with Client(build_mcp_server(ctx)) as client:
            await build_song(client)
            mp3 = await call(
                client,
                "export_project",
                project_id="lanterns-of-the-vale",
                format="mp3",
                bitrate=128,
            )
            assert mp3["file"] == "lanterns-of-the-vale-r5-128k.mp3"
            assert mp3["mediaType"] == "audio/mpeg"

    run(go())
