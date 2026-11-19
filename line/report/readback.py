from dataclasses import dataclass

from line.report.catalog import ReportCatalog
from line.report.provenance import SpecimenEvidence, resolve_report_evidence


class ReportNotFound(LookupError):
    pass


@dataclass(frozen=True)
class ReportView:
    report_id: int
    shift_id: str
    left_seal_id: int
    right_seal_id: int
    items: tuple[SpecimenEvidence, ...]


def read(db, report_id):
    draft = ReportCatalog(db).get(report_id)
    if draft is None:
        raise ReportNotFound(f'unknown report {report_id!r}')
    return ReportView(report_id, draft.shift_id, draft.left_seal_id, draft.right_seal_id,
                      resolve_report_evidence(db, draft))
