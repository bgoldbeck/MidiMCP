from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from midimcp.config import Settings
from midimcp.context import AppContext
from midimcp.server import build_app
from midimcp.service import CompositionService
from midimcp.soundbanks import SoundbankRegistry
from tests.sf2 import full_gm_presets, write_fake_sf2

TOKEN = "web-api-test-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PID = "lanterns"
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
    context = AppContext(tmp_path / "data")
    service = CompositionService(context.store)
    service.create_project(
        title="Lanterns", tempo_bpm=84, meter=(6, 8), tonic="G#", bars=4, project_id=PID
    )
    service.add_track(
        PID, expected_revision=1, instrument_id="retro.wooden_flute", name="Flute", track_id="flute"
    )
    notes = [
        {"pitch": 68 + (i % 3) * 2, "startTick": i * 1440, "durationTicks": 1320, "velocity": 76}
        for i in range(8)
    ]
    service.replace_notes(
        PID, expected_revision=2, track_id="flute", start_tick=0, end_tick=4 * 2880, notes=notes
    )
    return context


@pytest.fixture
def client(ctx: AppContext, tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", token=TOKEN, host="127.0.0.1")
    with TestClient(build_app(settings, ctx), base_url="http://nas.local:8765") as c:
        yield c


def test_requires_token(client: TestClient) -> None:
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", params={"token": TOKEN}).status_code == 200
    assert (
        client.patch("/api/projects/x/tracks/y", params={"token": TOKEN}, json={}).status_code
        == 401
    )  # query token only for GET/WS


def test_status_and_instruments(client: TestClient) -> None:
    status = client.get("/api/status", headers=AUTH).json()
    assert status["mcpPath"] == "/mcp" and status["banks"][0]["id"] == "fluidr3-gm"
    found = client.get("/api/instruments", params={"search": "harp"}, headers=AUTH).json()
    assert [i["id"] for i in found["instruments"]] == ["retro.harp", "retro.harpsichord"]


def test_list_and_get_project(client: TestClient) -> None:
    listing = client.get("/api/projects", headers=AUTH).json()
    assert [p["projectId"] for p in listing["projects"]] == [PID]
    view = client.get(f"/api/projects/{PID}", headers=AUTH).json()
    assert view["revision"] == 3
    assert view["timing"]["ticksPerBar"] == 2880 and view["timing"]["bars"] == 4
    assert view["validation"]["ok"] is True
    assert view["lastChange"]["author"] == "agent"
    old = client.get(f"/api/projects/{PID}", params={"revision": 1}, headers=AUTH).json()
    assert old["score"]["tracks"] == []
    assert client.get("/api/projects/nope", headers=AUTH).status_code == 404
    assert (
        client.get(f"/api/projects/{PID}", params={"revision": "x"}, headers=AUTH).status_code
        == 400
    )
    history = client.get(f"/api/projects/{PID}/revisions", headers=AUTH).json()
    assert [r["revision"] for r in history["revisions"]] == [1, 2, 3]


def test_update_track_and_conflicts(client: TestClient, ctx: AppContext) -> None:
    ok = client.patch(
        f"/api/projects/{PID}/tracks/flute",
        headers=AUTH,
        json={"expectedRevision": 3, "instrumentId": "retro.recorder", "mute": True},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["revision"] == 4
    track = ctx.store.load(PID).score.track("flute")
    assert (track.instrument_id, track.mute) == ("retro.recorder", True)
    stale = client.patch(
        f"/api/projects/{PID}/tracks/flute",
        headers=AUTH,
        json={"expectedRevision": 3, "mute": False},
    )
    assert stale.status_code == 409 and stale.json()["currentRevision"] == 4
    assert (
        client.patch(
            f"/api/projects/{PID}/tracks/flute", headers=AUTH, json={"mute": False}
        ).status_code
        == 400
    )
    assert (
        client.patch(
            f"/api/projects/{PID}/tracks/nope",
            headers=AUTH,
            json={"expectedRevision": 4, "mute": False},
        ).status_code
        == 404
    )
    bad = client.patch(
        f"/api/projects/{PID}/tracks/flute",
        headers=AUTH,
        json={"expectedRevision": 4, "instrumentId": "retro.kazoo"},
    )
    assert bad.status_code == 400 and bad.json()["code"] == "UNKNOWN_INSTRUMENT"
    assert (
        client.patch(
            f"/api/projects/{PID}/tracks/flute", headers=AUTH, content=b"not json"
        ).status_code
        == 400
    )


def test_locked_track_returns_423(client: TestClient, ctx: AppContext) -> None:
    CompositionService(ctx.store).lock(PID, expected_revision=3, track_id="flute")
    locked = client.patch(
        f"/api/projects/{PID}/tracks/flute",
        headers=AUTH,
        json={"expectedRevision": 4, "gainDb": -6},
    )
    assert locked.status_code == 423 and locked.json()["code"] == "LOCKED"


def test_restore(client: TestClient, ctx: AppContext) -> None:
    result = client.post(
        f"/api/projects/{PID}/restore", headers=AUTH, json={"expectedRevision": 3, "revision": 2}
    )
    assert result.status_code == 200 and result.json()["revision"] == 4
    assert ctx.store.load(PID).score.track("flute").notes == []


def test_exports_list_and_download(client: TestClient) -> None:
    made = client.post(f"/api/projects/{PID}/exports", headers=AUTH, json={"format": "midi"})
    assert made.status_code == 200, made.text
    entry = made.json()
    assert entry["file"] == "lanterns-r3.mid" and entry["mediaType"] == "audio/midi"
    listed = client.get(f"/api/projects/{PID}/exports", headers=AUTH).json()["exports"]
    assert [e["file"] for e in listed] == ["lanterns-r3.mid"]
    download = client.get(entry["downloadPath"], params={"token": TOKEN})
    assert download.status_code == 200 and download.content.startswith(b"MThd")
    assert (
        client.post(
            f"/api/projects/{PID}/exports", headers=AUTH, json={"format": "flac"}
        ).status_code
        == 400
    )
    assert (
        client.get(
            f"/api/projects/{PID}/exports/../../token.txt", params={"token": TOKEN}
        ).status_code
        in {400, 404}  # path is normalised away; never serves the file
    )


def test_render_argument_errors(client: TestClient) -> None:
    assert (
        client.post(f"/api/projects/{PID}/render", headers=AUTH, json={"speed": 9}).status_code
        == 400
    )
    assert (
        client.post(f"/api/projects/{PID}/render", headers=AUTH, json={"startBar": 1}).status_code
        == 400
    )
    assert client.get("/api/jobs/missing", headers=AUTH).status_code == 404


def test_websocket_requires_token_and_same_origin(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/events") as ws:
        ws.receive_json()
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            f"/api/events?token={TOKEN}", headers={"origin": "http://evil.example"}
        ) as ws,
    ):
        ws.receive_json()
    with client.websocket_connect(
        f"/api/events?token={TOKEN}", headers={"origin": "http://testserver"}
    ) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_websocket_receives_project_updates(client: TestClient, ctx: AppContext) -> None:
    with client.websocket_connect(f"/api/events?token={TOKEN}") as ws:
        assert ws.receive_json()["type"] == "hello"
        deadline = time.time() + 5
        while ctx.events.subscriber_count == 0 and time.time() < deadline:
            time.sleep(0.01)
        # An agent edit (MCP side) must reach the browser.
        CompositionService(ctx.store).update_track(
            PID,
            expected_revision=3,
            track_id="flute",
            changes={"gain_db": -4.0},
            author="agent",
        )
        event = ws.receive_json()
        assert event["type"] == "project.updated"
        assert (event["projectId"], event["revision"], event["author"]) == (PID, 4, "agent")
        assert "gainDb" in event["summary"]


@pytest.mark.skipif(not HAS_AUDIO, reason="fluidsynth and FluidR3 required")
def test_render_job_and_events(client: TestClient, ctx: AppContext) -> None:
    with client.websocket_connect(f"/api/events?token={TOKEN}") as ws:
        assert ws.receive_json()["type"] == "hello"
        job = client.post(f"/api/projects/{PID}/render", headers=AUTH, json={"speed": 1.25}).json()
        assert job["status"] in {"queued", "running", "completed"}
        seen = []
        while not seen or seen[-1]["type"] != "render.finished":
            seen.append(ws.receive_json())
        finished = seen[-1]["job"]
        assert finished["status"] == "completed" and finished["render"]["speed"] == 1.25
    status = client.get(f"/api/jobs/{job['jobId']}", headers=AUTH).json()
    audio = client.get(status["downloadPath"], params={"token": TOKEN})
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"


def test_update_track_allow_instrument(client: TestClient, ctx: AppContext) -> None:
    CompositionService(ctx.store).update_brief(
        PID, expected_revision=3, changes={"allowedInstrumentIds": ["retro.wooden_flute"]}
    )
    refused = client.patch(
        f"/api/projects/{PID}/tracks/flute",
        headers=AUTH,
        json={"expectedRevision": 4, "instrumentId": "retro.harp"},
    )
    assert refused.status_code == 422
    assert refused.json()["validation"]["errors"][0]["code"] == "INSTRUMENT_NOT_ALLOWED"
    ok = client.patch(
        f"/api/projects/{PID}/tracks/flute",
        headers=AUTH,
        json={"expectedRevision": 4, "instrumentId": "retro.harp", "allowInstrument": True},
    )
    assert ok.status_code == 200 and ok.json()["revision"] == 5
    assert ctx.store.load(PID).brief.allowed_instrument_ids == ["retro.wooden_flute", "retro.harp"]


def test_delete_project(client: TestClient, ctx: AppContext) -> None:
    assert client.delete(f"/api/projects/{PID}", params={"token": TOKEN}).status_code == 401
    with client.websocket_connect(f"/api/events?token={TOKEN}") as ws:
        assert ws.receive_json()["type"] == "hello"
        deadline = time.time() + 5
        while ctx.events.subscriber_count == 0 and time.time() < deadline:
            time.sleep(0.01)
        response = client.delete(f"/api/projects/{PID}", headers=AUTH)
        assert response.status_code == 200, response.text
        assert response.json()["trash"].startswith(f"{PID}--")
        event = ws.receive_json()
        assert (event["type"], event["projectId"]) == ("project.deleted", PID)
    assert client.get(f"/api/projects/{PID}", headers=AUTH).status_code == 404
    assert client.get("/api/projects", headers=AUTH).json()["projects"] == []
    assert client.delete(f"/api/projects/{PID}", headers=AUTH).status_code == 404
    assert any((ctx.data_dir / "trash").iterdir())


@pytest.mark.skipif(not (HAS_AUDIO and shutil.which("lame")), reason="fluidsynth + lame required")
def test_mp3_export(client: TestClient) -> None:
    status = client.get("/api/status", headers=AUTH).json()
    assert status["encoders"]["mp3"] is True and status["mp3Bitrates"] == [128, 192, 256, 320]
    made = client.post(
        f"/api/projects/{PID}/exports", headers=AUTH, json={"format": "mp3", "bitrate": 256}
    )
    assert made.status_code == 200, made.text
    entry = made.json()
    assert entry["file"] == "lanterns-r3-256k.mp3" and entry["mediaType"] == "audio/mpeg"
    audio = client.get(entry["downloadPath"], params={"token": TOKEN})
    assert audio.status_code == 200 and audio.content[:3] == b"ID3"
    assert audio.headers["content-type"] == "audio/mpeg"
    bad = client.post(
        f"/api/projects/{PID}/exports", headers=AUTH, json={"format": "mp3", "bitrate": 100}
    )
    assert bad.status_code == 400


def test_reset_track_endpoint(client: TestClient) -> None:
    view = client.get(f"/api/projects/{PID}", headers=AUTH).json()
    assert view["trackDefaults"]["flute"]["instrumentId"] == "retro.wooden_flute"
    client.patch(
        f"/api/projects/{PID}/tracks/flute",
        headers=AUTH,
        json={"expectedRevision": 3, "instrumentId": "retro.oboe", "gainDb": -9},
    )
    reset = client.post(
        f"/api/projects/{PID}/tracks/flute/reset",
        headers=AUTH,
        json={"expectedRevision": 4, "fields": ["instrument"]},
    )
    assert reset.status_code == 200, reset.text
    track = client.get(f"/api/projects/{PID}", headers=AUTH).json()["score"]["tracks"][0]
    assert (track["instrumentId"], track["gainDb"]) == ("retro.wooden_flute", -9.0)
    bad = client.post(
        f"/api/projects/{PID}/tracks/flute/reset",
        headers=AUTH,
        json={"expectedRevision": 5, "fields": ["tempo"]},
    )
    assert bad.status_code == 400
    stale = client.post(
        f"/api/projects/{PID}/tracks/flute/reset", headers=AUTH, json={"expectedRevision": 1}
    )
    assert stale.status_code == 409


@pytest.mark.skipif(not HAS_AUDIO, reason="fluidsynth and FluidR3 required")
def test_loop_render_endpoint(client: TestClient) -> None:
    job = client.post(f"/api/projects/{PID}/render", headers=AUTH, json={"loop": True}).json()
    for _ in range(200):
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
        job = client.get(f"/api/jobs/{job['jobId']}", headers=AUTH).json()
    assert job["status"] == "completed", job
    assert (job["render"]["startTick"], job["render"]["endTick"]) == (0, 4 * 2880)
    # 4 bars of 6/8 at 84 BPM = 8.571 s, and no decay tail.
    assert job["render"]["durationSeconds"] == pytest.approx(8.571, abs=0.01)


def test_template_routes(client: TestClient) -> None:
    listed = client.get("/api/templates", headers=AUTH).json()["templates"]
    assert len(listed) == 6 and all(t["builtIn"] for t in listed)
    town = client.get("/api/templates/peaceful-town", headers=AUTH).json()
    assert town["chart"][0]["chords"][:4] == ["G", "Em", "C", "D"]
    assert client.get("/api/templates/disco", headers=AUTH).status_code == 404
    copy = client.post(
        "/api/templates/peaceful-town/duplicate",
        headers=AUTH,
        json={"newId": "my-town", "name": "My Town"},
    )
    assert copy.status_code == 200 and copy.json()["builtIn"] is False
    edited = {**copy.json(), "default_tempo": 96}
    saved = client.put("/api/templates/my-town", headers=AUTH, json=edited)
    assert saved.status_code == 200 and saved.json()["default_tempo"] == 96
    bad = client.put("/api/templates/my-town", headers=AUTH, json={**edited, "default_tempo": 500})
    assert bad.status_code == 422 and bad.json()["code"] == "INVALID_TEMPLATE"
    assert client.put("/api/templates/tavern", headers=AUTH, json=edited).status_code == 422
    assert client.delete("/api/templates/tavern", headers=AUTH).status_code == 422
    assert client.delete("/api/templates/my-town", headers=AUTH).status_code == 200
    assert client.get("/api/templates/my-town", headers=AUTH).status_code == 404
