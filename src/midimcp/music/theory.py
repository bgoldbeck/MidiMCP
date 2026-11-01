"""Pitch classes, modes, and practical key spelling.

Pitch classes are integers 0-11 with C = 0. A key is a tonic pitch class plus a
mode. Spelling (``"G#"`` vs ``"Ab"``) is display data only; all music logic uses
pitch classes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

LETTERS: Final = ("C", "D", "E", "F", "G", "A", "B")
LETTER_PITCH_CLASS: Final = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

MAJOR_STEPS: Final = (0, 2, 4, 5, 7, 9, 11)

# Mode name -> index of its tonic within the parent major scale.
MODE_DEGREE: Final = {
    "ionian": 0,
    "dorian": 1,
    "phrygian": 2,
    "lydian": 3,
    "mixolydian": 4,
    "aeolian": 5,
    "locrian": 6,
}
MODE_ALIASES: Final = {"major": "ionian", "minor": "aeolian", "natural_minor": "aeolian"}
MODES: Final = tuple(MODE_DEGREE)

# Conventional spelling of each major key tonic (fewest accidentals; F# over Gb).
MAJOR_KEY_SPELLING: Final = {
    0: "C",
    1: "Db",
    2: "D",
    3: "Eb",
    4: "E",
    5: "F",
    6: "F#",
    7: "G",
    8: "Ab",
    9: "A",
    10: "Bb",
    11: "B",
}

_NOTE_RE: Final = re.compile(
    r"^\s*([A-Ga-g])[\s-]*(#{1,2}|b{1,2}|♯|♭|x|sharp|flat|double[ -]?sharp|double[ -]?flat)?\s*$",
    re.IGNORECASE,
)
_ACCIDENTAL_OFFSET: Final = {
    "": 0,
    "#": 1,
    "♯": 1,
    "sharp": 1,
    "##": 2,
    "x": 2,
    "doublesharp": 2,
    "b": -1,
    "♭": -1,
    "flat": -1,
    "bb": -2,
    "doubleflat": -2,
}


class TheoryError(ValueError):
    """Raised for unparseable note names or unknown modes."""


def normalize_mode(mode: str) -> str:
    key = mode.strip().lower().replace(" ", "_")
    key = MODE_ALIASES.get(key, key)
    if key not in MODE_DEGREE:
        raise TheoryError(f"unknown mode {mode!r}; expected one of {', '.join(MODES)}")
    return key


def parse_note_name(name: str) -> int:
    """Parse ``"G#"``, ``"Bb"``, ``"B flat"``, ``"E♭"`` etc. to a pitch class."""
    match = _NOTE_RE.match(name)
    if not match:
        raise TheoryError(f"cannot parse note name {name!r}")
    letter = match.group(1).upper()
    accidental = (match.group(2) or "").lower().replace(" ", "").replace("-", "")
    return (LETTER_PITCH_CLASS[letter] + _ACCIDENTAL_OFFSET[accidental]) % 12


def canonical_spelling(name: str) -> str:
    """Normalize a note name to ASCII form, e.g. ``"g sharp"`` -> ``"G#"``."""
    match = _NOTE_RE.match(name)
    if not match:
        raise TheoryError(f"cannot parse note name {name!r}")
    offset = _ACCIDENTAL_OFFSET[(match.group(2) or "").lower().replace(" ", "").replace("-", "")]
    return match.group(1).upper() + _accidental_text(offset)


def _accidental_text(offset: int) -> str:
    return {-2: "bb", -1: "b", 0: "", 1: "#", 2: "##"}[offset]


def spell_major_scale(tonic_name: str) -> tuple[str, ...]:
    """Spell the seven degrees of a major scale starting on ``tonic_name``."""
    tonic_pc = parse_note_name(tonic_name)
    start = LETTERS.index(canonical_spelling(tonic_name)[0])
    names = []
    for degree, step in enumerate(MAJOR_STEPS):
        letter = LETTERS[(start + degree) % 7]
        target = (tonic_pc + step) % 12
        offset = (target - LETTER_PITCH_CLASS[letter] + 6) % 12 - 6
        if abs(offset) > 2:
            raise TheoryError(f"{tonic_name} major needs triple accidentals")
        names.append(letter + _accidental_text(offset))
    return tuple(names)


def scale_pitch_classes(tonic_pc: int, mode: str) -> tuple[int, ...]:
    """Pitch classes of ``mode`` on ``tonic_pc``, in scale order from the tonic."""
    degree = MODE_DEGREE[normalize_mode(mode)]
    rotated = MAJOR_STEPS[degree:] + tuple(s + 12 for s in MAJOR_STEPS[:degree])
    base = rotated[0]
    return tuple((tonic_pc + s - base) % 12 for s in rotated)


def parent_major_pitch_class(tonic_pc: int, mode: str) -> int:
    degree = MODE_DEGREE[normalize_mode(mode)]
    return (tonic_pc - MAJOR_STEPS[degree]) % 12


def practical_tonic_spelling(tonic_pc: int, mode: str) -> str:
    """Conventional tonic spelling for a key, e.g. G# ionian -> ``"Ab"``."""
    degree = MODE_DEGREE[normalize_mode(mode)]
    parent = MAJOR_KEY_SPELLING[parent_major_pitch_class(tonic_pc, mode)]
    return spell_major_scale(parent)[degree]


def key_signature_accidentals(tonic_pc: int, mode: str) -> int:
    """Signed accidental count for the practical key: sharps > 0, flats < 0."""
    parent = MAJOR_KEY_SPELLING[parent_major_pitch_class(tonic_pc, mode)]
    names = spell_major_scale(parent)
    sharps = sum(n.count("#") for n in names)
    flats = sum(n.count("b") for n in names)
    return sharps - flats


@dataclass(frozen=True)
class Key:
    tonic_pitch_class: int
    mode: str
    requested_spelling: str
    display_spelling: str

    @property
    def pitch_classes(self) -> tuple[int, ...]:
        return scale_pitch_classes(self.tonic_pitch_class, self.mode)

    @property
    def display_name(self) -> str:
        if self.mode == "ionian":
            return f"{self.display_spelling} major"
        if self.mode == "aeolian":
            return f"{self.display_spelling} minor"
        return f"{self.display_spelling} {self.mode}"


def parse_key(tonic: str, mode: str) -> Key:
    """Resolve a user-requested key such as ``("G#", "ionian")``."""
    normalized_mode = normalize_mode(mode)
    pc = parse_note_name(tonic)
    return Key(
        tonic_pitch_class=pc,
        mode=normalized_mode,
        requested_spelling=canonical_spelling(tonic),
        display_spelling=practical_tonic_spelling(pc, normalized_mode),
    )


def pitch_class_of(midi_pitch: int) -> int:
    return midi_pitch % 12
