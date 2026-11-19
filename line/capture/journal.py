from dataclasses import dataclass
from fractions import Fraction

from line.calibration.exact import fraction_from_storage, fraction_to_storage
from line.capture.identity import ReadingClaim, ReadingKey


@dataclass(frozen=True)
class AcceptedReading:
    claim: ReadingClaim
    sequence: int
    thickness_um: Fraction
    profile_version: int


class ReadingConflict(ValueError):
    pass


_READING_COLUMNS = '''shift_id, reading_id, station, specimen_id, seq, source_line,
                      raw_n, raw_d, thickness_n, thickness_d, profile_version'''


def _decode_reading(row):
    shift, reading, station, specimen, seq, line, raw_n, raw_d, um_n, um_d, version = row
    claim = ReadingClaim(ReadingKey(shift, reading), station, specimen,
                         fraction_from_storage(raw_n, raw_d), line)
    return AcceptedReading(claim, seq, fraction_from_storage(um_n, um_d), version)


class ReadingJournal:
    def __init__(self, db):
        self.db = db

    def accept(self, claim, thickness_um, profile_version):
        """Allocate the next sequence inside the admission write transaction."""
        if not self.db.in_transaction:
            raise RuntimeError('accept requires the admission transaction')
        original = self.get_reading(claim.key)
        if original is not None:
            if not original.claim.matches(claim):
                raise ReadingConflict(f'reading {claim.key.reading_id!r} has different original parameters')
            return original

        sequence = self.head(claim.key.shift_id, claim.station) + 1
        self.db.execute(f'''
            INSERT INTO readings({_READING_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (claim.key.shift_id, claim.key.reading_id, claim.station, claim.specimen_id, sequence,
              claim.source_line, *fraction_to_storage(claim.raw_code),
              *fraction_to_storage(thickness_um), profile_version))
        return AcceptedReading(claim, sequence, thickness_um, profile_version)

    def get_reading(self, key: ReadingKey):
        row = self.db.execute(
            f'SELECT {_READING_COLUMNS} FROM readings WHERE shift_id = ? AND reading_id = ?',
            (key.shift_id, key.reading_id),
        ).fetchone()
        return None if row is None else _decode_reading(row)

    def head(self, shift_id, station):
        return self.db.execute(
            'SELECT COALESCE(MAX(seq), 0) FROM readings WHERE shift_id = ? AND station = ?',
            (shift_id, station),
        ).fetchone()[0]

    def list_through(self, shift_id, station, cutoff):
        rows = self.db.execute(f'''
            SELECT {_READING_COLUMNS} FROM readings
            WHERE shift_id = ? AND station = ? AND seq <= ? ORDER BY seq
        ''', (shift_id, station, cutoff))
        return tuple(_decode_reading(row) for row in rows)


def initialize_capture(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS readings (
            shift_id TEXT NOT NULL,
            reading_id TEXT NOT NULL,
            station TEXT NOT NULL,
            specimen_id TEXT NOT NULL,
            seq INTEGER NOT NULL CHECK (seq > 0),
            source_line INTEGER NOT NULL CHECK (source_line > 0),
            raw_n TEXT NOT NULL, raw_d TEXT NOT NULL,
            thickness_n TEXT NOT NULL, thickness_d TEXT NOT NULL,
            profile_version INTEGER NOT NULL REFERENCES gauge_versions(version),
            PRIMARY KEY (shift_id, reading_id),
            UNIQUE (shift_id, station, seq),
            FOREIGN KEY (shift_id, specimen_id) REFERENCES roster_items(shift_id, specimen_id)
        )
    ''')
