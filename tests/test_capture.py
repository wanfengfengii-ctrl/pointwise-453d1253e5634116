from fractions import Fraction
from io import StringIO
import json

from line.capture.admission import IngestRejected, ingest_recording
from line.capture.identity import ReadingKey
from line.capture.journal import ReadingJournal
from line.capture.recording import RecordingFormatError
from line.closing.cut import seal
from line.report.publish import publish
from line.report.readback import read
from tests.support import LineCase, SAMPLES


class CaptureTests(LineCase):
    def test_exact_threshold(self):
        self.open_day()
        receipt = self.capture('L-A', 'L1', 10)
        self.assertEqual(receipt.thickness_um, Fraction(16))
        detail = seal(self.db, 'day', 'L', 1).details[0]
        self.assertEqual((detail.count, detail.maximum_um, detail.status), (1, Fraction(16), 'within_limit'))

    def test_fractional_equality(self):
        self.open_day(gain='1/10', offset_um='1/5', limit_um='3/10')
        receipt = self.capture('L-A', 'L1', 1)
        self.assertEqual(receipt.thickness_um, Fraction(3, 10))
        left = seal(self.db, 'day', 'L', 1)
        report_id = publish(self.db, left.seal_id, seal(self.db, 'day', 'R', 0).seal_id)
        detail = left.details[0]
        evidence = read(self.db, report_id).items[1]
        self.assertEqual((detail.maximum_um, detail.status), (Fraction(3, 10), 'within_limit'))
        self.assertEqual((evidence.maximum_um, evidence.status, evidence.readings[0].thickness_um),
                         (Fraction(3, 10), 'within_limit', Fraction(3, 10)))
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v3.fractional_equality',
            'input': {'raw': 1, 'gain': '1/10', 'offset_um': '1/5', 'limit_um': '3/10'},
            'expected': '3/10', 'actual': str(receipt.thickness_um),
            'downstream_expected': {'maximum_um': '3/10', 'status': 'within_limit'},
            'downstream_actual': {'maximum_um': str(evidence.maximum_um), 'status': evidence.status},
            'code_paths': ['line/calibration/conversion.py', 'line/capture/admission.py',
                           'line/closing/quality.py', 'line/report/readback.py'],
            'oracle': 'One tenth plus two tenths is three tenths. Strict greater-than is false at equality.'
        }, sort_keys=True))

    def test_raw_range_endpoints(self):
        self.open_day(raw_min=0, raw_max=10)
        self.assertEqual(self.capture('L-A', 'L1', 0).thickness_um, Fraction(1))
        for raw in (-1, 11, None, '', 'NaN', True, 1.25):
            with self.subTest(raw=raw):
                with self.assertRaises(IngestRejected):
                    self.capture('L-A', 'bad', raw)
        receipt = self.capture('L-A', 'L2', 10)
        self.assertEqual((receipt.sequence, receipt.thickness_um), (2, Fraction(16)))
        self.assertEqual(ReadingJournal(self.db).head('day', 'L'), 2)

    def test_wrong_station(self):
        self.open_day()
        with self.assertRaises(IngestRejected):
            self.capture('L-A', 'bad', 4, station='R')
        self.assertEqual(self.capture('R-A', 'R1', 4, station='R').sequence, 1)
        detail = seal(self.db, 'day', 'R', 1).details[0]
        self.assertEqual((detail.specimen_id, detail.count, detail.readings[0].claim.key.reading_id),
                         ('R-A', 1, 'R1'))

    def test_local_sequences(self):
        self.open_day()
        self.open_day('next')
        left_first = self.capture('L-A', 'shared', 0)
        with self.assertRaises(IngestRejected):
            self.capture('R-A', 'shared', 0, station='R')
        right_first = self.capture('R-A', 'R1', 0, station='R')
        left_second = self.capture('L-B', 'L2', 4, 3)
        other_shift = self.capture('L-A', 'shared', 4, shift_id='next')
        right_second = self.capture('R-B', 'R2', 4, 3, station='R')
        self.assertEqual([r.sequence for r in (left_first, right_first, left_second, other_shift, right_second)],
                         [1, 1, 2, 1, 2])

    def test_replay_and_conflict(self):
        self.open_day()
        original = self.capture('L-A', 'L1', 10, 4)
        self.assertEqual(self.capture('L-A', 'L1', '10/1', 4), original)
        for specimen, raw in (('L-A', 9), ('L-B', 10)):
            with self.assertRaises(IngestRejected):
                self.capture(specimen, 'L1', raw, 4)
        original_row = ReadingJournal(self.db).get_reading(ReadingKey('day', 'L1'))
        self.assertEqual((original_row.sequence, original_row.claim.raw_code), (1, Fraction(10)))
        self.assertEqual(self.capture('L-A', 'L2', 4, 5).sequence, 2)

    def test_source_line_conflict(self):
        self.open_day()
        with (SAMPLES / 'left.csv').open(encoding='utf-8', newline='') as source:
            first, second = ingest_recording(self.db, 'day', 'L', source)
        self.assertEqual(self.capture('L-A', 'L2', 10, 4), second)
        with self.assertRaises(IngestRejected):
            self.capture('L-A', 'L2', 10, 9)
        malformed = StringIO('specimen_id,reading_id,raw_code\n\nL-A,broken,\n')
        with self.assertRaisesRegex(RecordingFormatError, 'line 3'):
            ingest_recording(self.db, 'day', 'L', malformed)
        detail = seal(self.db, 'day', 'L', 2).details[0]
        self.assertEqual((first.sequence, second.sequence, detail.count), (1, 2, 2))
        self.assertEqual([row.claim.source_line for row in detail.readings], [2, 4])
        self.assertEqual(self.capture('L-A', 'L3', 4, 5).sequence, 3)
