from __future__ import annotations

from pathlib import Path

import pytest

from midimcp.model import Brief
from midimcp.music.timing import bar_range
from midimcp.service import (
    CompositionService,
    InvalidOperation,
    InvalidRange,
    LockViolation,
    NoteNotFound,
    TrackNotFound,
    slugify,
)
from midimcp.store import ProjectStore, RevisionConflict, ValidationFailed

BAR = 2880
PID = "lanterns-of-the-vale"


def bars(first: int, last: int) -> tuple[int, int]:
    return bar_range(first, last, 960, 6, 8)


def melody(first_bar: int, last_bar: int, pitch: int = 68) -> list[dict]:
    """One dotted-quarter note per half bar (in Ab major)."""
    notes = []
    for bar in range(first_bar, last_bar + 1):
        start = (bar - 1) * BAR
        notes.append({"pitch": pitch, "startTick": start, "durationTicks": 1440, "velocity": 72})
        notes.append(
            {"pitch": pitch + 4, "startTick": start + 1440, "durationTicks": 1440, "velocity": 70}
        )
    return notes


@pytest.fixture
def service(tmp_path: Path) -> CompositionService:
    return CompositionService(ProjectStore(tmp_path))


@pytest.fixture
def song(service: CompositionService) -> CompositionService:
    """32-bar flute + lute song at revision 4."""
    service.create_project(
        title="Lanterns of the Vale",
        tempo_bpm=84,
        meter=(6, 8),
        tonic="G#",
        mode="ionian",
        bars=32,
        brief=Brief(percussion_allowed=False),
    )
    service.add_track(PID, expected_revision=1, instrument_id="retro.wooden_flute", name="Flute")
    service.add_track(PID, expected_revision=2, instrument_id="retro.lute", name="Lute")
    start, end = bars(1, 32)
    service.replace_notes(
        PID,
        expected_revision=3,
        track_id="flute",
        start_tick=start,
        end_tick=end,
        notes=melody(1, 32),
    )
    service.replace_notes(
        PID,
        expected_revision=4,
        track_id="lute",
        start_tick=start,
        end_tick=end,
        notes=melody(1, 32, pitch=56),
    )
    return service


def test_slugify() -> None:
    assert slugify("Lanterns of the Vale!") == "lanterns-of-the-vale"
    assert slugify("***") == "song"


def test_create_project_from_musical_parameters(service: CompositionService) -> None:
    result = service.create_project(
        title="Lanterns of the Vale", tempo_bpm=84, meter=(6, 8), tonic="G#", bars=32
    )
    assert result.project_id == PID
    assert result.revision == 1
    snap = service.get_project(PID)
    assert snap.score.timeline.total_ticks == 92_160
    assert snap.score.timeline.tempo_us_per_quarter == 714_286
    assert snap.score.tonality.display_spelling == "Ab"
    assert snap.score.timeline.loop.end_tick == 92_160
    assert result.validation.summary["durationSeconds"] == pytest.approx(68.57, abs=0.01)
    second = service.create_project(
        title="Lanterns of the Vale", tempo_bpm=84, meter=(6, 8), tonic="G#", bars=32
    )
    assert second.project_id == "lanterns-of-the-vale-2"


def test_create_rejects_bad_parameters(service: CompositionService) -> None:
    with pytest.raises(InvalidOperation):
        service.create_project(title="x", tempo_bpm=84, meter=(6, 8), tonic="G#", bars=0)
    with pytest.raises(InvalidOperation):
        service.create_project(
            title="x", tempo_bpm=84, meter=(6, 8), tonic="G#", bars=4, project_id="Bad Id"
        )


def test_song_fixture_shape(song: CompositionService) -> None:
    snap = song.get_project(PID)
    assert snap.revision == 5
    assert [t.id for t in snap.score.tracks] == ["flute", "lute"]
    assert len(snap.score.track("flute").notes) == 64
    note_ids = [n.id for t in snap.score.tracks for n in t.notes]
    assert len(set(note_ids)) == 128


