from dataclasses import dataclass


def valid_identifier(value):
    return (isinstance(value, str) and bool(value) and value == value.strip()
            and not any(character in value for character in ('\x00', '\r', '\n')))


@dataclass(frozen=True)
class StationPair:
    left: str
    right: str

    def side_of(self, station):
        if station == self.left:
            return 'left'
        if station == self.right:
            return 'right'
        raise ValueError(f'{station!r} is outside the station pair')


def make_station_pair(left, right):
    if not valid_identifier(left) or not valid_identifier(right) or left == right:
        raise ValueError('two different station identifiers are required')
    return StationPair(left, right)
