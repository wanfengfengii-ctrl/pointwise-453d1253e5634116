from contextlib import closing
from fractions import Fraction
from shutil import copyfile
import sqlite3

from line.calibration.revisions import ProfileRevisions, calibrate
from line.capture.admission import ingest_recording
from line.capture.identity import ReadingKey
from line.capture.journal import ReadingJournal
from line.closing.cut import seal
from line.closing.store import SealStore
from line.intake.registry import ShiftRegistry
from line.report.publish import PublishRejected, publish
from line.report.readback import ReportNotFound, read
from line.workday import connect, initialize
from tests.support import LineCase, ROSTER, SAMPLES, report_counts


class HandoverTests(LineCase):
    def _import_recordings(self):
        live_files = []
        for name, station in (('left.csv', 'L'), ('right.csv', 'R')):
            path = self.folder / name
            copyfile(SAMPLES / name, path)
            with path.open(encoding='utf-8', newline='') as source:
                ingest_recording(self.db, 'day', station, source)
            live_files.append(path)
        return live_files

    def _empty_report(self):
        self.open_day()
        left = seal(self.db, 'day', 'L', 0)
        right = seal(self.db, 'day', 'R', 0)
        report_id = publish(self.db, left.seal_id, right.seal_id)
        return left, right, report_id

    def test_read_without_source(self):
        versions = self.open_day()
        files = self._import_recordings()
        left = seal(self.db, 'day', 'L', 2)
        right = seal(self.db, 'day', 'R', 1)
        old_id = publish(self.db, left.seal_id, right.seal_id)
        old_view = read(self.db, old_id)
        new_profile = calibrate(self.db, 'L', 10, 0, 0, 20, 9)
        for path in files:
            path.unlink()
        self.assertEqual(self.capture('L-A', 'L3', 12, 5).thickness_um, Fraction(19))
        newer_left = seal(self.db, 'day', 'L', 3)
        new_id = publish(self.db, newer_left.seal_id, right.seal_id)
        initialize(self.db)
        self.db.close()
        with closing(connect(self.path)) as reopened:
            earlier = read(reopened, old_id)
            newer = read(reopened, new_id)
            self.assertEqual(SealStore(reopened).get(left.seal_id), left)
            self.assertEqual(ProfileRevisions(reopened).get_version(new_profile).gain, Fraction(10))
        self.assertEqual(earlier, old_view)
        self.assertEqual((earlier.left_seal_id, earlier.right_seal_id), (left.seal_id, right.seal_id))
        detail = earlier.items[1]
        self.assertEqual((detail.profile_version, detail.count, detail.maximum_um, detail.status),
                         (versions[0], 2, Fraction(16), 'within_limit'))
        self.assertEqual([(r.reading_id, r.raw_code, r.source_line) for r in detail.readings],
                         [('L1', Fraction(0), 2), ('L2', Fraction(10), 4)])
        self.assertEqual((newer.left_seal_id, newer.items[1].maximum_um, newer.items[1].status),
                         (newer_left.seal_id, Fraction(19), 'over_limit'))

    def test_parent_pair(self):
        self.open_day()
        self.open_day('next')
        self.capture('R-A', 'R1', 4, station='R')
        self.capture('R-A', 'R1', 8, station='R', shift_id='next')
        left = seal(self.db, 'day', 'L', 0)
        another_left = seal(self.db, 'day', 'L', 0)
        right = seal(self.db, 'day', 'R', 1)
        other_right = seal(self.db, 'next', 'R', 1)
        for second in (99999, left.seal_id, another_left.seal_id, other_right.seal_id):
            with self.subTest(second=second):
                with self.assertRaises(PublishRejected):
                    publish(self.db, left.seal_id, second)
                self.assertEqual(report_counts(self.db), (0, 0))
        self.assertEqual(SealStore(self.db).get(other_right.seal_id), other_right)
        view = read(self.db, publish(self.db, right.seal_id, left.seal_id))
        self.assertEqual((view.left_seal_id, view.right_seal_id, view.items[0].maximum_um),
                         (left.seal_id, right.seal_id, Fraction(7)))

    def test_roster_order(self):
        self.open_day()
        self.capture('L-A', 'L1', 10)
        self.capture('R-B', 'R1', 4, station='R')
        left = seal(self.db, 'day', 'L', 1)
        right = seal(self.db, 'day', 'R', 1)
        report_id = publish(self.db, left.seal_id, right.seal_id)
        with closing(connect(self.path)) as reopened:
            view = read(reopened, report_id)
        self.assertEqual([(item.specimen_id, item.station) for item in view.items], list(ROSTER))
        self.assertEqual([item.position for item in view.items], [0, 1, 2, 3])
        self.assertEqual([(item.specimen_id, item.count) for item in view.items],
                         [('R-A', 0), ('L-A', 1), ('R-B', 1), ('L-B', 0)])
        self.assertEqual([item.specimen_id for item in view.items if item.status == 'missing'], ['R-A', 'L-B'])

    def test_unknown_report(self):
        self._empty_report()
        with self.assertRaises(ReportNotFound):
            read(self.db, 99999)

    def test_reinitialize_preserves_data(self):
        first_versions = self.open_day()
        files = self._import_recordings()
        left = seal(self.db, 'day', 'L', 2)
        right = seal(self.db, 'day', 'R', 1)
        old_id = publish(self.db, left.seal_id, right.seal_id)
        original = read(self.db, old_id)
        self.register_day('user-night')
        new_version = calibrate(self.db, 'L', '5/4', '1/2', 0, 20, 21)
        extra = self.capture('L-B', 'L4', 4, 7)
        extra_seal = seal(self.db, 'day', 'L', extra.sequence)
        for path in files:
            path.unlink()
        initialize(self.db)
        self.db.close()
        with closing(connect(self.path)) as reopened:
            initialize(reopened)
            registry = ShiftRegistry(reopened)
            self.assertIsNotNone(registry.get_registration('user-night'))
            self.assertEqual(registry.get_opened_shift('day').left_version, first_versions[0])
            self.assertEqual(ProfileRevisions(reopened).get_version(new_version).gain, Fraction(5, 4))
            stored_extra = ReadingJournal(reopened).get_reading(ReadingKey('day', 'L4'))
            self.assertEqual((stored_extra.sequence, stored_extra.claim.source_line, stored_extra.thickness_um),
                             (3, 7, Fraction(7)))
            self.assertEqual(SealStore(reopened).get(extra_seal.seal_id), extra_seal)
            self.assertEqual(SealStore(reopened).get(left.seal_id), left)
            self.assertEqual(SealStore(reopened).get(right.seal_id), right)
            self.assertEqual(read(reopened, old_id), original)
            self.assertEqual(original.items[1].readings[1].source_line, 4)

    def test_commit_failure(self):
        left, right, old_id = self._empty_report()
        old_view = read(self.db, old_id)
        newer = seal(self.db, 'day', 'L', 0)
        with closing(connect(self.path)) as observer:
            before = report_counts(observer)
            self.db.executescript((SAMPLES / 'reject_commit.sql').read_text(encoding='utf-8'))
            with self.assertRaises(PublishRejected) as failure:
                publish(self.db, newer.seal_id, right.seal_id)
            self.assertIsInstance(failure.exception.__cause__, sqlite3.IntegrityError)
            self.assertEqual(failure.exception.__cause__.sqlite_errorname, 'SQLITE_CONSTRAINT_FOREIGNKEY')
            self.assertFalse(self.db.in_transaction)
            self.assertEqual(report_counts(observer), before)
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM commit_child').fetchone()[0], 0)
            self.assertEqual(read(observer, old_id), old_view)
            self.assertEqual(SealStore(observer).get(left.seal_id), left)
            self.assertEqual(SealStore(observer).get(right.seal_id), right)
            self.assertEqual(SealStore(observer).get(newer.seal_id), newer)
            self.db.execute('DROP TRIGGER reject_report_commit')
            retry = publish(self.db, newer.seal_id, right.seal_id)
            self.assertEqual(read(observer, retry).left_seal_id, newer.seal_id)

    def test_rollback_visibility(self):
        left, right, old_id = self._empty_report()
        original = read(self.db, old_id)
        self.db.executescript('''
            CREATE TEMP TRIGGER stop_partial_report
            BEFORE INSERT ON main.report_items
            WHEN NEW.position = 1 AND EXISTS (
                SELECT 1 FROM main.report_items WHERE report_id = NEW.report_id AND position = 0
            )
            BEGIN
                SELECT RAISE(ABORT, 'second item rejected after first item');
            END;
        ''')
        with closing(connect(self.path)) as observer:
            before = report_counts(observer)
            with self.assertRaisesRegex(PublishRejected, 'second item rejected after first item'):
                publish(self.db, left.seal_id, right.seal_id)
            self.assertFalse(self.db.in_transaction)
            self.assertEqual(report_counts(observer), before)
            self.assertEqual(report_counts(self.db), before)
            self.assertEqual(read(observer, old_id), original)
            self.assertEqual(SealStore(observer).get(left.seal_id), left)
            self.assertEqual(SealStore(observer).get(right.seal_id), right)
