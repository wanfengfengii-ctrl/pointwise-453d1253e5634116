import sqlite3

from line.calibration.conversion import RawCodeRejected, convert_raw
from line.calibration.exact import as_fraction, fraction_to_storage
from line.calibration.revisions import ProfileRevisions
from line.capture.anonymous import (READING_STREAM, STREAMS, TICKET_STREAM,
                                    AnonymousJournal, end_position, make_reading_arguments,
                                    make_ticket)
from line.capture.identity import make_reading_claim
from line.capture.journal import ReadingConflict, ReadingJournal
from line.capture.receipts import receipt_from_reading
from line.capture.recording import iter_recorded_readings
from line.intake.registry import ShiftRegistry
from line.workday import write_transaction


class IngestRejected(ValueError):
    pass


def _opened(db, shift_id, station):
    shift = ShiftRegistry(db).get_opened_shift(shift_id)
    if shift is None:
        raise IngestRejected(f'shift {shift_id!r} is not open')
    return shift


def _anonymous_shift(db, shift_id, station):
    """Return the opened shift only when this station runs the anonymous window."""
    shift = _opened(db, shift_id, station)
    if shift.anonymous_station != station:
        raise IngestRejected(f'station {station!r} does not run an anonymous window')
    return shift


def _check_end(db, shift_id, station, stream, source_seq):
    declared = AnonymousJournal(db).end(shift_id, station, stream)
    if declared is not None and source_seq > declared:
        raise IngestRejected(
            f'source sequence {source_seq} is beyond the declared end {declared} for {stream}')


def ingest(db, shift_id, station, specimen_id, reading_id, raw_code, source_line):
    try:
        claim = make_reading_claim(shift_id, station, specimen_id, reading_id, raw_code, source_line)
    except ValueError as exc:
        raise IngestRejected('invalid measurement input') from exc

    with write_transaction(db):
        shift = _opened(db, shift_id, station)
        if shift.anonymous_station == station:
            raise IngestRejected(f'station {station!r} runs an anonymous window')
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


def ingest_ticket(db, shift_id, station, source_seq, source_line, specimen_id, first_shot, last_shot):
    try:
        ticket = make_ticket(shift_id, station, source_seq, source_line, specimen_id,
                             first_shot, last_shot)
    except ValueError as exc:
        raise IngestRejected('invalid loading ticket') from exc

    with write_transaction(db):
        shift = _anonymous_shift(db, shift_id, station)
        if shift.roster.station_for(specimen_id) != station:
            raise IngestRejected(f'specimen {specimen_id!r} is not assigned to {station!r}')
        journal = AnonymousJournal(db)
        _check_end(db, shift_id, station, TICKET_STREAM, source_seq)
        original = journal.ticket(shift_id, station, source_seq)
        if original is not None:
            if not original.matches(source_line, specimen_id, first_shot, last_shot):
                raise IngestRejected(
                    f'ticket {source_seq} was already recorded with different parameters')
            return source_seq
        if journal.ticket_by_line(shift_id, station, source_line) is not None:
            raise IngestRejected(
                f'physical line {source_line} is already used by another ticket')
        if journal.ticket_for_specimen(shift_id, station, specimen_id) is not None:
            raise IngestRejected(f'specimen {specimen_id!r} already has a loading ticket')
        try:
            db.execute('''
                INSERT INTO anonymous_tickets(shift_id, station, source_seq, source_line,
                                              specimen_id, first_shot, last_shot)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (shift_id, station, source_seq, source_line, specimen_id, first_shot, last_shot))
        except sqlite3.IntegrityError as exc:
            raise IngestRejected(f'loading ticket {source_seq} was rejected') from exc
        return source_seq


def ingest_anonymous(db, shift_id, station, source_seq, source_line, shot, reading_id, raw_code):
    try:
        source_seq, source_line, shot, reading_id = make_reading_arguments(
            shift_id, station, source_seq, source_line, shot, reading_id)
    except ValueError as exc:
        raise IngestRejected('invalid anonymous reading') from exc

    with write_transaction(db):
        shift = _anonymous_shift(db, shift_id, station)
        journal = AnonymousJournal(db)
        _check_end(db, shift_id, station, READING_STREAM, source_seq)
        original = journal.reading(shift_id, station, source_seq)
        if original is not None:
            try:
                matches = original.matches_input(source_line, shot, reading_id, raw_code)
            except (TypeError, ValueError):
                matches = False
            if not matches:
                raise IngestRejected(
                    f'reading {source_seq} was already recorded with different parameters')
            return source_seq
        if journal.reading_by_line(shift_id, station, source_line) is not None:
            raise IngestRejected(
                f'physical line {source_line} is already used by another reading')
        if journal.reading_by_identifier(shift_id, station, reading_id) is not None:
            raise IngestRejected(f'reading identifier {reading_id!r} is already used')

        version = shift.version_for(station)
        profile = ProfileRevisions(db).get_version(version)
        try:
            original_raw = as_fraction(raw_code)
            thickness = convert_raw(profile, original_raw)
        except (RawCodeRejected, ValueError) as exc:
            raise IngestRejected(str(exc)) from exc
        try:
            db.execute('''
                INSERT INTO anonymous_readings(shift_id, station, source_seq, source_line, shot,
                                               reading_id, raw_n, raw_d, thickness_n, thickness_d,
                                               profile_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (shift_id, station, source_seq, source_line, shot, reading_id,
                  *fraction_to_storage(original_raw), *fraction_to_storage(thickness), version))
        except sqlite3.IntegrityError as exc:
            raise IngestRejected(f'anonymous reading {source_seq} was rejected') from exc
        return source_seq


def declare_end(db, shift_id, station, stream, last_seq):
    if stream not in STREAMS:
        raise IngestRejected(f'unknown stream {stream!r}')
    try:
        end_position(last_seq)
    except ValueError as exc:
        raise IngestRejected(str(exc)) from exc

    with write_transaction(db):
        _anonymous_shift(db, shift_id, station)
        journal = AnonymousJournal(db)
        existing = journal.end(shift_id, station, stream)
        if existing is not None:
            if existing != last_seq:
                raise IngestRejected(
                    f'the {stream} end is already declared as {existing}')
            return last_seq
        if last_seq < journal.maximum_position(shift_id, station, stream):
            raise IngestRejected(
                f'{stream} end {last_seq} is below an already received position')
        db.execute('''
            INSERT INTO anonymous_ends(shift_id, station, stream, last_seq) VALUES (?, ?, ?, ?)
        ''', (shift_id, station, stream, last_seq))
        return last_seq
