from line.closing.measurements import summarize_measurements
from line.closing.prefix import InvalidCut, load_prefix
from line.closing.quality import judge_specimen
from line.closing.store import SealStore
from line.intake.registry import ShiftRegistry
from line.workday import write_transaction

__all__ = ['SealRejected', 'seal', 'seal_anonymous']


class SealRejected(ValueError):
    pass


def seal(db, shift_id, station, cutoff):
    with write_transaction(db):
        shift = ShiftRegistry(db).get_opened_shift(shift_id)
        if shift is not None and shift.anonymous_station == station:
            raise SealRejected(f'station {station!r} runs an anonymous window; use seal_anonymous')
        try:
            prefix = load_prefix(db, shift_id, station, cutoff)
        except InvalidCut as exc:
            raise SealRejected(str(exc)) from exc
        measurements = summarize_measurements(prefix)
        details = tuple(judge_specimen(item, prefix.profile.limit_um) for item in measurements)
        return SealStore(db).save(prefix, details)


def seal_anonymous(db, shift_id, station):
    from line.closing.anonymous import seal_anonymous as _seal_anonymous
    return _seal_anonymous(db, shift_id, station)
