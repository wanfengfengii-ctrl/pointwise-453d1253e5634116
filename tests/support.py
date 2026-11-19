from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from line.calibration.revisions import calibrate
from line.capture.admission import ingest
from line.intake.shifts import open as open_shift, register
from line.workday import connect, initialize


SAMPLES = Path(__file__).resolve().parents[1] / 'samples'
ROSTER = (('R-A', 'R'), ('L-A', 'L'), ('R-B', 'R'), ('L-B', 'L'))


class LineCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='coating-test-')
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.path = self.folder / 'test.sqlite'
        self.db = connect(self.path)
        self.addCleanup(self.db.close)
        initialize(self.db)

    def register_day(self, shift_id='day'):
        return register(self.db, shift_id, 'L', 'R', ROSTER)

    def profile_pair(self, **left_overrides):
        left = {'gain': '3/2', 'offset_um': 1, 'raw_min': 0, 'raw_max': 20, 'limit_um': 16}
        left.update(left_overrides)
        return calibrate(self.db, 'L', **left), calibrate(self.db, 'R', 2, -1, 0, 20, 10)

    def open_day(self, shift_id='day', **left_overrides):
        self.register_day(shift_id)
        versions = self.profile_pair(**left_overrides)
        open_shift(self.db, shift_id, *versions)
        return versions

    def capture(self, specimen, reading_id, raw, line=2, *, station='L', shift_id='day'):
        return ingest(self.db, shift_id, station, specimen, reading_id, raw, line)


def report_counts(db):
    reports = db.execute('SELECT COUNT(*) FROM reports').fetchone()[0]
    items = db.execute('SELECT COUNT(*) FROM report_items').fetchone()[0]
    return reports, items
