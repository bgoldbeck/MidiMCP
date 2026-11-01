"""Composition templates for late-1990s fantasy RPG music.

A template is musical *guidance*, never a melody: tempo, meter, mode, key, an
ensemble with roles and registers, a song form with a chord plan per section,
accompaniment patterns, and phrasing advice. ``build_scaffold`` turns a template
into a ready-to-fill project: tracks with roles, part limits, sections and a
bar-by-bar chord chart. The agent then writes the notes.

All templates are original descriptions of common genre practice.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Final

from midimcp.instruments import instrument_range, resolve_instrument
from midimcp.music.theory import normalize_mode, parse_key, parse_roman
from midimcp.music.timing import DEFAULT_PPQ, ticks_per_bar


class TemplateError(ValueError):
    code = "UNKNOWN_TEMPLATE"


@dataclass(frozen=True)
class Part:
    role: str
    track_id: str
    name: str
    instrument_id: str
    gain_db: float
    pan: float
    lowest: int
    highest: int
    max_polyphony: int
    guidance: str


@dataclass(frozen=True)
class SectionPlan:
    label: str
    bars: int
    progression: tuple[str, ...]  # one chord per bar, repeated to fill the section
    intent: str


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    summary: str
    mood: str
    setting: str
    tempo_range: tuple[int, int]
    default_tempo: int
    meter: tuple[int, int]
    mode: str
    default_tonic: str
    alternative_modes: tuple[str, ...]
    parts: tuple[Part, ...]
    form: tuple[SectionPlan, ...]
    loop: bool
    percussion_allowed: bool
    melody: str
    accompaniment: str
    dos: tuple[str, ...]
    donts: tuple[str, ...]
    patterns: dict[str, str] = field(default_factory=dict)

    @property
    def form_bars(self) -> int:
        return sum(s.bars for s in self.form)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "mood": self.mood,
            "tempoBpm": self.default_tempo,
            "tempoRange": list(self.tempo_range),
            "meter": f"{self.meter[0]}/{self.meter[1]}",
            "mode": self.mode,
            "defaultTonic": self.default_tonic,
            "bars": self.form_bars,
            "instruments": [p.instrument_id for p in self.parts],
            "form": " ".join(f"{s.label}({s.bars})" for s in self.form),
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["formBars"] = self.form_bars
        data["ticksPerBar"] = ticks_per_bar(DEFAULT_PPQ, *self.meter)
        return data


def _part(
    role, track_id, name, instrument_id, gain_db, pan, max_poly, guidance, low=None, high=None
):
    rng = instrument_range(instrument_id) or (0, 127)
    return Part(
        role,
        track_id,
        name,
        instrument_id,
        gain_db,
        pan,
        low if low is not None else rng[0],
        high if high is not None else rng[1],
        max_poly,
        guidance,
    )


TEMPLATES: Final[dict[str, Template]] = {
    t.id: t
    for t in (
        Template(
            id="peaceful-town",
            name="Peaceful Town",
            summary="Warm, unhurried town theme: wooden flute melody over plucked lute arpeggios.",
            mood="peaceful, welcoming, slightly nostalgic",
            setting="medieval market town by day",
            tempo_range=(80, 100),
            default_tempo=88,
            meter=(6, 8),
            mode="ionian",
            default_tonic="G",
            alternative_modes=("mixolydian", "lydian"),
            parts=(
                _part(
                    "melody",
                    "flute",
                    "Wooden Flute",
                    "retro.wooden_flute",
                    -2,
                    0.1,
                    1,
                    "Singable 4-bar phrases; mostly stepwise with one expressive leap (4th-6th) "
                    "per phrase; land on chord tones on beat 1; breathe in bar 4 of each phrase.",
                    low=67,
                    high=91,
                ),
                _part(
                    "accompaniment",
                    "lute",
                    "Lute",
                    "retro.lute",
                    -6,
                    -0.25,
                    3,
                    "Broken chords in steady eighths (see pattern); change chord on the bar line; "
                    "stay below the melody.",
                    low=45,
                    high=69,
                ),
                _part(
                    "pad",
                    "strings",
                    "Warm Strings",
                    "retro.warm_strings",
                    -14,
                    0.2,
                    3,
                    "Soft sustained chord tones, one chord per bar; enter in section B for lift.",
                    low=48,
                    high=72,
                ),
                _part(
                    "bass",
                    "bass",
                    "Cello",
                    "retro.cello",
                    -9,
                    -0.1,
                    1,
                    "Chord roots on beat 1 (dotted half), occasional passing note into the next bar.",
                    low=36,
                    high=55,
                ),
            ),
            form=(
                SectionPlan(
                    "A", 8, ("I", "vi", "IV", "V", "I", "vi", "ii", "V"), "Present the main theme."
                ),
                SectionPlan(
                    "A'",
                    8,
                    ("I", "vi", "IV", "V", "I", "IV", "V", "I"),
                    "Repeat the theme with a varied ending that cadences on I.",
                ),
                SectionPlan(
                    "B",
                    8,
                    ("IV", "V", "iii", "vi", "ii", "IV", "Vsus4", "V"),
                    "Contrast: higher register, longer notes, strings enter.",
                ),
                SectionPlan(
                    "A''",
                    8,
                    ("I", "vi", "IV", "V", "I", "vi", "IV", "V"),
                    "Return of the theme; end on V so the loop resolves to bar 1.",
                ),
            ),
            loop=True,
            percussion_allowed=False,
            melody="Lyrical and simple enough to hum. Use dotted-quarter + eighth figures typical of 6/8, "
            "repeat the opening 2-bar motif at different pitches, and keep the highest note for section B.",
            accompaniment="Lute plays a rolling arpeggio every bar; strings only sustain; cello marks roots.",
            dos=(
                "Leave a rest at each phrase end",
                "Vary velocity 60-90 to shape phrases",
                "Keep the flute above the lute at all times",
            ),
            donts=(
                "No percussion",
                "No busy sixteenth runs",
                "Don't copy melodies from existing games",
            ),
            patterns={
                "lute 6/8 arpeggio (ticks from bar start)": "0:root, 480:5th, 960:octave, 1440:3rd(+8), 1920:5th, 2400:octave — each 480 long"
            },
        ),
        Template(
            id="forest-exploration",
            name="Forest Exploration",
            summary="Open, curious wandering music: modal flute over rippling harp and soft pad.",
            mood="curious, airy, a little mysterious",
            setting="old woodland paths and clearings",
            tempo_range=(70, 90),
            default_tempo=78,
            meter=(3, 4),
            mode="dorian",
            default_tonic="D",
            alternative_modes=("aeolian", "mixolydian"),
            parts=(
                _part(
                    "melody",
                    "flute",
                    "Pan Flute",
                    "retro.pan_flute",
                    -3,
                    0.15,
                    1,
                    "Long-short patterns, gentle turns around the 6th degree (the dorian colour).",
                    low=62,
                    high=88,
                ),
                _part(
                    "accompaniment",
                    "harp",
                    "Harp",
                    "retro.harp",
                    -7,
                    -0.3,
                    4,
                    "Rippling eighth-note arpeggios up then down across two octaves per bar.",
                    low=43,
                    high=79,
                ),
                _part(
                    "pad",
                    "pad",
                    "Choir Pad",
                    "retro.voice_oohs",
                    -15,
                    0.25,
                    3,
                    "Very soft sustained triads; swell into each section start.",
                    low=52,
                    high=72,
                ),
                _part(
                    "bass",
                    "bass",
                    "Contrabass",
                    "retro.contrabass",
                    -11,
                    0.0,
                    1,
                    "Root on beat 1, fifth on beat 3 occasionally; keep it sparse.",
                    low=28,
                    high=50,
                ),
            ),
            form=(
                SectionPlan(
                    "A",
                    8,
                    ("i", "IV", "i", "IV", "i", "bVII", "IV", "i"),
                    "Theme in dorian; the major IV gives the dorian lift.",
                ),
                SectionPlan(
                    "B",
                    8,
                    ("bIII", "bVII", "IV", "i", "bVI", "bVII", "IV", "IV"),
                    "Wander away: new contour, harp thins out.",
                ),
                SectionPlan(
                    "A'",
                    8,
                    ("i", "IV", "i", "IV", "i", "bVII", "IV", "bVII"),
                    "Theme returns; end on bVII leading back to i.",
                ),
            ),
            loop=True,
            percussion_allowed=False,
            melody="Phrases of 4 bars, often starting on beat 2; emphasise the raised 6th (B in D dorian).",
            accompaniment="Harp provides motion; pad and bass stay out of the way.",
            dos=(
                "Use space: 1-2 bars of harp alone between phrases",
                "Let notes ring (long durations)",
            ),
            donts=(
                "No drums",
                "Avoid strong V-I cadences; modal colour comes from i-IV and bVII-i",
            ),
            patterns={
                "harp 3/4 ripple (ticks)": "0,480,960,1440,1920,2400: root,5th,octave,10th,octave,5th — each 480 long"
            },
        ),
        Template(
            id="ruined-crypt",
            name="Ruined Crypt",
            summary="Slow, cold dungeon ambience: low drones, distant choir, sparse music-box motif.",
            mood="eerie, cold, foreboding",
            setting="ancient crypt or dungeon",
            tempo_range=(52, 70),
            default_tempo=60,
            meter=(4, 4),
            mode="phrygian",
            default_tonic="E",
            alternative_modes=("aeolian", "locrian"),
            parts=(
                _part(
                    "melody",
                    "motif",
                    "Music Box",
                    "retro.music_box",
                    -6,
                    0.3,
                    1,
                    "A 3-5 note motif, high and isolated, repeated with small changes; long rests.",
                    low=72,
                    high=96,
                ),
                _part(
                    "pad",
                    "drone",
                    "Church Organ",
                    "retro.church_organ",
                    -12,
                    -0.2,
                    2,
                    "Tonic + fifth drone held for whole sections; occasionally move to the b2.",
                    low=36,
                    high=60,
                ),
                _part(
                    "countermelody",
                    "choir",
                    "Choir",
                    "retro.choir",
                    -14,
                    0.1,
                    2,
                    "Slow two-note sighs (half steps), whole notes, enter and leave quietly.",
                    low=52,
                    high=72,
                ),
                _part(
                    "bass",
                    "low",
                    "Tremolo Strings",
                    "retro.tremolo_strings",
                    -13,
                    0.0,
                    2,
                    "Low tremolo swells on section changes only.",
                    low=36,
                    high=55,
                ),
            ),
            form=(
                SectionPlan("Intro", 4, ("i", "i", "bII", "i"), "Drone alone; establish darkness."),
                SectionPlan(
                    "A",
                    8,
                    ("i", "bII", "i", "bII", "iv", "i", "bVI", "bII"),
                    "Motif enters; choir sighs.",
                ),
                SectionPlan(
                    "B",
                    8,
                    ("bVI", "bVII", "i", "i", "iv", "bII", "bII", "i"),
                    "Thicker: tremolo strings swell, motif higher.",
                ),
            ),
            loop=True,
            percussion_allowed=False,
            melody="Less is more: at most one motif statement every 2 bars; let silence carry tension.",
            accompaniment="Drones and swells, no rhythm section.",
            dos=("Keep velocities low (35-70)", "Use the b2 (phrygian) half step for dread"),
            donts=("No percussion grooves", "No bright major cadences"),
            patterns={},
        ),
        Template(
            id="tavern",
            name="Tavern / Minstrel",
            summary="Lively dance for an inn: fiddle tune, strummed lute, recorder answers.",
            mood="cheerful, rustic, bouncy",
            setting="crowded tavern with a minstrel band",
            tempo_range=(108, 132),
            default_tempo=120,
            meter=(6, 8),
            mode="mixolydian",
            default_tonic="D",
            alternative_modes=("ionian", "dorian"),
            parts=(
                _part(
                    "melody",
                    "fiddle",
                    "Fiddle",
                    "retro.fiddle",
                    -3,
                    0.15,
                    2,
                    "Running eighth notes in jig rhythm, repeated 2-bar cells, ornament with neighbour notes.",
                    low=62,
                    high=91,
                ),
                _part(
                    "countermelody",
                    "recorder",
                    "Recorder",
                    "retro.recorder",
                    -8,
                    -0.35,
                    1,
                    "Answers the fiddle in the gaps (call and response), section B only.",
                    low=72,
                    high=93,
                ),
                _part(
                    "accompaniment",
                    "lute",
                    "Lute",
                    "retro.lute",
                    -6,
                    -0.15,
                    4,
                    "Strummed chords on each dotted-quarter beat (2 per bar), short and bright.",
                    low=48,
                    high=72,
                ),
                _part(
                    "bass",
                    "bass",
                    "Acoustic Bass",
                    "retro.acoustic_bass",
                    -9,
                    0.0,
                    1,
                    "Root-fifth on the two main beats.",
                    low=31,
                    high=52,
                ),
            ),
            form=(
                SectionPlan(
                    "A",
                    8,
                    ("I", "bVII", "I", "V", "I", "bVII", "IV", "I"),
                    "The tune: catchy, repeated cell.",
                ),
                SectionPlan(
                    "A",
                    8,
                    ("I", "bVII", "I", "V", "I", "bVII", "IV", "I"),
                    "Tune again with small variations.",
                ),
                SectionPlan(
                    "B",
                    8,
                    ("IV", "I", "bVII", "I", "IV", "I", "V", "V"),
                    "Higher register, recorder answers.",
                ),
                SectionPlan(
                    "B'",
                    8,
                    ("IV", "I", "bVII", "I", "IV", "bVII", "V", "I"),
                    "Varied B; cadence back to the tune.",
                ),
            ),
            loop=True,
            percussion_allowed=True,
            melody="Jig rhythm (long-short-long-short in 6/8), lots of repetition, mixolydian flat 7th.",
            accompaniment="Lute strums on beats 1 and 4 of each 6/8 bar; bass mirrors.",
            dos=(
                "Strong downbeats (velocity 90-105), lighter offbeats",
                "Repeat the A tune exactly once",
            ),
            donts=("Don't slow down", "Avoid long held notes in the fiddle"),
            patterns={
                "lute 6/8 strum (ticks)": "0 and 1440: full chord, 400 long, velocity 85 then 75"
            },
        ),
        Template(
            id="sea-voyage",
            name="Sea Voyage",
            summary="Broad, rolling travel theme: horn melody over swelling strings and harp waves.",
            mood="hopeful, expansive, adventurous",
            setting="ship at sea / open travel",
            tempo_range=(76, 96),
            default_tempo=84,
            meter=(3, 4),
            mode="ionian",
            default_tonic="F",
            alternative_modes=("lydian", "mixolydian"),
            parts=(
                _part(
                    "melody",
                    "horn",
                    "French Horn",
                    "retro.french_horn",
                    -4,
                    0.0,
                    1,
                    "Noble long notes; rising 4ths and 5ths; climax in the last A.",
                    low=53,
                    high=74,
                ),
                _part(
                    "countermelody",
                    "flute",
                    "Wooden Flute",
                    "retro.wooden_flute",
                    -9,
                    0.3,
                    1,
                    "Floating counter-line in B, an octave above the horn.",
                    low=72,
                    high=93,
                ),
                _part(
                    "accompaniment",
                    "harp",
                    "Harp",
                    "retro.harp",
                    -8,
                    -0.3,
                    4,
                    "Wave-like arpeggios: up for one bar, down the next.",
                    low=41,
                    high=77,
                ),
                _part(
                    "pad",
                    "strings",
                    "Strings",
                    "retro.strings",
                    -11,
                    0.15,
                    4,
                    "Sustained chords that swell (velocity rises) toward each phrase peak.",
                    low=48,
                    high=76,
                ),
                _part(
                    "bass",
                    "bass",
                    "Contrabass",
                    "retro.contrabass",
                    -10,
                    0.0,
                    1,
                    "Roots on beat 1, dotted half.",
                    low=29,
                    high=50,
                ),
            ),
            form=(
                SectionPlan(
                    "A", 8, ("I", "IV", "I", "V", "vi", "IV", "I", "V"), "Main theme in the horn."
                ),
                SectionPlan(
                    "B",
                    8,
                    ("vi", "IV", "I", "V", "vi", "IV", "ii", "V"),
                    "Flute counter-line; strings swell.",
                ),
                SectionPlan(
                    "A'",
                    8,
                    ("I", "IV", "I", "V", "vi", "IV", "V", "I"),
                    "Theme, fuller and higher; cadence.",
                ),
                SectionPlan(
                    "B'",
                    8,
                    ("IV", "V", "iii", "vi", "IV", "I", "Vsus4", "V"),
                    "Wind down toward the loop.",
                ),
            ),
            loop=True,
            percussion_allowed=False,
            melody="Few, long notes; the shape of the line matters more than speed.",
            accompaniment="Harp keeps motion; strings breathe in 2-bar swells.",
            dos=("Use II (lydian) for wonder in the alternative mode",),
            donts=("No percussion",),
            patterns={},
        ),
        Template(
            id="tense-borderlands",
            name="Tense Borderlands",
            summary="Restless danger music: string ostinato, horn calls, occasional timpani.",
            mood="tense, alert, threatening",
            setting="contested border, enemies nearby",
            tempo_range=(96, 116),
            default_tempo=104,
            meter=(4, 4),
            mode="aeolian",
            default_tonic="A",
            alternative_modes=("phrygian", "dorian"),
            parts=(
                _part(
                    "accompaniment",
                    "ostinato",
                    "Tremolo Strings",
                    "retro.tremolo_strings",
                    -8,
                    -0.2,
                    2,
                    "Driving repeated eighths on root/fifth; accent beats 1 and 3.",
                    low=45,
                    high=69,
                ),
                _part(
                    "melody",
                    "horn",
                    "Trumpet",
                    "retro.trumpet",
                    -5,
                    0.15,
                    1,
                    "Short fanfare-like calls (2 bars) answered by silence.",
                    low=60,
                    high=79,
                ),
                _part(
                    "countermelody",
                    "low-brass",
                    "Trombone",
                    "retro.trombone",
                    -9,
                    -0.1,
                    2,
                    "Low sustained notes underneath the calls, moving by half steps.",
                    low=40,
                    high=62,
                ),
                _part(
                    "percussion",
                    "timpani",
                    "Timpani",
                    "retro.timpani",
                    -8,
                    0.0,
                    1,
                    "Rolls and single hits on section starts and phrase ends only.",
                    low=40,
                    high=55,
                ),
                _part(
                    "bass",
                    "bass",
                    "Contrabass",
                    "retro.contrabass",
                    -10,
                    0.0,
                    1,
                    "Root eighths doubling the ostinato's lowest note.",
                    low=28,
                    high=48,
                ),
            ),
            form=(
                SectionPlan(
                    "A",
                    8,
                    ("i", "bVI", "bVII", "i", "i", "bVI", "iv", "V"),
                    "Ostinato + first calls.",
                ),
                SectionPlan(
                    "A'",
                    8,
                    ("i", "bVI", "bVII", "i", "iv", "bVI", "V", "V"),
                    "Calls higher; trombone enters.",
                ),
                SectionPlan(
                    "B",
                    8,
                    ("iv", "v", "bVI", "bVII", "iv", "bVI", "V", "V"),
                    "Climb: everything louder, timpani rolls.",
                ),
                SectionPlan(
                    "A",
                    8,
                    ("i", "bVI", "bVII", "i", "i", "bVI", "iv", "V"),
                    "Return; end on V for the loop.",
                ),
            ),
            loop=True,
            percussion_allowed=True,
            melody="Rhythmic, short motifs; leave gaps; harmonic minor V (major) for tension.",
            accompaniment="The ostinato never stops; everything else enters and exits.",
            dos=("Crescendo across B (velocities up 15-20)",),
            donts=("No sweet lyrical lines",),
            patterns={
                "strings 4/4 ostinato (ticks)": "every 480: root,root,5th,root,... 420 long; accent 0 and 1920"
            },
        ),
    )
}


def list_templates() -> list[dict[str, Any]]:
    return [t.summary_dict() for t in TEMPLATES.values()]


def get_template(template_id: str) -> Template:
    template = TEMPLATES.get(template_id)
    if template is None:
        raise TemplateError(
            f"unknown template {template_id!r}; choose one of {', '.join(TEMPLATES)}"
        )
    return template


@dataclass(frozen=True)
class Scaffold:
    sections: list[dict[str, Any]]
    harmony: list[dict[str, Any]]
    tracks: list[dict[str, Any]]
    part_limits: list[dict[str, Any]]
    bars: int


def build_form(template: Template, bars: int) -> list[SectionPlan]:
    """Fit the template form to ``bars``: repeat sections in order, truncate the last."""
    plans, used = [], 0
    while used < bars:
        for plan in template.form:
            if used >= bars:
                break
            length = min(plan.bars, bars - used)
            plans.append(SectionPlan(plan.label, length, plan.progression, plan.intent))
            used += length
    return plans


def build_scaffold(
    template: Template,
    *,
    tonic_pc: int,
    mode: str,
    meter: tuple[int, int],
    bars: int,
    ppq: int = DEFAULT_PPQ,
) -> Scaffold:
    per_bar = ticks_per_bar(ppq, *meter)
    sections, harmony = [], []
    bar = 0
    labels_seen: dict[str, int] = {}
    for plan in build_form(template, bars):
        labels_seen[plan.label] = labels_seen.get(plan.label, 0) + 1
        suffix = f"-{labels_seen[plan.label]}" if labels_seen[plan.label] > 1 else ""
        section_id = (
            "section-" + "".join(c if c.isalnum() else "p" for c in plan.label.lower()) + suffix
        )
        sections.append(
            {
                "id": section_id,
                "label": plan.label,
                "startTick": bar * per_bar,
                "endTick": (bar + plan.bars) * per_bar,
            }
        )
        for i in range(plan.bars):
            numeral = plan.progression[i % len(plan.progression)]
            chord = parse_roman(numeral, tonic_pc, mode)
            harmony.append(
                {
                    "startTick": (bar + i) * per_bar,
                    "durationTicks": per_bar,
                    "symbol": chord.symbol,
                    "romanNumeral": numeral,
                }
            )
        bar += plan.bars
    tracks, limits = [], []
    for part in template.parts:
        instrument = resolve_instrument(part.instrument_id)
        tracks.append(
            {
                "id": part.track_id,
                "name": part.name,
                "instrumentId": instrument.id,
                "isPercussion": instrument.is_percussion,
                "gainDb": float(part.gain_db),
                "pan": float(part.pan),
                "role": part.role,
                "notes": [],
            }
        )
        limits.append(
            {
                "trackId": part.track_id,
                "lowestPitch": part.lowest,
                "highestPitch": part.highest,
                "maxPolyphony": part.max_polyphony,
            }
        )
    return Scaffold(sections, harmony, tracks, limits, bars)


def resolve_key(template: Template, tonic: str | None, mode: str | None) -> tuple[str, str]:
    key = parse_key(tonic or template.default_tonic, normalize_mode(mode or template.mode))
    return key.requested_spelling, key.mode
