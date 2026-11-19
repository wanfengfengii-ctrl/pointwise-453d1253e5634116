from dataclasses import dataclass

from line.intake.roster import Roster, RosterItem
from line.intake.stations import StationPair


@dataclass(frozen=True)
class RegisteredShift:
    shift_id: str
    stations: StationPair
    roster: Roster


@dataclass(frozen=True)
class OpenedShift(RegisteredShift):
    left_version: int
    right_version: int
    anonymous_station: str | None = None

    def version_for(self, station):
        side = self.stations.side_of(station)
        return self.left_version if side == 'left' else self.right_version


class ShiftRegistry:
    def __init__(self, db):
        self.db = db

    def insert_registration(self, registration):
        shift_id = registration.shift_id
        self.db.execute(
            'INSERT INTO shifts(shift_id, left_station, right_station) VALUES (?, ?, ?)',
            (shift_id, registration.stations.left, registration.stations.right),
        )
        self.db.executemany(
            'INSERT INTO roster_items(shift_id, position, specimen_id, station) VALUES (?, ?, ?, ?)',
            ((shift_id, item.position, item.specimen_id, item.station) for item in registration.roster.items),
        )

    def _shift_row(self, shift_id):
        return self.db.execute(
            'SELECT left_station, right_station, left_version, right_version, anonymous_station '
            'FROM shifts WHERE shift_id = ?',
            (shift_id,),
        ).fetchone()

    def _roster(self, shift_id):
        rows = self.db.execute(
            'SELECT position, specimen_id, station FROM roster_items WHERE shift_id = ? ORDER BY position',
            (shift_id,),
        )
        return Roster(tuple(RosterItem(*row) for row in rows))

    def get_registration(self, shift_id):
        row = self._shift_row(shift_id)
        if row is None:
            return None
        return RegisteredShift(shift_id, StationPair(row[0], row[1]), self._roster(shift_id))

    def freeze_shift(self, shift_id, left_version, right_version, anonymous_station=None):
        result = self.db.execute(
            'UPDATE shifts SET left_version = ?, right_version = ?, anonymous_station = ? '
            'WHERE shift_id = ? AND left_version IS NULL',
            (left_version, right_version, anonymous_station, shift_id),
        )
        return result.rowcount == 1

    def get_opened_shift(self, shift_id):
        row = self._shift_row(shift_id)
        if row is None or row[2] is None:
            return None
        left, right, left_version, right_version, anonymous_station = row
        return OpenedShift(shift_id, StationPair(left, right), self._roster(shift_id),
                           left_version, right_version, anonymous_station)


def initialize_intake(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            shift_id TEXT PRIMARY KEY NOT NULL,
            left_station TEXT NOT NULL,
            right_station TEXT NOT NULL CHECK (right_station <> left_station),
            left_version INTEGER REFERENCES gauge_versions(version),
            right_version INTEGER REFERENCES gauge_versions(version),
            CHECK ((left_version IS NULL) = (right_version IS NULL))
        )
    ''')
    _ensure_anonymous_column(db)
    db.execute('''
        CREATE TABLE IF NOT EXISTS roster_items (
            shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
            position INTEGER NOT NULL CHECK (position >= 0),
            specimen_id TEXT NOT NULL,
            station TEXT NOT NULL,
            PRIMARY KEY (shift_id, specimen_id),
            UNIQUE (shift_id, position)
        )
    ''')


def _ensure_anonymous_column(db):
    columns = {row[1] for row in db.execute('PRAGMA table_info(shifts)')}
    if 'anonymous_station' not in columns:
        db.execute('ALTER TABLE shifts ADD COLUMN anonymous_station TEXT')
