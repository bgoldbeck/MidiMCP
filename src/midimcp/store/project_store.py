"""Project persistence with immutable revisions and optimistic concurrency.

Layout under ``root`` (see ``docs/reference/02-architecture.md``)::

    projects/<project-id>/
        manifest.json          head revision, content hash, timestamps
        score.json             current score (copy of head snapshot)
        brief.json             current brief (copy of head snapshot)
        revisions/000001.json  immutable snapshots: score + brief + metadata
        previews/  exports/
    library.sqlite             search index, rebuildable from disk

Commit protocol
---------------
1. The revision snapshot is the commit record. It is created with an exclusive,
   atomic write, so for any revision number exactly one writer wins (also across
   processes) and the file is never partially written. Existing snapshots are
   never rewritten.
2. ``score.json``, ``brief.json`` and finally ``manifest.json`` are replaced
   atomically.
3. If a crash happens between 1 and 2, the next access rolls forward: any
   verified snapshot beyond the manifest head becomes the head.

Every commit names ``expected_revision``; a mismatch raises
:class:`RevisionConflict` and writes nothing. Scores with validation errors are
never written.
"""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import ValidationError

from midimcp.model.brief import SUPPORTED_BRIEF_SCHEMA_VERSIONS, Brief
from midimcp.model.score import SUPPORTED_SCORE_SCHEMA_VERSIONS, Score, is_valid_identifier
from midimcp.store.errors import (
    CorruptProject,
    InvalidProjectId,
    OperationIdReused,
    ProjectExists,
    ProjectMismatch,
    ProjectNotFound,
    RevisionConflict,
    RevisionNotFound,
    UnsupportedFormat,
    ValidationFailed,
)
from midimcp.store.files import (
    atomic_write,
    content_hash,
    pretty_json_bytes,
    read_json,
    write_exclusive,
)
from midimcp.store.index import LibraryIndex, ProjectListing
from midimcp.validation import ValidationReport, validate_score

log = logging.getLogger(__name__)

STORE_FORMAT_VERSION: Final = 1
_REVISION_FILE: Final = re.compile(r"^(\d{6,})\.json$")

