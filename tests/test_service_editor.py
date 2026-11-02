import pytest

from midimcp.service.errors import InvalidOperation
from midimcp.store.errors import RevisionConflict
from tests.test_service import PID

pytest_plugins = ("tests.test_service",)


def test_growth_atomic_and_full_loop(song):
    before = song.get_project(PID)
    total = before.score.timeline.total_ticks
    with pytest.raises(InvalidOperation):
        song.edit_notes(
            PID,
            expected_revision=before.revision,
            operations=[{"op": "explode"}],
            extend_to_tick=total + 1,
        )
    assert song.get_project(PID).revision == before.revision
    note = before.score.tracks[0].notes[0]
    song.edit_notes(
        PID,
        expected_revision=before.revision,
        operations=[{"op": "update", "noteId": note.id, "startTick": total, "durationTicks": 120}],
        extend_to_tick=total + 120,
    )
    after = song.get_project(PID).score.timeline
    assert after.total_ticks == total + 2880
    assert after.loop.end_tick == after.total_ticks


def test_growth_stale_and_invalid(song):
    before = song.get_project(PID)
    for value in [True, -1, 1.2, 1000000001]:
        with pytest.raises(InvalidOperation):
            song.edit_notes(
                PID,
                expected_revision=before.revision,
                operations=[{"op": "delete", "noteId": "n1"}],
                extend_to_tick=value,
            )
    with pytest.raises(RevisionConflict):
        song.edit_notes(
            PID,
            expected_revision=0,
            operations=[{"op": "delete", "noteId": "n1"}],
            extend_to_tick=before.score.timeline.total_ticks + 1,
        )
    assert song.get_project(PID).revision == before.revision


def test_growth_preserves_custom_loop_and_never_shrinks(song):
    revision = song.get_project(PID).revision
    song.set_arrangement(
        PID, expected_revision=revision, loop={"enabled": True, "startTick": 2880, "endTick": 5760}
    )
    before = song.get_project(PID)
    note = before.score.tracks[0].notes[0]
    song.edit_notes(
        PID,
        expected_revision=before.revision,
        operations=[{"op": "update", "noteId": note.id, "velocity": 65}],
        extend_to_tick=before.score.timeline.total_ticks + 1,
    )
    after = song.get_project(PID)
    assert after.score.timeline.loop == before.score.timeline.loop
    song.edit_notes(
        PID,
        expected_revision=after.revision,
        operations=[{"op": "update", "noteId": note.id, "velocity": 66}],
        extend_to_tick=100,
    )
    assert song.get_project(PID).score.timeline.total_ticks == after.score.timeline.total_ticks


def test_invalid_note_with_growth_writes_nothing(song):
    from midimcp.store import ValidationFailed

    before = song.get_project(PID)
    total = before.score.timeline.total_ticks
    note = before.score.tracks[0].notes[0]
    with pytest.raises(ValidationFailed):
        song.edit_notes(
            PID,
            expected_revision=before.revision,
            operations=[{"op": "update", "noteId": note.id, "startTick": total + 10000}],
            extend_to_tick=total + 1,
        )
    assert song.get_project(PID).revision == before.revision
    assert song.get_project(PID).score == before.score


@pytest.mark.parametrize("range_lock", [False, True])
def test_growth_cannot_move_or_stretch_locked_notes(song, range_lock):
    from midimcp.service import LockViolation

    before = song.get_project(PID)
    lock_kwargs = {"start_tick": 0, "end_tick": 1440} if range_lock else {}
    song.lock(PID, expected_revision=before.revision, track_id="flute", **lock_kwargs)
    locked = song.get_project(PID)
    note = locked.score.track("flute").notes[0]
    for patch in [
        {"startTick": locked.score.timeline.total_ticks},
        {"durationTicks": locked.score.timeline.total_ticks + 100},
    ]:
        with pytest.raises(LockViolation):
            song.edit_notes(
                PID,
                expected_revision=locked.revision,
                operations=[{"op": "update", "noteId": note.id, **patch}],
                extend_to_tick=locked.score.timeline.total_ticks + 3000,
            )
        assert song.get_project(PID).score == locked.score
        assert song.get_project(PID).revision == locked.revision


def test_mixed_note_batch_preserves_sequential_semantics(song):
    before = song.get_project(PID)
    flute = before.score.track("flute").notes
    lute = before.score.track("lute").notes
    song.edit_notes(
        PID,
        expected_revision=before.revision,
        operations=[
            {"op": "delete", "noteId": flute[0].id},
            {"op": "update", "noteId": flute[1].id, "velocity": 60},
            {
                "op": "add",
                "trackId": "lute",
                "note": {
                    "id": "fresh",
                    "pitch": 60,
                    "startTick": 100,
                    "durationTicks": 100,
                    "velocity": 70,
                },
            },
            {"op": "update", "noteId": "fresh", "pitch": 62},
            {"op": "delete", "noteId": lute[0].id},
            {"op": "update", "noteId": flute[1].id, "pitch": 72},
            {"op": "update", "noteId": "fresh", "velocity": 90},
        ],
    )
    after = song.get_project(PID)
    notes = {n.id: n for t in after.score.tracks for n in t.notes}
    assert flute[0].id not in notes and lute[0].id not in notes
    assert (notes[flute[1].id].pitch, notes[flute[1].id].velocity) == (72, 60)
    assert (notes["fresh"].pitch, notes["fresh"].velocity) == (62, 90)
    with pytest.raises(InvalidOperation):
        song.edit_notes(
            PID,
            expected_revision=after.revision,
            operations=[
                {"op": "delete", "noteId": "fresh"},
                {
                    "op": "add",
                    "trackId": "flute",
                    "note": {
                        "id": "fresh",
                        "pitch": 60,
                        "startTick": 100,
                        "durationTicks": 100,
                        "velocity": 70,
                    },
                },
            ],
        )
    assert song.get_project(PID).revision == after.revision


def test_large_unique_note_batch(service):
    service.create_project(
        title="Large", project_id=PID, tempo_bpm=120, meter=(6, 8), tonic="C", bars=100
    )
    service.add_track(
        PID, expected_revision=1, instrument_id="retro.wooden_flute", name="Flute", track_id="flute"
    )
    service.edit_notes(
        PID,
        expected_revision=2,
        operations=[
            {
                "op": "add",
                "trackId": "flute",
                "note": {
                    "id": f"note-{i}",
                    "pitch": 60,
                    "startTick": i * 10,
                    "durationTicks": 5,
                    "velocity": 70,
                },
            }
            for i in range(20000)
        ],
    )
    service.edit_notes(
        PID,
        expected_revision=3,
        operations=[{"op": "update", "noteId": f"note-{i}", "velocity": 90} for i in range(20000)],
    )
    after = service.get_project(PID)
    notes = after.score.track("flute").notes
    assert len(notes) == 20000
    assert all(note.velocity == 90 for note in notes)
    assert [note.start_tick for note in notes] == list(range(0, 200000, 10))
