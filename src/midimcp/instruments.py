"""Instrument IDs and their General MIDI program mapping.

Instrument IDs used in scores:

* ``retro.<alias>`` — friendly curated aliases (``retro.wooden_flute``, ``retro.lute``).
* ``gm.<0-127>`` — any General MIDI melodic program by number (``gm.073``).
* ``gm.drums`` — the GM percussion kit (MIDI channel 10).

General MIDI has no dedicated lute program. ``retro.lute`` maps to the nylon
guitar patch, the closest plucked GM sound; a soundbank may supply a real lute
preset later through the soundbank registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

GM_PROGRAM_NAMES: Final = (
    "Acoustic Grand Piano", "Bright Acoustic Piano", "Electric Grand Piano", "Honky-tonk Piano",
    "Electric Piano 1", "Electric Piano 2", "Harpsichord", "Clavinet",
    "Celesta", "Glockenspiel", "Music Box", "Vibraphone",
    "Marimba", "Xylophone", "Tubular Bells", "Dulcimer",
    "Drawbar Organ", "Percussive Organ", "Rock Organ", "Church Organ",
    "Reed Organ", "Accordion", "Harmonica", "Tango Accordion",
    "Acoustic Guitar (nylon)", "Acoustic Guitar (steel)", "Electric Guitar (jazz)",
    "Electric Guitar (clean)", "Electric Guitar (muted)", "Overdriven Guitar",
    "Distortion Guitar", "Guitar Harmonics",
    "Acoustic Bass", "Electric Bass (finger)", "Electric Bass (pick)", "Fretless Bass",
    "Slap Bass 1", "Slap Bass 2", "Synth Bass 1", "Synth Bass 2",
    "Violin", "Viola", "Cello", "Contrabass",
    "Tremolo Strings", "Pizzicato Strings", "Orchestral Harp", "Timpani",
    "String Ensemble 1", "String Ensemble 2", "Synth Strings 1", "Synth Strings 2",
    "Choir Aahs", "Voice Oohs", "Synth Voice", "Orchestra Hit",
    "Trumpet", "Trombone", "Tuba", "Muted Trumpet",
    "French Horn", "Brass Section", "Synth Brass 1", "Synth Brass 2",
    "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax",
    "Oboe", "English Horn", "Bassoon", "Clarinet",
    "Piccolo", "Flute", "Recorder", "Pan Flute",
    "Blown Bottle", "Shakuhachi", "Whistle", "Ocarina",
    "Lead 1 (square)", "Lead 2 (sawtooth)", "Lead 3 (calliope)", "Lead 4 (chiff)",
    "Lead 5 (charang)", "Lead 6 (voice)", "Lead 7 (fifths)", "Lead 8 (bass + lead)",
    "Pad 1 (new age)", "Pad 2 (warm)", "Pad 3 (polysynth)", "Pad 4 (choir)",
    "Pad 5 (bowed)", "Pad 6 (metallic)", "Pad 7 (halo)", "Pad 8 (sweep)",
    "FX 1 (rain)", "FX 2 (soundtrack)", "FX 3 (crystal)", "FX 4 (atmosphere)",
    "FX 5 (brightness)", "FX 6 (goblins)", "FX 7 (echoes)", "FX 8 (sci-fi)",
    "Sitar", "Banjo", "Shamisen", "Koto",
    "Kalimba", "Bagpipe", "Fiddle", "Shanai",
    "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock",
    "Taiko Drum", "Melodic Tom", "Synth Drum", "Reverse Cymbal",
    "Guitar Fret Noise", "Breath Noise", "Seashore", "Bird Tweet",
    "Telephone Ring", "Helicopter", "Applause", "Gunshot",
)  # fmt: skip

PERCUSSION_BANK: Final = 128
DRUMS_ID: Final = "gm.drums"

# Curated fantasy-RPG palette: alias -> (GM program, display name, family).
RETRO_ALIASES: Final[dict[str, tuple[int, str, str]]] = {
    "wooden_flute": (73, "Wooden Flute", "wind"),
    "recorder": (74, "Recorder", "wind"),
    "pan_flute": (75, "Pan Flute", "wind"),
    "piccolo": (72, "Piccolo", "wind"),
    "ocarina": (79, "Ocarina", "wind"),
    "shakuhachi": (77, "Shakuhachi", "wind"),
    "whistle": (78, "Tin Whistle", "wind"),
    "oboe": (68, "Oboe", "wind"),
    "english_horn": (69, "English Horn", "wind"),
    "clarinet": (71, "Clarinet", "wind"),
    "bassoon": (70, "Bassoon", "wind"),
    "bagpipe": (109, "Bagpipe", "wind"),
    "french_horn": (60, "French Horn", "brass"),
    "trumpet": (56, "Trumpet", "brass"),
    "trombone": (57, "Trombone", "brass"),
    "tuba": (58, "Tuba", "brass"),
    "lute": (24, "Lute (nylon plucked)", "plucked"),
    "harp": (46, "Harp", "plucked"),
    "dulcimer": (15, "Dulcimer", "plucked"),
    "banjo": (105, "Banjo", "plucked"),
    "koto": (107, "Koto", "plucked"),
    "sitar": (104, "Sitar", "plucked"),
    "pizzicato": (45, "Pizzicato Strings", "plucked"),
    "harpsichord": (6, "Harpsichord", "keyboard"),
    "piano": (0, "Piano", "keyboard"),
    "church_organ": (19, "Church Organ", "keyboard"),
    "reed_organ": (20, "Reed Organ", "keyboard"),
    "accordion": (21, "Accordion", "keyboard"),
    "celesta": (8, "Celesta", "mallet"),
    "glockenspiel": (9, "Glockenspiel", "mallet"),
    "music_box": (10, "Music Box", "mallet"),
    "kalimba": (108, "Kalimba", "mallet"),
    "tubular_bells": (14, "Tubular Bells", "mallet"),
    "violin": (40, "Violin", "strings"),
    "fiddle": (110, "Fiddle", "strings"),
    "viola": (41, "Viola", "strings"),
    "cello": (42, "Cello", "strings"),
    "contrabass": (43, "Contrabass", "strings"),
    "strings": (48, "Strings", "strings"),
    "warm_strings": (49, "Warm Strings", "strings"),
    "tremolo_strings": (44, "Tremolo Strings", "strings"),
    "choir": (52, "Choir", "voice"),
    "voice_oohs": (53, "Voice Oohs", "voice"),
    "warm_pad": (89, "Warm Pad", "pad"),
    "timpani": (47, "Timpani", "percussion-melodic"),
    "acoustic_bass": (32, "Acoustic Bass", "bass"),
    "fretless_bass": (35, "Fretless Bass", "bass"),
    "synth_bass": (38, "Synth Bass", "bass"),
    "brass_section": (61, "Brass Section", "brass"),
    "synth_brass": (62, "Synth Brass", "brass"),
    "synth_strings": (50, "Synth Strings", "strings"),
    "electric_piano": (4, "Electric Piano", "keyboard"),
    "vibraphone": (11, "Vibraphone", "mallet"),
    "marimba": (12, "Marimba", "mallet"),
    "xylophone": (13, "Xylophone", "mallet"),
    "overdrive_guitar": (29, "Overdrive Guitar", "plucked"),
    "distortion_guitar": (30, "Distortion Guitar", "plucked"),
    "square_lead": (80, "Square Lead (chiptune)", "synth"),
    "saw_lead": (81, "Saw Lead", "synth"),
    "calliope": (82, "Calliope Lead", "synth"),
    "chiff_lead": (83, "Chiff Lead", "synth"),
    "new_age_pad": (88, "New Age Pad", "pad"),
    "halo_pad": (94, "Halo Pad", "pad"),
    "orchestra_hit": (55, "Orchestra Hit", "percussion-melodic"),
    "steel_drums": (114, "Steel Drums", "percussion-melodic"),
    "woodblock": (115, "Woodblock", "percussion-melodic"),
    "nylon_guitar": (24, "Nylon Guitar", "plucked"),
    "taiko": (116, "Taiko Drum", "percussion-melodic"),
    "synth_drum": (118, "Synth Drum", "percussion-melodic"),
}

_GM_ID = re.compile(r"^gm\.(\d{1,3})$")


class UnknownInstrument(ValueError):
    code = "UNKNOWN_INSTRUMENT"


@dataclass(frozen=True)
class Instrument:
    id: str
    name: str
    bank: int
    program: int
    family: str
    is_percussion: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "bank": self.bank,
            "program": self.program,
            "family": self.family,
            "isPercussion": self.is_percussion,
            "gmName": "Standard Drum Kit" if self.is_percussion else GM_PROGRAM_NAMES[self.program],
        }


def resolve_instrument(instrument_id: str) -> Instrument:
    """Map an instrument ID to its GM bank/program. Raises UnknownInstrument."""
    if instrument_id == DRUMS_ID:
        return Instrument(DRUMS_ID, "Drum Kit", PERCUSSION_BANK, 0, "drums", True)
    if instrument_id.startswith("retro."):
        alias = RETRO_ALIASES.get(instrument_id.removeprefix("retro."))
        if alias is not None:
            program, name, family = alias
            return Instrument(instrument_id, name, 0, program, family)
    match = _GM_ID.match(instrument_id)
    if match and int(match.group(1)) < 128:
        program = int(match.group(1))
        return Instrument(f"gm.{program:03d}", GM_PROGRAM_NAMES[program], 0, program, "gm")
    raise UnknownInstrument(f"unknown instrument {instrument_id!r}")


def builtin_instruments() -> list[Instrument]:
    """Curated aliases first, then the drum kit; ``gm.NNN`` IDs are also accepted."""
    items = [resolve_instrument(f"retro.{alias}") for alias in RETRO_ALIASES]
    items.append(resolve_instrument(DRUMS_ID))
    return items


def instrument_for_program(program: int, *, percussion: bool = False) -> str:
    """Preferred instrument ID for a GM program (used by MIDI import)."""
    if percussion:
        return DRUMS_ID
    for alias, (alias_program, _, _) in RETRO_ALIASES.items():
        if alias_program == program:
            return f"retro.{alias}"
    return f"gm.{program:03d}"


# Practical playing ranges (MIDI pitch, inclusive) for the curated aliases. Notes outside
# still sound in a SoundFont but stop sounding like the real instrument.
INSTRUMENT_RANGES: Final[dict[str, tuple[int, int]]] = {
    "wooden_flute": (60, 96), "recorder": (72, 98), "pan_flute": (60, 91), "piccolo": (74, 108),
    "ocarina": (60, 86), "shakuhachi": (60, 86), "whistle": (74, 98), "oboe": (58, 91),
    "english_horn": (52, 81), "clarinet": (50, 91), "bassoon": (34, 75), "bagpipe": (55, 79),
    "french_horn": (41, 77), "trumpet": (54, 84), "trombone": (40, 72), "tuba": (28, 58),
    "lute": (40, 81), "harp": (24, 103), "dulcimer": (48, 88), "banjo": (48, 86),
    "koto": (48, 91), "sitar": (48, 84), "pizzicato": (28, 96), "harpsichord": (29, 89),
    "piano": (21, 108), "church_organ": (24, 96), "reed_organ": (36, 96), "accordion": (41, 89),
    "celesta": (60, 108), "glockenspiel": (79, 108), "music_box": (60, 96), "kalimba": (60, 84),
    "tubular_bells": (60, 77), "violin": (55, 103), "fiddle": (55, 96), "viola": (48, 88),
    "cello": (36, 76), "contrabass": (28, 60), "strings": (28, 96), "warm_strings": (28, 96),
    "tremolo_strings": (28, 96), "choir": (48, 79), "voice_oohs": (48, 79), "warm_pad": (36, 96),
    "timpani": (40, 55), "acoustic_bass": (28, 55),
    "fretless_bass": (28, 60), "synth_bass": (24, 60), "brass_section": (41, 84),
    "synth_brass": (36, 84), "synth_strings": (36, 96), "electric_piano": (28, 103),
    "vibraphone": (53, 89), "marimba": (45, 96), "xylophone": (65, 108),
    "overdrive_guitar": (40, 86), "distortion_guitar": (40, 86), "square_lead": (36, 96),
    "saw_lead": (36, 96), "calliope": (48, 96), "chiff_lead": (48, 96), "new_age_pad": (36, 96),
    "halo_pad": (36, 96), "orchestra_hit": (36, 84), "steel_drums": (52, 88), "taiko": (36, 60),
    "synth_drum": (36, 72), "woodblock": (48, 96), "nylon_guitar": (38, 84),
}  # fmt: skip


def instrument_range(instrument_id: str) -> tuple[int, int] | None:
    if instrument_id.startswith("retro."):
        return INSTRUMENT_RANGES.get(instrument_id.removeprefix("retro."))
    return None


def instrument_family(instrument_id: str) -> str | None:
    try:
        return resolve_instrument(instrument_id).family
    except UnknownInstrument:
        return None
