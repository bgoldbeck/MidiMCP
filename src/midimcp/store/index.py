"""SQLite library index. A cache for fast listing/search; never the source of truth."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_id    TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    usage         TEXT,
    tags          TEXT NOT NULL,
    head_revision INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class ProjectListing:
    project_id: str
    title: str
    usage: str | None
    tags: tuple[str, ...]
    head_revision: int
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "projectId": self.project_id,
            "title": self.title,
            "usage": self.usage,
            "tags": list(self.tags),
            "headRevision": self.head_revision,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class LibraryIndex:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            conn.execute(_SCHEMA)
        except Exception:
            # A corrupt index must be replaceable immediately on Windows too.
            # The caller's closing() cannot own a connection we never returned.
            conn.close()
            raise
        return conn

    def upsert(self, listing: ProjectListing) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    title=excluded.title, usage=excluded.usage, tags=excluded.tags,
                    head_revision=excluded.head_revision, updated_at=excluded.updated_at
                """,
                (
                    listing.project_id,
                    listing.title,
                    listing.usage,
                    json.dumps(list(listing.tags)),
                    listing.head_revision,
                    listing.created_at,
                    listing.updated_at,
                ),
            )

    def replace_all(self, listings: Iterable[ProjectListing]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM projects")
            conn.executemany(
                "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.project_id,
                        item.title,
                        item.usage,
                        json.dumps(list(item.tags)),
                        item.head_revision,
                        item.created_at,
                        item.updated_at,
                    )
                    for item in listings
                ],
            )

    def delete(self, project_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))

    def project_ids(self) -> set[str]:
        with closing(self._connect()) as conn:
            return {row[0] for row in conn.execute("SELECT project_id FROM projects")}

    def search(self, text: str | None = None) -> list[ProjectListing]:
        query = "SELECT * FROM projects"
        params: tuple = ()
        if text:
            pattern = f"%{text.lower()}%"
            query += (
                " WHERE lower(title) LIKE ? OR lower(project_id) LIKE ?"
                " OR lower(coalesce(usage, '')) LIKE ? OR lower(tags) LIKE ?"
            )
            params = (pattern,) * 4
        query += " ORDER BY updated_at DESC, project_id"
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ProjectListing(
                project_id=r[0],
                title=r[1],
                usage=r[2],
                tags=tuple(json.loads(r[3])),
                head_revision=r[4],
                created_at=r[5],
                updated_at=r[6],
            )
            for r in rows
        ]
