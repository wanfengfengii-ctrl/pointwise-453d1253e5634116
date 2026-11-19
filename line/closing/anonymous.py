"""Match anonymous tickets to anonymous readings and seal the fixed account.

A complete pairing joins every ticket to exactly one reading and every reading
to exactly one ticket. A reading fits a ticket when its shot falls inside the
ticket's closed shot interval. Readings are separate nodes keyed by their
physical record, so equal raw codes never collapse into one another.
"""
import sqlite3

from line.calibration.exact import fraction_to_storage
from line.calibration.revisions import ProfileRevisions
from line.capture.anonymous import STREAMS, AnonymousJournal, AnonymousReading
from line.closing.cut import SealRejected
from line.closing.measurements import SpecimenMeasurements
from line.closing.quality import judge_specimen
from line.intake.registry import ShiftRegistry
from line.intake.stations import valid_identifier
from line.workday import write_transaction


PENDING = 'pending'
NO_MATCH = 'no_match'
AMBIGUOUS = 'ambiguous'
SEALED = 'sealed'


def _stream_complete(journal, shift_id, station, stream):
    end = journal.end(shift_id, station, stream)
    if end is None:
        return False
    positions = journal.positions(shift_id, station, stream)
    return positions == tuple(range(1, end + 1))


def _edges(tickets, readings):
    """Adjacency: which physical readings fall inside each ticket's shot interval."""
    return [[index for index, reading in enumerate(readings) if ticket.covers(reading.shot)]
            for ticket in tickets]


def _perfect_matching(tickets, readings):
    """Return one perfect ticket->reading assignment, or None when none exists."""
    edges = _edges(tickets, readings)
    count = len(tickets)
    match_reading = [-1] * count
    match_ticket = [-1] * count

    def augment(ticket, seen):
        for reading in edges[ticket]:
            if seen[reading]:
                continue
            seen[reading] = True
            if match_reading[reading] == -1 or augment(match_reading[reading], seen):
                match_reading[reading] = ticket
                match_ticket[ticket] = reading
                return True
        return False

    for ticket in range(count):
        if not augment(ticket, [False] * count):
            return None, edges
    return match_ticket, edges


def _unique_perfect_matching(match_ticket, edges):
    """A perfect matching is unique exactly when its alternating graph is acyclic."""
    count = len(match_ticket)
    graph = [[] for _ in range(2 * count)]
    for ticket in range(count):
        graph[ticket].append(count + match_ticket[ticket])
    for ticket in range(count):
        for reading in edges[ticket]:
            if match_ticket[ticket] != reading:
                graph[count + reading].append(ticket)

    color = [0] * (2 * count)

    def visit(node):
        color[node] = 1
        for neighbour in graph[node]:
            if color[neighbour] == 1:
                return False
            if color[neighbour] == 0 and not visit(neighbour):
                return False
        color[node] = 2
        return True

    return all(color[node] != 0 or visit(node) for node in range(2 * count))


def _classify(journal, shift_id, station):
    """Return (state, {ticket source_seq: accepted reading}) for a complete window."""
    tickets = journal.tickets(shift_id, station)
    readings = journal.readings(shift_id, station)
    if len(tickets) != len(readings):
        return NO_MATCH, None
    if not tickets:
        return SEALED, {}
    match_ticket, edges = _perfect_matching(tickets, readings)
    if match_ticket is None:
        return NO_MATCH, None
    if not _unique_perfect_matching(match_ticket, edges):
        return AMBIGUOUS, None
    assignment = {tickets[index].source_seq: readings[reading]
                  for index, reading in enumerate(match_ticket)}
    return SEALED, assignment


def _build_details(shift, station, tickets, assignment, profile):
    """Join each assigned reading to its ticket and judge the frozen thickness."""
    details = []
    for item in shift.roster.items_for(station):
        ticket = next((t for t in tickets if t.specimen_id == item.specimen_id), None)
        readings = []
        if ticket is not None and ticket.source_seq in assignment:
            reading = assignment[ticket.source_seq]
            readings.append(AnonymousReading(
                station, ticket, reading.reading_id, reading.source_seq, reading.source_line,
                reading.shot, reading.raw_code, reading.thickness_um, reading.profile_version))
        peak = max((row.thickness_um for row in readings), default=None)
        measurements = SpecimenMeasurements(item.position, item.specimen_id, len(readings),
                                            peak, tuple(readings))
        details.append(judge_specimen(measurements, profile.limit_um))
    return tuple(details)


def _store(db, shift, station, details, profile_version):
    cursor = db.execute('''
        INSERT INTO station_seals(shift_id, station, side, cutoff, profile_version, anonymous)
        VALUES (?, ?, ?, ?, ?, 1)
    ''', (shift.shift_id, station, shift.stations.side_of(station), 0, profile_version))
    seal_id = cursor.lastrowid
    for detail in details:
        peak = (None, None) if detail.maximum_um is None else fraction_to_storage(detail.maximum_um)
        db.execute('''
            INSERT INTO seal_details(seal_id, position, specimen_id, count, max_n, max_d, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (seal_id, detail.position, detail.specimen_id, detail.count, *peak, detail.status))
        db.executemany('''
            INSERT INTO anonymous_seal_readings(seal_id, position, evidence_order, shift_id,
                                                station, reading_seq, ticket_seq)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ((seal_id, detail.position, order, shift.shift_id, station,
               reading.sequence, reading.ticket.source_seq)
              for order, reading in enumerate(detail.readings)))
    return seal_id


def _existing_seal(db, shift_id, station):
    row = db.execute(
        'SELECT seal_id FROM station_seals WHERE shift_id = ? AND station = ? AND anonymous = 1',
        (shift_id, station)).fetchone()
    return None if row is None else row[0]


def seal_anonymous(db, shift_id, station):
    if not valid_identifier(shift_id) or not valid_identifier(station):
        raise SealRejected('a valid shift and station are required')

    try:
        with write_transaction(db):
            shift = ShiftRegistry(db).get_opened_shift(shift_id)
            if shift is None or shift.anonymous_station != station:
                raise SealRejected(f'station {station!r} has no anonymous window on this shift')
            existing = _existing_seal(db, shift_id, station)
            if existing is not None:
                return SEALED, existing

            journal = AnonymousJournal(db)
            if not all(_stream_complete(journal, shift_id, station, stream) for stream in STREAMS):
                return PENDING, None

            state, assignment = _classify(journal, shift_id, station)
            if state != SEALED:
                return state, None

            version = shift.version_for(station)
            profile = ProfileRevisions(db).get_version(version)
            tickets = journal.tickets(shift_id, station)
            details = _build_details(shift, station, tickets, assignment, profile)
            seal_id = _store(db, shift, station, details, version)
            return SEALED, seal_id
    except sqlite3.Error as exc:
        raise SealRejected(f'anonymous seal could not be committed: {exc}') from exc
