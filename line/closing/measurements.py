from dataclasses import dataclass
from fractions import Fraction

from line.capture.journal import AcceptedReading
from line.closing.prefix import SealPrefix


@dataclass(frozen=True)
class SpecimenMeasurements:
    position: int
    specimen_id: str
    count: int
    maximum_um: Fraction | None
    readings: tuple[AcceptedReading, ...]


def summarize_measurements(prefix: SealPrefix):
    grouped = {item.specimen_id: [] for item in prefix.roster_items}
    for reading in prefix.readings:
        grouped[reading.claim.specimen_id].append(reading)

    summaries = []
    for item in prefix.roster_items:
        readings = tuple(grouped[item.specimen_id])
        peak = max((reading.thickness_um for reading in readings), default=None)
        summaries.append(SpecimenMeasurements(item.position, item.specimen_id, len(readings), peak, readings))
    return tuple(summaries)
