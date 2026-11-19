from line.calibration.exact import as_fraction
from line.calibration.profiles import GaugeProfile


class RawCodeRejected(ValueError):
    pass


def convert_raw(profile: GaugeProfile, raw_code):
    try:
        code = as_fraction(raw_code)
    except ValueError as exc:
        raise RawCodeRejected('raw code must be an exact number') from exc
    if not profile.raw_range.contains(code):
        raise RawCodeRejected(f'raw code {code} is outside the frozen range for {profile.station!r}')
    return code * profile.gain + profile.offset_um
