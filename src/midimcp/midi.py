"""Standard MIDI File export (Type 1) and import.

Export layout:

* Track 0 (conductor): title, tempo, time signature, key signature, section markers.
* One named track per score track, on its own channel. Melodic tracks use
  channels 1-9 and 11-16 (1-based); percussion tracks use channel 10. With no
  percussion tracks, nothing is ever written to channel 10.
* Program (and bank select when non-zero), volume (CC7, from gainDb), pan
  (CC10), expression (CC11) precede the notes.
* Automation: expression points become CC11, modulation CC1 (vibrato) and
  pitchBend pitch-wheel messages. Tracks without automation produce exactly the
  bytes they did before automation existed.
* At equal ticks: note-offs, then controller changes, then note-ons (so a swell
  or bend applies to the note starting there); ties break by note ID / lane, so
  the output bytes are deterministic.
"""

from __future__ import annotations

import io
import math
from collections import deque
from dataclasses import dataclass
from typing import Final

import mido

from midimcp.instruments import (
    PERCUSSION_BANK,
    instrument_for_program,
    resolve_instrument,
)
from midimcp.model.score import (
    AUTOMATION_LANES,
    LANE_FIELDS,
    Automation,
    LoopRegion,
    Metadata,
    Meter,
    Note,
    Score,
    Section,
    SoundProfile,
    Timeline,
    Tonality,
    Track,
)
from midimcp.music.theory import (
    MAJOR_KEY_SPELLING,
    parent_major_pitch_class,
    parse_note_name,
    practical_tonic_spelling,
)
from midimcp.music.timing import bpm_to_tempo_us, ticks_per_bar

PERCUSSION_CHANNEL = 9  # 0-based (channel 10)
MELODIC_CHANNELS = tuple(c for c in range(16) if c != PERCUSSION_CHANNEL)


class MidiExportError(ValueError):
    code = "MIDI_EXPORT_FAILED"


class MidiImportError(ValueError):
    code = "MIDI_IMPORT_FAILED"


def gain_db_to_cc7(gain_db: float) -> int:
    """GM volume curve: dB = 40 * log10(cc / 127)."""
    return max(0, min(127, round(127 * 10 ** (gain_db / 40))))


def cc7_to_gain_db(value: int) -> float:
    if value <= 0:
        return -60.0
    return max(-60.0, min(12.0, round(40 * math.log10(value / 127), 2)))


def pan_to_cc10(pan: float) -> int:
    return max(0, min(127, round(64 + pan * 63)))


def cc10_to_pan(value: int) -> float:
    return max(-1.0, min(1.0, round((value - 64) / 63, 3)))


def midi_key_name(score: Score) -> str:
    """Key-signature name mido understands; non-major/minor modes use the parent major."""
    tonality = score.tonality
    if tonality.mode == "ionian":
        return practical_tonic_spelling(tonality.tonic_pitch_class, "ionian")
    if tonality.mode == "aeolian":
        return practical_tonic_spelling(tonality.tonic_pitch_class, "aeolian") + "m"
    return MAJOR_KEY_SPELLING[parent_major_pitch_class(tonality.tonic_pitch_class, tonality.mode)]


def _assign_channels(score: Score, tracks: list[Track]) -> dict[str, int]:
    channels: dict[str, int] = {}
    melodic = iter(MELODIC_CHANNELS)
    for track in tracks:
        if track.is_percussion:
            channels[track.id] = PERCUSSION_CHANNEL
        else:
            try:
                channels[track.id] = next(melodic)
            except StopIteration as exc:
                raise MidiExportError("more than 15 melodic tracks") from exc
    return channels


def _absolute_to_delta(events: list[tuple[int, mido.Message | mido.MetaMessage]]) -> mido.MidiTrack:
    track = mido.MidiTrack()
    last = 0
    for tick, message in events:
        track.append(message.copy(time=tick - last))
        last = tick
    return track


