import asyncio

import pytest
from mcp import Client

from midimcp.mcp_server import build_mcp_server
from tests.test_mcp import call
from tests.test_sampler_service import BINDING, Registry
from tests.test_web_api import AUTH, PID

pytest_plugins = ("tests.test_web_api",)


@pytest.fixture(autouse=True)
def registry_constructor(monkeypatch):
    monkeypatch.setattr("midimcp.context.SamplerRegistry", lambda _data: Registry())


def install_registry(ctx):
    registry = Registry()
    registry.list_patches = lambda: [
        {
            "id": BINDING["patchId"],
            "name": "Flute",
            "sha256": BINDING["patchSha256"],
            "available": True,
            "controllers": {},
            "description": "Test flute",
        }
    ]
    ctx.samplers = ctx.service.samplers = registry


def test_sources_binding_null_and_fallback_export(client, ctx):
    install_registry(ctx)
    path = f"/api/projects/{PID}/tracks/flute"
    assert client.get("/api/sampler-patches").status_code == 401
    patches = client.get("/api/sampler-patches", headers=AUTH).json()["patches"]
    assert patches[0]["sha256"] == BINDING["patchSha256"]
    assert (
        client.patch(
            path, headers=AUTH, json={"expectedRevision": 3, "sampler": BINDING}
        ).status_code
        == 200
    )
    native = client.post(
        f"/api/projects/{PID}/exports", headers=AUTH, json={"format": "json"}
    ).json()
    assert "warnings" not in native
    native_score = client.get(native["downloadPath"], headers=AUTH).json()["score"]
    assert native_score["tracks"][0]["sampler"] == BINDING
    midi = client.post(f"/api/projects/{PID}/exports", headers=AUTH, json={"format": "midi"}).json()
    assert midi["warnings"][0]["code"] == "SAMPLER_GM_FALLBACK"
    assert (
        client.patch(path, headers=AUTH, json={"expectedRevision": 4, "gainDb": -3.0}).status_code
        == 200
    )
    assert ctx.store.load(PID).score.track("flute").sampler is not None
    assert (
        client.patch(path, headers=AUTH, json={"expectedRevision": 5, "sampler": None}).status_code
        == 200
    )
    assert ctx.store.load(PID).score.track("flute").sampler is None


def test_sustain_endpoint_and_sample_release_are_persisted(client, ctx):
    install_registry(ctx)
    path = f"/api/projects/{PID}/tracks/flute"
    response = client.post(
        path + "/automation",
        headers=AUTH,
        json={
            "expectedRevision": 3,
            "lane": "sustain",
            "startTick": 0,
            "endTick": 480,
            "points": [{"tick": 0, "value": 127}, {"tick": 479, "value": 0}],
        },
    )
    assert response.status_code == 200, response.text
    assert (
        client.patch(
            path, headers=AUTH, json={"expectedRevision": 4, "releaseSeconds": 1.2}
        ).status_code
        == 400
    )
    response = client.patch(
        path,
        headers=AUTH,
        json={"expectedRevision": 4, "sampler": BINDING, "releaseSeconds": 1.2},
    )
    assert response.status_code == 200, response.text
    track = ctx.store.load(PID).score.track("flute")
    assert track.release_seconds == 1.2
    assert [p.value for p in track.automation.sustain] == [127, 0]
    assert (
        client.patch(path, headers=AUTH, json={"expectedRevision": 5, "sampler": None}).status_code
        == 200
    )
    assert ctx.store.load(PID).score.track("flute").release_seconds is None


def test_performance_endpoint_atomic_conflict_validation_lock(client, ctx):
    path = f"/api/projects/{PID}/tracks/flute/performance"
    assert client.post(path, json={"expectedRevision": 3}).status_code == 401
    assert (
        client.post(path, headers=AUTH, json={"expectedRevision": 3, "swell": 50}).status_code
        == 400
    )
    assert (
        client.post(path, headers=AUTH, json={"expectedRevision": 3, "seed": True}).status_code
        == 400
    )
    assert ctx.store.load(PID).revision == 3
    response = client.post(path, headers=AUTH, json={"expectedRevision": 3})
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 4
    assert client.post(path, headers=AUTH, json={"expectedRevision": 3}).status_code == 409
    ctx.service.lock(PID, expected_revision=4, track_id="flute")
    assert client.post(path, headers=AUTH, json={"expectedRevision": 5}).status_code == 423
    assert ctx.store.load(PID).revision == 5


