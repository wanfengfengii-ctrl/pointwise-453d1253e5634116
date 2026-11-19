from dataclasses import dataclass

from line.calibration.exact import fraction_from_storage, fraction_to_storage
from line.calibration.profiles import GaugeProfile
from line.calibration.revisions import ProfileRevisions
from line.capture.identity import ReadingKey
from line.capture.journal import ReadingJournal
from line.closing.prefix import SealPrefix
from line.closing.quality import QualityDetail
from line.workday import valid_database_id


@dataclass(frozen=True)
class StationSeal:
    seal_id: int
    shift_id: str
    station: str
    side: str
    cutoff: int
    profile_version: int
    profile: GaugeProfile
    details: tuple[QualityDetail, ...]


class SealStore:
    def __init__(self, db):
        self.db = db

    def save(self, prefix: SealPrefix, details: tuple[QualityDetail, ...]):
        cursor = self.db.execute('''
            INSERT INTO station_seals(shift_id, station, side, cutoff, profile_version)
            VALUES (?, ?, ?, ?, ?)
        ''', (prefix.shift_id, prefix.station, prefix.side, prefix.cutoff, prefix.profile_version))
        seal_id = cursor.lastrowid
        for detail in details:
            peak = (None, None) if detail.maximum_um is None else fraction_to_storage(detail.maximum_um)
            self.db.execute('''
                INSERT INTO seal_details(seal_id, position, specimen_id, count, max_n, max_d, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (seal_id, detail.position, detail.specimen_id, detail.count, *peak, detail.status))
            self.db.executemany('''
                INSERT INTO seal_readings(seal_id, position, evidence_order, shift_id, reading_id)
                VALUES (?, ?, ?, ?, ?)
            ''', ((seal_id, detail.position, order, reading.claim.key.shift_id, reading.claim.key.reading_id)
                  for order, reading in enumerate(detail.readings)))
        return StationSeal(seal_id, prefix.shift_id, prefix.station, prefix.side, prefix.cutoff,
                           prefix.profile_version, prefix.profile, details)

    def get(self, seal_id):
        if not valid_database_id(seal_id):
            return None
        row = self.db.execute('''
            SELECT shift_id, station, side, cutoff, profile_version FROM station_seals WHERE seal_id = ?
        ''', (seal_id,)).fetchone()
        if row is None:
            return None
        shift_id, station, side, cutoff, version = row
        profile = ProfileRevisions(self.db).get_version(version)
        return StationSeal(seal_id, shift_id, station, side, cutoff, version, profile,
                           self._get_details(seal_id))

    def _get_details(self, seal_id):
        journal = ReadingJournal(self.db)
        refs = self.db.execute('''
            SELECT position, shift_id, reading_id FROM seal_readings
            WHERE seal_id = ? ORDER BY position, evidence_order
        ''', (seal_id,))
        readings_by_position = {}
        for position, shift_id, reading_id in refs:
            reading = journal.get_reading(ReadingKey(shift_id, reading_id))
            if reading is None:
                raise LookupError(f'seal {seal_id} references missing reading {reading_id!r}')
            readings_by_position.setdefault(position, []).append(reading)

        rows = self.db.execute('''
            SELECT position, specimen_id, count, max_n, max_d, status
            FROM seal_details WHERE seal_id = ? ORDER BY position
        ''', (seal_id,))
        details = []
        for position, specimen_id, count, numerator, denominator, status in rows:
            peak = None if numerator is None else fraction_from_storage(numerator, denominator)
            readings = tuple(readings_by_position.get(position, ()))
            details.append(QualityDetail(position, specimen_id, count, peak, status, readings))
        return tuple(details)


def initialize_closing(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS station_seals (
            seal_id INTEGER PRIMARY KEY,
            shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
            station TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('left', 'right')),
            cutoff INTEGER NOT NULL CHECK (cutoff >= 0),
            profile_version INTEGER NOT NULL REFERENCES gauge_versions(version)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS seal_details (
            seal_id INTEGER NOT NULL REFERENCES station_seals(seal_id),
            position INTEGER NOT NULL CHECK (position >= 0),
            specimen_id TEXT NOT NULL,
            count INTEGER NOT NULL CHECK (count >= 0),
            max_n TEXT, max_d TEXT,
            status TEXT NOT NULL CHECK (status IN ('missing', 'within_limit', 'over_limit')),
            CHECK ((max_n IS NULL) = (max_d IS NULL)),
            CHECK ((count = 0) = (max_n IS NULL)),
            CHECK ((count = 0) = (status = 'missing')),
            PRIMARY KEY (seal_id, position),
            UNIQUE (seal_id, specimen_id)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS seal_readings (
            seal_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            evidence_order INTEGER NOT NULL CHECK (evidence_order >= 0),
            shift_id TEXT NOT NULL,
            reading_id TEXT NOT NULL,
            PRIMARY KEY (seal_id, position, evidence_order),
            UNIQUE (seal_id, shift_id, reading_id),
            FOREIGN KEY (seal_id, position) REFERENCES seal_details(seal_id, position),
            FOREIGN KEY (shift_id, reading_id) REFERENCES readings(shift_id, reading_id)
        )
    ''')