def test_replace_flute_bars_9_to_16_leaves_everything_else(song: CompositionService) -> None:
    before = song.get_project(PID).score
    start, end = bars(9, 16)
    result = song.replace_notes(
        PID,
        expected_revision=5,
        track_id="flute",
        start_tick=start,
        end_tick=end,
        notes=[{"pitch": 75, "startTick": start, "durationTicks": 960, "velocity": 70}],
    )
    after = song.get_project(PID).score
    assert result.revision == 6
    assert after.track("lute") == before.track("lute")

    def outside(score):
        return [n for n in score.track("flute").notes if not start <= n.start_tick < end]

    assert outside(after) == outside(before)
    inside = [n for n in after.track("flute").notes if start <= n.start_tick < end]
    assert [(n.pitch, n.start_tick) for n in inside] == [(75, start)]
    assert result.summary.text == (
        "Flute: 16 notes replaced with 1 in measures 9-16; Lute unchanged"
    )
    assert result.created_ids == (inside[0].id,)


def test_replace_keeps_note_sustaining_into_range(song: CompositionService) -> None:
    start, end = bars(9, 16)
    song.edit_notes(
        PID,
        expected_revision=5,
        operations=[
            {
                "op": "add",
                "trackId": "flute",
                "note": {
                    "pitch": 80,
                    "startTick": start - 480,
                    "durationTicks": 960,
                    "velocity": 60,
                },
            }
        ],
    )
    song.replace_notes(
        PID, expected_revision=6, track_id="flute", start_tick=start, end_tick=end, notes=[]
    )
    flute = song.get_project(PID).score.track("flute")
    assert any(n.start_tick == start - 480 and n.pitch == 80 for n in flute.notes)


def test_replace_rejects_notes_outside_range(song: CompositionService) -> None:
    start, end = bars(9, 16)
    with pytest.raises(InvalidRange):
        song.replace_notes(
            PID,
            expected_revision=5,
            track_id="flute",
            start_tick=start,
            end_tick=end,
            notes=[{"pitch": 68, "startTick": end, "durationTicks": 10, "velocity": 70}],
        )
    with pytest.raises(InvalidRange):
        song.replace_notes(
            PID, expected_revision=5, track_id="flute", start_tick=10, end_tick=10, notes=[]
        )
    with pytest.raises(InvalidRange):
        song.replace_notes(
            PID, expected_revision=5, track_id="flute", start_tick=0, end_tick=10**7, notes=[]
        )
    with pytest.raises(TrackNotFound):
        song.replace_notes(
            PID, expected_revision=5, track_id="drums", start_tick=0, end_tick=10, notes=[]
        )
    assert song.get_project(PID).revision == 5


def test_invalid_note_values_rejected(song: CompositionService) -> None:
    with pytest.raises(InvalidOperation, match="pitch"):
        song.replace_notes(
            PID,
            expected_revision=5,
            track_id="flute",
            start_tick=0,
            end_tick=BAR,
            notes=[{"pitch": 200, "startTick": 0, "durationTicks": 10, "velocity": 70}],
        )


def test_locked_track_rejected_atomically(song: CompositionService) -> None:
    lock = song.lock(PID, expected_revision=5, track_id="flute")
    assert lock.created_ids == ("lock-1",)
    for attempt in (
        lambda: song.replace_notes(
            PID, expected_revision=6, track_id="flute", start_tick=0, end_tick=BAR, notes=[]
        ),
        lambda: song.update_track(
            PID, expected_revision=6, track_id="flute", changes={"instrument_id": "retro.harp"}
        ),
        lambda: song.remove_track(PID, expected_revision=6, track_id="flute"),
        lambda: song.edit_notes(
            PID, expected_revision=6, operations=[{"op": "update", "noteId": "n1", "velocity": 10}]
        ),
    ):
        with pytest.raises(LockViolation) as caught:
            attempt()
        assert caught.value.lock_ids == ["lock-1"]
    assert song.get_project(PID).revision == 6
    # Unlocked track is still editable.
    song.replace_notes(
        PID, expected_revision=6, track_id="lute", start_tick=0, end_tick=BAR, notes=[]
    )


def test_range_lock(song: CompositionService) -> None:
    start, end = bars(1, 8)
    song.lock(PID, expected_revision=5, track_id="flute", start_tick=start, end_tick=end)
    with pytest.raises(LockViolation):
        song.replace_notes(
            PID,
            expected_revision=6,
            track_id="flute",
            start_tick=bars(8, 8)[0],
            end_tick=bars(12, 12)[1],
            notes=[],
        )
    # A new note that would ring into the locked range is also refused.
    with pytest.raises(LockViolation):
        song.edit_notes(
            PID,
            expected_revision=6,
            operations=[
                {
                    "op": "add",
                    "trackId": "flute",
                    "note": {"pitch": 70, "startTick": 0, "durationTicks": 100, "velocity": 50},
                }
            ],
        )
    song.replace_notes(
        PID,
        expected_revision=6,
        track_id="flute",
        start_tick=bars(9, 9)[0],
        end_tick=bars(16, 16)[1],
        notes=[],
    )


