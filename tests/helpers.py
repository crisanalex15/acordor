"""Semnale sintetice care imită o coardă ciupită."""

from __future__ import annotations

import numpy as np

SAMPLE_RATE = 48000


def pluck(
    f0: float,
    n_samples: int,
    harmonics: tuple[float, ...] = (1.0, 2.0, 1.0, 0.5, 0.4, 0.3),
    noise: float = 0.002,
    phase_time: float = 0.0,
    seed: int = 0,
) -> np.ndarray:
    """Sumă de armonici (a 2-a mai puternică decât fundamentala, ca la corzile groase) + zgomot."""
    rng = np.random.default_rng(seed)
    t = np.arange(n_samples) / SAMPLE_RATE + phase_time
    x = sum(a * np.sin(2 * np.pi * f0 * (k + 1) * t + k) for k, a in enumerate(harmonics))
    x = 0.1 * x / np.max(np.abs(x))
    return x + rng.normal(0.0, noise, n_samples)
