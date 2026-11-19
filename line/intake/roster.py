from dataclasses import dataclass

from line.intake.stations import StationPair, valid_identifier


@dataclass(frozen=True)
class RosterItem:
    position: int
    specimen_id: str
    station: str


@dataclass(frozen=True)
class Roster:
    items: tuple[RosterItem, ...]

    def station_for(self, specimen_id):
        return next((item.station for item in self.items if item.specimen_id == specimen_id), None)

    def items_for(self, station):
        return tuple(item for item in self.items if item.station == station)


def build_roster(stations: StationPair, entries):
    seen = set()
    items = []
    for position, entry in enumerate(entries):
        if isinstance(entry, (str, bytes)):
            raise ValueError('roster entries must be specimen and station pairs')
        specimen_id, station = entry
        if not valid_identifier(specimen_id) or specimen_id in seen:
            raise ValueError(f'invalid or repeated specimen {specimen_id!r}')
        stations.side_of(station)
        seen.add(specimen_id)
        items.append(RosterItem(position, specimen_id, station))
    return Roster(tuple(items))
