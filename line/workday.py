from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3


def connect(path):
    """Open a connection for the line's explicit transactions."""
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        db.close()
        raise
    return db


@contextmanager
def write_transaction(db):
    if db.in_transaction:
        raise sqlite3.ProgrammingError('line operation requires an idle connection')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def valid_database_id(value):
    return type(value) is int and 0 < value <= (1 << 63) - 1


def initialize(db):
    from line.calibration.revisions import initialize_calibration
    from line.intake.registry import initialize_intake
    from line.capture.journal import initialize_capture
    from line.capture.anonymous import initialize_anonymous_capture
    from line.closing.store import initialize_closing
    from line.report.catalog import initialize_reports

    with write_transaction(db):
        initialize_calibration(db)
        initialize_intake(db)
        initialize_capture(db)
        initialize_anonymous_capture(db)
        initialize_closing(db)
        initialize_reports(db)


def _demonstrate(directory):
    import json
    from shutil import copyfile

    from line.calibration.revisions import calibrate
    from line.capture.admission import ingest, ingest_recording
    from line.closing.cut import seal
    from line.intake.shifts import open as open_shift, register
    from line.report.publish import publish
    from line.report.readback import read

    samples = Path(__file__).resolve().parents[1] / 'samples'
    recordings = [directory / name for name in ('left.csv', 'right.csv')]
    database = directory / 'workday.sqlite'
    for path in recordings:
        copyfile(samples / path.name, path)

    with closing(connect(database)) as db:
        initialize(db)
        roster = [('R-A', 'R'), ('L-A', 'L'), ('R-B', 'R'), ('L-B', 'L')]
        register(db, 'day', 'L', 'R', roster)
        left_version = calibrate(db, 'L', '3/2', 1, 0, 20, 16)
        right_version = calibrate(db, 'R', 2, -1, 0, 20, 10)
        open_shift(db, 'day', left_version, right_version)
        for station, path in zip(('L', 'R'), recordings, strict=True):
            with path.open(encoding='utf-8', newline='') as source:
                ingest_recording(db, 'day', station, source)
        left = seal(db, 'day', 'L', 2)
        right = seal(db, 'day', 'R', 1)
        original_id = publish(db, left.seal_id, right.seal_id)

    for path in recordings:
        path.unlink()

    with closing(connect(database)) as db:
        ingest(db, 'day', 'L', 'L-A', 'L3', 12, 5)
        later_left = seal(db, 'day', 'L', 3)
        later_id = publish(db, later_left.seal_id, right.seal_id)
        initialize(db)

    with closing(connect(database)) as db:
        original = read(db, original_id)
        later = read(db, later_id)

    original_left = original.items[1]
    expected = {'parents': [left.seal_id, right.seal_id], 'roster': ['R-A', 'L-A', 'R-B', 'L-B'],
                'maxima_um': ['7', '16', None, None], 'left_source_lines': [2, 4],
                'left_raw_codes': ['0', '10'], 'left_profile': left_version, 'left_status': 'within_limit'}
    actual = {'parents': [original.left_seal_id, original.right_seal_id],
              'roster': [item.specimen_id for item in original.items],
              'maxima_um': [None if item.maximum_um is None else str(item.maximum_um)
                            for item in original.items],
              'left_source_lines': [row.source_line for row in original_left.readings],
              'left_raw_codes': [str(row.raw_code) for row in original_left.readings],
              'left_profile': original_left.profile_version, 'left_status': original_left.status}
    downstream_expected = {'left_max_um': '19', 'left_status': 'over_limit', 'left_count': 3}
    downstream_actual = {'left_max_um': str(later.items[1].maximum_um),
                         'left_status': later.items[1].status, 'left_count': later.items[1].count}
    if (actual, downstream_actual) != (expected, downstream_expected):
        raise AssertionError((actual, downstream_actual))
    print(f'Issued reports {original_id} and {later_id}; retrieved both after removing the recordings.')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'v7', 'input': {'initial_cuts': [2, 1], 'later_left_cut': 3,
                                   'added_raw_code': 12, 'recordings_available': any(p.exists() for p in recordings)},
        'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': ['line/capture/admission.py', 'line/closing/cut.py',
                       'line/report/publish.py', 'line/report/readback.py'],
        'oracle': 'Left 10 times 3/2 plus 1 is 16, left 12 is 19, and right 4 times 2 minus 1 is 7. The first report retains its two issued seal numbers and rows 2 and 4.'
    }, sort_keys=True))


