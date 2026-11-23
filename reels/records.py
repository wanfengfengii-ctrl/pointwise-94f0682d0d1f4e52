import json
import re
from dataclasses import dataclass, field


_REEL_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')


def check_reel_id(reel_id: str) -> None:
    if not isinstance(reel_id, str) or not _REEL_ID.fullmatch(reel_id):
        raise ValueError(f'invalid reel id {reel_id!r}')


@dataclass(frozen=True)
class ReelHeader:
    reel_id: str
    role: str
    serial: str

    def __post_init__(self) -> None:
        check_reel_id(self.reel_id)
        if self.role not in ('amplitude', 'quality'):
            raise ValueError(f'invalid reel role {self.role!r}')
        if not isinstance(self.serial, str) or not self.serial.strip():
            raise ValueError('reel serial must be nonempty text')

    def identity(self) -> list[str]:
        return [self.reel_id, self.serial]


@dataclass(frozen=True)
class RecordAddress:
    reel_id: str
    ordinal: int

    def __post_init__(self) -> None:
        check_reel_id(self.reel_id)
        if type(self.ordinal) is not int or self.ordinal <= 0:
            raise ValueError('record ordinal must be a positive integer')


@dataclass(frozen=True, init=False)
class LogicalRecord:
    kind: str
    _frame: bytes = field(repr=False)

    def __init__(self, kind: str, payload: dict):
        if not isinstance(kind, str) or not kind.strip() or not isinstance(payload, dict):
            raise ValueError('record requires a kind and a JSON object payload')
        try:
            frame = json.dumps(
                {'kind': kind, 'payload': payload},
                ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False,
            ).encode('ascii')
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError('invalid JSON record payload') from exc
        object.__setattr__(self, 'kind', kind)
        object.__setattr__(self, '_frame', frame)

    @property
    def payload(self) -> dict:
        return json.loads(self._frame)['payload']


@dataclass(frozen=True)
class StoredRecord:
    address: RecordAddress
    logical: LogicalRecord


def encode_record(record: LogicalRecord) -> bytes:
    if not isinstance(record, LogicalRecord):
        raise ValueError('expected a complete LogicalRecord')
    return record._frame


def decode_record(frame: bytes) -> LogicalRecord:
    if not isinstance(frame, bytes):
        raise ValueError('record frame must be bytes')
    try:
        envelope = json.loads(frame)
    except (ValueError, RecursionError) as exc:
        raise ValueError('invalid record frame') from exc
    if not isinstance(envelope, dict) or envelope.keys() != {'kind', 'payload'}:
        raise ValueError('invalid record envelope')
    return LogicalRecord(envelope['kind'], envelope['payload'])
