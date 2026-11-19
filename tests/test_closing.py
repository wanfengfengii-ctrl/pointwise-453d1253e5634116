from fractions import Fraction

from line.closing.cut import SealRejected, seal
from line.closing.store import SealStore
from tests.support import LineCase


class ClosingTests(LineCase):
    def test_zero_and_missing(self):
        self.open_day()
        self.capture('L-A', 'L1', 0)
        measured, absent = seal(self.db, 'day', 'L', 1).details
        self.assertEqual((measured.specimen_id, measured.count, measured.maximum_um, measured.status),
                         ('L-A', 1, Fraction(1), 'within_limit'))
        self.assertEqual(measured.readings[0].claim.raw_code, 0)
        self.assertEqual((absent.specimen_id, absent.count, absent.maximum_um, absent.status, absent.readings),
                         ('L-B', 0, None, 'missing', ()))

    def test_sealed_prefix(self):
        self.open_day()
        self.capture('L-A', 'L1', 0, 2)
        self.capture('L-A', 'L2', 12, 3)
        self.capture('L-B', 'L3', 4, 4)
        empty = seal(self.db, 'day', 'L', 0)
        earlier = seal(self.db, 'day', 'L', 1)
        latest = seal(self.db, 'day', 'L', 3)
        self.assertEqual((empty.cutoff, earlier.cutoff, latest.cutoff), (0, 1, 3))
        self.assertEqual([(item.count, item.maximum_um, item.status) for item in empty.details],
                         [(0, None, 'missing'), (0, None, 'missing')])
        self.assertEqual([(item.count, item.maximum_um, item.status) for item in earlier.details],
                         [(1, Fraction(1), 'within_limit'), (0, None, 'missing')])
        self.assertEqual([(item.count, item.maximum_um, item.status) for item in latest.details],
                         [(2, Fraction(19), 'over_limit'), (1, Fraction(7), 'within_limit')])
        self.assertEqual([[row.claim.key.reading_id for row in item.readings] for item in earlier.details],
                         [['L1'], []])
        self.assertEqual([[row.claim.key.reading_id for row in item.readings] for item in latest.details],
                         [['L1', 'L2'], ['L3']])
        self.capture('L-B', 'L4', 13, 5)
        self.assertEqual(SealStore(self.db).get(earlier.seal_id), earlier)
        self.assertEqual(SealStore(self.db).get(latest.seal_id), latest)

    def test_invalid_cut(self):
        self.open_day()
        self.register_day('draft')
        self.capture('L-A', 'L1', 0)
        for shift, station, cutoff in (('unknown', 'L', 0), ('draft', 'L', 0), ('day', 'X', 0),
                                       ('day', 'L', -1), ('day', 'L', 2), ('day', 'R', 1),
                                       ('day', 'L', True)):
            with self.subTest(shift=shift, station=station, cutoff=cutoff):
                with self.assertRaises(SealRejected):
                    seal(self.db, shift, station, cutoff)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM station_seals').fetchone()[0], 0)
        self.assertEqual(seal(self.db, 'day', 'L', 1).cutoff, 1)