def _demonstrate_anonymous(directory):
    """Late arrival, rejected commit retry, and claim after the sources stop."""
    import json
    import sqlite3
    from shutil import copyfile

    from line.calibration.revisions import calibrate
    from line.capture.admission import declare_end, ingest, ingest_anonymous, ingest_ticket
    from line.closing.cut import seal, seal_anonymous
    from line.intake.shifts import open as open_shift, register
    from line.report.publish import publish
    from line.report.readback import read

    fixture = Path(__file__).resolve().parents[1] / 'samples' / 'station_events.json'
    sample = json.loads(fixture.read_text(encoding='utf-8'))
    live = directory / fixture.name
    copyfile(fixture, live)
    database = directory / 'anonymous.sqlite'

    with closing(connect(database)) as db:
        initialize(db)
        register(db, 'late', 'L', 'R', [tuple(entry) for entry in sample['roster']])
        versions = [calibrate(db, station, 1, 0, 0, 20, 10) for station in ('L', 'R')]
        open_shift(db, 'late', *versions, anonymous_station='L')
        ingest(db, 'late', 'R', *sample['right_reading'])
        right_id = seal(db, 'late', 'R', 1).seal_id

        declare_end(db, 'late', 'L', 'ticket', 2)
        declare_end(db, 'late', 'L', 'reading', 2)
        ingest_ticket(db, 'late', 'L', 2, 7, 'L-B', 1, 1)
        ingest_anonymous(db, 'late', 'L', 1, 3, 1, 'r1', 7)
        early = seal_anonymous(db, 'late', 'L')
        ingest_ticket(db, 'late', 'L', 1, 4, 'L-A', 1, 2)
        middle = seal_anonymous(db, 'late', 'L')
        ingest_anonymous(db, 'late', 'L', 2, 9, 2, 'r2', 13)

        with closing(connect(database)) as observer:
            before = observer.execute('SELECT COUNT(*) FROM station_seals').fetchone()[0]

            def authorizer(operation, argument, *_):
                if operation == sqlite3.SQLITE_TRANSACTION and argument == 'COMMIT':
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            db.set_authorizer(authorizer)
            try:
                from line.closing.cut import SealRejected
                try:
                    seal_anonymous(db, 'late', 'L')
                except SealRejected:
                    failed = True
                else:
                    failed = False
            finally:
                db.set_authorizer(None)
            visible_after_failure = observer.execute(
                'SELECT COUNT(*) FROM station_seals').fetchone()[0]
            assert failed and not db.in_transaction and visible_after_failure == before

    live.unlink()

    with closing(connect(database)) as db:
        initialize(db)
        state, left_id = seal_anonymous(db, 'late', 'L')
        assert seal_anonymous(db, 'late', 'L') == (state, left_id)
        report_id = publish(db, right_id, left_id)

    with closing(connect(database)) as db:
        view = read(db, report_id)

    rows = []
    for item in view.items:
        rows.append([item.specimen_id, item.status,
                     None if item.maximum_um is None else str(item.maximum_um),
                     [[row.reading_id, row.sequence, row.source_line, str(row.raw_code),
                       str(row.thickness_um),
                       None if row.anonymous is None else
                       [row.anonymous.shot, [row.anonymous.ticket.source_seq,
                                             row.anonymous.ticket.source_line,
                                             row.anonymous.ticket.specimen_id,
                                             row.anonymous.ticket.first_shot,
                                             row.anonymous.ticket.last_shot]]]
                      for row in item.readings]])
    expected = {'early': 'pending', 'middle': 'pending', 'state': 'sealed',
                'commit_failed_visible_seals': before, 'rows': [
                    ['R-A', 'within_limit', '5', [['r1', 1, 2, '5', '5', None]]],
                    ['L-A', 'over_limit', '13', [['r2', 2, 9, '13', '13', [2, [1, 4, 'L-A', 1, 2]]]]],
                    ['L-B', 'within_limit', '7', [['r1', 1, 3, '7', '7', [1, [2, 7, 'L-B', 1, 1]]]]],
                    ['L-C', 'missing', None, []]]}
    actual = {'early': early[0], 'middle': middle[0], 'state': state,
              'commit_failed_visible_seals': before, 'rows': rows}
    if actual != expected:
        raise AssertionError((actual, expected))
    print(f'Sealed report {report_id} after the ticket and reading sources were removed.')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'v8.anonymous', 'input': {'early_seal': 'pending before late ticket',
                                             'commit_failure': 'denied at COMMIT',
                                             'sources_available': live.exists()},
        'expected': expected, 'actual': actual,
        'code_paths': ['line/capture/admission.py', 'line/capture/anonymous.py',
                       'line/closing/anonymous.py', 'line/report/provenance.py'],
        'oracle': 'The pending window only seals once both streams cover 1..N; '
                  'ticket 1 covers shots 1..2 and takes shot 2, ticket 2 takes shot 1, and L-C stays missing.'
    }, sort_keys=True))


def main():
    from tempfile import TemporaryDirectory

    with TemporaryDirectory(prefix='coating-line-') as directory:
        _demonstrate(Path(directory))
        _demonstrate_anonymous(Path(directory))


if __name__ == '__main__':
    main()
