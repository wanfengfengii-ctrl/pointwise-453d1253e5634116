from contextlib import closing
from fractions import Fraction
import json
import sqlite3

from line.calibration.revisions import calibrate
from line.capture.admission import (IngestRejected, declare_end, ingest, ingest_anonymous,
                                    ingest_recording, ingest_ticket)
from line.closing.cut import SealRejected, seal, seal_anonymous
from line.closing.store import SealStore
from line.intake.registry import ShiftRegistry
from line.intake.shifts import OpeningRejected, open as open_shift, register
from line.report.publish import publish
from line.report.readback import read
from line.workday import connect, initialize
from tests.support import LineCase, ROSTER

ANON_ROSTER = (('R-A', 'R'), ('L-A', 'L'), ('L-B', 'L'), ('L-C', 'L'))


class AnonymousCase(LineCase):
    def open_anonymous(self, shift_id='day', roster=ANON_ROSTER):
        register(self.db, shift_id, 'L', 'R', roster)
        versions = self.profile_pair()
        opened = open_shift(self.db, shift_id, *versions, anonymous_station='L')
        return versions, opened

    def ticket(self, seq, line, specimen, first, last, shift_id='day', station='L'):
        return ingest_ticket(self.db, shift_id, station, seq, line, specimen, first, last)

    def reading(self, seq, line, shot, reading_id, raw, shift_id='day', station='L'):
        return ingest_anonymous(self.db, shift_id, station, seq, line, shot, reading_id, raw)

    def end(self, stream, last, shift_id='day', station='L'):
        return declare_end(self.db, shift_id, station, stream, last)

    def seals(self):
        return self.db.execute('SELECT COUNT(*) FROM station_seals').fetchone()[0]


class AnonymousOpeningTests(AnonymousCase):
    def test_open_without_window_keeps_old_mode(self):
        self.open_day()
        opened = ShiftRegistry(self.db).get_opened_shift('day')
        self.assertIsNone(opened.anonymous_station)
        self.capture('L-A', 'L1', 4)
        self.assertEqual(seal(self.db, 'day', 'L', 1).details[0].count, 1)

    def test_foreign_anonymous_station_rejected(self):
        self.register_day()
        versions = self.profile_pair()
        with self.assertRaises(OpeningRejected):
            open_shift(self.db, 'day', *versions, anonymous_station='X')
        self.assertIsNone(ShiftRegistry(self.db).get_opened_shift('day'))

    def test_window_is_per_shift_and_station(self):
        _, opened = self.open_anonymous()
        self.assertEqual(opened.anonymous_station, 'L')
        # The opposite station still accepts named readings and seals by cut.
        self.capture('R-A', 'R1', 4, station='R')
        self.assertEqual(seal(self.db, 'day', 'R', 1).details[0].count, 1)

    def test_anonymous_side_rejects_named_paths(self):
        self.open_anonymous()
        with self.assertRaises(IngestRejected):
            self.capture('L-A', 'L1', 4)
        from io import StringIO
        with self.assertRaises(IngestRejected):
            ingest_recording(self.db, 'day', 'L',
                             StringIO('specimen_id,reading_id,raw_code\nL-A,L1,4\n'))
        with self.assertRaises(SealRejected):
            seal(self.db, 'day', 'L', 0)

    def test_anonymous_entries_require_window(self):
        self.open_day()
        with self.assertRaises(IngestRejected):
            self.ticket(1, 2, 'L-A', 1, 1)
        with self.assertRaises(IngestRejected):
            self.reading(1, 2, 1, 'r1', 4)
        with self.assertRaises(IngestRejected):
            self.end('ticket', 1)
        with self.assertRaises(SealRejected):
            seal_anonymous(self.db, 'day', 'L')


