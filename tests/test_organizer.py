"""Favorites and collections: organizer, web API, MCP tools."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from mcp import Client
from starlette.testclient import TestClient

from midimcp.context import AppContext
from midimcp.mcp_server import build_mcp_server
from midimcp.organizer import CollectionNotFound, OrganizerError, SongNotFound, SongOrganizer
from tests.test_mcp import call, call_error
from tests.test_web_api import AUTH, PID, client, ctx  # noqa: F401  (fixtures)


@pytest.fixture
def songs() -> set[str]:
    return {"town", "forest", "crypt"}


@pytest.fixture
def org(tmp_path: Path, songs: set[str]) -> SongOrganizer:
    return SongOrganizer(tmp_path, song_exists=lambda pid: pid in songs)


def test_favorites_and_collections(org: SongOrganizer, songs: set[str], tmp_path: Path) -> None:
    assert org.snapshot() == {"favorites": [], "collections": []}
    org.set_favorite("town", True)
    org.set_favorite("town", True)  # idempotent
    org.set_favorite("forest", True)
    org.set_favorite("forest", False)
    towns = org.create_collection("  Town   themes ")
    assert towns == {"id": "town-themes", "name": "Town themes", "projectIds": [], "count": 0}
    bosses = org.create_collection("Boss fights")
    org.set_collections("town", [towns["id"], bosses["id"]])
    org.set_collections("crypt", [bosses["id"]])
    org.set_collections("town", [towns["id"]])  # exact set: removed from bosses
    snap = org.snapshot()
    assert snap["favorites"] == ["town"]
    assert [(c["name"], c["projectIds"]) for c in snap["collections"]] == [
        ("Town themes", ["town"]),
        ("Boss fights", ["crypt"]),
    ]
    assert org.for_project("town") == {"favorite": True, "collections": ["town-themes"]}
    # Stored as plain JSON next to the songs; reloading gives the same state.
    stored = json.loads((tmp_path / "collections.json").read_text())
    assert stored["formatVersion"] == 1 and stored["favorites"] == ["town"]
    again = SongOrganizer(tmp_path, song_exists=lambda pid: pid in songs)
    assert again.snapshot() == snap


def test_names_ids_and_errors(org: SongOrganizer) -> None:
    first = org.create_collection("Overworld")
    with pytest.raises(OrganizerError):
        org.create_collection("overworld")  # names are unique, ignoring case
    for bad in ("", "   ", "x" * 41, None):
        with pytest.raises(OrganizerError):
            org.create_collection(bad)  # type: ignore[arg-type]
    assert org.create_collection("Favorites")["id"] == "favorites-2"  # reserved filter ids
    org.rename_collection(first["id"], "World map")
    assert org.find("world MAP")["id"] == "overworld"  # id stays, name changes
    with pytest.raises(OrganizerError):
        org.rename_collection("favorites-2", "World map")
    with pytest.raises(CollectionNotFound) as error:
        org.find("Dungeons")
    assert "World map" in str(error.value)
    with pytest.raises(SongNotFound):
        org.set_favorite("missing", True)
    with pytest.raises(CollectionNotFound):
        org.set_collections("town", ["nope"])
    with pytest.raises(CollectionNotFound):
        org.delete_collection("nope")


def test_deleted_songs_are_hidden_but_come_back(org: SongOrganizer, songs: set[str]) -> None:
    towns = org.create_collection("Towns")
    org.set_favorite("town", True)
    org.set_collections("town", [towns["id"]])
    songs.discard("town")  # moved to trash
    snap = org.snapshot()
    assert snap["favorites"] == [] and snap["collections"][0]["count"] == 0
    songs.add("town")  # restored from trash
    assert org.for_project("town") == {"favorite": True, "collections": ["towns"]}
    org.delete_collection(towns["id"])  # deleting a collection keeps the song
    assert org.for_project("town") == {"favorite": True, "collections": []}


def test_unreadable_file_is_kept_aside(tmp_path: Path) -> None:
    (tmp_path / "collections.json").write_text("{ not json")
    org = SongOrganizer(tmp_path, song_exists=lambda pid: True)
    assert org.snapshot() == {"favorites": [], "collections": []}
    assert list(tmp_path.glob("collections.json.unreadable-*"))


# ------------------------------------------------------------------ web API


def test_web_api_organization(client: TestClient, ctx: AppContext) -> None:  # noqa: F811
    revision = ctx.store.load(PID).revision
    created = client.post("/api/collections", headers=AUTH, json={"name": "Town themes"})
    assert created.status_code == 200 and created.json()["id"] == "town-themes"
    assert client.post("/api/collections", headers=AUTH, json={"name": ""}).status_code == 422
    saved = client.put(
        f"/api/projects/{PID}/organization",
        headers=AUTH,
        json={"favorite": True, "collections": ["town-themes"]},
    )
    assert saved.json() == {"favorite": True, "collections": ["town-themes"]}
    listed = client.get("/api/projects", headers=AUTH).json()["projects"][0]
    assert listed["favorite"] is True and listed["collections"] == ["town-themes"]
    assert ctx.store.load(PID).revision == revision  # organizing never touches the song
    bad = client.put(f"/api/projects/{PID}/organization", headers=AUTH, json={"favorite": "yes"})
    assert bad.status_code == 400
    missing = client.put(
        f"/api/projects/{PID}/organization", headers=AUTH, json={"collections": ["nope"]}
    )
    assert missing.status_code == 404 and missing.json()["code"] == "COLLECTION_NOT_FOUND"
    assert (
        client.put("/api/projects/nope/organization", headers=AUTH, json={}).status_code == 200
    )  # nothing to change
    assert (
        client.put(
            "/api/projects/nope/organization", headers=AUTH, json={"favorite": True}
        ).status_code
        == 404
    )
    renamed = client.patch("/api/collections/town-themes", headers=AUTH, json={"name": "Towns"})
    assert renamed.json()["name"] == "Towns"
    assert client.delete("/api/collections/town-themes", headers=AUTH).json()["ok"] is True
    assert client.get("/api/collections", headers=AUTH).json()["collections"] == []
    assert client.get("/api/collections").status_code == 401  # token required


def test_organizing_publishes_a_live_event(client: TestClient, ctx: AppContext) -> None:  # noqa: F811
    seen: list[dict] = []
    original = ctx.events.publish
    ctx.events.publish = lambda event: (seen.append(event), original(event))  # type: ignore[method-assign]
    client.put(f"/api/projects/{PID}/organization", headers=AUTH, json={"favorite": True})
    assert {"type": "library.organized"} in seen


# ---------------------------------------------------------------------- MCP


def test_mcp_lists_and_files_songs_but_cannot_create(ctx: AppContext) -> None:  # noqa: F811
    ctx.organizer.create_collection("Town themes")
    ctx.organizer.set_favorite(PID, True)

    async def go() -> None:
        async with Client(build_mcp_server(ctx)) as mcp:
            tools = {t.name for t in (await mcp.list_tools()).tools}
            assert {"list_collections", "add_to_collection"} <= tools
            assert not tools & {"create_collection", "set_favorite", "delete_collection"}
            listed = await call(mcp, "list_collections")
            assert listed["favorites"] == [PID]
            added = await call(mcp, "add_to_collection", project_id=PID, collection="town THEMES")
            assert added["collection"] == "Town themes" and added["collections"] == ["town-themes"]
            projects = (await call(mcp, "list_projects"))["projects"]
            assert projects[0]["favorite"] is True and projects[0]["collections"] == ["town-themes"]
            error = await call_error(mcp, "add_to_collection", project_id=PID, collection="Bosses")
            assert error["code"] == "COLLECTION_NOT_FOUND" and "Town themes" in error["message"]

    asyncio.run(go())
