"""Schema and value objects for the optional anonymous capture window.

Each anonymous window is scoped to one shift and one station. Its two
independent streams (loading tickets and anonymous gauge readings) use their
own positive-int source sequences and physical lines, both unique inside the
stream. Reading identifiers are validated by the ordinary identifier rules and
are independent from the named readings kept by the opposite station.
"""
from dataclasses import dataclass
from fractions import Fraction

from line.calibration.exact import as_fraction, fraction_from_storage
from line.intake.stations import valid_identifier

INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1

TICKET_STREAM = 'ticket'
READING_STREAM = 'reading'
STREAMS = (TICKET_STREAM, READING_STREAM)


def positive_integer(value, label):
    """Accept a positive signed 64-bit integer, never a boolean or float."""
    if type(value) is not int or not 1 <= value <= INT64_MAX:
        raise ValueError(f'{label} must be a positive 64-bit integer')
    return value


def signed_integer(value, label):
    """Accept any signed 64-bit integer, never a boolean or float."""
    if type(value) is not int or not INT64_MIN <= value <= INT64_MAX:
        raise ValueError(f'{label} must be a 64-bit integer')
    return value


def end_position(value):
    if type(value) is not int or not 0 <= value <= INT64_MAX:
        raise ValueError('end position must be a nonnegative 64-bit integer')
    return value


@dataclass(frozen=True)
class AnonymousTicket:
    source_seq: int
    source_line: int
    specimen_id: str
    first_shot: int
    last_shot: int

    def covers(self, shot):
        return self.first_shot <= shot <= self.last_shot

    def matches(self, source_line, specimen_id, first_shot, last_shot):
        return (self.source_line == source_line and self.specimen_id == specimen_id
                and self.first_shot == first_shot and self.last_shot == last_shot)


@dataclass(frozen=True)
class AnonymousOrigin:
    """The provenance attached to an anonymous reading in a sealed report."""

    shot: int
    ticket: AnonymousTicket


@dataclass(frozen=True)
class AnonymousKey:
    reading_id: str


@dataclass(frozen=True)
class AnonymousClaim:
    station: str
    specimen_id: str
    raw_code: Fraction
    source_line: int
    reading_id: str

    @property
    def key(self):
        return AnonymousKey(self.reading_id)


@dataclass(frozen=True)
class StoredReading:
    """One accepted anonymous reading exactly as the source delivered it."""

    shift_id: str
    station: str
    source_seq: int
    source_line: int
    shot: int
    reading_id: str
    raw_code: Fraction
    thickness_um: Fraction
    profile_version: int

    def matches_input(self, source_line, shot, reading_id, raw_code):
        try:
            raw = as_fraction(raw_code)
        except ValueError:
            return False
        return (self.source_line == source_line and self.shot == shot
                and self.reading_id == reading_id and self.raw_code == raw)


@dataclass(frozen=True)
class AnonymousReading:
    """An anonymous reading joined to the ticket it was sealed against."""

    station: str
    ticket: AnonymousTicket
    reading_id: str
    sequence: int
    source_line: int
    shot: int
    raw_code: Fraction
    thickness_um: Fraction
    profile_version: int

    @property
    def anonymous(self):
        return AnonymousOrigin(self.shot, self.ticket)

    @property
    def claim(self):
        return AnonymousClaim(self.station, self.ticket.specimen_id, self.raw_code,
                              self.source_line, self.reading_id)


def make_ticket(shift_id, station, source_seq, source_line, specimen_id, first_shot, last_shot):
    if not all(valid_identifier(value) for value in (shift_id, station, specimen_id)):
        raise ValueError('shift, station and specimen identifiers are required')
    positive_integer(source_seq, 'source sequence')
    positive_integer(source_line, 'physical line')
    first = signed_integer(first_shot, 'first shot')
    last = signed_integer(last_shot, 'last shot')
    if first > last:
        raise ValueError('first shot must not exceed last shot')
    return AnonymousTicket(source_seq, source_line, specimen_id, first, last)


def make_reading_arguments(shift_id, station, source_seq, source_line, shot, reading_id):
    if not all(valid_identifier(value) for value in (shift_id, station, reading_id)):
        raise ValueError('shift, station and reading identifiers are required')
    positive_integer(source_seq, 'source sequence')
    positive_integer(source_line, 'physical line')
    signed_integer(shot, 'shot')
    return source_seq, source_line, shot, reading_id


_TICKET_COLUMNS = 'shift_id, station, source_seq, source_line, specimen_id, first_shot, last_shot'
_READING_COLUMNS = ('shift_id, station, source_seq, source_line, shot, reading_id, '
                    'raw_n, raw_d, thickness_n, thickness_d, profile_version')


def _decode_ticket(row):
    _, _, source_seq, source_line, specimen_id, first_shot, last_shot = row
    return AnonymousTicket(source_seq, source_line, specimen_id, first_shot, last_shot)


def _decode_reading(row):
    (shift_id, station, source_seq, source_line, shot, reading_id, raw_n, raw_d,
     um_n, um_d, version) = row
    return StoredReading(shift_id, station, source_seq, source_line, shot, reading_id,
                         fraction_from_storage(raw_n, raw_d),
                         fraction_from_storage(um_n, um_d), version)


