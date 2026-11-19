from dataclasses import dataclass

from line.calibration.profiles import GaugeProfile
from line.calibration.revisions import ProfileRevisions
from line.capture.journal import AcceptedReading, ReadingJournal
from line.intake.registry import ShiftRegistry
from line.intake.roster import RosterItem
from line.intake.stations import valid_identifier


class InvalidCut(ValueError):
    pass


@dataclass(frozen=True)
class SealPrefix:
    shift_id: str
    station: str
    side: str
    cutoff: int
    profile_version: int
    profile: GaugeProfile
    roster_items: tuple[RosterItem, ...]
    readings: tuple[AcceptedReading, ...]


def load_prefix(db, shift_id, station, cutoff):
    if not valid_identifier(shift_id) or not valid_identifier(station):
        raise InvalidCut('a valid shift and station are required')
    if type(cutoff) is not int or cutoff < 0:
        raise InvalidCut('cutoff must be a nonnegative integer')

    shift = ShiftRegistry(db).get_opened_shift(shift_id)
    if shift is None:
        raise InvalidCut(f'shift {shift_id!r} is not open')
    try:
        side = shift.stations.side_of(station)
    except ValueError as exc:
        raise InvalidCut(str(exc)) from exc

    journal = ReadingJournal(db)
    head = journal.head(shift_id, station)
    if cutoff > head:
        raise InvalidCut(f'cutoff {cutoff} exceeds local head {head}')
    version = shift.version_for(station)
    profile = ProfileRevisions(db).get_version(version)
    return SealPrefix(shift_id, station, side, cutoff, version, profile,
                      shift.roster.items_for(station), journal.list_through(shift_id, station, cutoff))
