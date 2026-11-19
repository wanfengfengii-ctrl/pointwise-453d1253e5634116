from dataclasses import dataclass
from fractions import Fraction

from line.calibration.profiles import GaugeProfile
from line.capture.anonymous import AnonymousOrigin, AnonymousReading
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
    anonymous: AnonymousOrigin | None = None


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


def _reading_evidence(row):
    return ReadingEvidence(row.claim.key.reading_id, row.sequence, row.claim.raw_code,
                           row.thickness_um, row.claim.source_line, row.profile_version)


def _anonymous_evidence(row: AnonymousReading):
    return ReadingEvidence(row.reading_id, row.sequence, row.raw_code, row.thickness_um,
                           row.source_line, row.profile_version, row.anonymous)


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
        rows = []
        for row in detail.readings:
            if type(row) is AnonymousReading:
                rows.append(_anonymous_evidence(row))
            else:
                rows.append(_reading_evidence(row))
        evidence.append(SpecimenEvidence(
            detail.position, detail.specimen_id, parent.station, ref.seal_id, parent.profile_version,
            parent.profile, detail.count, detail.maximum_um, detail.status, tuple(rows),
        ))
    return tuple(evidence)
