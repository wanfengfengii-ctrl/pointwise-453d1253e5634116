import sqlite3

from line.calibration.revisions import ProfileRevisions
from line.intake.registry import RegisteredShift, ShiftRegistry
from line.intake.roster import build_roster
from line.intake.stations import make_station_pair, valid_identifier
from line.workday import valid_database_id, write_transaction


class RegistrationRejected(ValueError):
    pass


class OpeningRejected(ValueError):
    pass


def register(db, shift_id, left, right, entries):
    if not valid_identifier(shift_id):
        raise RegistrationRejected('a valid shift identifier is required')
    try:
        stations = make_station_pair(left, right)
        roster = build_roster(stations, entries)
    except (TypeError, ValueError) as exc:
        raise RegistrationRejected('invalid station pair or roster') from exc

    try:
        with write_transaction(db):
            ShiftRegistry(db).insert_registration(RegisteredShift(shift_id, stations, roster))
    except sqlite3.IntegrityError as exc:
        raise RegistrationRejected(f'could not register shift {shift_id!r}') from exc
    return shift_id


def open(db, shift_id, left_version, right_version, *, anonymous_station=None):
    if not valid_identifier(shift_id):
        raise OpeningRejected('a valid shift identifier is required')
    if not valid_database_id(left_version) or not valid_database_id(right_version):
        raise OpeningRejected('both profile version numbers are required')
    if anonymous_station is not None and not valid_identifier(anonymous_station):
        raise OpeningRejected('the anonymous station must be a valid identifier')

    registry = ShiftRegistry(db)
    versions = ProfileRevisions(db)
    with write_transaction(db):
        registration = registry.get_registration(shift_id)
        if registration is None:
            raise OpeningRejected(f'unknown shift {shift_id!r}')
        for station, version in ((registration.stations.left, left_version),
                                 (registration.stations.right, right_version)):
            profile = versions.get_version(version)
            if profile is None or profile.station != station:
                raise OpeningRejected(f'version {version} does not belong to station {station!r}')
        if anonymous_station is not None:
            try:
                registration.stations.side_of(anonymous_station)
            except ValueError as exc:
                raise OpeningRejected(
                    f'anonymous station {anonymous_station!r} is not in this shift') from exc
        if not registry.freeze_shift(shift_id, left_version, right_version, anonymous_station):
            raise OpeningRejected(f'shift {shift_id!r} is already open')
        return registry.get_opened_shift(shift_id)