Author = Literal["user", "agent", "system"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class RevisionInfo:
    revision: int
    parent_revision: int | None
    created_at: str
    author: str
    summary: str
    operation_id: str | None
    content_sha256: str

    def to_dict(self) -> dict:
        return {
            "revision": self.revision,
            "parentRevision": self.parent_revision,
            "createdAt": self.created_at,
            "author": self.author,
            "summary": self.summary,
            "operationId": self.operation_id,
            "contentSha256": self.content_sha256,
        }


@dataclass(frozen=True)
class ProjectSnapshot:
    """A project's score and brief at one revision."""

    project_id: str
    revision: int
    score: Score
    brief: Brief
    info: RevisionInfo


@dataclass(frozen=True)
class CommitResult:
    snapshot: ProjectSnapshot
    validation: ValidationReport
    replayed: bool = False
    """True when an earlier commit with the same operation ID was returned."""

    @property
    def revision(self) -> int:
        return self.snapshot.revision


class ProjectStore:
    def __init__(self, root: Path | str, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self.root = Path(root)
        self.projects_dir = self.root / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.index = LibraryIndex(self.root / "library.sqlite")
        self._clock = clock
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    # ------------------------------------------------------------------ paths

    def project_dir(self, project_id: str) -> Path:
        if not is_valid_identifier(project_id):
            raise InvalidProjectId(f"invalid project id {project_id!r}")
        path = self.projects_dir / project_id
        if path.resolve().parent != self.projects_dir.resolve():
            raise InvalidProjectId(f"invalid project id {project_id!r}")
        return path

    @staticmethod
    def _revision_path(project_dir: Path, revision: int) -> Path:
        return project_dir / "revisions" / f"{revision:06d}.json"

    def _lock(self, project_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(project_id, threading.RLock())

    def exists(self, project_id: str) -> bool:
        return (self.project_dir(project_id) / "manifest.json").is_file()

    # ---------------------------------------------------------------- public

    def create_project(
        self,
        score: Score,
        brief: Brief | None = None,
        *,
        summary: str = "Created project",
        author: Author = "user",
        operation_id: str | None = None,
    ) -> CommitResult:
        """Create a project at revision 1. Raises ProjectExists if the ID is taken."""
        project_id = score.project_id
        final_dir = self.project_dir(project_id)
        brief = brief or Brief()
        with self._lock(project_id):
            if final_dir.exists():
                raise ProjectExists(f"project {project_id!r} already exists")
            score, brief, report = self._prepare(project_id, score, brief, revision=1)
            staging = self.projects_dir / f".creating-{project_id}-{uuid.uuid4().hex[:8]}"
            try:
                for sub in ("revisions", "previews", "exports"):
                    (staging / sub).mkdir(parents=True)
                info = self._write_commit(
                    staging, score, brief, 1, None, summary, author, operation_id
                )
                try:
                    staging.rename(final_dir)
                except OSError as exc:
                    raise ProjectExists(f"project {project_id!r} already exists") from exc
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
            self._update_index(score, info, created_at=info.created_at)
            return CommitResult(ProjectSnapshot(project_id, 1, score, brief, info), report)

    def load(self, project_id: str) -> ProjectSnapshot:
        """Load the head revision, recovering from interrupted commits if needed."""
        project_dir = self._existing_dir(project_id)
        with self._lock(project_id):
            manifest = self._recover(project_dir)
            return self._load_head(project_dir, manifest)

    def commit(
        self,
        project_id: str,
        *,
        expected_revision: int,
        score: Score,
        brief: Brief,
        summary: str,
        author: Author = "user",
        operation_id: str | None = None,
    ) -> CommitResult:
        """Write a new head revision if ``expected_revision`` is still the head."""
        project_dir = self._existing_dir(project_id)
        with self._lock(project_id):
            manifest = self._recover(project_dir)
            head = manifest["headRevision"]
            if operation_id is not None:
                replay = self._replay(project_dir, project_id, operation_id, score, brief)
                if replay is not None:
                    return replay
            if expected_revision != head:
                raise RevisionConflict(project_id, expected_revision, head)
            new_revision = head + 1
            score, brief, report = self._prepare(project_id, score, brief, new_revision)
            try:
                info = self._write_commit(
                    project_dir,
                    score,
                    brief,
                    new_revision,
                    head,
                    summary,
                    author,
                    operation_id,
                    created_at=manifest["createdAt"],
                )
            except FileExistsError as exc:
                # Another process committed this revision number first.
                raise RevisionConflict(project_id, expected_revision, new_revision) from exc
            self._update_index(score, info, created_at=manifest["createdAt"])
            return CommitResult(
                ProjectSnapshot(project_id, new_revision, score, brief, info), report
            )

    def find_operation(self, project_id: str, operation_id: str) -> CommitResult | None:
        """Return the commit made with ``operation_id``, if any (for idempotent retries)."""
        project_dir = self._existing_dir(project_id)
        with self._lock(project_id):
            self._recover(project_dir)
            for _, path in reversed(self._snapshot_files(project_dir)):
                raw = self._read_snapshot_raw(path, project_id)
                if raw["operationId"] == operation_id:
                    snapshot = self._read_snapshot(path, project_id)
                    report = validate_score(snapshot.score, snapshot.brief)
                    return CommitResult(snapshot, report, replayed=True)
        return None

    def load_revision(self, project_id: str, revision: int) -> ProjectSnapshot:
        project_dir = self._existing_dir(project_id)
        path = self._revision_path(project_dir, revision)
        if not path.is_file():
            raise RevisionNotFound(f"project {project_id!r} has no revision {revision}")
        return self._read_snapshot(path, project_id)

    def list_revisions(self, project_id: str) -> list[RevisionInfo]:
        project_dir = self._existing_dir(project_id)
        with self._lock(project_id):
            manifest = self._recover(project_dir)
            head = manifest["headRevision"]
            return [
                self._read_snapshot(path, project_id).info
                for number, path in self._snapshot_files(project_dir)
                if number <= head
            ]

    def list_projects(self, search: str | None = None) -> list[ProjectListing]:
        on_disk = {p.name for p in self.projects_dir.iterdir() if (p / "manifest.json").is_file()}
        try:
            if self.index.project_ids() != on_disk:
                self.rebuild_index()
            return self.index.search(search)
        except sqlite3.DatabaseError:
            log.warning("library index unreadable; rebuilding", exc_info=True)
            self.index.path.unlink(missing_ok=True)
            self.rebuild_index()
            return self.index.search(search)

    def rebuild_index(self) -> None:
        listings = []
        for project_dir in sorted(self.projects_dir.iterdir()):
            if not (project_dir / "manifest.json").is_file():
                continue
            try:
                snapshot = self.load(project_dir.name)
                manifest = read_json(project_dir / "manifest.json")
            except Exception:
                log.warning("skipping unreadable project %s", project_dir.name, exc_info=True)
                continue
            listings.append(self._listing(snapshot.score, snapshot.info, manifest["createdAt"]))
        self.index.replace_all(listings)

    # -------------------------------------------------------------- internals

    def _existing_dir(self, project_id: str) -> Path:
        project_dir = self.project_dir(project_id)
        if not (project_dir / "manifest.json").is_file():
            raise ProjectNotFound(f"project {project_id!r} does not exist")
        return project_dir

    def _prepare(
        self, project_id: str, score: Score, brief: Brief, revision: int
    ) -> tuple[Score, Brief, ValidationReport]:
        if score.project_id != project_id:
            raise ProjectMismatch(
                f"score projectId {score.project_id!r} does not match {project_id!r}"
            )
        # Round-trip through JSON so the stored form is exactly what will be reloaded.
        score_data = score.to_json_dict()
        score_data["revision"] = revision
        score = Score.model_validate(score_data)
        brief = Brief.model_validate(brief.to_json_dict())
        report = validate_score(score, brief)
        if not report.ok:
            raise ValidationFailed(report)
        return score, brief, report

    def _write_commit(
        self,
        project_dir: Path,
        score: Score,
        brief: Brief,
        revision: int,
        parent: int | None,
        summary: str,
        author: str,
        operation_id: str | None,
        created_at: str | None = None,
    ) -> RevisionInfo:
        score_data, brief_data = score.to_json_dict(), brief.to_json_dict()
        digest = content_hash(score_data, brief_data)
        now = _iso(self._clock())
        snapshot = {
            "formatVersion": STORE_FORMAT_VERSION,
            "projectId": score.project_id,
            "revision": revision,
            "parentRevision": parent,
            "createdAt": now,
            "author": author,
            "summary": summary,
            "operationId": operation_id,
            "contentSha256": digest,
            "score": score_data,
            "brief": brief_data,
        }
        write_exclusive(self._revision_path(project_dir, revision), pretty_json_bytes(snapshot))
        self._write_head(project_dir, snapshot, created_at or now)
        return self._info(snapshot)

    def _write_head(self, project_dir: Path, snapshot: dict, created_at: str) -> None:
        score_data = snapshot["score"]
        atomic_write(project_dir / "score.json", pretty_json_bytes(score_data))
        atomic_write(project_dir / "brief.json", pretty_json_bytes(snapshot["brief"]))
        manifest = {
            "formatVersion": STORE_FORMAT_VERSION,
            "projectId": snapshot["projectId"],
            "title": score_data["metadata"]["title"],
            "headRevision": snapshot["revision"],
            "headContentSha256": snapshot["contentSha256"],
            "scoreSchemaVersion": score_data["schemaVersion"],
            "briefSchemaVersion": snapshot["brief"]["schemaVersion"],
            "soundProfile": score_data["soundProfile"],
            "renderProfile": None,
            "createdAt": created_at,
            "updatedAt": snapshot["createdAt"],
        }
        atomic_write(project_dir / "manifest.json", pretty_json_bytes(manifest))

    def _read_manifest(self, project_dir: Path) -> dict:
        try:
            manifest = read_json(project_dir / "manifest.json")
        except (OSError, ValueError) as exc:
            raise CorruptProject(f"cannot read manifest for {project_dir.name!r}: {exc}") from exc
        if manifest.get("formatVersion") != STORE_FORMAT_VERSION:
            raise UnsupportedFormat(
                f"project {project_dir.name!r} uses store format "
                f"{manifest.get('formatVersion')!r}; this version supports {STORE_FORMAT_VERSION}"
            )
        return manifest

    def _snapshot_files(self, project_dir: Path) -> list[tuple[int, Path]]:
        found = []
        for path in (project_dir / "revisions").iterdir():
            match = _REVISION_FILE.match(path.name)
            if match:
                found.append((int(match.group(1)), path))
        return sorted(found)

    def _recover(self, project_dir: Path) -> dict:
        """Roll forward snapshots committed after the manifest head (crash recovery)."""
        manifest = self._read_manifest(project_dir)
        head = manifest["headRevision"]
        rolled = False
        while True:
            path = self._revision_path(project_dir, head + 1)
            if not path.is_file():
                break
            snapshot = self._read_snapshot_raw(path, project_dir.name)
            self._write_head(project_dir, snapshot, manifest["createdAt"])
            log.warning(
                "recovered project %s: rolled forward to revision %s", project_dir.name, head + 1
            )
            head += 1
            rolled = True
        if rolled:
            manifest = self._read_manifest(project_dir)
            snapshot = self._read_snapshot(self._revision_path(project_dir, head), project_dir.name)
            self._update_index(snapshot.score, snapshot.info, created_at=manifest["createdAt"])
        return manifest

    def _load_head(self, project_dir: Path, manifest: dict) -> ProjectSnapshot:
        project_id = project_dir.name
        head = manifest["headRevision"]
        head_path = self._revision_path(project_dir, head)
        try:
            score_data = read_json(project_dir / "score.json")
            brief_data = read_json(project_dir / "brief.json")
            intact = content_hash(score_data, brief_data) == manifest["headContentSha256"]
        except (OSError, ValueError):
            intact = False
        if not intact:
            log.warning("project %s working files damaged; restoring from snapshot", project_id)
            snapshot = self._read_snapshot_raw(head_path, project_id)
            self._write_head(project_dir, snapshot, manifest["createdAt"])
            score_data, brief_data = snapshot["score"], snapshot["brief"]
        score, brief = self._parse(score_data, brief_data, project_id)
        info = self._read_snapshot(head_path, project_id).info
        return ProjectSnapshot(project_id, head, score, brief, info)

    def _read_snapshot_raw(self, path: Path, project_id: str) -> dict:
        try:
            snapshot = read_json(path)
        except (OSError, ValueError) as exc:
            raise CorruptProject(f"cannot read {path.name} of {project_id!r}: {exc}") from exc
        if snapshot.get("formatVersion") != STORE_FORMAT_VERSION:
            raise UnsupportedFormat(f"{path.name} of {project_id!r} has unknown format version")
        digest = content_hash(snapshot.get("score"), snapshot.get("brief"))
        if digest != snapshot.get("contentSha256"):
            raise CorruptProject(f"revision file {path.name} of {project_id!r} failed checksum")
        return snapshot

    def _read_snapshot(self, path: Path, project_id: str) -> ProjectSnapshot:
        raw = self._read_snapshot_raw(path, project_id)
        score, brief = self._parse(raw["score"], raw["brief"], project_id)
        return ProjectSnapshot(project_id, raw["revision"], score, brief, self._info(raw))

    @staticmethod
    def _parse(score_data: dict, brief_data: dict, project_id: str) -> tuple[Score, Brief]:
        for kind, data, supported in (
            ("score", score_data, SUPPORTED_SCORE_SCHEMA_VERSIONS),
            ("brief", brief_data, SUPPORTED_BRIEF_SCHEMA_VERSIONS),
        ):
            version = data.get("schemaVersion")
            if version not in supported:
                raise UnsupportedFormat(
                    f"{kind} of {project_id!r} uses schemaVersion {version!r}; "
                    f"supported: {', '.join(sorted(supported))}"
                )
        try:
            return Score.model_validate(score_data), Brief.model_validate(brief_data)
        except ValidationError as exc:
            raise CorruptProject(f"stored project {project_id!r} is invalid: {exc}") from exc

    @staticmethod
    def _info(raw: dict) -> RevisionInfo:
        return RevisionInfo(
            revision=raw["revision"],
            parent_revision=raw["parentRevision"],
            created_at=raw["createdAt"],
            author=raw["author"],
            summary=raw["summary"],
            operation_id=raw["operationId"],
            content_sha256=raw["contentSha256"],
        )

    def _replay(
        self, project_dir: Path, project_id: str, operation_id: str, score: Score, brief: Brief
    ) -> CommitResult | None:
        for _, path in reversed(self._snapshot_files(project_dir)):
            raw = self._read_snapshot_raw(path, project_id)
            if raw["operationId"] != operation_id:
                continue
            stored_score = dict(raw["score"], revision=0)
            incoming_score = dict(score.to_json_dict(), revision=0)
            if stored_score != incoming_score or raw["brief"] != brief.to_json_dict():
                raise OperationIdReused(
                    f"operation id {operation_id!r} was already used for different content "
                    f"(revision {raw['revision']})"
                )
            snapshot = self._read_snapshot(path, project_id)
            return CommitResult(snapshot, validate_score(snapshot.score, snapshot.brief), True)
        return None

    def _listing(self, score: Score, info: RevisionInfo, created_at: str) -> ProjectListing:
        return ProjectListing(
            project_id=score.project_id,
            title=score.metadata.title,
            usage=score.metadata.usage,
            tags=tuple(score.metadata.tags),
            head_revision=info.revision,
            created_at=created_at,
            updated_at=info.created_at,
        )

    def _update_index(self, score: Score, info: RevisionInfo, created_at: str) -> None:
        # The index is a rebuildable cache: a failure here must not fail a durable commit.
        try:
            self.index.upsert(self._listing(score, info, created_at))
        except sqlite3.Error:
            log.warning("library index update failed; it will be rebuilt", exc_info=True)
