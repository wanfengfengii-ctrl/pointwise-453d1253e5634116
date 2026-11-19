from dataclasses import dataclass
from fractions import Fraction

from line.calibration.profiles import GaugeProfile
from line.closing.store import SealStore
from line.report.assembly import ReportDraft


@dataclass(frozen=True)
class ReadingEvidence:
    reading_id: str
    sequence: int
    raw_code: Fraction
    thickness_um: Fraction
    source_line: int
    profile_version: int


@dataclass(frozen=True)
class SpecimenEvidence:
    position: int
    specimen_id: str
    station: str
    seal_id: int
    profile_version: int
    profile: GaugeProfile
    count: int
    maximum_um: Fraction | None
    status: str
    readings: tuple[ReadingEvidence, ...]


def resolve_report_evidence(db, draft: ReportDraft):
    store = SealStore(db)
    detail_refs = {}
    for seal_id in (draft.left_seal_id, draft.right_seal_id):
        parent = store.get(seal_id)
        if parent is None:
            raise LookupError(f'fixed parent seal {seal_id} is unavailable')
        for detail in parent.details:
            detail_refs[seal_id, detail.position] = (parent, detail)

    evidence = []
    for ref in draft.items:
        parent, detail = detail_refs[ref.seal_id, ref.position]
        readings = tuple(ReadingEvidence(
            row.claim.key.reading_id, row.sequence, row.claim.raw_code, row.thickness_um,
            row.claim.source_line, row.profile_version,
        ) for row in detail.readings)
        evidence.append(SpecimenEvidence(
            detail.position, detail.specimen_id, parent.station, ref.seal_id, parent.profile_version,
            parent.profile, detail.count, detail.maximum_um, detail.status, readings,
        ))
    return tuple(evidence)
