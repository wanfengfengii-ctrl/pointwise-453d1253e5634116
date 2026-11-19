from decimal import Decimal
from fractions import Fraction


def as_fraction(value):
    """Accept exact input types and reject missing or nonfinite values."""
    if isinstance(value, bool) or not isinstance(value, (int, Fraction, Decimal, str)):
        raise ValueError('expected an integer or exact rational value')
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError(f'invalid exact value {value!r}') from exc


def fraction_to_storage(value):
    return str(value.numerator), str(value.denominator)


def fraction_from_storage(numerator, denominator):
    return Fraction(int(numerator), int(denominator))
