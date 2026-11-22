import unittest

from notes import cents_off
from pitch import PitchEstimate
from tracker import PitchTracker


def est(hz: float) -> PitchEstimate:
    return PitchEstimate(hz, 0.95)


class TrackerTest(unittest.TestCase):
    def test_single_spike_is_ignored(self):
        t = PitchTracker()
        now = 0.0
        for _ in range(10):
            now += 0.016
            t.update(est(110.0), now)
        out = t.update(est(220.0), now + 0.016)  # o octavă greșită, izolată
        self.assertAlmostEqual(out.frequency, 110.0, delta=0.1)

    def test_new_note_is_accepted_after_confirmation(self):
        t = PitchTracker(confirm=3)
        now = 0.0
        for _ in range(10):
            now += 0.016
            t.update(est(110.0), now)
        out = None
        for _ in range(3):
            now += 0.016
            out = t.update(est(146.83), now)
        self.assertAlmostEqual(cents_off(out.frequency, 146.83), 0.0, delta=1.0)

    def test_jitter_is_smoothed(self):
        t = PitchTracker()
        now = 0.0
        out = None
        for i in range(40):
            now += 0.016
            out = t.update(est(110.0 * 2 ** ((6 if i % 2 else -6) / 1200)), now)
        self.assertLess(abs(cents_off(out.frequency, 110.0)), 3.0)
        self.assertTrue(out.stable)

    def test_hold_then_expire(self):
        t = PitchTracker(hold_seconds=1.0)
        t.update(est(110.0), 0.0)
        held = t.update(None, 0.5)
        self.assertIsNotNone(held)
        self.assertTrue(held.holding)
        self.assertIsNone(t.update(None, 1.2))


if __name__ == "__main__":
    unittest.main()
