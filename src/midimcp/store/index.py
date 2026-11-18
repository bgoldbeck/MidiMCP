"""SQLite library index. A cache for fast listing/search; never the source of truth."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

# The table is versioned by name: a newer layout gets a new table, which starts empty, so the
# store sees the mismatch with the projects on disk and rebuilds the index.
_TABLE = "songs_v2"
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    project_id    TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    usage         TEXT,
    tags          TEXT NOT NULL,
    head_revision INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    template_id   TEXT,
    mood          TEXT,
    setting       TEXT,
    key_name      TEXT
)
"""
_PLACEHOLDERS = ", ".join(["?"] * 11)
# Fields a search word may match.
_SEARCH_FIELDS = (
    "title",
    "project_id",
    "coalesce(usage, '')",
    "tags",
    "coalesce(template_id, '')",
    "coalesce(mood, '')",
    "coalesce(setting, '')",
    "coalesce(key_name, '')",
)


@dataclass(frozen=True)
class ProjectListing:
    project_id: str
    title: str
    usage: str | None
    tags: tuple[str, ...]
    head_revision: int
    created_at: str
    updated_at: str
    template_id: str | None = None
    mood: str | None = None
    setting: str | None = None
    key_name: str | None = None  # e.g. "F ionian"

    def to_dict(self) -> dict:
        return {
            "projectId": self.project_id,
            "title": self.title,
            "usage": self.usage,
            "tags": list(self.tags),
            "headRevision": self.head_revision,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "templateId": self.template_id,
            "mood": self.mood,
            "setting": self.setting,
            "key": self.key_name,
        }

    def row(self) -> tuple:
        return (
            self.project_id,
            self.title,
            self.usage,
            json.dumps(list(self.tags)),
            self.head_revision,
            self.created_at,
            self.updated_at,
            self.template_id,
            self.mood,
            self.setting,
            self.key_name,
        )


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
                f"""
                INSERT INTO {_TABLE} VALUES ({_PLACEHOLDERS})
                ON CONFLICT(project_id) DO UPDATE SET
                    title=excluded.title, usage=excluded.usage, tags=excluded.tags,
                    head_revision=excluded.head_revision, updated_at=excluded.updated_at,
                    template_id=excluded.template_id, mood=excluded.mood,
                    setting=excluded.setting, key_name=excluded.key_name
                """,
                listing.row(),
            )

    def replace_all(self, listings: Iterable[ProjectListing]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(f"DELETE FROM {_TABLE}")
            conn.executemany(
                f"INSERT INTO {_TABLE} VALUES ({_PLACEHOLDERS})",
                [item.row() for item in listings],
            )

    def delete(self, project_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(f"DELETE FROM {_TABLE} WHERE project_id = ?", (project_id,))

    def project_ids(self) -> set[str]:
        with closing(self._connect()) as conn:
            return {row[0] for row in conn.execute(f"SELECT project_id FROM {_TABLE}")}

    def search(self, text: str | None = None) -> list[ProjectListing]:
        """Songs, newest first. With ``text``, every word must appear in the title, id, usage,
        tags, template, mood, setting or key (case-insensitive)."""
        query = f"SELECT * FROM {_TABLE}"
        params: list = []
        clauses = []
        for word in (text or "").lower().split():
            clauses.append("(" + " OR ".join(f"lower({f}) LIKE ?" for f in _SEARCH_FIELDS) + ")")
            params += [f"%{word}%"] * len(_SEARCH_FIELDS)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
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
                template_id=r[7],
                mood=r[8],
                setting=r[9],
                key_name=r[10],
            )
            for r in rows
        ]