class AnonymousJournal:
    """Read-side access to the two anonymous streams."""

    def __init__(self, db):
        self.db = db

    def ticket(self, shift_id, station, source_seq):
        row = self.db.execute(
            f'SELECT {_TICKET_COLUMNS} FROM anonymous_tickets '
            'WHERE shift_id = ? AND station = ? AND source_seq = ?',
            (shift_id, station, source_seq)).fetchone()
        return None if row is None else _decode_ticket(row)

    def ticket_by_line(self, shift_id, station, source_line):
        row = self.db.execute(
            f'SELECT {_TICKET_COLUMNS} FROM anonymous_tickets '
            'WHERE shift_id = ? AND station = ? AND source_line = ?',
            (shift_id, station, source_line)).fetchone()
        return None if row is None else _decode_ticket(row)

    def ticket_for_specimen(self, shift_id, station, specimen_id):
        row = self.db.execute(
            f'SELECT {_TICKET_COLUMNS} FROM anonymous_tickets '
            'WHERE shift_id = ? AND station = ? AND specimen_id = ?',
            (shift_id, station, specimen_id)).fetchone()
        return None if row is None else _decode_ticket(row)

    def reading(self, shift_id, station, source_seq):
        row = self.db.execute(
            f'SELECT {_READING_COLUMNS} FROM anonymous_readings '
            'WHERE shift_id = ? AND station = ? AND source_seq = ?',
            (shift_id, station, source_seq)).fetchone()
        return None if row is None else _decode_reading(row)

    def reading_by_line(self, shift_id, station, source_line):
        row = self.db.execute(
            f'SELECT {_READING_COLUMNS} FROM anonymous_readings '
            'WHERE shift_id = ? AND station = ? AND source_line = ?',
            (shift_id, station, source_line)).fetchone()
        return None if row is None else _decode_reading(row)

    def reading_by_identifier(self, shift_id, station, reading_id):
        row = self.db.execute(
            f'SELECT {_READING_COLUMNS} FROM anonymous_readings '
            'WHERE shift_id = ? AND station = ? AND reading_id = ?',
            (shift_id, station, reading_id)).fetchone()
        return None if row is None else _decode_reading(row)

    def tickets(self, shift_id, station):
        rows = self.db.execute(
            f'SELECT {_TICKET_COLUMNS} FROM anonymous_tickets '
            'WHERE shift_id = ? AND station = ? ORDER BY source_seq',
            (shift_id, station))
        return tuple(_decode_ticket(row) for row in rows)

    def readings(self, shift_id, station):
        rows = self.db.execute(
            f'SELECT {_READING_COLUMNS} FROM anonymous_readings '
            'WHERE shift_id = ? AND station = ? ORDER BY source_seq',
            (shift_id, station))
        return tuple(_decode_reading(row) for row in rows)

    def positions(self, shift_id, station, stream):
        if stream == TICKET_STREAM:
            table = 'anonymous_tickets'
        elif stream == READING_STREAM:
            table = 'anonymous_readings'
        else:
            raise ValueError(f'unknown stream {stream!r}')
        return tuple(row[0] for row in self.db.execute(
            f'SELECT source_seq FROM {table} WHERE shift_id = ? AND station = ? ORDER BY source_seq',
            (shift_id, station)))

    def maximum_position(self, shift_id, station, stream):
        positions = self.positions(shift_id, station, stream)
        return positions[-1] if positions else 0

    def end(self, shift_id, station, stream):
        row = self.db.execute(
            'SELECT last_seq FROM anonymous_ends '
            'WHERE shift_id = ? AND station = ? AND stream = ?',
            (shift_id, station, stream)).fetchone()
        return None if row is None else row[0]


def initialize_anonymous_capture(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS anonymous_tickets (
            shift_id TEXT NOT NULL,
            station TEXT NOT NULL,
            source_seq INTEGER NOT NULL CHECK (source_seq > 0),
            source_line INTEGER NOT NULL CHECK (source_line > 0),
            specimen_id TEXT NOT NULL,
            first_shot INTEGER NOT NULL,
            last_shot INTEGER NOT NULL,
            CHECK (first_shot <= last_shot),
            PRIMARY KEY (shift_id, station, source_seq),
            UNIQUE (shift_id, station, source_line),
            UNIQUE (shift_id, station, specimen_id),
            FOREIGN KEY (shift_id, specimen_id) REFERENCES roster_items(shift_id, specimen_id)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS anonymous_readings (
            shift_id TEXT NOT NULL,
            station TEXT NOT NULL,
            source_seq INTEGER NOT NULL CHECK (source_seq > 0),
            source_line INTEGER NOT NULL CHECK (source_line > 0),
            shot INTEGER NOT NULL,
            reading_id TEXT NOT NULL,
            raw_n TEXT NOT NULL, raw_d TEXT NOT NULL,
            thickness_n TEXT NOT NULL, thickness_d TEXT NOT NULL,
            profile_version INTEGER NOT NULL REFERENCES gauge_versions(version),
            PRIMARY KEY (shift_id, station, source_seq),
            UNIQUE (shift_id, station, source_line),
            UNIQUE (shift_id, station, reading_id)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS anonymous_ends (
            shift_id TEXT NOT NULL,
            station TEXT NOT NULL,
            stream TEXT NOT NULL CHECK (stream IN ('ticket', 'reading')),
            last_seq INTEGER NOT NULL CHECK (last_seq >= 0),
            PRIMARY KEY (shift_id, station, stream)
        )
    ''')
