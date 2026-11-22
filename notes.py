"""Note muzicale, instrumente și calcule în cents (sistemul temperat, A4 reglabil)."""

from __future__ import annotations

from dataclasses import dataclass
from math import log2

A4_MIDI = 69
DEFAULT_A4_HZ = 440.0
IN_TUNE_CENTS = 5.0
"""Toleranța „acordat”. Urechea abia distinge ~5 cents; tunerele de telefon folosesc 3–5."""

NOTE_NAMES: tuple[str, ...] = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def hz_to_midi(frequency_hz: float, a4_hz: float = DEFAULT_A4_HZ) -> float:
    """Hz → număr MIDI fracționar (69.0 = A4)."""
    if frequency_hz <= 0:
        raise ValueError("frecvența trebuie să fie pozitivă")
    return A4_MIDI + 12.0 * log2(frequency_hz / a4_hz)


def midi_to_hz(midi: float, a4_hz: float = DEFAULT_A4_HZ) -> float:
    return a4_hz * 2.0 ** ((midi - A4_MIDI) / 12.0)


def cents_off(frequency_hz: float, target_hz: float) -> float:
    """Abaterea în cents (100 = un semiton). Negativ = prea jos."""
    if frequency_hz <= 0 or target_hz <= 0:
        raise ValueError("frecvențele trebuie să fie pozitive")
    return 1200.0 * log2(frequency_hz / target_hz)


def in_tune(cents: float, tolerance: float = IN_TUNE_CENTS) -> bool:
    return abs(cents) <= tolerance


@dataclass(frozen=True)
class Note:
    """O notă cromatică, identificată prin numărul MIDI."""

    midi: int

    @property
    def name(self) -> str:
        return NOTE_NAMES[self.midi % 12]

    @property
    def letter(self) -> str:
        return self.name[0]

    @property
    def accidental(self) -> str:
        return self.name[1:]

    @property
    def octave(self) -> int:
        return self.midi // 12 - 1

    @property
    def label(self) -> str:
        return f"{self.name}{self.octave}"

    def frequency(self, a4_hz: float = DEFAULT_A4_HZ) -> float:
        return midi_to_hz(self.midi, a4_hz)


def nearest_note(frequency_hz: float, a4_hz: float = DEFAULT_A4_HZ) -> Note:
    return Note(round(hz_to_midi(frequency_hz, a4_hz)))


@dataclass(frozen=True)
class InstrumentString:
    """O coardă. `number` 1 = cea mai subțire, ca în tabulaturi."""

    number: int
    note: Note

    def frequency(self, a4_hz: float = DEFAULT_A4_HZ) -> float:
        return self.note.frequency(a4_hz)


@dataclass(frozen=True)
class Instrument:
    key: str
    label: str
    strings: tuple[InstrumentString, ...]
    """În ordinea de pe instrument, de la coarda de sus (cea mai groasă) în jos."""
    fmin: float
    fmax: float
    """Plaja de frecvențe în care caută detectorul (cu rezervă pentru Drop D)."""

    def string(self, number: int) -> InstrumentString | None:
        return next((s for s in self.strings if s.number == number), None)

    def nearest_string(self, frequency_hz: float, a4_hz: float = DEFAULT_A4_HZ) -> InstrumentString:
        """Coarda cea mai apropiată, ca distanță muzicală (cents), nu în Hz."""
        return min(self.strings, key=lambda s: abs(cents_off(frequency_hz, s.frequency(a4_hz))))


def _strings(*midis: int) -> tuple[InstrumentString, ...]:
    count = len(midis)
    return tuple(InstrumentString(count - i, Note(m)) for i, m in enumerate(midis))


GUITAR = Instrument("guitar", "Chitară", _strings(40, 45, 50, 55, 59, 64), fmin=70.0, fmax=1000.0)
"""E2 A2 D3 G3 B3 E4"""

BASS = Instrument("bass", "Bass", _strings(28, 33, 38, 43), fmin=35.0, fmax=400.0)
"""E1 A1 D2 G2"""

UKULELE = Instrument("ukulele", "Ukulele", _strings(67, 60, 64, 69), fmin=200.0, fmax=1200.0)
"""G4 C4 E4 A4 (acordaj re-entrant standard)"""

INSTRUMENTS: tuple[Instrument, ...] = (GUITAR, BASS, UKULELE)
