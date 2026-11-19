from line.report.assembly import ReportDraft, ReportItemRef
from line.workday import valid_database_id


class ReportCatalog:
    def __init__(self, db):
        self.db = db

    def save(self, draft: ReportDraft):
        cursor = self.db.execute('''
            INSERT INTO reports(shift_id, left_seal_id, right_seal_id) VALUES (?, ?, ?)
        ''', (draft.shift_id, draft.left_seal_id, draft.right_seal_id))
        report_id = cursor.lastrowid
        self.db.executemany('''
            INSERT INTO report_items(report_id, position, seal_id) VALUES (?, ?, ?)
        ''', ((report_id, item.position, item.seal_id) for item in draft.items))
        return report_id

    def get(self, report_id):
        if not valid_database_id(report_id):
            return None
        row = self.db.execute('''
            SELECT shift_id, left_seal_id, right_seal_id FROM reports WHERE report_id = ?
        ''', (report_id,)).fetchone()
        if row is None:
            return None
        refs = self.db.execute('''
            SELECT position, seal_id FROM report_items WHERE report_id = ? ORDER BY position
        ''', (report_id,))
        return ReportDraft(*row, tuple(ReportItemRef(*ref) for ref in refs))


def initialize_reports(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            report_id INTEGER PRIMARY KEY,
            shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
            left_seal_id INTEGER NOT NULL REFERENCES station_seals(seal_id),
            right_seal_id INTEGER NOT NULL REFERENCES station_seals(seal_id),
            CHECK (left_seal_id <> right_seal_id)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS report_items (
            report_id INTEGER NOT NULL REFERENCES reports(report_id),
            position INTEGER NOT NULL,
            seal_id INTEGER NOT NULL,
            PRIMARY KEY (report_id, position),
            FOREIGN KEY (seal_id, position) REFERENCES seal_details(seal_id, position)
        )
    ''')
