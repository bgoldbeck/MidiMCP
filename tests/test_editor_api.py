import pytest

from tests.test_web_api import AUTH, PID

pytest_plugins = ("tests.test_web_api",)


@pytest.mark.parametrize(
    "operations",
    [
        None,
        {},
        [None],
        [{"op": "add", "trackId": []}],
        [{"op": "add", "trackId": "flute", "note": []}],
        [{"op": "update", "noteId": []}],
    ],
)
def test_malformed_notes(client, ctx, operations):
    response = client.post(
        f"/api/projects/{PID}/notes",
        headers=AUTH,
        json={"expectedRevision": 3, "operations": operations},
    )
    assert response.status_code == 400, response.text
    assert ctx.store.load(PID).revision == 3


def test_notes_atomic_conflict_and_auth(client, ctx):
    path = f"/api/projects/{PID}/notes"
    note_id = ctx.store.load(PID).score.tracks[0].notes[0].id
    ops = [{"op": "update", "noteId": note_id, "pitch": 70}]
    assert client.post(path, json={"expectedRevision": 3, "operations": ops}).status_code == 401
    bad = client.post(
        path,
        headers=AUTH,
        json={"expectedRevision": 3, "operations": [*ops, {"op": "delete", "noteId": "missing"}]},
    )
    assert bad.status_code == 404
    assert ctx.store.load(PID).revision == 3
    assert (
        client.post(path, headers=AUTH, json={"expectedRevision": 3, "operations": ops}).status_code
        == 200
    )
    assert (
        client.post(path, headers=AUTH, json={"expectedRevision": 3, "operations": ops}).status_code
        == 409
    )


def test_lock_source_destination_and_unlock(client, ctx):
    path = f"/api/projects/{PID}"
    lock = client.post(
        path + "/locks",
        headers=AUTH,
        json={"expectedRevision": 3, "trackId": "flute", "startTick": 0, "endTick": 1440},
    )
    assert lock.status_code == 200, lock.text
    notes = ctx.store.load(PID).score.tracks[0].notes
    for note, start in [(notes[0], 3000), (notes[2], 0)]:
        result = client.post(
            path + "/notes",
            headers=AUTH,
            json={
                "expectedRevision": 4,
                "operations": [{"op": "update", "noteId": note.id, "startTick": start}],
            },
        )
        assert result.status_code == 423, result.text
    lock_id = lock.json()["createdIds"][0]
    result = client.request(
        "DELETE", path + "/locks/" + lock_id, headers=AUTH, json={"expectedRevision": 4}
    )
    assert result.status_code == 200


def test_arrangement_and_render_ticks(client, ctx, monkeypatch):
    path = f"/api/projects/{PID}"
    response = client.post(
        path + "/arrangement",
        headers=AUTH,
        json={
            "expectedRevision": 3,
            "bars": 5,
            "loopEnabled": True,
            "loopStartBar": 2,
            "loopEndBar": 4,
        },
    )
    assert response.status_code == 200, response.text
    timeline = ctx.store.load(PID).score.timeline
    assert (timeline.total_ticks, timeline.loop.start_tick, timeline.loop.end_tick) == (
        14400,
        2880,
        11520,
    )
    calls = []

    class Result:
        def to_dict(self):
            return {"ok": True}

    def submit(score, **kwargs):
        calls.append(kwargs)
        return Result()

    monkeypatch.setattr(ctx.jobs, "submit", submit)
    result = client.post(path + "/render", headers=AUTH, json={"startTick": 100, "endTick": 500})
    assert result.status_code == 200
    assert calls == [{"speed": 1.0, "start_tick": 100, "end_tick": 500, "tail": False}]
    for body in [
        {"startTick": 1},
        {"startTick": True, "endTick": 3},
        {"startTick": 3, "endTick": 3},
        {"startTick": 0, "endTick": 15000},
        {"startTick": 1, "endTick": 5, "loop": True},
    ]:
        assert client.post(path + "/render", headers=AUTH, json=body).status_code == 400
    assert len(calls) == 1


def test_editor_limits(client):
    path = f"/api/projects/{PID}/notes"
    assert (
        client.post(
            path,
            headers=AUTH,
            json={"expectedRevision": 3, "operations": [{"op": "delete", "noteId": "n1"}] * 20001},
        ).status_code
        == 400
    )
    assert client.post(path, headers=AUTH, content=" " * (4 * 1024 * 1024 + 1)).status_code == 413


def test_arrangement_conflict_bounds_and_restore(client, ctx):
    path = f"/api/projects/{PID}"
    for body in [
        {"expectedRevision": 2, "bars": 5},
        {"expectedRevision": 3, "loopStartBar": 4, "loopEndBar": 2},
        {"expectedRevision": 3, "bars": True},
        {"expectedRevision": 3, "loopEnabled": "true"},
    ]:
        response = client.post(path + "/arrangement", headers=AUTH, json=body)
        assert 400 <= response.status_code < 500, response.text
        assert ctx.store.load(PID).revision == 3
    note = ctx.store.load(PID).score.tracks[0].notes[0]
    response = client.post(
        path + "/notes",
        headers=AUTH,
        json={
            "expectedRevision": 3,
            "extendToTick": 12000,
            "operations": [{"op": "update", "noteId": note.id, "startTick": 11520}],
        },
    )
    assert response.status_code == 200, response.text
    assert ctx.store.load(PID).score.timeline.total_ticks == 14400
    response = client.post(
        path + "/restore", headers=AUTH, json={"expectedRevision": 4, "revision": 3}
    )
    assert response.status_code == 200
    assert ctx.store.load(PID).score.timeline.total_ticks == 11520
    response = client.post(
        path + "/restore", headers=AUTH, json={"expectedRevision": 5, "revision": 4}
    )
    assert response.status_code == 200
    assert ctx.store.load(PID).score.timeline.total_ticks == 14400


@pytest.mark.parametrize(
    "body",
    [
        [],
        None,
        "bad",
        {"expectedRevision": True, "operations": []},
        {
            "expectedRevision": 3,
            "operations": [{"op": "add", "trackId": "flute", "note": {"id": []}}],
        },
    ],
)
def test_invalid_body_types(client, ctx, body):
    result = client.post(f"/api/projects/{PID}/notes", headers=AUTH, json=body)
    assert result.status_code == 400, result.text
    assert ctx.store.load(PID).revision == 3


def test_accepts_full_track_batch(client, ctx, monkeypatch):
    class Result:
        def to_dict(self):
            return {"ok": True}

    captured = []

    def edit_notes(project_id, **kwargs):
        captured.append(kwargs)
        return Result()

    monkeypatch.setattr(ctx.service, "edit_notes", edit_notes)
    operations = [
        {
            "op": "update",
            "noteId": f"n{i}",
            "startTick": i * 100,
            "durationTicks": 100,
            "velocity": 80,
            "pitch": 60,
        }
        for i in range(20000)
    ]
    response = client.post(
        f"/api/projects/{PID}/notes",
        headers=AUTH,
        json={"expectedRevision": 3, "operations": operations},
    )
    assert response.status_code == 200, response.text
    assert len(captured[0]["operations"]) == 20000
