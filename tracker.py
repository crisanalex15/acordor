"""
Stabilizarea citirilor brute, ca acul să nu tremure.

Trei etape, aplicate pe scara logaritmică (cents), unde distanțele
muzicale sunt egale pe toată plaja:

1. confirmarea salturilor  o citire la > `jump_cents` de valoarea curentă e
                           ignorată până vin `confirm` citiri care se înțeleg
                           între ele (o notă nouă) — un vârf izolat dispare;
2. median pe ultimele N    elimină citirile aberante rămase;
3. netezire exponențială   mișcare lină, fără întârziere mare.

După ce coarda se stinge, ultima valoare este ținută `hold_seconds`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import log2
from statistics import median

from pitch import PitchEstimate


def _to_cents(frequency: float) -> float:
    return 1200.0 * log2(frequency)


def _to_hz(cents: float) -> float:
    return 2.0 ** (cents / 1200.0)


@dataclass(frozen=True)
class TrackedPitch:
    frequency: float
    holding: bool
    """True când semnalul s-a oprit și afișăm ultima valoare."""
    stable: bool
    """True după câteva citiri consecutive pe aceeași notă."""


class PitchTracker:
    def __init__(
        self,
        median_size: int = 5,
        smoothing: float = 0.35,
        jump_cents: float = 70.0,
        confirm: int = 3,
        hold_seconds: float = 1.5,
        stable_after: int = 4,
    ) -> None:
        self._smoothing = smoothing
        self._jump = jump_cents
        self._confirm = confirm
        self._hold = hold_seconds
        self._stable_after = stable_after
        self._history: deque[float] = deque(maxlen=median_size)
        self._pending: list[float] = []
        self._value: float | None = None
        self._streak = 0
        self._last_seen = 0.0

    def reset(self) -> None:
        self._history.clear()
        self._pending.clear()
        self._value = None
        self._streak = 0

    def update(self, estimate: PitchEstimate | None, now: float) -> TrackedPitch | None:
        """Adaugă o citire nouă (sau lipsa ei) și întoarce valoarea afișabilă."""
        if estimate is None:
            self._pending.clear()
            return self.current(now)

        reading = _to_cents(estimate.frequency)
        self._last_seen = now

        if self._value is None:
            self._start(reading)
        elif abs(reading - self._value) > self._jump:
            self._pending.append(reading)
            if len(self._pending) >= self._confirm:
                if max(self._pending) - min(self._pending) <= self._jump:
                    self._start(median(self._pending))
                else:
                    self._pending = self._pending[1:]
            return self.current(now)
        else:
            self._pending.clear()
            self._history.append(reading)
            target = median(self._history)
            self._value += self._smoothing * (target - self._value)
            self._streak += 1

        return self.current(now)

    def current(self, now: float) -> TrackedPitch | None:
        """Valoarea curentă, fără o citire nouă. Expiră după `hold_seconds`."""
        if self._value is None:
            return None
        holding = now - self._last_seen > 0.12
        if holding and now - self._last_seen > self._hold:
            self.reset()
            return None
        return TrackedPitch(
            frequency=_to_hz(self._value),
            holding=holding,
            stable=not holding and self._streak >= self._stable_after,
        )

    def _start(self, cents: float) -> None:
        self._history.clear()
        self._history.append(cents)
        self._pending.clear()
        self._value = cents
        self._streak = 1
