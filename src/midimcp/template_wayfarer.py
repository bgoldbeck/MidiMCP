"""Original location templates for a fantasy travel soundtrack.

Each template follows the lessons in ``docs/reference/09-composing-playbook.md``:
an intro before the tune, layered sections (parts rest, enter and leave), a break
where the melody rests, a short turnaround into the loop, every pitched part at
or below C6, and tick-level patterns for hooks, walking bass and fills.
"""

from __future__ import annotations

from typing import Final

from midimcp.templates import Layer, SectionPlan, Template, _part

_ORIGINAL = "Write fresh themes. Don't copy or paraphrase existing game melodies."
_HIGH = "Keep every pitched part at or below C6 so nothing turns shrill"
_PIANO_PEDAL = (
    "Use set_automation on the piano's sustain lane (CC64). Place 127 at the chord "
    "attack, release the written notes while the pedal is down, then place 0 a "
    "sixteenth before the next harmony or loop seam. "
)


def _rest(track_id: str, note: str = "") -> Layer:
    return Layer(track_id, "rest", 1, note)


def _enter(track_id: str, bar: int, note: str = "") -> Layer:
    return Layer(track_id, "enter", bar, note)


def _exit(track_id: str, bar: int, note: str = "") -> Layer:
    return Layer(track_id, "exit", bar, note)


