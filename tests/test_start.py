from fractions import Fraction

from line.calibration.profiles import ProfileRejected
from line.calibration.revisions import ProfileRevisions, calibrate
from line.capture.admission import IngestRejected
from line.closing.cut import seal
from line.intake.registry import ShiftRegistry
from line.intake.shifts import OpeningRejected, RegistrationRejected, open as open_shift, register
from tests.support import LineCase, ROSTER


class StartTests(LineCase):
    def test_open_freezes_profiles(self):
        self.register_day()
        left, right = self.profile_pair()
        later = calibrate(self.db, 'L', 2, 0, 0, 20, 12)
        opened = open_shift(self.db, 'day', left, right)
        self.assertEqual((opened.left_version, opened.right_version), (left, right))
        self.assertNotEqual(left, later)
        self.assertEqual(self.capture('L-A', 'L1', 10).thickness_um, Fraction(16))
        fixed = seal(self.db, 'day', 'L', 1)
        self.assertEqual(fixed.profile_version, left)
        self.assertEqual((fixed.profile.gain, fixed.profile.limit_um), (Fraction(3, 2), Fraction(16)))
        self.assertEqual(fixed.details[0].status, 'within_limit')
        with self.assertRaises(OpeningRejected):
            open_shift(self.db, 'day', later, right)
        self.assertEqual(seal(self.db, 'day', 'L', 1).profile_version, left)

    def test_profile_input(self):
        self.register_day()
        left, right = self.profile_pair()
        for gain, low, high in ((0, 0, 20), (-1, 0, 20), (1, 20, 0), ('1/0', 0, 20), (0.1, 0, 20)):
            with self.subTest(gain=gain, low=low, high=high):
                with self.assertRaises(ProfileRejected):
                    calibrate(self.db, 'L', gain, 0, low, high, 16)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM gauge_versions').fetchone()[0], 2)
        open_shift(self.db, 'day', left, right)
        self.assertEqual(ProfileRevisions(self.db).get_version(left).gain, Fraction(3, 2))
        self.assertEqual(self.capture('L-A', 'L1', 10).thickness_um, Fraction(16))

    def test_wrong_station_profile(self):
        self.register_day()
        _, right = self.profile_pair()
        with self.assertRaises(OpeningRejected):
            open_shift(self.db, 'day', right, right)
        self.assertIsNone(ShiftRegistry(self.db).get_opened_shift('day'))
        with self.assertRaises(IngestRejected):
            self.capture('L-A', 'L1', 10)

    def test_roster_integrity(self):
        for left, right, entries in (
            ('L', 'R', (('A', 'L'), ('A', 'R'))),
            ('L', 'R', (('A', 'L'), ('B', 'foreign'))),
            ('L', 'L', (('A', 'L'),)),
        ):
            with self.subTest(entries=entries):
                with self.assertRaises(RegistrationRejected):
                    register(self.db, 'day', left, right, entries)
                self.assertIsNone(ShiftRegistry(self.db).get_registration('day'))
                self.assertEqual(self.db.execute('SELECT COUNT(*) FROM roster_items').fetchone()[0], 0)
        self.assertEqual(self.register_day(), 'day')
        saved = ShiftRegistry(self.db).get_registration('day')
        self.assertEqual([(row.specimen_id, row.station) for row in saved.roster.items], list(ROSTER))

    def test_open_all_or_none(self):
        self.register_day()
        left, right = self.profile_pair()
        for versions in ((right, right), (left, None), (left, 9999)):
            with self.subTest(versions=versions):
                with self.assertRaises(OpeningRejected):
                    open_shift(self.db, 'day', *versions)
                pins = self.db.execute('SELECT left_version, right_version FROM shifts').fetchone()
                self.assertEqual(pins, (None, None))
                with self.assertRaises(IngestRejected):
                    self.capture('L-A', 'L1', 4)
                with self.assertRaises(IngestRejected):
                    self.capture('R-A', 'R1', 4, station='R')
        open_shift(self.db, 'day', left, right)
        self.assertEqual(self.capture('L-A', 'L1', 4).sequence, 1)
        self.assertEqual(self.capture('R-A', 'R1', 4, station='R').sequence, 1)
