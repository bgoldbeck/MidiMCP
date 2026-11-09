from __future__ import annotations

from pathlib import Path

import pytest

from midimcp.instruments import instrument_range
from midimcp.music.theory import parse_roman
from midimcp.service import CompositionService
from midimcp.store import ProjectStore
from midimcp.templates import (
    LAYER_ACTIONS,
    TEMPLATES,
    Layer,
    SectionPlan,
    TemplateError,
    TemplateLibrary,
    build_form,
    get_template,
    list_templates,
    section_plans,
)


@pytest.fixture
def service(tmp_path: Path) -> CompositionService:
    return CompositionService(ProjectStore(tmp_path))


def test_builtin_templates_listed() -> None:
    ids = [t["id"] for t in list_templates()]
    assert ids[:6] == [
        "peaceful-town",
        "forest-exploration",
        "ruined-crypt",
        "tavern",
        "sea-voyage",
        "tense-borderlands",
    ]
    old_realm = [i for i in ids if i.startswith("old-realm-")]
    retro = [i for i in ids if i.startswith("retro-")]
    assert len(old_realm) == 9 and len(retro) == 12
    assert {"old-realm-title", "old-realm-town", "old-realm-sailing", "old-realm-forest"} <= set(
        old_realm
    )
    assert {i for i in ids if i.startswith("wayfarer-")} == {
        "wayfarer-city",
        "wayfarer-dungeon",
        "wayfarer-forest",
        "wayfarer-harbor",
        "wayfarer-village",
        "wayfarer-desert",
    }
    assert len(ids) == len(set(ids)) == 6 + 9 + 12 + 6
    with pytest.raises(TemplateError):
        get_template("disco")


def test_legacy_wayfarer_id_resolves_without_appearing_in_catalog(tmp_path: Path) -> None:
    library = TemplateLibrary(tmp_path)
    legacy_id = "runescape-forest"
    current_id = "wayfarer-forest"
    assert get_template(legacy_id) is get_template(current_id)
    assert library.detail(legacy_id) == library.detail(current_id)
    assert library.detail(legacy_id)["name"] == "Wayfarer Forest Trails"
    assert library.detail(legacy_id)["builtIn"]
    assert legacy_id not in {template["id"] for template in library.summaries()}


@pytest.mark.parametrize("template_id", list(TEMPLATES))
def test_template_is_internally_consistent(template_id: str) -> None:
    template = TEMPLATES[template_id]
    assert template.expression  # every built-in says how to make it sound played
    assert any("copy" in d.lower() for d in template.donts), "must forbid copying melodies"
    low, high = template.tempo_range
    assert low <= template.default_tempo <= high
    assert [p.role for p in template.parts].count("melody") == 1
    for part in template.parts:
        span = instrument_range(part.instrument_id)
        assert span is not None, part.instrument_id
        assert span[0] <= part.lowest < part.highest <= span[1], part
    track_ids = {p.track_id for p in template.parts}
    for section in template.form:
        for numeral in section.progression:
            parse_roman(numeral, 0, template.mode)  # every numeral parses
        assert 1 <= section.chord_bars <= section.bars
        layered = [layer.track_id for layer in section.layers]
        assert len(layered) == len(set(layered)) and set(layered) <= track_ids
        for layer in section.layers:
            assert layer.action in LAYER_ACTIONS
            if layer.action in ("enter", "exit"):
                assert 2 <= layer.bar <= section.bars, (section.label, layer)
            else:
                assert layer.bar == 1
    assert template.to_dict()["ticksPerBar"] > 0


