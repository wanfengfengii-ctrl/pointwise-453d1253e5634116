from dataclasses import dataclass
from fractions import Fraction

from line.calibration.exact import as_fraction


@dataclass(frozen=True)
class RawRange:
    minimum: Fraction
    maximum: Fraction

    def contains(self, value):
        return self.minimum <= value <= self.maximum


def make_raw_range(minimum, maximum):
    lower = as_fraction(minimum)
    upper = as_fraction(maximum)
    if lower > upper:
        raise ValueError('raw range minimum exceeds maximum')
    return RawRange(lower, upper)


def is_over_limit(thickness_um, limit_um):
    return thickness_um > limit_um
