from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from midimcp.model import Brief, Note, Score
from midimcp.store import (
    CorruptProject,
    InvalidProjectId,
    OperationIdReused,
    ProjectExists,
    ProjectMismatch,
    ProjectNotFound,
    ProjectStore,
    RevisionConflict,
    RevisionNotFound,
    UnsupportedFormat,
    ValidationFailed,
)
from midimcp.store.files import sha256_hex


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(tmp_path / "RetroMIDI", clock=FakeClock())


@pytest.fixture
def score(score_dict: dict) -> Score:
    return Score.model_validate(score_dict)


def with_extra_note(score: Score, note_id: str = "f9", pitch: int = 80) -> Score:
    data = score.to_json_dict()
    data["tracks"][0]["notes"].append(
        Note(
            id=note_id, pitch=pitch, start_tick=5000, duration_ticks=480, velocity=70
        ).to_json_dict()
    )
    return Score.model_validate(data)


def file_hashes(directory: Path) -> dict[str, str]:
    return {
        str(p.relative_to(directory)): sha256_hex(p.read_bytes())
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def test_create_writes_layout(store: ProjectStore, score: Score) -> None:
    result = store.create_project(score, Brief(percussion_allowed=False))
    assert result.revision == 1
    assert result.snapshot.score.revision == 1
    project = store.root / "projects" / "lanterns-of-the-vale"
    for name in ("manifest.json", "score.json", "brief.json", "revisions/000001.json"):
        assert (project / name).is_file(), name
    assert (project / "previews").is_dir()
    assert (project / "exports").is_dir()
    assert (store.root / "library.sqlite").is_file()
    manifest = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["headRevision"] == 1
    assert manifest["title"] == "Lanterns of the Vale"
    assert manifest["soundProfile"]["profileId"] == "retro-gm-1997-v1"
    assert not list((store.root / "projects").glob(".creating-*"))


def test_reopen_with_new_store_is_identical(store: ProjectStore, score: Score) -> None:
    created = store.create_project(score, Brief(loop_required=True))
    reopened = ProjectStore(store.root).load("lanterns-of-the-vale")
    assert reopened.score == created.snapshot.score
    assert reopened.brief == created.snapshot.brief
    assert reopened.revision == 1
    assert reopened.info.summary == "Created project"


def test_create_twice_fails(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    with pytest.raises(ProjectExists):
        store.create_project(score)


def test_commit_advances_and_keeps_old_revision(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    rev1_path = store.root / "projects/lanterns-of-the-vale/revisions/000001.json"
    rev1_bytes = rev1_path.read_bytes()
    result = store.commit(
        "lanterns-of-the-vale",
        expected_revision=1,
        score=with_extra_note(score),
        brief=Brief(),
        summary="Flute: 1 note added",
        author="agent",
    )
    assert result.revision == 2
    assert result.snapshot.info.parent_revision == 1
    assert rev1_path.read_bytes() == rev1_bytes
    head = store.load("lanterns-of-the-vale")
    assert head.revision == 2
    assert len(head.score.track("flute-1").notes) == 5
    old = store.load_revision("lanterns-of-the-vale", 1)
    assert len(old.score.track("flute-1").notes) == 4
    infos = store.list_revisions("lanterns-of-the-vale")
    assert [(i.revision, i.author, i.summary) for i in infos] == [
        (1, "user", "Created project"),
        (2, "agent", "Flute: 1 note added"),
    ]
    with pytest.raises(RevisionNotFound):
        store.load_revision("lanterns-of-the-vale", 3)


def test_stale_revision_conflicts_without_writing(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    store.commit(
        "lanterns-of-the-vale", expected_revision=1, score=score, brief=Brief(), summary="b"
    )
    before = file_hashes(store.root / "projects")
    with pytest.raises(RevisionConflict) as caught:
        store.commit(
            "lanterns-of-the-vale",
            expected_revision=1,
            score=with_extra_note(score),
            brief=Brief(),
            summary="stale",
        )
    assert caught.value.to_dict()["currentRevision"] == 2
    assert caught.value.code == "REVISION_CONFLICT"
    assert file_hashes(store.root / "projects") == before


def test_validation_errors_block_create_and_commit(store: ProjectStore, score: Score) -> None:
    no_drums = Brief(allowed_instrument_ids=["retro.wooden_flute"])
    with pytest.raises(ValidationFailed) as caught:
        store.create_project(score, no_drums)
    assert caught.value.to_dict()["validation"]["errors"][0]["code"] == "INSTRUMENT_NOT_ALLOWED"
    assert not store.exists("lanterns-of-the-vale")

    store.create_project(score)
    before = file_hashes(store.root / "projects")
    bad = with_extra_note(score, note_id="f1")  # duplicate note id
    with pytest.raises(ValidationFailed):
        store.commit(
            "lanterns-of-the-vale", expected_revision=1, score=bad, brief=Brief(), summary="x"
        )
    assert file_hashes(store.root / "projects") == before


def test_warnings_do_not_block(store: ProjectStore, score: Score) -> None:
    result = store.create_project(with_extra_note(score, pitch=81))  # A natural: out of key
    assert result.validation.ok
    assert "NOTE_OUT_OF_KEY" in result.validation.codes()


def test_project_id_rules(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    other = score.model_copy(update={"project_id": "other-song"})
    with pytest.raises(ProjectMismatch):
        store.commit(
            "lanterns-of-the-vale", expected_revision=1, score=other, brief=Brief(), summary="x"
        )
    with pytest.raises(ProjectNotFound):
        store.load("missing-song")
    for bad in ("../escape", "Upper", "", "a/b"):
        with pytest.raises(InvalidProjectId):
            store.load(bad)


def test_concurrent_commits_one_winner(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    outcomes: list[str] = []
    barrier = threading.Barrier(8)

    def worker(i: int) -> None:
        barrier.wait()
        try:
            store.commit(
                "lanterns-of-the-vale",
                expected_revision=1,
                score=with_extra_note(score, note_id=f"w{i}"),
                brief=Brief(),
                summary=f"worker {i}",
            )
            outcomes.append("ok")
        except RevisionConflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["conflict"] * 7 + ["ok"]
    assert store.load("lanterns-of-the-vale").revision == 2


def test_two_store_instances_cannot_both_commit(tmp_path: Path, score: Score) -> None:
    a = ProjectStore(tmp_path)
    b = ProjectStore(tmp_path)
    a.create_project(score)
    a.commit("lanterns-of-the-vale", expected_revision=1, score=score, brief=Brief(), summary="a")
    with pytest.raises(RevisionConflict):
        b.commit(
            "lanterns-of-the-vale", expected_revision=1, score=score, brief=Brief(), summary="b"
        )


def test_operation_id_is_idempotent(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    changed = with_extra_note(score)
    first = store.commit(
        "lanterns-of-the-vale",
        expected_revision=1,
        score=changed,
        brief=Brief(),
        summary="add",
        operation_id="op-123",
    )
    again = store.commit(
        "lanterns-of-the-vale",
        expected_revision=1,  # stale on purpose: retry after a lost response
        score=changed,
        brief=Brief(),
        summary="add",
        operation_id="op-123",
    )
    assert again.replayed
    assert again.revision == first.revision == 2
    assert store.load("lanterns-of-the-vale").revision == 2
    with pytest.raises(OperationIdReused):
        store.commit(
            "lanterns-of-the-vale",
            expected_revision=2,
            score=score,
            brief=Brief(),
            summary="different",
            operation_id="op-123",
        )


def test_crash_after_snapshot_rolls_forward(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    project = store.root / "projects/lanterns-of-the-vale"
    manifest_before = (project / "manifest.json").read_bytes()
    score_before = (project / "score.json").read_bytes()
    store.commit(
        "lanterns-of-the-vale",
        expected_revision=1,
        score=with_extra_note(score),
        brief=Brief(),
        summary="x",
    )
    # Simulate a crash after the snapshot was written but before head files were replaced.
    (project / "manifest.json").write_bytes(manifest_before)
    (project / "score.json").write_bytes(score_before)
    reopened = ProjectStore(store.root)
    head = reopened.load("lanterns-of-the-vale")
    assert head.revision == 2
    assert len(head.score.track("flute-1").notes) == 5
    assert json.loads((project / "manifest.json").read_text())["headRevision"] == 2


def test_damaged_working_file_restored_from_snapshot(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    project = store.root / "projects/lanterns-of-the-vale"
    (project / "score.json").write_text("{ not json", encoding="utf-8")
    assert store.load("lanterns-of-the-vale").score.metadata.title == "Lanterns of the Vale"
    assert json.loads((project / "score.json").read_text())["projectId"] == "lanterns-of-the-vale"


def test_corrupt_snapshot_detected(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    project = store.root / "projects/lanterns-of-the-vale"
    rev = project / "revisions/000001.json"
    data = json.loads(rev.read_text())
    data["score"]["metadata"]["title"] = "Tampered"
    rev.write_text(json.dumps(data), encoding="utf-8")
    (project / "score.json").write_text("{}", encoding="utf-8")
    with pytest.raises(CorruptProject):
        store.load("lanterns-of-the-vale")


def test_unknown_schema_version_rejected(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    project = store.root / "projects/lanterns-of-the-vale"
    manifest = json.loads((project / "manifest.json").read_text())
    from midimcp.store.files import content_hash, pretty_json_bytes

    score_data = json.loads((project / "score.json").read_text())
    brief_data = json.loads((project / "brief.json").read_text())
    score_data["schemaVersion"] = "2.0.0"
    (project / "score.json").write_bytes(pretty_json_bytes(score_data))
    manifest["headContentSha256"] = content_hash(score_data, brief_data)
    (project / "manifest.json").write_bytes(pretty_json_bytes(manifest))
    with pytest.raises(UnsupportedFormat):
        store.load("lanterns-of-the-vale")

    manifest["formatVersion"] = 99
    (project / "manifest.json").write_bytes(pretty_json_bytes(manifest))
    with pytest.raises(UnsupportedFormat):
        store.load("lanterns-of-the-vale")


def test_list_and_search_projects(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    data = score.to_json_dict()
    data["projectId"] = "crypt-of-ash"
    data["metadata"] = {"title": "Crypt of Ash", "usage": "sparkfall.dungeon", "tags": ["dark"]}
    store.create_project(Score.model_validate(data))
    assert {p.project_id for p in store.list_projects()} == {"lanterns-of-the-vale", "crypt-of-ash"}
    assert [p.project_id for p in store.list_projects("dungeon")] == ["crypt-of-ash"]
    assert [p.project_id for p in store.list_projects("DARK")] == ["crypt-of-ash"]
    assert [p.project_id for p in store.list_projects("vale")] == ["lanterns-of-the-vale"]


def test_index_rebuilds_when_missing_or_corrupt(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    store.commit(
        "lanterns-of-the-vale", expected_revision=1, score=score, brief=Brief(), summary="b"
    )
    db = store.root / "library.sqlite"
    db.unlink()
    listing = store.list_projects()
    assert [(p.project_id, p.head_revision) for p in listing] == [("lanterns-of-the-vale", 2)]
    db.write_bytes(b"this is not sqlite")
    assert [p.project_id for p in store.list_projects()] == ["lanterns-of-the-vale"]


def test_delete_moves_project_to_trash(store: ProjectStore, score: Score) -> None:
    store.create_project(score)
    seen: list[str] = []
    store.add_delete_listener(seen.append)
    trash = store.delete_project("lanterns-of-the-vale")
    assert trash.parent == store.root / "trash"
    assert trash.name.startswith("lanterns-of-the-vale--")
    assert (trash / "revisions" / "000001.json").is_file()
    assert not store.exists("lanterns-of-the-vale")
    assert store.list_projects() == []
    assert seen == ["lanterns-of-the-vale"]
    with pytest.raises(ProjectNotFound):
        store.delete_project("lanterns-of-the-vale")
    # The ID is free again, and a second delete gets its own trash folder.
    store.create_project(score)
    second = store.delete_project("lanterns-of-the-vale")
    assert second != trash and second.is_dir()
