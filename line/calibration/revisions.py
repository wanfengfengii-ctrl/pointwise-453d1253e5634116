from line.calibration.exact import fraction_from_storage, fraction_to_storage
from line.calibration.limits import RawRange
from line.calibration.profiles import GaugeProfile, make_profile
from line.workday import valid_database_id, write_transaction


class ProfileRevisions:
    def __init__(self, db):
        self.db = db

    def append(self, profile):
        cursor = self.db.execute('''
            INSERT INTO gauge_versions(station, gain_n, gain_d, offset_n, offset_d,
                                       raw_min_n, raw_min_d, raw_max_n, raw_max_d, limit_n, limit_d)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (profile.station, *fraction_to_storage(profile.gain),
              *fraction_to_storage(profile.offset_um), *fraction_to_storage(profile.raw_range.minimum),
              *fraction_to_storage(profile.raw_range.maximum), *fraction_to_storage(profile.limit_um)))
        return cursor.lastrowid

    def get_version(self, version):
        if not valid_database_id(version):
            return None
        row = self.db.execute('''
            SELECT station, gain_n, gain_d, offset_n, offset_d,
                   raw_min_n, raw_min_d, raw_max_n, raw_max_d, limit_n, limit_d
            FROM gauge_versions WHERE version = ?
        ''', (version,)).fetchone()
        if row is None:
            return None
        station, gain_n, gain_d, offset_n, offset_d, min_n, min_d, max_n, max_d, limit_n, limit_d = row
        raw_range = RawRange(fraction_from_storage(min_n, min_d), fraction_from_storage(max_n, max_d))
        return GaugeProfile(station, fraction_from_storage(gain_n, gain_d),
                            fraction_from_storage(offset_n, offset_d), raw_range,
                            fraction_from_storage(limit_n, limit_d))


def calibrate(db, station, gain, offset_um, raw_min, raw_max, limit_um):
    profile = make_profile(station, gain, offset_um, raw_min, raw_max, limit_um)
    with write_transaction(db):
        return ProfileRevisions(db).append(profile)


def initialize_calibration(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS gauge_versions (
            version INTEGER PRIMARY KEY,
            station TEXT NOT NULL,
            gain_n TEXT NOT NULL, gain_d TEXT NOT NULL,
            offset_n TEXT NOT NULL, offset_d TEXT NOT NULL,
            raw_min_n TEXT NOT NULL, raw_min_d TEXT NOT NULL,
            raw_max_n TEXT NOT NULL, raw_max_d TEXT NOT NULL,
            limit_n TEXT NOT NULL, limit_d TEXT NOT NULL
        )
    ''')