class AnonymousIntakeTests(AnonymousCase):
    def test_ticket_validation(self):
        self.open_anonymous()
        for args in ((1, 2, 'R-A', 1, 1), (1, 2, 'unknown', 1, 1), (0, 2, 'L-A', 1, 1),
                     (1, 0, 'L-A', 1, 1), (1, 2, 'L-A', 2, 1), (True, 2, 'L-A', 1, 1),
                     (1, 2, 'L-A', True, 1), (1.0, 2, 'L-A', 1, 1)):
            with self.subTest(args=args):
                with self.assertRaises(IngestRejected):
                    ingest_ticket(self.db, 'day', 'L', *args)
        self.assertEqual(self.ticket(1, 2, 'L-A', -3, 5), 1)

    def test_one_ticket_per_specimen_and_unique_lines(self):
        self.open_anonymous()
        self.ticket(1, 2, 'L-A', 1, 2)
        self.assertEqual(self.ticket(1, 2, 'L-A', 1, 2), 1)
        with self.assertRaises(IngestRejected):
            self.ticket(2, 3, 'L-A', 1, 2)
        with self.assertRaises(IngestRejected):
            self.ticket(2, 2, 'L-B', 1, 2)
        self.assertEqual(self.ticket(2, 3, 'L-B', 1, 2), 2)

    def test_source_seq_replay_and_conflict(self):
        self.open_anonymous()
        self.ticket(1, 4, 'L-A', 1, 2)
        with self.assertRaises(IngestRejected):
            self.ticket(1, 4, 'L-B', 1, 2)
        self.assertEqual(self.ticket(1, 4, 'L-A', 1, 2), 1)
        self.reading(1, 3, 1, 'r1', 7)
        with self.assertRaises(IngestRejected):
            self.reading(1, 3, 1, 'r1', 8)
        with self.assertRaises(IngestRejected):
            self.reading(1, 5, 1, 'r1', 7)
        self.assertEqual(self.reading(1, 3, 1, 'r1', '7/1'), 1)

    def test_reading_validation(self):
        self.open_anonymous()
        for args in ((1, 3, 1, 'r1', 21), (1, 3, 1, 'r1', -1), (1, 3, 1, 'r1', True),
                     (1, 3, True, 'r1', 7), (0, 3, 1, 'r1', 7), (1, 0, 1, 'r1', 7),
                     (1, 3, 1, '', 7)):
            with self.subTest(args=args):
                with self.assertRaises(IngestRejected):
                    ingest_anonymous(self.db, 'day', 'L', *args)
        self.assertEqual(self.reading(1, 3, -7, 'r1', 7), 1)

    def test_reading_id_unique_in_stream_only(self):
        self.open_anonymous()
        self.capture('R-A', 'r1', 5, station='R')
        self.reading(1, 3, 1, 'r1', 7)
        with self.assertRaises(IngestRejected):
            self.reading(2, 4, 2, 'r1', 7)
        self.assertEqual(self.reading(2, 4, 2, 'r2', 7), 2)

    def test_end_declarations(self):
        self.open_anonymous()
        with self.assertRaises(IngestRejected):
            self.end('unknown', 0)
        with self.assertRaises(IngestRejected):
            self.end('ticket', -1)
        self.reading(2, 9, 2, 'r2', 13)
        with self.assertRaises(IngestRejected):
            self.end('reading', 1)
        self.assertEqual(self.end('reading', 2), 2)
        self.assertEqual(self.end('reading', 2), 2)
        with self.assertRaises(IngestRejected):
            self.end('reading', 3)
        with self.assertRaises(IngestRejected):
            self.reading(3, 10, 3, 'r3', 8)

    def test_interleaved_and_late_acceptance(self):
        self.open_anonymous()
        self.end('ticket', 2)
        self.end('reading', 2)
        self.ticket(2, 7, 'L-B', 1, 1)
        self.reading(1, 3, 1, 'r1', 7)
        self.assertEqual(seal_anonymous(self.db, 'day', 'L'), ('pending', None))
        self.ticket(1, 4, 'L-A', 1, 2)
        self.assertEqual(seal_anonymous(self.db, 'day', 'L'), ('pending', None))
        self.reading(2, 9, 2, 'r2', 13)
        state, seal_id = seal_anonymous(self.db, 'day', 'L')
        self.assertEqual(state, 'sealed')
        self.assertEqual(seal_anonymous(self.db, 'day', 'L'), ('sealed', seal_id))


