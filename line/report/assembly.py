from dataclasses import dataclass

from line.closing.store import StationSeal


@dataclass(frozen=True)
class ReportItemRef:
    position: int
    seal_id: int


@dataclass(frozen=True)
class ReportDraft:
    shift_id: str
    left_seal_id: int
    right_seal_id: int
    items: tuple[ReportItemRef, ...]


class InvalidSealPair(ValueError):
    pass


def assemble_report(first: StationSeal | None, second: StationSeal | None):
    if first is None or second is None:
        raise InvalidSealPair('both parent seals must exist')
    if first.shift_id != second.shift_id:
        raise InvalidSealPair('parent seals belong to different shifts')
    if {first.side, second.side} != {'left', 'right'} or first.station == second.station:
        raise InvalidSealPair('one seal from each station is required')

    left, right = (first, second) if first.side == 'left' else (second, first)
    refs = [ReportItemRef(detail.position, parent.seal_id)
            for parent in (left, right) for detail in parent.details]
    refs.sort(key=lambda ref: ref.position)
    return ReportDraft(left.shift_id, left.seal_id, right.seal_id, tuple(refs))