def test_mcp_source_omission_null_and_performance(ctx):
    install_registry(ctx)

    async def scenario():
        async with Client(build_mcp_server(ctx)) as client:
            listing = await call(client, "list_sampler_patches")
            assert listing["patches"][0]["available"]
            await call(
                client,
                "update_track",
                project_id=PID,
                expected_revision=3,
                track_id="flute",
                sampler=BINDING,
                release_seconds=1.2,
            )
            await call(
                client,
                "update_track",
                project_id=PID,
                expected_revision=4,
                track_id="flute",
                gain_db=-3.0,
            )
            assert ctx.store.load(PID).score.track("flute").sampler is not None
            assert ctx.store.load(PID).score.track("flute").release_seconds == 1.2
            await call(
                client,
                "update_track",
                project_id=PID,
                expected_revision=5,
                track_id="flute",
                release_seconds=None,
            )
            assert ctx.store.load(PID).score.track("flute").release_seconds is None
            await call(
                client,
                "update_track",
                project_id=PID,
                expected_revision=6,
                track_id="flute",
                sampler=None,
            )
            assert ctx.store.load(PID).score.track("flute").sampler is None
            result = await call(
                client, "apply_performance", project_id=PID, expected_revision=7, track_id="flute"
            )
            assert result["revision"] == 8

    asyncio.run(scenario())


def test_actual_sources_validation_http_mcp_and_missing_assets(client, ctx, monkeypatch):
    install_registry(ctx)
    ctx.service.update_track(
        PID, expected_revision=3, track_id="flute", changes={"sampler": BINDING}
    )

    # A saved GM fallback must not need an installed bank for sampled playback.
    def no_gm_bank(*args, **kwargs):
        raise AssertionError("sampled-only song consulted GM bank")

    monkeypatch.setattr(ctx.registry, "require", no_gm_bank)
    view = client.get(f"/api/projects/{PID}", headers=AUTH)
    assert view.status_code == 200 and view.json()["validation"]["ok"], view.text

    async def validation():
        async with Client(build_mcp_server(ctx)) as mcp:
            return await call(mcp, "validate_project", project_id=PID)

    assert asyncio.run(validation())["ok"]
    from midimcp.sampler import SamplerError

    def unavailable(*args, **kwargs):
        raise SamplerError("missing flute samples")

    monkeypatch.setattr(ctx.samplers, "require", unavailable)
    issues = client.get(f"/api/projects/{PID}", headers=AUTH).json()["validation"]["errors"]
    assert issues[0]["code"] == "SAMPLER_ERROR"
    assert issues[0]["trackId"] == "flute"
    assert asyncio.run(validation())["errors"][0]["code"] == "SAMPLER_ERROR"


@pytest.mark.parametrize("fmt", ["wav", "mp3"])
@pytest.mark.parametrize("clipped_samples", [0, 17])
def test_audio_exports_preserve_clipping_report(
    client, ctx, tmp_path, monkeypatch, fmt, clipped_samples
):
    from midimcp.render import RenderResult

    install_registry(ctx)
    ctx.service.update_track(
        PID, expected_revision=3, track_id="flute", changes={"sampler": BINDING}
    )
    rendered = tmp_path / "rendered.wav"
    rendered.write_bytes(b"rendered sampled flute audio")
    result = RenderResult(
        path=rendered,
        cache_key="cache",
        pcm_sha256="b" * 64,
        sample_rate=44100,
        channels=2,
        frames=44100,
        speed=1.0,
        start_tick=0,
        end_tick=11520,
        cached=False,
        clipped_samples=clipped_samples,
    )

    def render(score, **kwargs):
        assert score.revision == 4
        assert score.track("flute").sampler.to_json_dict() == BINDING
        return result

    monkeypatch.setattr(ctx.renderer, "render", render)

    def encode(source, target, **kwargs):
        assert source == rendered
        target.write_bytes(b"encoded sampled flute audio")
        return target

    monkeypatch.setattr("midimcp.views.encode_mp3", encode)
    response = client.post(f"/api/projects/{PID}/exports", headers=AUTH, json={"format": fmt})
    assert response.status_code == 200, response.text
    entry = response.json()
    assert entry["clippedSamples"] == clipped_samples
    assert entry["revision"] == 4 and entry["format"] == fmt
    if clipped_samples:
        assert entry["warnings"][0]["code"] == "AUDIO_CLIPPING"
        assert "17" in entry["warnings"][0]["message"]
    else:
        assert not entry.get("warnings")
    content = client.get(entry["downloadPath"], headers=AUTH).content
    assert content == (rendered.read_bytes() if fmt == "wav" else b"encoded sampled flute audio")