def score_to_midi(
    score: Score, *, include_muted: bool = False, tail_ticks: int = 0
) -> mido.MidiFile:
    """Build a MIDI file. ``tail_ticks`` extends every track's end (render decay tail)."""
    tracks = [t for t in score.tracks if include_muted or not t.mute]
    channels = _assign_channels(score, tracks)
    timeline = score.timeline
    end = timeline.total_ticks + max(0, tail_ticks)

    conductor: list[tuple[int, mido.MetaMessage]] = [
        (0, mido.MetaMessage("track_name", name=score.metadata.title)),
        (0, mido.MetaMessage("set_tempo", tempo=timeline.tempo_us_per_quarter)),
        (
            0,
            mido.MetaMessage(
                "time_signature",
                numerator=timeline.meter.numerator,
                denominator=timeline.meter.denominator,
                clocks_per_click=24,
                notated_32nd_notes_per_beat=8,
            ),
        ),
        (0, mido.MetaMessage("key_signature", key=midi_key_name(score))),
    ]
    for section in sorted(score.sections, key=lambda s: (s.start_tick, s.id)):
        conductor.append((section.start_tick, mido.MetaMessage("marker", text=section.label)))
    conductor.append((end, mido.MetaMessage("end_of_track")))

    midi = mido.MidiFile(type=1, ticks_per_beat=timeline.ppq)
    midi.tracks.append(_absolute_to_delta(conductor))

    for track in tracks:
        channel = channels[track.id]
        instrument = resolve_instrument(track.instrument_id)
        setup: list[tuple[int, mido.BaseMessage]] = [
            (0, mido.MetaMessage("track_name", name=track.name)),
            (0, mido.MetaMessage("instrument_name", name=track.instrument_id)),
        ]
        if not track.is_percussion and instrument.bank:
            setup.append(
                (
                    0,
                    mido.Message(
                        "control_change", channel=channel, control=0, value=instrument.bank >> 7
                    ),
                )
            )
            setup.append(
                (
                    0,
                    mido.Message(
                        "control_change", channel=channel, control=32, value=instrument.bank & 0x7F
                    ),
                )
            )
        setup += [
            (0, mido.Message("program_change", channel=channel, program=instrument.program)),
            (
                0,
                mido.Message(
                    "control_change",
                    channel=channel,
                    control=7,
                    value=gain_db_to_cc7(track.gain_db),
                ),
            ),
            (
                0,
                mido.Message(
                    "control_change", channel=channel, control=10, value=pan_to_cc10(track.pan)
                ),
            ),
            (0, mido.Message("control_change", channel=channel, control=11, value=127)),
        ]
        # (tick, order, key): note-off (0) < controller (1) < note-on (2).
        note_events: list[tuple[int, int, str, mido.Message]] = []
        for lane, points in track.automation.lanes().items():
            for point in points:
                message = _automation_message(lane, channel, point.value)
                note_events.append((point.tick, 1, lane, message))
        for note in track.notes:
            note_events.append(
                (
                    note.start_tick,
                    2,
                    note.id,
                    mido.Message(
                        "note_on", channel=channel, note=note.pitch, velocity=note.velocity
                    ),
                )
            )
            note_events.append(
                (
                    note.end_tick,
                    0,
                    note.id,
                    mido.Message("note_off", channel=channel, note=note.pitch, velocity=0),
                )
            )
        note_events.sort(key=lambda e: (e[0], e[1], e[2]))
        events = setup + [(tick, msg) for tick, _, _, msg in note_events]
        last = max([end] + [tick for tick, _ in events])
        events.append((last, mido.MetaMessage("end_of_track")))
        midi.tracks.append(_absolute_to_delta(events))
    return midi


_LANE_CC: Final = {"expression": 11, "modulation": 1}


def _automation_message(lane: str, channel: int, value: int) -> mido.Message:
    if lane == "pitchBend":
        return mido.Message("pitchwheel", channel=channel, pitch=value)
    return mido.Message("control_change", channel=channel, control=_LANE_CC[lane], value=value)


