from dataclasses import dataclass
from fractions import Fraction

from line.calibration.exact import as_fraction
from line.calibration.limits import RawRange, make_raw_range
from line.intake.stations import valid_identifier


class ProfileRejected(ValueError):
    pass


@dataclass(frozen=True)
class GaugeProfile:
    station: str
    gain: Fraction
    offset_um: Fraction
    raw_range: RawRange
    limit_um: Fraction


def make_profile(station, gain, offset_um, raw_min, raw_max, limit_um):
    if not valid_identifier(station):
        raise ProfileRejected('a valid gauge station is required')
    try:
        multiplier = as_fraction(gain)
        offset = as_fraction(offset_um)
        raw_range = make_raw_range(raw_min, raw_max)
        limit = as_fraction(limit_um)
    except ValueError as exc:
        raise ProfileRejected('invalid gauge parameters') from exc
    if multiplier <= 0:
        raise ProfileRejected('gauge gain must be positive')
    return GaugeProfile(station, multiplier, offset, raw_range, limit)
