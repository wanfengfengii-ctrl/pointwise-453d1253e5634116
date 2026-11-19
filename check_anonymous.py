"""Inspect sample tapes or exercise the public anonymous capture interfaces."""
import argparse
from contextlib import closing
from io import StringIO
import json
from pathlib import Path
from shutil import copyfile
import sqlite3
from tempfile import TemporaryDirectory

from line.calibration.revisions import calibrate
from line.intake.shifts import open as open_shift, register
from line.report.publish import publish
from line.report.readback import read
from line.workday import connect, initialize, valid_database_id

FIXTURE = Path(__file__).resolve().parent / 'samples' / 'station_events.json'


def load_fixture(path):
    sample = json.loads(path.read_text(encoding='utf-8'))
    arity = {'end': 3, 'ticket': 6, 'reading': 6, 'expect': 2}
    for case in sample['cases']:
        for event in case['events']:
            if len(event) != arity[event[0]]:
                raise ValueError(f'invalid sample event in {case["name"]}: {event!r}')
    return sample


def expect_rejection(error, action, *args):
    try:
        action(*args)
    except error:
        return
    raise AssertionError(f'{action.__name__} should raise {error.__name__}')


def seal_count(db):
    return db.execute('SELECT COUNT(*) FROM station_seals').fetchone()[0]


def reject_commit(db, observer, action, shift):
    before = seal_count(observer)
    attempted = False

    def authorizer(operation, argument, *_):
        nonlocal attempted
        if operation == sqlite3.SQLITE_TRANSACTION and argument == 'COMMIT':
            attempted = True
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    db.set_authorizer(authorizer)
    try:
        from line.closing.cut import SealRejected
        expect_rejection(SealRejected, action, db, shift, 'L')
    finally:
        db.set_authorizer(None)
    assert attempted and not db.in_transaction and seal_count(observer) == before


def view_reading(row):
    origin = row.anonymous
    details = None
    if origin is not None:
        ticket = origin.ticket
        details = [origin.shot, [ticket.source_seq, ticket.source_line,
                                 ticket.specimen_id, ticket.first_shot, ticket.last_shot]]
    return [row.reading_id, row.sequence, row.source_line, str(row.raw_code),
            str(row.thickness_um), details]


def replay(directory):
    from line.capture.admission import (IngestRejected, declare_end, ingest, ingest_anonymous,
                                        ingest_recording, ingest_ticket)
    from line.closing.cut import SealRejected, seal, seal_anonymous

    source = directory / FIXTURE.name
    copyfile(FIXTURE, source)
    sample = load_fixture(source)
    actions = {'end': declare_end, 'ticket': ingest_ticket, 'reading': ingest_anonymous}
    for case in sample['cases']:
        shift = case['name']
        state = case['state']
        path = directory / (shift + '.sqlite')
        with closing(connect(path)) as db:
            initialize(db)
            register(db, shift, 'L', 'R', sample['roster'])
            versions = [calibrate(db, station, 1, 0, 0, 20, 10) for station in ('L', 'R')]
            open_shift(db, shift, *versions, anonymous_station='L')
            ingest(db, shift, 'R', *sample['right_reading'])
            right_id = seal(db, shift, 'R', 1).seal_id
            expect_rejection(IngestRejected, ingest, db, shift, 'L', 'L-A', 'manual', 6, 2)
            manual = StringIO('specimen_id,reading_id,raw_code\nL-A,manual,6\n')
            expect_rejection(IngestRejected, ingest_recording, db, shift, 'L', manual)
            expect_rejection(SealRejected, seal, db, shift, 'L', 0)
            for kind, *args in case['events']:
                if kind == 'expect':
                    result = seal_anonymous(db, shift, 'L')
                    assert result == (args[0], None) and seal_count(db) == 1
                    print(shift, result[0])
                else:
                    action = actions[kind]
                    expected_receipt = args[-1] if kind == 'end' else args[0]
                    assert action(db, shift, 'L', *args) == expected_receipt
                    assert action(db, shift, 'L', *args) == expected_receipt
            if state != 'sealed':
                assert seal_anonymous(db, shift, 'L') == (state, None)
                assert seal_count(db) == 1
                print(shift, state)
                continue
            expect_rejection(IngestRejected, ingest_anonymous, db, shift, 'L', 1, 3, 1, 'r1', 8)
            expect_rejection(IngestRejected, ingest_anonymous, db, shift, 'L', 3, 10, 3, 'r3', 8)
            with closing(connect(path)) as observer:
                reject_commit(db, observer, seal_anonymous, shift)
            print(shift, 'commit rejected; no new seal')
        source.unlink()
        with closing(connect(path)) as db:
            initialize(db)
            status, left_id = seal_anonymous(db, shift, 'L')
            assert status == state and valid_database_id(left_id)
            count = seal_count(db)
            assert seal_anonymous(db, shift, 'L') == (state, left_id)
            assert seal_count(db) == count
            report_id = publish(db, right_id, left_id)
            ingest(db, shift, 'R', 'R-A', 'r2', 6, 5)
        with closing(connect(path)) as db:
            view = read(db, report_id)
            assert (view.left_seal_id, view.right_seal_id) == (left_id, right_id)
            actual = [[i.specimen_id, i.status, None if i.maximum_um is None else str(i.maximum_um),
                       [view_reading(row) for row in i.readings]] for i in view.items]
            assert actual == case['report'], (actual, case['report'])
            assert [i.count for i in view.items] == [len(i[3]) for i in actual]
            print(json.dumps({'case': shift, 'state': state, 'report_id': report_id, 'items': actual}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('fixture', 'replay'))
    args = parser.parse_args()
    if args.mode == 'fixture':
        for case in load_fixture(FIXTURE)['cases']:
            print(case['name'], len(case['events']), case['state'])
    else:
        with TemporaryDirectory(prefix='coating-anonymous-') as directory:
            replay(Path(directory))


if __name__ == '__main__':
    main()