WAYFARER: Final[tuple[Template, ...]] = (
    Template(
        id="wayfarer-city",
        name="Wayfarer Market City",
        summary="A bustling stone city: a lute-and-bass intro with a tambourine, a nimble "
        "clarinet call answered by piano, a fiddle that joins in the market, a break where "
        "fiddle and piano trade, and a turnaround into the loop.",
        mood="lively, friendly, full of small discoveries",
        setting="city gates, a market square, busy crafting stalls",
        tempo_range=(104, 128),
        default_tempo=116,
        meter=(4, 4),
        mode="mixolydian",
        default_tonic="G",
        alternative_modes=("ionian", "dorian"),
        parts=(
            _part(
                "melody",
                "clarinet",
                "Clarinet",
                "retro.clarinet",
                -5,
                0.12,
                1,
                "Short upward calls with a pickup, built on one hook rhythm (eighth pickup, "
                "dotted quarter, eighth, half); leave beat four free for replies.",
                low=60,
                high=84,
            ),
            _part(
                "accompaniment",
                "lute",
                "Lute",
                "retro.lute",
                -9,
                -0.28,
                3,
                "Pluck a low chord tone, then two offbeat dyads; every note rings until it "
                "is plucked again or the bar ends.",
                low=45,
                high=69,
            ),
            _part(
                "countermelody",
                "piano",
                "Market Piano",
                "retro.piano",
                -12,
                0.25,
                3,
                "Answer in thirds or sixths in the clarinet's gaps. Rolled chords only at "
                "cadences.",
                low=57,
                high=81,
            ),
            _part(
                "countermelody",
                "fiddle",
                "Fiddle",
                "retro.fiddle",
                -10,
                -0.1,
                1,
                "A dancing counter-line of eighths in the market; the tune in the square.",
                low=62,
                high=81,
            ),
            _part(
                "bass",
                "bass",
                "Acoustic Bass",
                "retro.acoustic_bass",
                -11,
                0.0,
                1,
                "Roots on beats one and three, walking by step into each new chord.",
                low=32,
                high=52,
            ),
            _part(
                "percussion",
                "drums",
                "Tambourine",
                "gm.drums",
                -14,
                0.3,
                1,
                "GM drum kit: tambourine 54 on beats two and four, a low conga 64 on one.",
                low=54,
                high=64,
            ),
        ),
        form=(
            SectionPlan(
                "Intro",
                4,
                ("I", "bVII", "IV", "I"),
                "Lute and bass set the walking pulse; the tambourine joins at bar 3.",
                layers=(
                    _rest("clarinet"),
                    _rest("piano"),
                    _rest("fiddle"),
                    _enter("drums", 3),
                ),
            ),
            SectionPlan(
                "Gate",
                8,
                ("I", "bVII", "IV", "I", "vi", "IV", "bVII", "V"),
                "The clarinet call over lute and bass; the piano answers in its gaps.",
                layers=(_rest("fiddle"),),
            ),
            SectionPlan(
                "Market",
                8,
                ("IV", "I", "bVII", "IV", "ii", "bVII", "IV", "V"),
                "Busier and louder: the fiddle dances under shorter clarinet calls.",
                layers=(_enter("fiddle", 2, "a pickup into its counter-line"),),
            ),
            SectionPlan(
                "Square",
                4,
                ("vi", "IV", "bVII", "V"),
                "The clarinet rests: fiddle and piano trade the hook over the lute.",
                layers=(_rest("clarinet"), _rest("drums")),
            ),
            SectionPlan(
                "Return",
                8,
                ("I", "bVII", "IV", "I", "vi", "ii", "bVII", "V"),
                "The opening call returns with the whole market.",
                layers=(_exit("fiddle", 5),),
            ),
            SectionPlan(
                "Turnaround",
                2,
                ("IV", "V"),
                "Clarinet and piano climb in thirds into bar 1 of the loop.",
                layers=(_rest("fiddle"),),
            ),
        ),
        loop=True,
        percussion_allowed=True,
        melody="Start with a quick pickup and a longer destination note. Shift the rhythm to "
        "the offbeat in the reply while keeping the contour recognizable.",
        accompaniment="Dry lute and bass carry the walking pulse; piano and fiddle fill the "
        "gaps; the tambourine stays light.",
        dos=(
            "Open with lute, bass and tambourine before the clarinet",
            "Use a flattened seventh as a passing colour",
            "Walk the bass by step into each new chord",
            "Let the lute ring",
            "Play the market louder than the gate",
        ),
        donts=(
            "Avoid continuous block chords under the clarinet",
            "Don't let the fiddle and clarinet play tunes at the same time",
            _HIGH,
            _ORIGINAL,
        ),
        patterns={
            "clarinet hook (ticks)": "Pickup eighth at 3360 of the bar before; 0 (1440), "
            "1440 (480), 1920 (1700); beat four left free for the reply.",
            "lute (ticks)": "Low chord tone at 0, dyads at 1440 and 2400; let each ring to "
            "the bar end.",
            "bass walk (ticks)": "Root at 0 and 1920 (900); a step toward the next root at 2880.",
            "piano reply (ticks)": "Two or three notes in thirds from 2880.",
            "tambourine (ticks)": "54 at 960 and 2880, low conga 64 at 0; a shake of four "
            "sixteenths from 2880 every fourth bar.",
        },
        expression="Give the clarinet short attacks and breaths between two-bar calls; "
        "humanize (timing_ticks 10, breath_ticks 140, phrase_dynamics 10) with four-bar "
        "swells. Swell only the held destinations. Fiddle: humanize timing_ticks 8. Stagger "
        "lute dyads slightly and play their upper notes softer. Leave the pedal up in the "
        "busy market section. "
        + _PIANO_PEDAL
        + "Use that brief pedal only on cadential piano chords.",
    ),
    Template(
        id="wayfarer-dungeon",
        name="Wayfarer Dungeon Passages",
        summary="Dungeon passages in 5/4: a drone-and-toll intro, a low bassoon over "
        "tremolo strings and contrabass, a timpani heartbeat, distant voices in a hollow "
        "chamber break, and an exit that leaves room for the loop.",
        mood="uneasy, hollow, watchful",
        setting="underground passages, flooded stone vaults, abandoned mines",
        tempo_range=(52, 72),
        default_tempo=62,
        meter=(5, 4),
        mode="phrygian",
        default_tonic="D",
        alternative_modes=("aeolian", "locrian"),
        parts=(
            _part(
                "melody",
                "bassoon",
                "Bassoon",
                "retro.bassoon",
                -6,
                0.14,
                1,
                "Two- or three-note fragments that approach the tonic from the flat second; "
                "one fragment per bar at most.",
                low=42,
                high=64,
            ),
            _part(
                "pad",
                "tremolo",
                "Tremolo Strings",
                "retro.tremolo_strings",
                -14,
                -0.2,
                2,
                "Enter softly on the second half of the bar with a slowly fading dyad.",
                low=46,
                high=70,
            ),
            _part(
                "countermelody",
                "bells",
                "Tubular Bells",
                "retro.tubular_bells",
                -17,
                0.33,
                1,
                "Toll once after the bassoon falls silent; leave the next bar free of bells.",
                low=60,
                high=72,
            ),
            _part(
                "pad",
                "voices",
                "Distant Voices",
                "retro.voice_oohs",
                -16,
                0.25,
                2,
                "Far-off 'ooh' fifths that swell and fade in the chamber and under the "
                "second passage.",
                low=50,
                high=69,
            ),
            _part(
                "bass",
                "bass",
                "Contrabass",
                "retro.contrabass",
                -10,
                0.0,
                1,
                "Sustained roots with gaps between them; lead into each new chord by a half step.",
                low=30,
                high=46,
            ),
            _part(
                "percussion",
                "timpani",
                "Timpani",
                "retro.timpani",
                -13,
                0.0,
                1,
                "A soft heartbeat on the root: beats one and four (the 3+2 grouping).",
                low=40,
                high=50,
            ),
        ),
        form=(
            SectionPlan(
                "Intro",
                4,
                ("i", "i", "bII", "i"),
                "Contrabass drone and tremolo expose the 3+2 pulse; a bell tolls at bar 3.",
                layers=(
                    _rest("bassoon"),
                    _rest("voices"),
                    _rest("timpani"),
                    _enter("bells", 3, "a single toll"),
                ),
            ),
            SectionPlan(
                "Depths",
                8,
                ("i", "bII", "i", "iv", "bII", "i", "iv", "bII"),
                "Bassoon fragments answer each other from farther apart; the heartbeat starts.",
                layers=(_rest("voices"), _enter("timpani", 3, "the heartbeat")),
            ),
            SectionPlan(
                "Chamber",
                4,
                ("iv", "iv", "bII", "bII"),
                "The bassoon rests: distant voices and the heartbeat in a hollow room.",
                layers=(_rest("bassoon"), _rest("tremolo")),
            ),
            SectionPlan(
                "Depths'",
                8,
                ("i", "bII", "iv", "i", "bII", "i", "iv", "bII"),
                "The fragments return a little louder; the voices hold under them, then fade.",
                layers=(_exit("voices", 5),),
            ),
            SectionPlan(
                "Exit",
                4,
                ("iv", "i", "bII", "bII"),
                "Fade the strings and leave the final two beats open for the loop.",
                layers=(_rest("voices"), _exit("timpani", 3)),
            ),
        ),
        loop=True,
        percussion_allowed=False,
        melody="Group the five beats 3+2. Occasionally delay a bassoon reply until the "
        "fourth beat so the space between calls varies.",
        accompaniment="Keep the drone, tremolo and voices out of the bassoon's active "
        "register; the heartbeat stays soft.",
        dos=(
            "Open with drone and a single toll before the bassoon",
            "Let silence separate the tolls",
            "Lead the bass into each chord by a half step",
            "Taper the drone early at the seam",
        ),
        donts=(
            "Avoid dense ostinatos and bright cadences",
            _HIGH,
            _ORIGINAL,
        ),
        patterns={
            "bassoon fragment (ticks)": "Bar of 4800: two or three notes from 0 or 2880 "
            "(about 700 each), b2 falling to the root.",
            "tremolo (ticks)": "A dyad from 2880 to about 4700, swelling then fading.",
            "timpani heartbeat (ticks)": "Root at 0 and 2880, about 600 each, soft.",
            "bells (ticks)": "One toll at 0 of a bar after the bassoon rests (about 2000).",
            "bass (ticks)": "Root from 0 for about 3800; a half-step approach at 4320 when "
            "the chord changes.",
        },
        expression="On bassoon, use humanize_notes (timing_ticks 12, breath_ticks 220) and "
        "shape_expression (base 72, peak 98, swell 12, vibrato_depth 8). Let each response "
        "end with a softer release. Draw a slow CC11 rise then fade on the tremolo strings "
        "and voices. Keep CC64 up throughout and use the bell's natural decay between "
        "sparse strikes.",
    ),
    Template(
        id="wayfarer-forest",
        name="Wayfarer Forest Trails",
        summary="Forest trails in 6/8: a harp-and-celesta intro, an airy flute over ringing "
        "harp figures, a viola that answers in the clearing, a glade break without the "
        "flute, and a turn back into the loop.",
        mood="curious, leafy, quietly magical",
        setting="forest paths, woodcutting clearings, hidden groves",
        tempo_range=(72, 94),
        default_tempo=82,
        meter=(6, 8),
        mode="dorian",
        default_tonic="A",
        alternative_modes=("aeolian", "mixolydian"),
        parts=(
            _part(
                "melody",
                "flute",
                "Wooden Flute",
                "retro.wooden_flute",
                -4,
                0.14,
                1,
                "Airy three-note calls answered by a longer note; rest between calls. Stay "
                "at or below C6.",
                low=65,
                high=84,
            ),
            _part(
                "accompaniment",
                "harp",
                "Harp",
                "retro.harp",
                -10,
                -0.27,
                3,
                "Break each chord upward, often omitting the sixth eighth; notes ring until "
                "plucked again.",
                low=45,
                high=76,
            ),
            _part(
                "countermelody",
                "viola",
                "Viola",
                "retro.viola",
                -12,
                0.24,
                1,
                "Answer at phrase ends. Start low and climb only in the clearing.",
                low=50,
                high=71,
            ),
            _part(
                "accompaniment",
                "celesta",
                "Celesta",
                "retro.celesta",
                -15,
                0.35,
                1,
                "Sparkles: two or three soft notes on the dotted beats in the intro and the glade.",
                low=72,
                high=84,
            ),
            _part(
                "bass",
                "cello",
                "Cello",
                "retro.cello",
                -13,
                0.0,
                1,
                "Roots in the low register on the dotted beat, walking by step into new "
                "chords; occasionally a whole bar empty.",
                low=36,
                high=55,
            ),
        ),
        form=(
            SectionPlan(
                "Intro",
                4,
                ("i", "IV", "i", "IV"),
                "Harp ripple and celesta sparkles; the cello steps in at bar 3.",
                layers=(_rest("flute"), _rest("viola"), _enter("cello", 3)),
            ),
            SectionPlan(
                "Path",
                8,
                ("i", "IV", "bVII", "i", "i", "IV", "bIII", "bVII"),
                "Flute calls against the uneven harp ripple.",
                layers=(_rest("viola"), _exit("celesta", 2)),
            ),
            SectionPlan(
                "Clearing",
                8,
                ("bIII", "IV", "i", "IV", "bIII", "bVII", "IV", "v"),
                "A little louder: the viola answers and the flute shows the raised sixth.",
                layers=(_rest("celesta"),),
            ),
            SectionPlan(
                "Glade",
                4,
                ("bIII", "IV", "bVII", "i"),
                "The flute rests: celesta and viola share a short tune over the harp.",
                layers=(_rest("flute"),),
            ),
            SectionPlan(
                "Path Return",
                8,
                ("i", "IV", "bVII", "i", "bIII", "IV", "i", "bVII"),
                "The path winds back into shade; the viola drops out halfway.",
                layers=(_rest("celesta"), _exit("viola", 5)),
            ),
            SectionPlan(
                "Turn",
                2,
                ("IV", "bVII"),
                "Harp and flute rise gently into bar 1 of the loop.",
                layers=(_rest("viola"), _rest("celesta")),
            ),
        ),
        loop=True,
        percussion_allowed=False,
        melody="Let long notes arrive after brief pickups. Use the Dorian sixth in the "
        "middle of the phrase, with softer stepwise descents into rests.",
        accompaniment="Harp and cello carry the pulse with room for the viola's replies and "
        "the celesta's sparkles.",
        dos=(
            "Open with harp and celesta before the flute",
            "Let every harp note ring until it is plucked again",
            "Rest a full dotted beat between some flute calls",
            "Vary arpeggio accents",
        ),
        donts=(
            "Avoid continuous winds or pad chords",
            "Don't let the flute and viola play tunes at the same time",
            _HIGH,
            _ORIGINAL,
        ),
        patterns={
            "flute call (ticks)": "Bar of 2880: eighths at 0, 480, 960, then a long note "
            "from 1440 (about 1300); the next bar answers it lower.",
            "harp ripple (ticks)": "Eighths at 0, 480, 960, 1440, 1920 rising, the sixth "
            "eighth (2400) often left out; each rings to the bar end.",
            "cello (ticks)": "Root at 0 (about 1300); a step toward the next root at 1440 "
            "when the chord changes.",
            "celesta (ticks)": "Soft notes at 0 and 1440, sometimes 1920.",
            "viola answer (ticks)": "From 1440 of a phrase's last bar, two or three notes.",
        },
        expression="On flute, use humanize_notes (legato 0.9, timing_ticks 10, "
        "breath_ticks 200), then shape_expression with a quiet swell and delayed vibrato on "
        "longer notes. When a sampled flute is selected, start with release_seconds 0.45. "
        "Shape the viola reply in one swell and pull it back before the flute returns. Use "
        "light velocity changes and natural decay for harp and celesta. Leave CC64 up on "
        "winds and bowed parts.",
    ),
    Template(
        id="wayfarer-harbor",
        name="Wayfarer Working Harbor",
        summary="A rolling 12/8 harbor tune: a pizzicato-and-bass intro with a hand drum, "
        "an accordion call answered by marimba, a ship's bell, a pier break where the "
        "marimba takes the tune, and a turn back to the dock.",
        mood="outgoing, playful, salt-air adventure",
        setting="ferry docks, coastal warehouses, an island embarkation point",
        tempo_range=(106, 134),
        default_tempo=120,
        meter=(12, 8),
        mode="mixolydian",
        default_tonic="C",
        alternative_modes=("ionian", "dorian"),
        parts=(
            _part(
                "melody",
                "accordion",
                "Accordion",
                "retro.accordion",
                -5,
                0.08,
                1,
                "Lift off the dotted beats with short calls followed by a longer falling reply.",
                low=55,
                high=82,
            ),
            _part(
                "accompaniment",
                "pizz",
                "Pizzicato Strings",
                "retro.pizzicato",
                -10,
                -0.24,
                2,
                "Answer the bass on the last eighth of beats two and four.",
                low=48,
                high=72,
            ),
            _part(
                "countermelody",
                "marimba",
                "Marimba",
                "retro.marimba",
                -13,
                0.27,
                2,
                "A pair of soft taps when accordion phrases end; the tune on the pier.",
                low=58,
                high=83,
            ),
            _part(
                "percussion",
                "bell",
                "Ship's Bell",
                "retro.tubular_bells",
                -18,
                0.35,
                1,
                "Two strokes on the root at the start of the dock sections.",
                low=60,
                high=72,
            ),
            _part(
                "bass",
                "bass",
                "Acoustic Bass",
                "retro.acoustic_bass",
                -10,
                0.0,
                1,
                "Roots on one, lighter fifths on three, walking pickups into new chords.",
                low=31,
                high=51,
            ),
            _part(
                "percussion",
                "drums",
                "Hand Drum",
                "gm.drums",
                -14,
                0.15,
                1,
                "GM drum kit: low conga 64 on the dotted beats one and three, tambourine 54 "
                "on two and four.",
                low=54,
                high=64,
            ),
        ),
        form=(
            SectionPlan(
                "Intro",
                2,
                ("I", "bVII"),
                "Pizzicato and bass set the dotted swing; the hand drum joins at bar 2.",
                layers=(
                    _rest("accordion"),
                    _rest("marimba"),
                    _rest("bell"),
                    _enter("drums", 2),
                ),
            ),
            SectionPlan(
                "Dock",
                8,
                ("I", "bVII", "IV", "I", "I", "bVII", "ii", "V"),
                "The accordion call; the ship's bell rings at the start.",
            ),
            SectionPlan(
                "Ferry",
                8,
                ("IV", "I", "bVII", "IV", "ii", "I", "bVII", "V"),
                "Louder: the marimba replies more as the accordion pulls back.",
                layers=(_rest("bell"),),
            ),
            SectionPlan(
                "Pier",
                4,
                ("ii", "V", "IV", "V"),
                "The accordion rests: the marimba carries the tune over pizzicato and bass.",
                layers=(_rest("accordion"), _rest("bell")),
            ),
            SectionPlan(
                "Back at Dock",
                8,
                ("I", "bVII", "IV", "I", "ii", "IV", "I", "V"),
                "The opening groove returns, bell and all.",
            ),
            SectionPlan(
                "Turn",
                2,
                ("IV", "V"),
                "A rising accordion pickup and a drum roll back to the dock.",
                layers=(_rest("bell"), _rest("marimba")),
            ),
        ),
        loop=True,
        percussion_allowed=True,
        melody="Use dotted-beat starts, then place the occasional pickup on the third "
        "eighth of the preceding beat. Write different endings for question and answer.",
        accompaniment="Keep the dotted four-beat swing audible through separated bass, "
        "pizzicato and hand drum.",
        dos=(
            "Open with pizzicato, bass and hand drum before the accordion",
            "Accent the first dotted beat over the third",
            "Leave a breath between accordion calls",
            "Walk the bass into each new chord",
            "Fill with the drum at the end of every fourth bar",
        ),
        donts=(
            "Avoid straight-eighth strumming",
            "Don't let the accordion and marimba play tunes at the same time",
            _HIGH,
            _ORIGINAL,
        ),
        patterns={
            "accordion call (ticks)": "Bar of 5760: 0 (1440), 1440 (480), 1920 (960), then a "
            "falling reply from 2880 ending on a long note (about 2400).",
            "bass (ticks)": "Root at 0, 5th at 2880 (about 1200 each); a pickup at 5280 "
            "walking to the next root.",
            "pizzicato (ticks)": "Dyads at 2400 and 5280 (about 300).",
            "hand drum (ticks)": "Conga 64 at 0 and 2880, tambourine 54 at 1440 and 4320; "
            "every fourth bar 64 at 4800, 5040, 5280, 5520.",
            "ship's bell (ticks)": "Root at 0 and 1440 of the section's first bar.",
        },
        expression="Make accordion notes move with bellows-like CC11 swells on held tones "
        "and short gaps before reattacks; humanize timing_ticks 10, phrase_dynamics 10. Keep "
        "attacks near the grid for the bass, with softer velocities on the fifths. Let "
        "marimba taps and the bell decay. Hand drum: humanize timing_ticks 6, "
        "velocity_variation 8. Keep CC64 up throughout.",
    ),
    Template(
        id="wayfarer-village",
        name="Wayfarer Riverside Village",
        summary="A gentle 3/4 waltz for a riverside settlement: a piano-and-music-box "
        "intro, an ocarina tune over soft piano, ringing lute answers, a cello that joins "
        "by the river, a mill break without the ocarina, and a coda into the loop.",
        mood="warm, intimate, quietly nostalgic",
        setting="village lanes, mills, small farms beside a river",
        tempo_range=(74, 96),
        default_tempo=84,
        meter=(3, 4),
        mode="ionian",
        default_tonic="Bb",
        alternative_modes=("mixolydian", "dorian"),
        parts=(
            _part(
                "melody",
                "ocarina",
                "Ocarina",
                "retro.ocarina",
                -6,
                0.13,
                1,
                "A small lilting tune on one hook rhythm (half, quarter; dotted quarter, "
                "eighth, quarter); let the last beat fall away before each pickup. Stay at "
                "or below C6.",
                low=64,
                high=84,
            ),
            _part(
                "accompaniment",
                "piano",
                "Soft Piano",
                "retro.piano",
                -9,
                -0.23,
                4,
                "A low note on one, a split voicing on two, an occasional soft answer on three.",
                low=45,
                high=76,
            ),
            _part(
                "countermelody",
                "lute",
                "Lute",
                "retro.lute",
                -13,
                0.26,
                2,
                "Answer softly from the lower register when the ocarina leaves space; notes "
                "ring until plucked again. The tune in the mill break.",
                low=43,
                high=66,
            ),
            _part(
                "accompaniment",
                "musicbox",
                "Music Box",
                "retro.music_box",
                -15,
                0.3,
                1,
                "A soft quarter-note line in the intro and coda only.",
                low=72,
                high=84,
            ),
            _part(
                "bass",
                "cello",
                "Cello",
                "retro.cello",
                -14,
                0.0,
                1,
                "Connect adjacent roots with single notes; enters by the river.",
                low=36,
                high=53,
            ),
        ),
        form=(
            SectionPlan(
                "Intro",
                4,
                ("I", "IV", "ii", "V"),
                "Soft piano waltz and a music-box line; the tune waits.",
                layers=(_rest("ocarina"), _rest("lute"), _rest("cello")),
            ),
            SectionPlan(
                "Village",
                8,
                ("I", "IV", "I", "V", "I", "vi", "IV", "V"),
                "The ocarina sings over separated piano voicings; the lute answers.",
                layers=(_rest("musicbox"), _rest("cello")),
            ),
            SectionPlan(
                "River",
                8,
                ("vi", "iii", "IV", "I", "ii", "vi", "IV", "V"),
                "The cello joins and the ocarina uses longer notes; a little louder.",
                layers=(_rest("musicbox"), _enter("cello", 2)),
            ),
            SectionPlan(
                "Mill",
                4,
                ("vi", "IV", "ii", "V"),
                "The ocarina rests: the lute plays the tune over piano and cello.",
                layers=(_rest("ocarina"), _rest("musicbox")),
            ),
            SectionPlan(
                "Home",
                8,
                ("I", "IV", "I", "V", "vi", "ii", "I", "V"),
                "The tune returns; the cello leaves for the last bars.",
                layers=(_rest("musicbox"), _exit("cello", 7)),
            ),
            SectionPlan(
                "Coda",
                2,
                ("IV", "V"),
                "The music box over held piano chords, leading back to the opening.",
                layers=(_rest("ocarina"), _rest("cello"), _rest("lute")),
            ),
        ),
        loop=True,
        percussion_allowed=False,
        melody="Answer a rising two-bar phrase with a descending one. Leave beat three empty "
        "at the end of alternate phrases.",
        accompaniment="Open piano voicings; the lute answers stay separate from them.",
        dos=(
            "Open with piano and music box before the ocarina",
            "Let a few upper piano tones ring into the next beat",
            "Let the lute ring until plucked again",
            "Keep each reply softer than the tune",
        ),
        donts=(
            "Avoid pedaling across moving bass lines",
            _HIGH,
            _ORIGINAL,
        ),
        patterns={
            "ocarina hook (ticks)": "Bar of 2880: 0 (1920), 1920 (960); answer bar 0 "
            "(1440), 1440 (480), 1920 (900).",
            "piano waltz (ticks)": "Low note at 0 (about 900), split voicing at 960 "
            "(about 800), an occasional soft note at 1920.",
            "lute answer (ticks)": "Two or three notes from 1920 of the ocarina's long "
            "note, each ringing to the bar end.",
            "cello (ticks)": "Root at 0 (about 2700); a passing note at 1920 into a new chord.",
            "music box (ticks)": "Quarters at 0, 960, 1920 (about 800).",
        },
        expression="Keep a soft, unequal waltz pulse on piano and give the ocarina a clear "
        "breath and a small expression arc at each turn (humanize timing_ticks 10, "
        "breath_ticks 160; shape_expression vibrato_depth 20). "
        + _PIANO_PEDAL
        + "Pedal the still harmonies in Village and leave it up under the moving cello in "
        "River. Taper cello notes with CC11 and preserve gaps in the lute replies.",
    ),
    Template(
        id="wayfarer-desert",
        name="Wayfarer Desert Caravan",
        summary="An uneven 7/8 caravan: a dulcimer-and-drum intro with a sitar drone, an "
        "oboe call over the 2+2+3 groove, a viola that builds at the gate, a camp break "
        "where the sitar takes the tune, and a turn back onto the road.",
        mood="sunlit, restless, far from home",
        setting="desert roads, ancient sandstone gates, a caravan camp",
        tempo_range=(86, 108),
        default_tempo=96,
        meter=(7, 8),
        mode="phrygian",
        default_tonic="A",
        alternative_modes=("dorian", "aeolian"),
        parts=(
            _part(
                "melody",
                "oboe",
                "Oboe",
                "retro.oboe",
                -5,
                0.14,
                1,
                "A held tone against an uneven pickup; lean into the flat second sparingly.",
                low=60,
                high=83,
            ),
            _part(
                "accompaniment",
                "dulcimer",
                "Dulcimer",
                "retro.dulcimer",
                -10,
                -0.25,
                2,
                "Mark the groups of two, two and three eighths with alternating strokes.",
                low=50,
                high=78,
            ),
            _part(
                "accompaniment",
                "sitar",
                "Sitar",
                "retro.sitar",
                -13,
                0.3,
                2,
                "A root-and-fifth drone plucked on group one; the tune in the camp break.",
                low=48,
                high=72,
            ),
            _part(
                "pad",
                "viola",
                "Viola",
                "retro.viola",
                -14,
                0.25,
                2,
                "Swell into a fifth behind longer oboe notes, then thin out before the next bar.",
                low=48,
                high=68,
            ),
            _part(
                "bass",
                "bass",
                "Contrabass",
                "retro.contrabass",
                -12,
                0.0,
                1,
                "A short root on group one and an occasional fifth on the last group.",
                low=30,
                high=48,
            ),
            _part(
                "percussion",
                "drums",
                "Hand Drums",
                "gm.drums",
                -13,
                0.0,
                1,
                "GM drum kit: low conga 64 on group one, high bongo 60 and low bongo 61 on "
                "the others, tambourine 54 on the long group.",
                low=54,
                high=64,
            ),
        ),
        form=(
            SectionPlan(
                "Intro",
                4,
                ("i", "bII", "i", "bII"),
                "Dulcimer strokes and hand drums set 2+2+3; the sitar drone joins at bar 3.",
                layers=(
                    _rest("oboe"),
                    _rest("viola"),
                    _enter("sitar", 3, "the drone"),
                ),
            ),
            SectionPlan(
                "Road",
                8,
                ("i", "bII", "i", "bVII", "iv", "bII", "i", "i"),
                "Isolated oboe calls over the uneven groove.",
                layers=(_rest("viola"),),
            ),
            SectionPlan(
                "Gate",
                8,
                ("iv", "bII", "bIII", "iv", "i", "bVII", "bII", "bII"),
                "Louder: the viola builds through the gate and the oboe moves higher.",
            ),
            SectionPlan(
                "Camp",
                4,
                ("iv", "bII", "iv", "bII"),
                "The oboe rests: the sitar plays the tune over dulcimer and drums.",
                layers=(_rest("oboe"), _rest("viola")),
            ),
            SectionPlan(
                "Road'",
                8,
                ("i", "iv", "bII", "i", "iv", "bVII", "i", "bII"),
                "Shorter answers; the viola fades out halfway.",
                layers=(_exit("viola", 5),),
            ),
            SectionPlan(
                "Turn",
                2,
                ("bVII", "bII"),
                "A drum fill and a rising oboe pickup back onto the road.",
                layers=(_rest("viola"),),
            ),
        ),
        loop=True,
        percussion_allowed=True,
        melody="Place the strongest note at the first group. Move a soft pickup into the "
        "long third group and let the answering phrase start higher.",
        accompaniment="Accents make the 2+2+3 meter audible with only a few attacks per bar.",
        dos=(
            "Open with dulcimer and drums before the oboe",
            "Give the three-note group room to breathe",
            "Fill with the drums at the end of every fourth bar",
            "Fade the viola before the loop",
        ),
        donts=(
            "Avoid repeating the same ornament in every call",
            "Don't let the oboe and sitar play tunes at the same time",
            _HIGH,
            _ORIGINAL,
        ),
        patterns={
            "groups (ticks)": "Bar of 3360: group one at 0, group two at 960, the long "
            "group three at 1920.",
            "oboe call (ticks)": "A held tone from 0 (about 1800), a soft pickup at 2880 "
            "into the next bar.",
            "dulcimer (ticks)": "Strokes at 0, 480, 960, 1440, 1920, 2400, 2880; accent 0, "
            "960 and 1920.",
            "hand drums (ticks)": "Conga 64 at 0, bongo 60 at 960, tambourine 54 at 1920, "
            "bongo 61 at 2400; every fourth bar 60, 61, 60, 61 at 1920, 2160, 2400, 2640.",
            "bass (ticks)": "Root at 0 (about 700); a fifth at 1920 now and then.",
        },
        expression="Accent the first dulcimer stroke and vary the second stroke's velocity. "
        "Keep CC64 up so the hammered and plucked notes decay around the uneven pulse. On "
        "oboe, use humanize_notes (timing_ticks 9, breath_ticks 180), then shape_expression "
        "with a late peak on the longest tones. Fade the viola with CC11 before each new "
        "oboe call. Hand drums: humanize timing_ticks 5, velocity_variation 8.",
    ),
)
