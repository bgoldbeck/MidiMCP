from __future__ import annotations

from pathlib import Path

import pytest

from midimcp.instruments import instrument_range
from midimcp.music.theory import parse_roman
from midimcp.service import CompositionService
from midimcp.store import ProjectStore
from midimcp.templates import (
    TEMPLATES,
    TemplateError,
    build_form,
    get_template,
    list_templates,
)


@pytest.fixture
def service(tmp_path: Path) -> CompositionService:
    return CompositionService(ProjectStore(tmp_path))


def test_six_original_templates_listed() -> None:
    ids = [t["id"] for t in list_templates()]
    assert ids == [
        "peaceful-town",
        "forest-exploration",
        "ruined-crypt",
        "tavern",
        "sea-voyage",
        "tense-borderlands",
    ]
    with pytest.raises(TemplateError):
        get_template("disco")


@pytest.mark.parametrize("template_id", list(TEMPLATES))
def test_template_is_internally_consistent(template_id: str) -> None:
    template = TEMPLATES[template_id]
    low, high = template.tempo_range
    assert low <= template.default_tempo <= high
    assert [p.role for p in template.parts].count("melody") == 1
    for part in template.parts:
        span = instrument_range(part.instrument_id)
        assert span is not None, part.instrument_id
        assert span[0] <= part.lowest < part.highest <= span[1], part
    for section in template.form:
        for numeral in section.progression:
            parse_roman(numeral, 0, template.mode)  # every numeral parses
    assert template.to_dict()["ticksPerBar"] > 0


@pytest.mark.parametrize("template_id", list(TEMPLATES))
def test_scaffold_creates_valid_project_in_one_revision(
    service: CompositionService, template_id: str
) -> None:
    template = TEMPLATES[template_id]
    result = service.create_from_template(template_id=template_id, title=f"Song {template_id}")
    assert result.revision == 1
    snap = service.get_project(result.project_id)
    score, brief = snap.score, snap.brief
    assert score.tonality.mode == template.mode
    assert [t.role for t in score.tracks] == [p.role for p in template.parts]
    assert len(score.harmony) == template.form_bars
    assert [s.label for s in score.sections] == [s.label for s in template.form]
    for prev, cur in zip(score.sections, score.sections[1:], strict=False):
        assert prev.end_tick == cur.start_tick
    assert score.sections[-1].end_tick == score.timeline.total_ticks
    assert brief.template_id == template_id
    assert brief.percussion_allowed == template.percussion_allowed
    assert {p.track_id for p in brief.part_limits} == {t.id for t in score.tracks}
    assert len(brief.chord_plan) == template.form_bars
    assert result.validation.ok
    assert result.validation.codes() <= {"EMPTY_TRACK"}


def test_overrides_and_form_fitting(service: CompositionService) -> None:
    result = service.create_from_template(
        template_id="peaceful-town",
        title="Lanterns",
        tonic="G#",
        mode="ionian",
        tempo_bpm=84,
        bars=20,
    )
    score = service.get_project(result.project_id).score
    assert score.tonality.display_spelling == "Ab"
    assert score.timeline.tempo_us_per_quarter == 714286
    assert [s.label for s in score.sections] == ["A", "A'", "B"]
    assert score.sections[-1].end_tick - score.sections[-1].start_tick == 4 * 2880
    assert [h.symbol for h in score.harmony[:4]] == ["Ab", "Fm", "Db", "Eb"]

    long_form = build_form(TEMPLATES["ruined-crypt"], 30)
    assert sum(p.bars for p in long_form) == 30
    assert [p.label for p in long_form] == ["Intro", "A", "B", "Intro", "A"]


def test_tavern_duplicate_section_labels_get_unique_ids(service: CompositionService) -> None:
    result = service.create_from_template(template_id="tavern", title="Inn")
    ids = [s.id for s in service.get_project(result.project_id).score.sections]
    assert len(ids) == len(set(ids))
