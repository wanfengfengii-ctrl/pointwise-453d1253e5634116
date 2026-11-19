from line.closing.measurements import summarize_measurements
from line.closing.prefix import InvalidCut, load_prefix
from line.closing.quality import judge_specimen
from line.closing.store import SealStore
from line.workday import write_transaction


class SealRejected(ValueError):
    pass


def seal(db, shift_id, station, cutoff):
    with write_transaction(db):
        try:
            prefix = load_prefix(db, shift_id, station, cutoff)
        except InvalidCut as exc:
            raise SealRejected(str(exc)) from exc
        measurements = summarize_measurements(prefix)
        details = tuple(judge_specimen(item, prefix.profile.limit_um) for item in measurements)
        return SealStore(db).save(prefix, details)
