import pytest

from midimcp.music.theory import (
    TheoryError,
    canonical_spelling,
    key_signature_accidentals,
    normalize_mode,
    parse_key,
    parse_note_name,
    practical_tonic_spelling,
    scale_pitch_classes,
    spell_major_scale,
)


@pytest.mark.parametrize(
    ("name", "pc"),
    [
        ("C", 0),
        ("G#", 8),
        ("Ab", 8),
        ("Bb", 10),
        ("B flat", 10),
        ("b-flat", 10),
        ("E♭", 3),
        ("F♯", 6),
        ("Cb", 11),
        ("B#", 0),
        ("g sharp", 8),
        ("Fx", 7),
        ("Ebb", 2),
    ],
)
def test_parse_note_name(name: str, pc: int) -> None:
    assert parse_note_name(name) == pc


@pytest.mark.parametrize("bad", ["H", "", "C###", "G#b", "12"])
def test_parse_note_name_rejects_garbage(bad: str) -> None:
    with pytest.raises(TheoryError):
        parse_note_name(bad)


def test_canonical_spelling() -> None:
    assert canonical_spelling("g sharp") == "G#"
    assert canonical_spelling("B♭") == "Bb"


def test_g_sharp_ionian_is_a_flat_major() -> None:
    key = parse_key("G#", "ionian")
    assert key.tonic_pitch_class == 8
    assert key.mode == "ionian"
    assert key.requested_spelling == "G#"
    assert key.display_spelling == "Ab"
    assert key.display_name == "Ab major"
    assert set(key.pitch_classes) == {8, 10, 0, 1, 3, 5, 7}
    assert key.pitch_classes[0] == 8
    assert key_signature_accidentals(8, "ionian") == -4


def test_g_sharp_minor_keeps_sharp_spelling() -> None:
    key = parse_key("G#", "minor")
    assert key.mode == "aeolian"
    assert key.display_name == "G# minor"
    assert key_signature_accidentals(8, "aeolian") == 5


@pytest.mark.parametrize(
    ("tonic_pc", "mode", "expected"),
    [
        (0, "ionian", "C"),
        (6, "ionian", "F#"),
        (10, "ionian", "Bb"),
        (2, "dorian", "D"),
        (9, "aeolian", "A"),
        (1, "aeolian", "C#"),
        (5, "lydian", "F"),
        (7, "mixolydian", "G"),
        (11, "locrian", "B"),
        (4, "phrygian", "E"),
    ],
)
def test_practical_spelling(tonic_pc: int, mode: str, expected: str) -> None:
    assert practical_tonic_spelling(tonic_pc, mode) == expected


def test_modes_of_c_major_share_pitch_classes() -> None:
    expected = {0, 2, 4, 5, 7, 9, 11}
    for tonic, mode in [(0, "ionian"), (2, "dorian"), (4, "phrygian"), (9, "aeolian")]:
        assert set(scale_pitch_classes(tonic, mode)) == expected


def test_dorian_intervals() -> None:
    assert scale_pitch_classes(2, "dorian") == (2, 4, 5, 7, 9, 11, 0)


def test_spell_major_scale() -> None:
    assert spell_major_scale("Ab") == ("Ab", "Bb", "C", "Db", "Eb", "F", "G")
    assert spell_major_scale("F#") == ("F#", "G#", "A#", "B", "C#", "D#", "E#")


def test_mode_aliases_and_errors() -> None:
    assert normalize_mode("Major") == "ionian"
    assert normalize_mode("minor") == "aeolian"
    with pytest.raises(TheoryError):
        normalize_mode("bebop")


@pytest.mark.parametrize(
    ("numeral", "tonic", "mode", "symbol", "pcs"),
    [
        ("I", 8, "ionian", "Ab", (8, 0, 3)),
        ("vi", 8, "ionian", "Fm", (5, 8, 0)),
        ("V7", 8, "ionian", "Eb7", (3, 7, 10, 1)),
        ("vii°", 0, "ionian", "Bdim", (11, 2, 5)),
        ("Vsus4", 7, "ionian", "Dsus4", (2, 7, 9)),
        ("bVII", 2, "dorian", "C", (0, 4, 7)),
        ("IV", 2, "dorian", "G", (7, 11, 2)),
        ("bII", 4, "phrygian", "F", (5, 9, 0)),
        ("bIII", 9, "aeolian", "C", (0, 4, 7)),
        ("V", 9, "aeolian", "E", (4, 8, 11)),
        ("II", 5, "lydian", "G", (7, 11, 2)),
    ],
)
def test_parse_roman(numeral: str, tonic: int, mode: str, symbol: str, pcs: tuple) -> None:
    from midimcp.music.theory import parse_roman

    chord = parse_roman(numeral, tonic, mode)
    assert chord.symbol == symbol
    assert chord.pitch_classes == pcs


def test_parse_roman_rejects_garbage() -> None:
    from midimcp.music.theory import parse_roman

    for bad in ("VIII", "x", "", "I#"):
        with pytest.raises(TheoryError):
            parse_roman(bad, 0, "ionian")
