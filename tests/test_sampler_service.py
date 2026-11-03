from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from midimcp.model.score import Score
from midimcp.service import InvalidOperation, LockViolation
from midimcp.store.errors import RevisionConflict
from tests.conftest import lanterns_score_dict
from tests.test_expression import PID

pytest_plugins = ("tests.test_expression",)

BINDING = {"patchId": "vsco-flute-controlled", "patchSha256": "a" * 64}


class Registry:
    def require(self, patch_id, sha256=None):
        if patch_id != BINDING["patchId"] or sha256 != BINDING["patchSha256"]:
            raise ValueError("patch unavailable or checksum changed")
        return SimpleNamespace(id=patch_id, sha256=sha256)


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0", "1.2.0"])
def test_schema_compatibility_and_complete_pin(version):
    raw = lanterns_score_dict()
    raw["schemaVersion"] = version
    score = Score.model_validate(raw)
    assert score.schema_version == version
    assert score.tracks[0].sampler is None
    raw["tracks"][0]["sampler"] = dict(BINDING)
    assert Score.model_validate(raw).tracks[0].sampler.patch_sha256 == "a" * 64
    raw["tracks"][0]["sampler"]["patchSha256"] = "short"
    with pytest.raises(ValidationError):
        Score.model_validate(raw)


def test_binding_persist_reset_and_instrument_independence(service):
    service.samplers = Registry()
    service.update_track(PID, expected_revision=3, track_id="flute", changes={"sampler": BINDING})
    snap = service.get_project(PID)
    assert snap.score.schema_version == "1.2.0"
    assert snap.score.track("flute").sampler.patch_id == BINDING["patchId"]
    service.update_track(
        PID, expected_revision=4, track_id="flute", changes={"instrument_id": "retro.harp"}
    )
    assert service.get_project(PID).score.track("flute").sampler is not None
    assert service.track_defaults(PID)["flute"]["sampler"] is None
    service.reset_track(PID, expected_revision=5, track_id="flute", fields=["sampler"])
    assert service.get_project(PID).score.track("flute").sampler is None
    assert service.get_project(PID).score.track("flute").instrument_id == "retro.harp"


def test_missing_registry_and_invalid_pin_do_not_commit(service):
    with pytest.raises(InvalidOperation):
        service.update_track(
            PID, expected_revision=3, track_id="flute", changes={"sampler": BINDING}
        )
    service.samplers = Registry()
    with pytest.raises(ValueError):
        service.update_track(
            PID,
            expected_revision=3,
            track_id="flute",
            changes={"sampler": {**BINDING, "patchSha256": "b" * 64}},
        )
    assert service.get_project(PID).revision == 3


def test_performance_atomic_seeded_range_and_undo(service):
    original = service.get_project(PID).score
    result = service.apply_performance(
        PID, expected_revision=3, track_id="flute", start_tick=3840, end_tick=7680
    )
    after = service.get_project(PID).score
    assert result.revision == 4
    assert len(service.list_revisions(PID)) == 4
    before_notes = {n.id: n for n in original.track("flute").notes}
    for note in after.track("flute").notes:
        if not 3840 <= before_notes[note.id].start_tick < 7680:
            assert note == before_notes[note.id]
    assert after.track("flute").automation.expression
    with pytest.raises(RevisionConflict):
        service.apply_performance(PID, expected_revision=3, track_id="flute")
    service.restore_revision(PID, expected_revision=4, revision=3, author="user")
    assert service.get_project(PID).score.tracks == original.tracks
    service.apply_performance(
        PID, expected_revision=5, track_id="flute", start_tick=3840, end_tick=7680
    )
    assert service.get_project(PID).score.tracks == after.tracks


def test_performance_and_binding_respect_locks(service):
    service.samplers = Registry()
    service.lock(PID, expected_revision=3, track_id="flute")
    for operation in [
        lambda: service.apply_performance(PID, expected_revision=4, track_id="flute"),
        lambda: service.update_track(
            PID, expected_revision=4, track_id="flute", changes={"sampler": BINDING}
        ),
    ]:
        with pytest.raises(LockViolation):
            operation()
    assert service.get_project(PID).revision == 4


def test_performance_preserves_controller_state_after_range(service):
    service.set_automation(
        PID,
        expected_revision=3,
        track_id="flute",
        lane="expression",
        start_tick=0,
        end_tick=30720,
        points=[{"tick": 0, "value": 70}, {"tick": 20000, "value": 80}],
    )
    service.apply_performance(PID, expected_revision=4, track_id="flute", end_tick=7680)
    points = service.get_project(PID).score.track("flute").automation.expression
    assert next(p.value for p in reversed(points) if p.tick <= 10000) == 70
    assert points[-1].tick == 20000 and points[-1].value == 80


def test_performance_zero_vibrato_clears_existing_modulation(service):
    service.set_automation(
        PID,
        expected_revision=3,
        track_id="flute",
        lane="modulation",
        start_tick=0,
        end_tick=30720,
        points=[{"tick": 0, "value": 90}],
    )
    service.apply_performance(PID, expected_revision=4, track_id="flute", vibrato_depth=0)
    assert [
        (point.tick, point.value)
        for point in service.get_project(PID).score.track("flute").automation.modulation
    ] == [(0, 0)]


def test_performance_range_lock_rejects_whole_atomic_result(service):
    service.lock(PID, expected_revision=3, track_id="flute", start_tick=0, end_tick=960)
    original = service.get_project(PID).score
    with pytest.raises(LockViolation):
        service.apply_performance(PID, expected_revision=4, track_id="flute")
    assert service.get_project(PID).score == original


def test_performance_adjacent_locked_range_allows_inside_boundary_restore(service):
    service.lock(PID, expected_revision=3, track_id="flute", start_tick=7680, end_tick=11520)
    service.apply_performance(PID, expected_revision=4, track_id="flute", end_tick=7680)
    track = service.get_project(PID).score.track("flute")
    assert all(
        point.tick < 7680 for points in track.automation.lanes().values() for point in points
    )
    assert track.automation.expression[-1].value == 127
    assert track.automation.modulation[-1].value == 0
