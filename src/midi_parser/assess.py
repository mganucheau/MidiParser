"""MidiBrowser-style note assessment (Pass 2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import mido


@dataclass
class NoteEvent:
    note_number: int
    velocity: int
    channel: int  # 1–16
    start_beat: float
    length_beats: float


@dataclass
class MidiClip:
    name: str
    file_path: str
    bpm: float = 120.0
    time_sig_num: int = 4
    time_sig_den: int = 4
    length_beats: float = 0.0
    notes: list[NoteEvent] = field(default_factory=list)


def parse_midi_file(path: Path | str) -> MidiClip:
    """Parse a MIDI file into notes + tempo/time-sig metadata."""
    path = Path(path)
    clip = MidiClip(name=path.stem, file_path=str(path.resolve()))

    try:
        mid = mido.MidiFile(path)
    except Exception:
        return clip

    ticks_per_beat = mid.ticks_per_beat or 480
    bpm = 120.0
    time_sig_num, time_sig_den = 4, 4

    # Tempo / time sig from merged timeline (track 0 often holds meta)
    for track in mid.tracks:
        for msg in track:
            if msg.type == "set_tempo" and bpm == 120.0:
                bpm = mido.tempo2bpm(msg.tempo)
            elif msg.type == "time_signature" and time_sig_num == 4 and time_sig_den == 4:
                time_sig_num = max(1, msg.numerator)
                time_sig_den = max(1, msg.denominator)

    clip.bpm = bpm
    clip.time_sig_num = time_sig_num
    clip.time_sig_den = time_sig_den

    # Collect note ons/offs across all tracks with absolute tick times
    abs_ticks = 0
    # Per track absolute time
    open_notes: dict[tuple[int, int], list[tuple[int, int]]] = {}
    # key: (channel, note) -> stack of (start_tick, velocity)
    notes: list[NoteEvent] = []
    max_tick = 0

    for track in mid.tracks:
        abs_ticks = 0
        for msg in track:
            abs_ticks += msg.time
            max_tick = max(max_tick, abs_ticks)
            if msg.type == "note_on" and msg.velocity > 0:
                ch = msg.channel + 1  # mido 0–15 → MIDI 1–16
                key = (ch, msg.note)
                open_notes.setdefault(key, []).append((abs_ticks, msg.velocity))
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                ch = msg.channel + 1
                key = (ch, msg.note)
                stack = open_notes.get(key)
                if not stack:
                    continue
                start_tick, vel = stack.pop()
                length_ticks = max(1, abs_ticks - start_tick)
                notes.append(
                    NoteEvent(
                        note_number=msg.note,
                        velocity=vel,
                        channel=ch,
                        start_beat=start_tick / ticks_per_beat,
                        length_beats=length_ticks / ticks_per_beat,
                    )
                )

    # Close any hanging notes at end of file
    for (ch, note), stack in open_notes.items():
        for start_tick, vel in stack:
            length_ticks = max(1, max_tick - start_tick)
            notes.append(
                NoteEvent(
                    note_number=note,
                    velocity=vel,
                    channel=ch,
                    start_beat=start_tick / ticks_per_beat,
                    length_beats=length_ticks / ticks_per_beat,
                )
            )

    notes.sort(key=lambda n: (n.start_beat, n.note_number))
    clip.notes = notes
    if notes:
        clip.length_beats = max(
            max_tick / ticks_per_beat,
            max(n.start_beat + n.length_beats for n in notes),
        )
    else:
        clip.length_beats = max_tick / ticks_per_beat
    return clip


def _looks_like_arp(notes: list[NoteEvent], max_poly: int, dif_notes: int) -> bool:
    """Lightweight arpeggio detector for monophonic/short stepwise patterns."""
    if max_poly > 1 or dif_notes < 4 or len(notes) < 4:
        return False

    short = sum(1 for n in notes if n.length_beats <= 0.5)
    if short * 2 < len(notes):
        return False

    ordered = sorted(notes, key=lambda n: n.start_beat)
    pitches = [n.note_number for n in ordered]
    span = max(pitches) - min(pitches)
    if span < 7:
        return False

    steps = [pitches[i + 1] - pitches[i] for i in range(len(pitches) - 1)]
    nonzero = [s for s in steps if s != 0]
    if len(nonzero) < 3:
        return False

    # Mostly stepwise (within an octave) and consistently directed or zig-zag
    stepwise = sum(1 for s in nonzero if abs(s) <= 12)
    if stepwise * 4 < len(nonzero) * 3:
        return False

    return True


def assess_clip(clip: MidiClip) -> str:
    """
    Classify a parsed clip into Drums / Bass / Chords / Lead / Arp / Unknown.

    Mirrors MidiBrowser makeStepClip with remapped categories.
    """
    notes = clip.notes
    if not notes:
        return "Unknown"

    any_drum_channel = any(n.channel == 10 for n in notes)
    if any_drum_channel:
        return "Drums"

    pitch_sum = sum(n.note_number for n in notes)
    distinct = {n.note_number for n in notes}
    dif_notes = len(distinct)
    mean_pitch = pitch_sum // len(notes)

    max_poly = 1
    poly_sum = 0.0
    poly_samples = 0
    chord3_hits = 0
    for n in notes:
        active = 0
        for o in notes:
            if o.start_beat <= n.start_beat + 1e-9 and o.start_beat + o.length_beats > n.start_beat + 1e-9:
                active += 1
        max_poly = max(max_poly, active)
        poly_sum += active
        poly_samples += 1
        if active >= 3:
            chord3_hits += 1

    mean_poly = poly_sum / poly_samples if poly_samples else 1.0
    frequent_chords = poly_samples > 0 and chord3_hits * 4 >= poly_samples

    if mean_pitch < 48:
        return "Bass"
    if mean_poly >= 2.5 or frequent_chords:
        return "Chords"

    # Melodic / keys / piano-like
    if _looks_like_arp(notes, max_poly, dif_notes):
        return "Arp"
    return "Lead"


def assess_file(path: Path | str) -> str:
    """Parse and assess a MIDI file path."""
    try:
        clip = parse_midi_file(path)
    except Exception:
        return "Unknown"
    return assess_clip(clip)