def test_only_users_unlock(song: CompositionService) -> None:
    song.lock(PID, expected_revision=5, track_id="flute")
    with pytest.raises(InvalidOperation):
        song.unlock(PID, expected_revision=6, lock_id="lock-1", author="agent")
    song.unlock(PID, expected_revision=6, lock_id="lock-1", author="user")
    song.replace_notes(
        PID, expected_revision=7, track_id="flute", start_tick=0, end_tick=BAR, notes=[]
    )
    with pytest.raises(InvalidOperation):
        song.update_brief(PID, expected_revision=8, changes={"locks": []})


def test_stale_revision(song: CompositionService) -> None:
    with pytest.raises(RevisionConflict):
        song.add_track(PID, expected_revision=4, instrument_id="retro.harp", name="Harp")


def test_operation_id_retry_is_idempotent(song: CompositionService) -> None:
    first = song.add_track(
        PID,
        expected_revision=5,
        instrument_id="retro.harp",
        name="Harp",
        track_id="harp",
        operation_id="op-harp",
    )
    retry = song.add_track(
        PID,
        expected_revision=5,
        instrument_id="retro.harp",
        name="Harp",
        track_id="harp",
        operation_id="op-harp",
    )
    assert retry.replayed
    assert retry.revision == first.revision == 6
    assert [t.id for t in song.get_project(PID).score.tracks] == ["flute", "lute", "harp"]


def test_create_project_idempotent(service: CompositionService) -> None:
    kwargs = dict(
        title="Crypt",
        tempo_bpm=60,
        meter=(4, 4),
        tonic="D",
        mode="dorian",
        bars=8,
        operation_id="op-create",
    )
    a = service.create_project(**kwargs)
    b = service.create_project(**kwargs)
    assert b.replayed and a.project_id == b.project_id == "crypt"
    assert [p["projectId"] for p in service.list_projects()] == ["crypt"]


def test_brief_rules_enforced(song: CompositionService) -> None:
    with pytest.raises(ValidationFailed) as caught:
        song.add_track(
            PID, expected_revision=5, instrument_id="gm.drums", name="Drums", is_percussion=True
        )
    assert "PERCUSSION_FORBIDDEN" in caught.value.report.codes()


def test_edit_notes_operations(song: CompositionService) -> None:
    result = song.edit_notes(
        PID,
        expected_revision=5,
        operations=[
            {"op": "update", "noteId": "n1", "velocity": 99, "pitch": 70},
            {"op": "delete", "noteId": "n2"},
            {
                "op": "add",
                "trackId": "lute",
                "note": {
                    "id": "custom-1",
                    "pitch": 63,
                    "startTick": 0,
                    "durationTicks": 960,
                    "velocity": 50,
                },
            },
        ],
    )
    score = song.get_project(PID).score
    n1 = next(n for n in score.track("flute").notes if n.id == "n1")
    assert (n1.pitch, n1.velocity) == (70, 99)
    assert all(n.id != "n2" for n in score.track("flute").notes)
    assert any(n.id == "custom-1" for n in score.track("lute").notes)
    assert "Flute: 1 notes removed; 1 notes modified" in result.summary.text
    with pytest.raises(NoteNotFound):
        song.edit_notes(PID, expected_revision=6, operations=[{"op": "delete", "noteId": "zz"}])
    with pytest.raises(InvalidOperation):
        song.edit_notes(PID, expected_revision=6, operations=[{"op": "explode"}])
    with pytest.raises(InvalidOperation):
        song.edit_notes(
            PID, expected_revision=6, operations=[{"op": "update", "noteId": "n1", "colour": "red"}]
        )
    with pytest.raises(InvalidOperation):
        song.edit_notes(
            PID,
            expected_revision=6,
            operations=[
                {
                    "op": "add",
                    "trackId": "lute",
                    "note": {
                        "id": "n1",
                        "pitch": 60,
                        "startTick": 0,
                        "durationTicks": 1,
                        "velocity": 1,
                    },
                }
            ],
        )
    assert song.get_project(PID).revision == 6