def test_old_realm_forms_are_layered_not_blocks() -> None:
    for template in TEMPLATES.values():
        if not template.id.startswith("old-realm-"):
            continue
        melody = next(p.track_id for p in template.parts if p.role == "melody")
        sizes = {s.bars for s in template.form}
        assert len(sizes) > 1, f"{template.id}: every section is the same length"
        assert any(s.layers for s in template.form), template.id
        silent = [
            s.label
            for s in template.form
            for layer in s.layers
            if layer.track_id == melody and layer.action in ("rest", "enter", "exit")
        ]
        assert silent, f"{template.id}: the melody never rests, enters or leaves"
        assert any(
            layer.action in ("enter", "exit") for s in template.form for layer in s.layers
        ), f"{template.id}: no part enters or leaves mid-section"


def test_chord_bars_hold_chords_in_the_scaffold(service: CompositionService) -> None:
    result = service.create_from_template(
        template_id="old-realm-forest", title="Glade", tonic="E", mode="dorian"
    )
    score = service.get_project(result.project_id).score
    assert [h.symbol for h in score.harmony[:6]] == ["Em", "Em", "A", "A", "Em", "A"]
    intro = SectionPlan("I", 4, ("i", "iv", "V"), "", chord_bars=2)
    assert [intro.numeral_at(i) for i in range(6)] == ["i", "i", "iv", "iv", "V", "V"]


def test_section_plans_give_song_bars() -> None:
    template = TEMPLATES["old-realm-forest"]
    plans = section_plans(template, template.form_bars)
    assert [p["startBar"] for p in plans] == [1, 5, 13, 19, 23]
    assert plans[-1]["endBar"] == template.form_bars
    assert plans[1]["layers"] == [
        {"trackId": "oboe", "action": "enter", "bar": 9, "note": plans[1]["layers"][0]["note"]}
    ]
    assert [p["sectionId"] for p in plans][:2] == ["section-intro", "section-a"]


def test_cut_sections_resolve_enters_and_exits() -> None:
    plan = SectionPlan(
        "A",
        8,
        ("i",),
        "",
        layers=(
            Layer("flute", "enter", 6, "late"),
            Layer("oboe", "exit", 7),
            Layer("harp", "enter", 3),
            Layer("pad", "rest"),
        ),
    )
    cut = plan.fitted(4)
    assert cut.bars == 4
    assert cut.layers == (
        Layer("flute", "rest", 1, "late"),
        Layer("oboe", "play", 1),
        Layer("harp", "enter", 3),
        Layer("pad", "rest"),
    )
    assert plan.fitted(8) is plan


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


# ------------------------------------------------------------- custom library

import json  # noqa: E402

from midimcp.templates import (  # noqa: E402
    TemplateValidationError,
    template_from_dict,
)


@pytest.mark.parametrize("template_id", list(TEMPLATES))
def test_builtin_templates_round_trip_through_json(template_id: str) -> None:
    template = TEMPLATES[template_id]
    assert template_from_dict(json.loads(json.dumps(template.to_dict()))) == template


