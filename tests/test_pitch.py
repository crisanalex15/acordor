import unittest

import numpy as np

from notes import INSTRUMENTS, cents_off
from pitch import analysis_size, estimate_pitch
from tests.helpers import SAMPLE_RATE, pluck


class PitchAccuracyTest(unittest.TestCase):
    def _errors(self, instrument, f0, harmonics):
        n = analysis_size(SAMPLE_RATE, instrument.fmin)
        errors = []
        for i in range(20):
            x = pluck(f0, n, harmonics, phase_time=i * 0.021, seed=i)
            est = estimate_pitch(x, SAMPLE_RATE, instrument.fmin, instrument.fmax)
            self.assertIsNotNone(est, f"{f0:.2f} Hz nedetectat")
            errors.append(cents_off(est.frequency, f0))
        return np.array(errors)

    def test_every_string_within_one_cent(self):
        for instrument in INSTRUMENTS:
            for string in instrument.strings:
                with self.subTest(instrument=instrument.key, string=string.note.label):
                    errors = self._errors(instrument, string.frequency(), (1.0, 2.0, 1.0, 0.5, 0.4, 0.3))
                    self.assertLess(abs(np.median(errors)), 0.5)
                    self.assertLess(np.max(np.abs(errors)), 1.5)

    def test_weak_fundamental_is_not_an_octave_error(self):
        """Fundamentala slabă (25%) nu trebuie să ducă la octava de sus."""
        for instrument in INSTRUMENTS:
            for string in instrument.strings:
                with self.subTest(instrument=instrument.key, string=string.note.label):
                    errors = self._errors(instrument, string.frequency(), (0.25, 1.0, 0.8, 0.6, 0.4, 0.3, 0.2))
                    self.assertLess(np.max(np.abs(errors)), 1.5)

    def test_detuned_string_is_measured(self):
        n = analysis_size(SAMPLE_RATE, 70)
        for offset in (-40.0, -12.0, 7.0, 33.0):
            f = 110.0 * 2 ** (offset / 1200)
            est = estimate_pitch(pluck(f, n), SAMPLE_RATE, 70, 1000)
            self.assertAlmostEqual(cents_off(est.frequency, 110.0), offset, delta=1.0)


class PitchRejectionTest(unittest.TestCase):
    def test_silence(self):
        n = analysis_size(SAMPLE_RATE, 70)
        self.assertIsNone(estimate_pitch(np.zeros(n), SAMPLE_RATE))

    def test_white_noise(self):
        rng = np.random.default_rng(1)
        n = analysis_size(SAMPLE_RATE, 70)
        hits = sum(estimate_pitch(rng.normal(0, 0.02, n), SAMPLE_RATE) is not None for _ in range(100))
        self.assertLessEqual(hits, 2)

    def test_too_short_buffer(self):
        self.assertIsNone(estimate_pitch(np.ones(100), SAMPLE_RATE))


if __name__ == "__main__":
    unittest.main()