def test_update_track_and_remove(song: CompositionService) -> None:
    result = song.update_track(
        PID,
        expected_revision=5,
        track_id="lute",
        changes={"instrument_id": "retro.harp", "gain_db": -3, "mute": True},
    )
    lute = song.get_project(PID).score.track("lute")
    assert (lute.instrument_id, lute.gain_db, lute.mute) == ("retro.harp", -3.0, True)
    assert "instrumentId" in result.summary.text
    with pytest.raises(InvalidOperation):
        song.update_track(PID, expected_revision=6, track_id="lute", changes={"notes": []})
    song.remove_track(PID, expected_revision=6, track_id="lute")
    assert [t.id for t in song.get_project(PID).score.tracks] == ["flute"]


def test_set_arrangement(song: CompositionService) -> None:
    sections = [
        {"id": "a", "label": "A", "startTick": 0, "endTick": bars(1, 8)[1]},
        {"id": "b", "label": "B", "startTick": bars(9, 9)[0], "endTick": bars(1, 16)[1]},
    ]
    harmony = [{"startTick": 0, "durationTicks": BAR, "symbol": "Ab", "romanNumeral": "I"}]
    result = song.set_arrangement(PID, expected_revision=5, sections=sections, harmony=harmony)
    snap = song.get_project(PID)
    assert [s.label for s in snap.score.sections] == ["A", "B"]
    assert "sections changed" in result.summary.text
    with pytest.raises(ValidationFailed):  # shrinking would cut off notes
        song.set_arrangement(PID, expected_revision=6, bars=8)
    song.set_arrangement(
        PID, expected_revision=6, loop={"enabled": True, "startTick": 0, "endTick": bars(1, 16)[1]}
    )
    assert song.get_project(PID).score.timeline.loop.end_tick == 46_080
    with pytest.raises(InvalidOperation):
        song.set_arrangement(PID, expected_revision=7)


def test_update_brief(song: CompositionService) -> None:
    song.update_brief(PID, expected_revision=5, changes={"mood": "peaceful", "max_tracks": 3})
    brief = song.get_project(PID).brief
    assert brief.mood == "peaceful" and brief.max_tracks == 3
    with pytest.raises(ValidationFailed):
        song.update_brief(PID, expected_revision=6, changes={"maxTracks": 1})


def test_undo_and_restore_keep_history(song: CompositionService) -> None:
    song.remove_track(PID, expected_revision=5, track_id="lute")
    undo = song.undo(PID, expected_revision=6)
    assert undo.revision == 7
    assert [t.id for t in song.get_project(PID).score.tracks] == ["flute", "lute"]
    restore = song.restore_revision(PID, expected_revision=7, revision=1)
    assert restore.revision == 8
    assert song.get_project(PID).score.tracks == []
    assert [r["revision"] for r in song.list_revisions(PID)] == list(range(1, 9))
    assert song.list_revisions(PID)[5]["summary"] == "Lute: track removed; Flute unchanged"


def test_restore_respects_locks(song: CompositionService) -> None:
    song.lock(PID, expected_revision=5, track_id="flute")
    with pytest.raises(LockViolation):
        song.restore_revision(PID, expected_revision=6, revision=1)


def test_validate_reports(song: CompositionService) -> None:
    report = song.validate(PID)
    assert report.ok
    assert report.summary["noteCount"] == 128


def test_allow_instrument_extends_brief_in_one_revision(service: CompositionService) -> None:
    service.create_project(
        title="Narrow",
        tempo_bpm=90,
        meter=(4, 4),
        tonic="C",
        bars=2,
        project_id="narrow",
        brief=Brief(allowed_instrument_ids=["retro.wooden_flute"]),
    )
    service.add_track(
        "narrow",
        expected_revision=1,
        instrument_id="retro.wooden_flute",
        name="Flute",
        track_id="flute",
    )
    with pytest.raises(ValidationFailed) as caught:
        service.update_track(
            "narrow", expected_revision=2, track_id="flute", changes={"instrument_id": "retro.harp"}
        )
    assert "INSTRUMENT_NOT_ALLOWED" in caught.value.report.codes()
    result = service.update_track(
        "narrow",
        expected_revision=2,
        track_id="flute",
        changes={"instrument_id": "retro.harp"},
        allow_instrument=True,
        author="user",
    )
    assert result.revision == 3
    snap = service.get_project("narrow")
    assert snap.score.track("flute").instrument_id == "retro.harp"
    assert snap.brief.allowed_instrument_ids == ["retro.wooden_flute", "retro.harp"]