def test_library_duplicate_edit_delete(tmp_path: Path) -> None:
    library = TemplateLibrary(tmp_path)
    copy = library.duplicate("tavern", "my-tavern", "My Tavern")
    assert copy.name == "My Tavern" and not library.is_builtin("my-tavern")
    assert [s["id"] for s in library.summaries()][-1] == "my-tavern"
    data = library.detail("my-tavern")
    assert data["builtIn"] is False and data["chart"][0]["chords"][:2] == ["D", "C"]
    data["default_tempo"] = 128
    data["form"][0]["progression"] = ["I", "IV", "V", "I"]
    library.save("my-tavern", data)
    reloaded = TemplateLibrary(tmp_path).get("my-tavern")
    assert reloaded.default_tempo == 128 and reloaded.form[0].progression == ("I", "IV", "V", "I")
    with pytest.raises(TemplateValidationError):
        library.save("tavern", data)  # built-ins are read-only
    with pytest.raises(TemplateValidationError):
        library.delete("tavern")
    with pytest.raises(TemplateValidationError):
        library.duplicate("tavern", "my-tavern")  # id taken
    library.delete("my-tavern")
    with pytest.raises(TemplateError):
        library.get("my-tavern")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["form"][0].update(progression=["I", "XIV"]), "cannot read chord"),
        (lambda d: d["parts"][0].update(instrument_id="retro.kazoo"), "unknown instrument"),
        (lambda d: d.update(default_tempo=300), "inside tempo_range"),
        (lambda d: d["parts"][1].update(track_id=d["parts"][0]["track_id"]), "unique"),
        (lambda d: d.update(colour="red"), "unknown fields"),
        (lambda d: d.update(mode="bebop"), "mode must be"),
        (lambda d: d["parts"][0].update(lowest=90, highest=60), "lowest < highest"),
        (lambda d: d.update(meter=[5, 3]), "meter"),
        (lambda d: d["form"][0].update(chord_bars=0), "chord_bars"),
        (lambda d: d["form"][0].update(chord_bars=99), "longer than the section"),
        (lambda d: d["form"][0].update(layers="flute"), "'layers' must be a list"),
        (
            lambda d: d["form"][0].update(layers=[{"track_id": "kazoo", "action": "rest"}]),
            "track_id must name",
        ),
        (
            lambda d: d["form"][0].update(layers=[{"track_id": "flute", "action": "solo"}]),
            "action must be",
        ),
        (
            lambda d: d["form"][0].update(
                layers=[{"track_id": "flute", "action": "enter", "bar": 99}]
            ),
            "past the end",
        ),
        (
            lambda d: d["form"][0].update(layers=[{"track_id": "flute", "action": "enter"}]),
            "same as play",
        ),
        (
            lambda d: d["form"][0].update(
                layers=[{"track_id": "flute", "action": "rest", "bar": 3}]
            ),
            "leave bar at 1",
        ),
        (
            lambda d: d["form"][0].update(
                layers=[
                    {"track_id": "flute", "action": "rest"},
                    {"track_id": "flute", "action": "play"},
                ]
            ),
            "already has a layer",
        ),
    ],
)
def test_template_validation_errors(tmp_path: Path, change, message: str) -> None:
    library = TemplateLibrary(tmp_path)
    library.duplicate("peaceful-town", "mine")
    data = library.detail("mine")
    change(data)
    with pytest.raises(TemplateValidationError, match=message):
        library.save("mine", data)


def test_broken_custom_file_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "broken.json").write_text("{ nope")
    assert "broken" not in [s["id"] for s in TemplateLibrary(tmp_path).summaries()]


def test_song_from_custom_template(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    library = TemplateLibrary(tmp_path)
    library.duplicate("peaceful-town", "quick-town", "Quick Town")
    data = library.detail("quick-town")
    data["form"] = [
        {"label": "A", "bars": 4, "progression": ["I", "IV", "V", "I"], "intent": "short"}
    ]
    library.save("quick-town", data)
    result = CompositionService(store).create_from_template(template_id="quick-town", title="Q")
    score = CompositionService(store).get_project(result.project_id).score
    assert [h.symbol for h in score.harmony] == ["G", "C", "D", "G"]


def test_custom_template_layers_round_trip(tmp_path: Path) -> None:
    library = TemplateLibrary(tmp_path)
    library.duplicate("peaceful-town", "layered-town")
    data = library.detail("layered-town")
    melody = data["parts"][0]["track_id"]
    data["form"][0]["chord_bars"] = 2
    data["form"][0]["layers"] = [
        {"track_id": melody, "action": "enter", "bar": 3, "note": "pickup into bar 3"}
    ]
    library.save("layered-town", data)
    reloaded = TemplateLibrary(tmp_path).get("layered-town")
    assert reloaded.form[0].chord_bars == 2
    assert reloaded.form[0].layers == (Layer(melody, "enter", 3, "pickup into bar 3"),)
    chart = TemplateLibrary(tmp_path).detail("layered-town")["chart"][0]
    assert chart["chordBars"] == 2
    assert chart["layers"] == [
        {"trackId": melody, "action": "enter", "bar": 3, "note": "pickup into bar 3"}
    ]