def export_midi_bytes(score: Score, *, include_muted: bool = False, tail_ticks: int = 0) -> bytes:
    buffer = io.BytesIO()
    score_to_midi(score, include_muted=include_muted, tail_ticks=tail_ticks).save(file=buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------- import


@dataclass
class _TrackState:
    name: str | None = None
    channel: int | None = None
    program: int = 0
    volume: int | None = None
    pan: int | None = None


def import_midi_bytes(
    data: bytes,
    *,
    project_id: str,
    title: str | None = None,
    profile_id: str = "retro-gm-1997-v1",
    bank_id: str = "fluidr3-gm",
) -> Score:
    """Build a score from a Standard MIDI File (Type 0 or 1).

    Uses the first tempo, time signature and key signature found. Notes are
    paired note-on/note-off per channel and pitch in FIFO order. Track IDs and
    note IDs are generated (``track-1``, ``n1`` ...). Tempo changes after the
    first are not supported yet and raise MidiImportError.
    """
    try:
        midi = mido.MidiFile(file=io.BytesIO(data))
    except (OSError, ValueError, EOFError) as exc:
        raise MidiImportError(f"not a readable MIDI file: {exc}") from exc
    if midi.type == 2:
        raise MidiImportError("MIDI type 2 files are not supported")

    tempo: int | None = None
    meter = (4, 4)
    key_name: str | None = None
    song_title = title
    markers: list[tuple[int, str]] = []
    built: list[
        tuple[_TrackState, list[tuple[int, int, int, int]], dict[str, list[tuple[int, int]]]]
    ] = []
    last_tick = 0

    for index, midi_track in enumerate(midi.tracks):
        state = _TrackState()
        open_notes: dict[tuple[int, int], deque[tuple[int, int]]] = {}
        per_channel: dict[int, list[tuple[int, int, int, int]]] = {}
        curves: dict[int, dict[str, list[tuple[int, int]]]] = {}
        tick = 0
        for message in midi_track:
            tick += message.time
            last_tick = max(last_tick, tick)
            kind = message.type
            if kind == "set_tempo":
                if tempo is None:
                    tempo = message.tempo
                elif message.tempo != tempo:
                    raise MidiImportError("tempo changes are not supported yet")
            elif kind == "time_signature" and tick == 0:
                meter = (message.numerator, message.denominator)
            elif kind == "key_signature" and key_name is None:
                key_name = message.key
            elif kind == "track_name":
                if index == 0 and song_title is None:
                    song_title = message.name
                state.name = state.name or message.name
            elif kind == "marker":
                markers.append((tick, message.text))
            elif kind == "program_change":
                state.program = message.program
                state.channel = message.channel
            elif kind == "control_change" and message.control == 7:
                state.volume = message.value
            elif kind == "control_change" and message.control == 10:
                state.pan = message.value
            elif kind == "control_change" and message.control in (1, 11):
                lane = "expression" if message.control == 11 else "modulation"
                curves.setdefault(message.channel, {}).setdefault(lane, []).append(
                    (tick, message.value)
                )
            elif kind == "pitchwheel":
                curves.setdefault(message.channel, {}).setdefault("pitchBend", []).append(
                    (tick, message.pitch)
                )
            elif kind == "note_on" and message.velocity > 0:
                open_notes.setdefault((message.channel, message.note), deque()).append(
                    (tick, message.velocity)
                )
            elif kind in {"note_off", "note_on"}:
                queue = open_notes.get((message.channel, message.note))
                if queue:
                    start, velocity = queue.popleft()
                    if tick > start:
                        per_channel.setdefault(message.channel, []).append(
                            (message.note, start, tick - start, velocity)
                        )
        for channel, notes in sorted(per_channel.items()):
            channel_state = _TrackState(
                name=state.name,
                channel=channel,
                program=state.program,
                volume=state.volume,
                pan=state.pan,
            )
            built.append((channel_state, notes, curves.get(channel, {})))

    tempo = tempo or bpm_to_tempo_us(120)
    numerator, denominator = meter
    if denominator not in (1, 2, 4, 8, 16, 32):
        raise MidiImportError(f"unsupported time signature {numerator}/{denominator}")
    bar = ticks_per_bar(midi.ticks_per_beat, numerator, denominator)
    note_end = max((s + d for _, notes, _ in built for _, s, d, _ in notes), default=0)
    total = max(bar, math.ceil(max(note_end, last_tick) / bar) * bar)

    tracks = []
    counter = 0
    for number, (state, notes, lanes) in enumerate(built, start=1):
        percussion = state.channel == PERCUSSION_CHANNEL
        model_notes = []
        for pitch, start, duration, velocity in sorted(notes, key=lambda n: (n[1], n[0])):
            counter += 1
            model_notes.append(
                Note(
                    id=f"n{counter}",
                    pitch=pitch,
                    start_tick=start,
                    duration_ticks=duration,
                    velocity=velocity,
                )
            )
        tracks.append(
            Track(
                id=f"track-{number}",
                name=(state.name or f"Track {number}")[:100],
                instrument_id=instrument_for_program(state.program, percussion=percussion),
                is_percussion=percussion,
                gain_db=cc7_to_gain_db(state.volume) if state.volume is not None else 0.0,
                pan=cc10_to_pan(state.pan) if state.pan is not None else 0.0,
                notes=model_notes,
                automation=_automation_from_curves(lanes, total),
            )
        )

    sections = []
    ordered = sorted(markers)
    for i, (tick, label) in enumerate(ordered):
        end_tick = ordered[i + 1][0] if i + 1 < len(ordered) else total
        if end_tick > tick:
            sections.append(
                Section(
                    id=f"section-{i + 1}",
                    label=label[:50] or f"S{i + 1}",
                    start_tick=tick,
                    end_tick=end_tick,
                )
            )

    tonality = _tonality_from_key(key_name)
    return Score(
        project_id=project_id,
        metadata=Metadata(title=(song_title or "Imported MIDI")[:200] or "Imported MIDI"),
        timeline=Timeline(
            ppq=midi.ticks_per_beat,
            tempo_us_per_quarter=tempo,
            meter=Meter(numerator=numerator, denominator=denominator),
            total_ticks=total,
            loop=LoopRegion(enabled=False),
        ),
        tonality=tonality,
        sound_profile=SoundProfile(profile_id=profile_id, bank_id=bank_id),
        tracks=tracks,
        sections=sections,
    )


def _automation_from_curves(lanes: dict[str, list[tuple[int, int]]], total: int) -> Automation:
    """Keep only real changes: drop values that repeat the previous (or resting) value,
    so the CC11=127 every exporter writes at tick 0 does not become a curve."""
    data: dict[str, list[dict[str, int]]] = {}
    for lane, events in lanes.items():
        current = AUTOMATION_LANES[lane][3]
        by_tick: dict[int, int] = {}
        for tick, value in events:
            if tick < total:
                by_tick[tick] = value
        points = []
        for tick in sorted(by_tick):
            if by_tick[tick] != current:
                points.append({"tick": tick, "value": by_tick[tick]})
                current = by_tick[tick]
        data[LANE_FIELDS[lane]] = points
    return Automation.model_validate(data)


def _tonality_from_key(key_name: str | None) -> Tonality:
    if not key_name:
        return Tonality(tonic_pitch_class=0, mode="ionian", display_spelling="C")
    minor = key_name.endswith("m")
    tonic = key_name[:-1] if minor else key_name
    mode = "aeolian" if minor else "ionian"
    pc = parse_note_name(tonic)
    return Tonality(
        tonic_pitch_class=pc,
        mode=mode,
        requested_spelling=tonic,
        display_spelling=practical_tonic_spelling(pc, mode),
    )


__all__ = [
    "PERCUSSION_BANK",
    "MidiExportError",
    "MidiImportError",
    "export_midi_bytes",
    "import_midi_bytes",
    "score_to_midi",
]
