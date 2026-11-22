"""
Detecția frecvenței fundamentale cu algoritmul YIN.

de Cheveigné & Kawahara (2002), "YIN, a fundamental frequency estimator
for speech and music". Pașii din articol, în ordine:

1. funcția diferență   d(τ) = Σ_{j<W} (x_j − x_{j+τ})²       (calculată prin FFT)
2. normalizarea         d'(τ) = d(τ) · τ / Σ_{k=1..τ} d(k)
3. pragul absolut       primul τ cu d'(τ) < prag (evită octava de jos)
4. interpolare parabolică pe d(τ) → precizie sub un eșantion

Fereastra de integrare W este fixă (nu scade cu τ) și semnalul NU este
ponderat cu o fereastră Hann: ambele ar strica periodicitatea pe care
YIN o măsoară și ar împinge rezultatul în sus.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

YIN_THRESHOLD = 0.12
"""Sub prag semnalul e considerat periodic (articolul recomandă 0.10–0.15)."""

FALLBACK_THRESHOLD = 0.30
"""Dacă nimic nu trece de prag, acceptăm minimul global doar sub valoarea asta."""

DEFAULT_RMS_GATE = 0.002
"""Sub acest nivel RMS (≈ −54 dBFS) tratăm intrarea ca liniște."""


@dataclass(frozen=True)
class PitchEstimate:
    frequency: float
    """Frecvența fundamentală, în Hz."""
    clarity: float
    """1 − d'(τ): 1 = perfect periodic, 0 = zgomot."""


def analysis_size(sample_rate: int, fmin: float) -> int:
    """
    Câte eșantioane trebuie citite ca să detectăm `fmin`.

    W cuprinde ≥ 3 perioade din nota cea mai joasă, plus încă o perioadă
    maximă de decalaj (τ_max). La 48 kHz și 70 Hz: ~2.7k eșantioane ≈ 57 ms.
    """
    max_lag = int(np.ceil(sample_rate / fmin)) + 2
    window = max(1024, int(3 * sample_rate / fmin))
    return window + max_lag


def _difference(x: NDArray[np.float64], window: int, max_lag: int) -> NDArray[np.float64]:
    """d(τ) pentru τ = 0..max_lag, în O(N log N)."""
    nfft = 1 << (x.size + window).bit_length()
    # corr[τ] = Σ_{j<W} x_j · x_{j+τ}
    corr = np.fft.irfft(np.fft.rfft(x, nfft) * np.conj(np.fft.rfft(x[:window], nfft)), nfft)
    corr = corr[: max_lag + 1]

    energy = np.concatenate(([0.0], np.cumsum(x * x)))
    taus = np.arange(max_lag + 1)
    head = energy[window]  # Σ_{j<W} x_j²
    shifted = energy[taus + window] - energy[taus]  # Σ_{j<W} x_{j+τ}²
    d = head + shifted - 2.0 * corr
    d[0] = 0.0
    return np.maximum(d, 0.0)


def _cmndf(d: NDArray[np.float64]) -> NDArray[np.float64]:
    """Diferența normalizată cu media cumulativă: d'(0) = 1."""
    out = np.ones_like(d)
    running = np.cumsum(d[1:])
    taus = np.arange(1, d.size)
    np.divide(d[1:] * taus, running, out=out[1:], where=running > 0)
    return out


def _parabolic_vertex(left: float, mid: float, right: float) -> float:
    """Poziția minimului parabolei prin trei puncte, relativ la punctul din mijloc."""
    denom = left - 2.0 * mid + right
    if denom <= 0.0:
        return 0.0
    return float(np.clip(0.5 * (left - right) / denom, -0.5, 0.5))


def estimate_pitch(
    samples: NDArray[np.floating],
    sample_rate: int,
    fmin: float = 70.0,
    fmax: float = 1000.0,
    rms_gate: float = DEFAULT_RMS_GATE,
) -> PitchEstimate | None:
    """Frecvența fundamentală din `samples`, sau None la liniște / zgomot."""
    x = np.asarray(samples, dtype=np.float64)
    x = x - x.mean() if x.size else x

    max_lag = int(np.ceil(sample_rate / fmin)) + 1
    min_lag = max(2, int(sample_rate / fmax))
    window = x.size - max_lag - 1
    if window < max_lag or max_lag <= min_lag + 2:
        return None
    if float(np.sqrt(np.mean(x * x))) < rms_gate:
        return None

    d = _difference(x, window, max_lag)
    dn = _cmndf(d)
    search = dn[min_lag:max_lag]

    below = np.flatnonzero(search < YIN_THRESHOLD)
    if below.size:
        tau = int(below[0]) + min_lag
        # coborâm până la fundul văii în care am intrat
        while tau + 1 < max_lag and dn[tau + 1] < dn[tau]:
            tau += 1
    else:
        tau = int(np.argmin(search)) + min_lag
        if dn[tau] > FALLBACK_THRESHOLD:
            return None

    # minimul exact al lui d (nu d') se poate afla la un eșantion distanță
    while tau + 1 < max_lag and d[tau + 1] < d[tau]:
        tau += 1
    while tau - 1 > min_lag and d[tau - 1] < d[tau]:
        tau -= 1
    if tau <= 1 or tau >= max_lag:
        return None

    lag = tau + _parabolic_vertex(float(d[tau - 1]), float(d[tau]), float(d[tau + 1]))
    frequency = sample_rate / lag
    if not fmin * 0.95 <= frequency <= fmax * 1.05:
        return None
    return PitchEstimate(frequency=float(frequency), clarity=float(1.0 - min(1.0, dn[tau])))
