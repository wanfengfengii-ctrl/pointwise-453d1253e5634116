from line.calibration.conversion import RawCodeRejected, convert_raw
from line.calibration.revisions import ProfileRevisions
from line.capture.identity import make_reading_claim
from line.capture.journal import ReadingConflict, ReadingJournal
from line.capture.receipts import receipt_from_reading
from line.capture.recording import iter_recorded_readings
from line.intake.registry import ShiftRegistry
from line.workday import write_transaction


class IngestRejected(ValueError):
    pass


def ingest(db, shift_id, station, specimen_id, reading_id, raw_code, source_line):
    try:
        claim = make_reading_claim(shift_id, station, specimen_id, reading_id, raw_code, source_line)
    except ValueError as exc:
        raise IngestRejected('invalid measurement input') from exc

    with write_transaction(db):
        shift = ShiftRegistry(db).get_opened_shift(shift_id)
        if shift is None:
            raise IngestRejected(f'shift {shift_id!r} is not open')
        if shift.roster.station_for(specimen_id) != station:
            raise IngestRejected(f'specimen {specimen_id!r} is not assigned to {station!r}')
        version = shift.version_for(station)
        profile = ProfileRevisions(db).get_version(version)
        try:
            thickness = convert_raw(profile, claim.raw_code)
            accepted = ReadingJournal(db).accept(claim, thickness, version)
        except (RawCodeRejected, ReadingConflict) as exc:
            raise IngestRejected(str(exc)) from exc
        return receipt_from_reading(accepted)


def ingest_recording(db, shift_id, station, source):
    receipts = []
    for row in iter_recorded_readings(source):
        receipts.append(ingest(db, shift_id, station, row.specimen_id, row.reading_id,
                               row.raw_code, row.source_line))
    return tuple(receipts)
