import unittest

from notes import BASS, GUITAR, UKULELE, Note, cents_off, nearest_note
from pitch import PitchEstimate
from tuner import Hint, Mode, TunerModel


def feed(model: TunerModel, hz: float, seconds: float = 1.0, start: float = 0.0) -> float:
    now = start
    while now < start + seconds:
        now += 1 / 60
        model.feed(PitchEstimate(hz, 0.95), now)
    return now


class NotesTest(unittest.TestCase):
    def test_note_names(self):
        self.assertEqual(Note(40).label, "E2")
        self.assertEqual(Note(69).label, "A4")
        self.assertEqual(Note(61).label, "C#4")
        self.assertEqual(nearest_note(440.0).label, "A4")

    def test_standard_tunings(self):
        self.assertEqual([s.note.label for s in GUITAR.strings], ["E2", "A2", "D3", "G3", "B3", "E4"])
        self.assertEqual([s.number for s in GUITAR.strings], [6, 5, 4, 3, 2, 1])
        self.assertEqual([s.note.label for s in BASS.strings], ["E1", "A1", "D2", "G2"])
        self.assertEqual([s.note.label for s in UKULELE.strings], ["G4", "C4", "E4", "A4"])
        self.assertAlmostEqual(GUITAR.strings[0].frequency(), 82.4069, places=3)

    def test_nearest_string_uses_cents_not_hz(self):
        # 95.7 Hz e la 13.3 Hz de E2 și 14.3 Hz de A2, dar muzical (259 vs 241 cents) e mai aproape de A2.
        self.assertEqual(GUITAR.nearest_string(95.7).note.label, "A2")

    def test_a4_calibration(self):
        self.assertAlmostEqual(Note(69).frequency(432.0), 432.0)
        self.assertAlmostEqual(cents_off(442.0, 440.0), 7.85, places=2)


class TunerModelTest(unittest.TestCase):
    def test_auto_picks_nearest_string(self):
        m = TunerModel()
        feed(m, 110.0 * 2 ** (-20 / 1200))
        self.assertEqual(m.reading.target.label, "A2")
        self.assertAlmostEqual(m.reading.cents, -20.0, delta=1.0)
        self.assertIs(m.hint, Hint.TOO_LOW)

    def test_string_is_marked_tuned(self):
        m = TunerModel()
        feed(m, 82.41, seconds=1.2)
        self.assertIs(m.hint, Hint.IN_TUNE)
        self.assertIn(6, m.tuned)

    def test_tuned_mark_is_removed_when_detuned(self):
        m = TunerModel()
        now = feed(m, 82.41, seconds=1.2)
        feed(m, 82.41 * 2 ** (-30 / 1200), seconds=1.0, start=now)
        self.assertNotIn(6, m.tuned)

    def test_manual_string_reports_wrong_string(self):
        m = TunerModel()
        m.select_string(1)
        feed(m, 82.41)
        self.assertIs(m.mode, Mode.STRING)
        self.assertIs(m.hint, Hint.WRONG_STRING)

    def test_clicking_selected_string_returns_to_auto(self):
        m = TunerModel()
        m.select_string(3)
        m.select_string(3)
        self.assertIs(m.mode, Mode.AUTO)

    def test_chromatic_uses_nearest_semitone(self):
        m = TunerModel()
        m.set_chromatic()
        feed(m, 277.18)  # C#4
        self.assertEqual(m.reading.target.label, "C#4")
        self.assertIsNone(m.reading.target_string)

    def test_changing_instrument_resets(self):
        m = TunerModel()
        feed(m, 82.41, seconds=1.2)
        m.set_instrument(BASS)
        self.assertEqual(m.tuned, set())
        self.assertIsNone(m.reading)


if __name__ == "__main__":
    unittest.main()
