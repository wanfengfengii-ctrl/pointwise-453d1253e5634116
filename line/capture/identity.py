from dataclasses import dataclass
from fractions import Fraction

from line.calibration.exact import as_fraction
from line.intake.stations import valid_identifier
from line.workday import valid_database_id


@dataclass(frozen=True)
class ReadingKey:
    shift_id: str
    reading_id: str


@dataclass(frozen=True)
class ReadingClaim:
    key: ReadingKey
    station: str
    specimen_id: str
    raw_code: Fraction
    source_line: int

    def matches(self, other):
        return (self.key == other.key and self.station == other.station
                and self.specimen_id == other.specimen_id and self.raw_code == other.raw_code
                and self.source_line == other.source_line)


def make_reading_claim(shift_id, station, specimen_id, reading_id, raw_code, source_line):
    if not all(valid_identifier(value) for value in (shift_id, station, specimen_id, reading_id)):
        raise ValueError('shift, station, specimen and reading identifiers are required')
    if not valid_database_id(source_line):
        raise ValueError('recording line must be a positive integer')
    return ReadingClaim(ReadingKey(shift_id, reading_id), station, specimen_id,
                        as_fraction(raw_code), source_line)
