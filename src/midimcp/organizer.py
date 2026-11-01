"""Favorites and collections: the user's own organization of songs.

Stored in ``<data>/collections.json``, separate from song content: changing it
creates no song revision and never invalidates renders. Memberships of deleted
songs are kept, so a song restored from the trash comes back in its
collections; listings simply skip songs that do not exist.

File format (``formatVersion`` 1)::

    {"formatVersion": 1,
     "favorites": ["lanterns-of-the-vale"],
     "collections": [{"id": "town-themes", "name": "Town themes",
                      "projectIds": ["lanterns-of-the-vale"]}]}
"""

from __future__ import annotations

import contextlib
import logging
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from midimcp.store.files import atomic_write, pretty_json_bytes, read_json

log = logging.getLogger(__name__)

FORMAT_VERSION: Final = 1
MAX_COLLECTIONS: Final = 100
MAX_NAME: Final = 40


class OrganizerError(ValueError):
    code = "INVALID_COLLECTION"

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self)}


class CollectionNotFound(OrganizerError):
    code = "COLLECTION_NOT_FOUND"


class SongNotFound(OrganizerError):
    code = "PROJECT_NOT_FOUND"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "collection"


class SongOrganizer:
    def __init__(
        self,
        data_dir: Path | str,
        *,
        song_exists: Callable[[str], bool],
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.path = Path(data_dir) / "collections.json"
        self.song_exists = song_exists
        self.on_change = on_change
        self._lock = threading.Lock()

    # ------------------------------------------------------------ file

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"formatVersion": FORMAT_VERSION, "favorites": [], "collections": []}
        try:
            data = read_json(self.path)
            if data.get("formatVersion") != FORMAT_VERSION:
                raise ValueError("unknown formatVersion")
            favorites = [p for p in data["favorites"] if isinstance(p, str)]
            collections = [
                {
                    "id": str(c["id"]),
                    "name": str(c["name"]),
                    "projectIds": [p for p in c["projectIds"] if isinstance(p, str)],
                }
                for c in data["collections"]
            ]
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            # Never lose the user's file: keep it aside and start empty.
            aside = self.path.with_name(f"collections.json.unreadable-{int(time.time())}")
            log.error("cannot read %s (%s); moved it to %s", self.path, exc, aside.name)
            with contextlib.suppress(OSError):
                self.path.replace(aside)
            return {"formatVersion": FORMAT_VERSION, "favorites": [], "collections": []}
        return {"formatVersion": FORMAT_VERSION, "favorites": favorites, "collections": collections}

    def _save(self, data: dict[str, Any]) -> None:
        atomic_write(self.path, pretty_json_bytes(data))
        if self.on_change is not None:
            self.on_change()

    def _update(self, change: Callable[[dict[str, Any]], Any]) -> Any:
        with self._lock:
            data = self._load()
            result = change(data)
            self._save(data)
            return result

    # ------------------------------------------------------------ reads

    def snapshot(self) -> dict[str, Any]:
        """Favorites and collections, listing only songs that currently exist."""
        with self._lock:
            data = self._load()
        favorites = [p for p in data["favorites"] if self.song_exists(p)]
        collections = []
        for c in data["collections"]:
            members = [p for p in c["projectIds"] if self.song_exists(p)]
            collections.append(
                {"id": c["id"], "name": c["name"], "projectIds": members, "count": len(members)}
            )
        return {"favorites": favorites, "collections": collections}

    def for_project(self, project_id: str, snapshot: dict[str, Any] | None = None) -> dict:
        snap = snapshot or self.snapshot()
        return {
            "favorite": project_id in snap["favorites"],
            "collections": [c["id"] for c in snap["collections"] if project_id in c["projectIds"]],
        }

    def annotate(self, projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Add ``favorite`` and ``collections`` to project listings."""
        snap = self.snapshot()
        return [{**p, **self.for_project(p["projectId"], snap)} for p in projects]

    def find(self, collection: str) -> dict[str, Any]:
        """A collection by id or (case-insensitive) name."""
        wanted = collection.strip().lower()
        for c in self.snapshot()["collections"]:
            if c["id"] == wanted or c["name"].lower() == wanted:
                return c
        names = ", ".join(c["name"] for c in self.snapshot()["collections"]) or "none yet"
        raise CollectionNotFound(f"no collection {collection!r}; existing: {names}")

    # ----------------------------------------------------------- writes

    @staticmethod
    def _clean_name(name: Any) -> str:
        if not isinstance(name, str) or not name.strip():
            raise OrganizerError("collection name must not be empty")
        name = " ".join(name.split())
        if len(name) > MAX_NAME:
            raise OrganizerError(f"collection name must be at most {MAX_NAME} characters")
        return name

    @staticmethod
    def _collection(data: dict[str, Any], collection_id: str) -> dict[str, Any]:
        for c in data["collections"]:
            if c["id"] == collection_id:
                return c
        raise CollectionNotFound(f"no collection {collection_id!r}")

    def _require_song(self, project_id: str) -> None:
        if not self.song_exists(project_id):
            raise SongNotFound(f"no song {project_id!r}")

    def create_collection(self, name: str) -> dict[str, Any]:
        name = self._clean_name(name)

        def change(data: dict[str, Any]) -> dict[str, Any]:
            if len(data["collections"]) >= MAX_COLLECTIONS:
                raise OrganizerError(f"at most {MAX_COLLECTIONS} collections")
            if any(c["name"].lower() == name.lower() for c in data["collections"]):
                raise OrganizerError(f"a collection named {name!r} already exists")
            taken = {c["id"] for c in data["collections"]}
            base = _slug(name)
            new_id, n = base, 2
            while new_id in taken or new_id in {"all", "favorites"}:
                new_id = f"{base}-{n}"
                n += 1
            created = {"id": new_id, "name": name, "projectIds": []}
            data["collections"].append(created)
            return {**created, "count": 0}

        return self._update(change)

    def rename_collection(self, collection_id: str, name: str) -> dict[str, Any]:
        name = self._clean_name(name)

        def change(data: dict[str, Any]) -> dict[str, Any]:
            target = self._collection(data, collection_id)
            if any(
                c["name"].lower() == name.lower() and c is not target for c in data["collections"]
            ):
                raise OrganizerError(f"a collection named {name!r} already exists")
            target["name"] = name
            return {"id": target["id"], "name": name}

        return self._update(change)

    def delete_collection(self, collection_id: str) -> None:
        """Remove the collection only; its songs are untouched."""

        def change(data: dict[str, Any]) -> None:
            target = self._collection(data, collection_id)
            data["collections"].remove(target)

        self._update(change)

    def set_favorite(self, project_id: str, favorite: bool) -> None:
        self._require_song(project_id)

        def change(data: dict[str, Any]) -> None:
            favorites = [p for p in data["favorites"] if p != project_id]
            if favorite:
                favorites.append(project_id)
            data["favorites"] = favorites

        self._update(change)

    def set_collections(self, project_id: str, collection_ids: list[str]) -> None:
        """Make ``collection_ids`` exactly the collections holding this song."""
        self._require_song(project_id)
        wanted = set(collection_ids)

        def change(data: dict[str, Any]) -> None:
            unknown = wanted - {c["id"] for c in data["collections"]}
            if unknown:
                raise CollectionNotFound(f"no collection {sorted(unknown)[0]!r}")
            for c in data["collections"]:
                members = [p for p in c["projectIds"] if p != project_id]
                if c["id"] in wanted:
                    members.append(project_id)
                c["projectIds"] = members

        self._update(change)

    def add_to_collection(self, project_id: str, collection_id: str) -> None:
        self._require_song(project_id)

        def change(data: dict[str, Any]) -> None:
            target = self._collection(data, collection_id)
            if project_id not in target["projectIds"]:
                target["projectIds"].append(project_id)

        self._update(change)
