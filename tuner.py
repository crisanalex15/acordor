"""Logica tunerului, fără interfață: mod de lucru, coarda țintă, cents, corzi acordate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from notes import (
    DEFAULT_A4_HZ,
    GUITAR,
    Instrument,
    InstrumentString,
    Note,
    cents_off,
    in_tune,
    nearest_note,
)
from pitch import PitchEstimate
from tracker import PitchTracker, TrackedPitch

A4_RANGE = (415.0, 466.0)
TUNED_AFTER_SECONDS = 0.6
"""Cât trebuie ținută coarda în toleranță ca să fie bifată „acordată”."""
UNTUNED_CENTS = 15.0
"""Peste abaterea asta (citire stabilă) bifa dispare."""
WRONG_STRING_CENTS = 150.0


class Mode(Enum):
    AUTO = "auto"
    """Recunoaște singur coarda cea mai apropiată."""
    CHROMATIC = "chromatic"
    """Orice notă, față de cel mai apropiat semiton."""
    STRING = "string"
    """Coarda aleasă manual."""


class Hint(Enum):
    IDLE = "idle"
    IN_TUNE = "in_tune"
    TOO_LOW = "too_low"
    TOO_HIGH = "too_high"
    WRONG_STRING = "wrong_string"


@dataclass(frozen=True)
class Reading:
    frequency: float
    heard: Note
    """Nota cromatică cea mai apropiată de ce se aude."""
    target: Note
    target_hz: float
    target_string: InstrumentString | None
    cents: float
    holding: bool
    stable: bool

    @property
    def in_tune(self) -> bool:
        return in_tune(self.cents)


class TunerModel:
    def __init__(self, instrument: Instrument = GUITAR) -> None:
        self.instrument = instrument
        self.mode = Mode.AUTO
        self.selected: InstrumentString | None = None
        self.a4 = DEFAULT_A4_HZ
        self.reading: Reading | None = None
        self.tuned: set[int] = set()
        self._tracker = PitchTracker()
        self._candidate: int | None = None
        self._candidate_since = 0.0

    # ---- comenzi -------------------------------------------------------

    def set_instrument(self, instrument: Instrument) -> None:
        if instrument.key == self.instrument.key:
            return
        self.instrument = instrument
        self.mode = Mode.AUTO
        self.selected = None
        self.tuned.clear()
        self._reset_reading()

    def set_auto(self) -> None:
        self.mode = Mode.AUTO
        self.selected = None

    def set_chromatic(self) -> None:
        self.mode = Mode.CHROMATIC
        self.selected = None

    def select_string(self, number: int) -> None:
        string = self.instrument.string(number)
        if string is None:
            return
        if self.mode is Mode.STRING and self.selected == string:
            self.set_auto()  # al doilea click pe aceeași coardă revine la Auto
            return
        self.mode = Mode.STRING
        self.selected = string

    def nudge_a4(self, step: float) -> None:
        low, high = A4_RANGE
        self.a4 = min(high, max(low, round(self.a4 + step)))
        self.tuned.clear()

    # ---- semnal ---------------------------------------------------------

    def feed(self, estimate: PitchEstimate | None, now: float) -> None:
        """O analiză nouă a venit de la microfon."""
        self._refresh(self._tracker.update(estimate, now), now)

    def tick(self, now: float) -> None:
        """Nu a venit audio nou; doar lasă timpul să treacă (expirarea notei ținute)."""
        self._refresh(self._tracker.current(now), now)

    @property
    def hint(self) -> Hint:
        r = self.reading
        if r is None:
            return Hint.IDLE
        if self.mode is Mode.STRING and abs(r.cents) > WRONG_STRING_CENTS:
            return Hint.WRONG_STRING
        if r.in_tune:
            return Hint.IN_TUNE
        return Hint.TOO_LOW if r.cents < 0 else Hint.TOO_HIGH

    # ---- intern ---------------------------------------------------------

    def _reset_reading(self) -> None:
        self._tracker.reset()
        self.reading = None
        self._candidate = None

    def _refresh(self, tracked: TrackedPitch | None, now: float) -> None:
        if tracked is None:
            self.reading = None
            self._candidate = None
            return

        freq = tracked.frequency
        heard = nearest_note(freq, self.a4)
        string: InstrumentString | None
        if self.mode is Mode.CHROMATIC:
            string, target = None, heard
        elif self.mode is Mode.STRING and self.selected is not None:
            string, target = self.selected, self.selected.note
        else:
            string = self.instrument.nearest_string(freq, self.a4)
            target = string.note

        target_hz = target.frequency(self.a4)
        self.reading = Reading(
            frequency=freq,
            heard=heard,
            target=target,
            target_hz=target_hz,
            target_string=string,
            cents=cents_off(freq, target_hz),
            holding=tracked.holding,
            stable=tracked.stable,
        )
        self._update_tuned(self.reading, now)

    def _update_tuned(self, r: Reading, now: float) -> None:
        if r.target_string is None or not r.stable:
            self._candidate = None
            return
        number = r.target_string.number
        if abs(r.cents) > UNTUNED_CENTS:
            self.tuned.discard(number)
        if not r.in_tune:
            self._candidate = None
        elif self._candidate != number:
            self._candidate, self._candidate_since = number, now
        elif now - self._candidate_since >= TUNED_AFTER_SECONDS:
            self.tuned.add(number)
