from dataclasses import dataclass
from fractions import Fraction

from line.calibration.limits import is_over_limit
from line.capture.journal import AcceptedReading
from line.closing.measurements import SpecimenMeasurements


@dataclass(frozen=True)
class QualityDetail:
    position: int
    specimen_id: str
    count: int
    maximum_um: Fraction | None
    status: str
    readings: tuple[AcceptedReading, ...]


def judge_specimen(measurements: SpecimenMeasurements, limit_um):
    peak = measurements.maximum_um
    if peak is None:
        status = 'missing'
    elif is_over_limit(peak, limit_um):
        status = 'over_limit'
    else:
        status = 'within_limit'
    return QualityDetail(measurements.position, measurements.specimen_id, measurements.count,
                         peak, status, measurements.readings)
