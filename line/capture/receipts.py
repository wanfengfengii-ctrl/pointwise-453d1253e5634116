from dataclasses import dataclass
from fractions import Fraction

from line.capture.journal import AcceptedReading


@dataclass(frozen=True)
class Receipt:
    reading_id: str
    sequence: int
    thickness_um: Fraction


def receipt_from_reading(reading: AcceptedReading):
    return Receipt(reading.claim.key.reading_id, reading.sequence, reading.thickness_um)