class AnonymousSealTests(AnonymousCase):
    def _pair(self):
        self.open_anonymous()

    def test_pending_needs_both_ends(self):
        self.open_anonymous()
        self.assertEqual(seal_anonymous(self.db, 'day', 'L'), ('pending', None))
        self.end('ticket', 0)
        self.assertEqual(seal_anonymous(self.db, 'day', 'L'), ('pending', None))
        self.end('reading', 0)
        state, seal_id = seal_anonymous(self.db, 'day', 'L')
        self.assertEqual(state, 'sealed')
        self.assertEqual(self.seals(), 1)

    def test_gap_keeps_pending(self):
        self.open_anonymous()
        self.ticket(1, 4, 'L-A', 1, 1)
        self.reading(1, 3, 1, 'r1', 7)
        self.reading(3, 9, 3, 'r3', 7)
        self.end('ticket', 2)
        self.end('reading', 3)
        self.assertEqual(seal_anonymous(self.db, 'day', 'L'), ('pending', None))
        self.assertEqual(self.seals(), 0)

    def test_no_match_when_count_differs(self):
        self.open_anonymous()
        self.ticket(1, 4, 'L-A', 1, 1)
        self.end('ticket', 1)
        self.end('reading', 0)
        self.assertEqual(seal_anonymous(self.db, 'day', 'L'), ('no_match', None))
        self.assertEqual(self.seals(), 0)

    def test_no_match_when_shots_uncovered(self):
        self.open_anonymous()
        self.ticket(1, 4, 'L-A', 1, 1)
        self.reading(1, 3, 2, 'r1', 7)
        self.end('ticket', 1)
        self.end('reading', 1)
        self.assertEqual(seal_anonymous(self.db, 'day', 'L'), ('no_match', None))

    def test_ambiguous_with_equal_raw_codes(self):
        self.open_anonymous()
        self.ticket(1, 4, 'L-A', 1, 2)
        self.ticket(2, 7, 'L-B', 1, 2)
        self.reading(1, 3, 1, 'r1', 7)
        self.reading(2, 9, 2, 'r2', 7)
        self.end('ticket', 2)
        self.end('reading', 2)
        self.assertEqual(seal_anonymous(self.db, 'day', 'L'), ('ambiguous', None))
        self.assertEqual(self.seals(), 0)

    def test_unique_pairing_distinguishes_physical_records(self):
        self.open_anonymous()
        self.end('ticket', 2)
        self.end('reading', 2)
        self.ticket(2, 7, 'L-B', 1, 1)
        self.reading(1, 3, 1, 'r1', 7)
        self.ticket(1, 4, 'L-A', 1, 2)
        self.reading(2, 9, 2, 'r2', 13)
        state, seal_id = seal_anonymous(self.db, 'day', 'L')
        self.assertEqual(state, 'sealed')
        report_id = publish(self.db, seal(self.db, 'day', 'R', 0).seal_id, seal_id)
        view = read(self.db, report_id)
        items = {item.specimen_id: item for item in view.items}
        self.assertEqual(items['L-A'].status, 'over_limit')
        self.assertEqual(items['L-A'].readings[0].anonymous.shot, 2)
        self.assertEqual(items['L-B'].readings[0].anonymous.shot, 1)
        self.assertEqual(items['L-C'].status, 'missing')
        self.assertEqual(items['L-C'].count, 0)
        self.assertIsNone(items['L-C'].maximum_um)

    def test_wrong_station_or_window(self):
        self.open_anonymous()
        with self.assertRaises(SealRejected):
            seal_anonymous(self.db, 'day', 'R')
        with self.assertRaises(SealRejected):
            seal_anonymous(self.db, 'unknown', 'L')
        with self.assertRaises(SealRejected):
            seal_anonymous(self.db, 'day', '')

    def test_commit_failure_leaves_no_seal(self):
        self.open_anonymous()
        self.end('ticket', 1)
        self.end('reading', 1)
        self.ticket(1, 4, 'L-A', 1, 1)
        self.reading(1, 3, 1, 'r1', 7)
        with closing(connect(self.path)) as observer:
            before = observer.execute('SELECT COUNT(*) FROM station_seals').fetchone()[0]

            def authorizer(operation, argument, *_):
                if operation == sqlite3.SQLITE_TRANSACTION and argument == 'COMMIT':
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            self.db.set_authorizer(authorizer)
            try:
                with self.assertRaises(SealRejected):
                    seal_anonymous(self.db, 'day', 'L')
            finally:
                self.db.set_authorizer(None)
            self.assertFalse(self.db.in_transaction)
            self.assertEqual(observer.execute('SELECT COUNT(*) FROM station_seals').fetchone()[0], before)
        state, seal_id = seal_anonymous(self.db, 'day', 'L')
        self.assertEqual(state, 'sealed')
        self.assertEqual(seal_anonymous(self.db, 'day', 'L'), ('sealed', seal_id))

    def test_readback_after_reopen_with_independent_provenance(self):
        versions, _ = self.open_anonymous()
        self.capture('R-A', 'r1', 5, station='R')
        right = seal(self.db, 'day', 'R', 1)
        self.ticket(1, 4, 'L-A', 1, 1)
        self.reading(1, 3, 1, 'r1', 7)
        self.end('ticket', 1)
        self.end('reading', 1)
        state, left_id = seal_anonymous(self.db, 'day', 'L')
        self.assertEqual(state, 'sealed')
        report_id = publish(self.db, right.seal_id, left_id)
        self.db.close()
        with closing(connect(self.path)) as reopened:
            initialize(reopened)
            view = read(reopened, report_id)
        left = next(item for item in view.items if item.specimen_id == 'L-A')
        right_item = next(item for item in view.items if item.specimen_id == 'R-A')
        self.assertEqual((left.readings[0].reading_id, right_item.readings[0].reading_id), ('r1', 'r1'))
        self.assertEqual(left.readings[0].anonymous.ticket.source_seq, 1)
        self.assertEqual(left.readings[0].anonymous.ticket.source_line, 4)
        self.assertIsNone(right_item.readings[0].anonymous)
        self.assertEqual(left.profile_version, versions[0])
        json.dumps({'state': state, 'left': left.seal_id})
