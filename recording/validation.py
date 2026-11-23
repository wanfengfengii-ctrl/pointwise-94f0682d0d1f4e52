import re
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation

from recording.models import DeviceSource, RawReading


_FIELDS = frozenset({'position', 'amplitude', 'unit', 'status'})
_DECIMAL = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?')


def _require_text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be nonempty text')


def _read_amplitude(value: object) -> Decimal | None:
    if value is None:
        return None
    valid = isinstance(value, Decimal) or type(value) is int
    if isinstance(value, str):
        valid = _DECIMAL.fullmatch(value) is not None
    if not valid:
        raise ValueError('amplitude must be an exact decimal or null')
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('invalid decimal amplitude') from exc
    if not decimal.is_finite():
        raise ValueError('amplitude must be finite')
    return decimal


def validate_raw_row(raw: Mapping) -> RawReading:
    if not isinstance(raw, Mapping) or raw.keys() != _FIELDS:
        raise ValueError('expected position, amplitude, unit, and status')
    position = raw['position']
    if type(position) is not int or position <= 0:
        raise ValueError('position must be a positive integer')
    _require_text(raw['unit'], 'unit')
    _require_text(raw['status'], 'status')
    return RawReading(position, _read_amplitude(raw['amplitude']), raw['unit'], raw['status'])


def validate_submission(
    submission: str, source: DeviceSource, rows: Iterable[Mapping],
) -> tuple[RawReading, ...]:
    _require_text(submission, 'submission')
    if not isinstance(source, DeviceSource):
        raise ValueError('expected a DeviceSource')
    _require_text(source.device_id, 'device_id')
    _require_text(source.section, 'section')
    if not isinstance(rows, Iterable):
        raise ValueError('expected an iterable of readings')
    validated = []
    positions = set()
    for raw in rows:
        row = validate_raw_row(raw)
        if row.position in positions:
            raise ValueError(f'duplicate position {row.position}')
        positions.add(row.position)
        validated.append(row)
    if not validated:
        raise ValueError('recording must contain at least one row')
    return tuple(validated)
