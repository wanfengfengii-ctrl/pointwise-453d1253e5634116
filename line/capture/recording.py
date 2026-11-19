import csv
from dataclasses import dataclass
from fractions import Fraction

from line.calibration.exact import as_fraction
from line.intake.stations import valid_identifier


class RecordingFormatError(ValueError):
    pass


@dataclass(frozen=True)
class RecordedReading:
    specimen_id: str
    reading_id: str
    raw_code: Fraction
    source_line: int


def iter_recorded_readings(source):
    reader = csv.reader(source, strict=True)
    try:
        header = next(reader, None)
    except csv.Error as exc:
        raise RecordingFormatError('invalid recording header at line 1') from exc
    if header != ['specimen_id', 'reading_id', 'raw_code']:
        raise RecordingFormatError('expected specimen_id, reading_id, raw_code at line 1')

    while True:
        start_line = reader.line_num + 1
        try:
            row = next(reader)
        except StopIteration:
            return
        except csv.Error as exc:
            raise RecordingFormatError(f'invalid CSV at line {start_line}') from exc
        if not row:
            continue
        if len(row) != 3 or not all(valid_identifier(value) for value in row[:2]):
            raise RecordingFormatError(f'invalid reading fields at line {start_line}')
        specimen_id, reading_id, raw_code = row
        try:
            exact_code = as_fraction(raw_code)
        except ValueError as exc:
            raise RecordingFormatError(f'invalid raw code at line {start_line}') from exc
        yield RecordedReading(specimen_id, reading_id, exact_code, start_line)
