from decimal import Decimal
from fractions import Fraction

from prepare.profile import ConversionProfile


def convert_amplitude(value: Decimal | None, unit: str, profile: ConversionProfile) -> int | None:
    try:
        factor = profile.unit_factors[unit]
    except KeyError:
        raise ValueError(f'unsupported amplitude unit {unit!r}') from None
    if value is None:
        return None
    ratio = Fraction(value) * factor
    numerator, denominator = ratio.numerator, ratio.denominator
    magnitude = (2 * abs(numerator) + denominator) // (2 * denominator)
    return -magnitude if numerator < 0 else magnitude
