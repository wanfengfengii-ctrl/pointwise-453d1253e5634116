import sqlite3

from line.closing.store import SealStore
from line.report.assembly import InvalidSealPair, assemble_report
from line.report.catalog import ReportCatalog
from line.workday import write_transaction


class PublishRejected(ValueError):
    pass


def publish(db, first_seal_id, second_seal_id):
    try:
        with write_transaction(db):
            seals = SealStore(db)
            draft = assemble_report(seals.get(first_seal_id), seals.get(second_seal_id))
            report_id = ReportCatalog(db).save(draft)
    except (InvalidSealPair, sqlite3.Error) as exc:
        raise PublishRejected(f'report could not be published: {exc}') from exc
    return report_id
