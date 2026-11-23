from dataclasses import dataclass

from reels.copy import ReelCopy
from reels.records import RecordAddress, StoredRecord
from reels.scan import ReelPrefix, record_at, scan_prefix


@dataclass(frozen=True)
class MatchedRow:
    recording_id: str
    row_index: int
    position: int
    amplitude_uv: int | None
    quality: str
    amplitude_address: RecordAddress
    quality_address: RecordAddress


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _pair_is_bound(body: dict, amplitude: ReelPrefix, quality: ReelPrefix) -> bool:
    return (
        amplitude.header.role == 'amplitude'
        and quality.header.role == 'quality'
        and amplitude.header.reel_id != quality.header.reel_id
        and amplitude.header.serial != quality.header.serial
        and body.get('left') == amplitude.header.identity()
        and body.get('right') == quality.header.identity()
        and _text(body.get('recording'))
        and _text(body.get('release'))
    )


def _join_row(
    recording_id: str, index: int, left: object, right: object,
    left_address: RecordAddress, right_address: RecordAddress,
) -> MatchedRow | None:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return None
    for row in (left, right):
        if type(row.get('index')) is not int or row['index'] != index or not _positive(row.get('position')):
            return None
    if left['position'] != right['position'] or 'value' not in left:
        return None
    value = left['value']
    code = right.get('value')
    if (value is not None and type(value) is not int) or not _text(code):
        return None
    return MatchedRow(recording_id, index, left['position'], value, code, left_address, right_address)


def _current_rows(
    effective: StoredRecord, body: dict, amplitude: ReelPrefix, quality: ReelPrefix,
) -> tuple[MatchedRow, ...] | None:
    attempt = body.get('attempt')
    right_start = body.get('right_start')
    count = body.get('count')
    if not all(_positive(value) for value in (attempt, right_start, count)):
        return None
    if not _text(body.get('request')) or not _text(body.get('prepared')):
        return None
    if attempt + count > effective.address.ordinal or right_start + count - 1 > len(quality.records):
        return None

    rows = []
    for index in range(count):
        left_address = RecordAddress(amplitude.header.reel_id, attempt + index)
        right_address = RecordAddress(quality.header.reel_id, right_start + index)
        left = record_at(amplitude, left_address)
        right = record_at(quality, right_address)
        if left is None or right is None:
            return None
        if left.logical.kind != 'amplitude_v1' or right.logical.kind != 'quality_v1':
            return None
        left_row = left.logical.payload
        right_row = right.logical.payload
        for row in (left_row, right_row):
            if row.get('release') != body['release'] or row.get('recording') != body['recording']:
                return None
            if type(row.get('attempt')) is not int or row['attempt'] != attempt:
                return None
        joined = _join_row(body['recording'], index, left_row, right_row, left_address, right_address)
        if joined is None:
            return None
        rows.append(joined)
    return tuple(rows)


def _legacy_rows(
    left: StoredRecord, body: dict, quality: ReelPrefix,
) -> tuple[MatchedRow, ...] | None:
    right_ordinal = body.get('right_ordinal')
    left_ordinal = body.get('left_ordinal')
    count = body.get('count')
    if not all(_positive(value) for value in (right_ordinal, left_ordinal, count)):
        return None
    if left_ordinal != left.address.ordinal:
        return None
    right_address = RecordAddress(quality.header.reel_id, right_ordinal)
    right = record_at(quality, right_address)
    if right is None or right.logical.kind != 'legacy_quality_v0':
        return None
    counterpart = right.logical.payload
    left_rows = body.pop('rows', None)
    right_rows = counterpart.pop('rows', None)
    if body != counterpart or not isinstance(left_rows, list) or not isinstance(right_rows, list):
        return None
    if len(left_rows) != count or len(right_rows) != count:
        return None
    rows = []
    for index, (left_row, right_row) in enumerate(zip(left_rows, right_rows)):
        joined = _join_row(body['recording'], index, left_row, right_row, left.address, right_address)
        if joined is None:
            return None
        rows.append(joined)
    return tuple(rows)


def verify_pair_coverage(
    effective: StoredRecord, amplitude: ReelPrefix, quality: ReelPrefix,
) -> tuple[MatchedRow, ...] | None:
    if record_at(amplitude, effective.address) != effective:
        return None
    body = effective.logical.payload
    if not _pair_is_bound(body, amplitude, quality):
        return None
    if effective.logical.kind == 'effective_v1':
        rows = _current_rows(effective, body, amplitude, quality)
    elif effective.logical.kind == 'legacy_amplitude_v0':
        rows = _legacy_rows(effective, body, quality)
    else:
        return None
    if rows is None or len({row.position for row in rows}) != len(rows):
        return None
    return rows


def resolve_release(
    release_id: str, amplitude_copy: ReelCopy, quality_copy: ReelCopy,
) -> tuple[MatchedRow, ...] | None:
    if not _text(release_id) or not isinstance(amplitude_copy, ReelCopy) or not isinstance(quality_copy, ReelCopy):
        return None
    try:
        amplitude = scan_prefix(amplitude_copy.header, amplitude_copy.frames)
        quality = scan_prefix(quality_copy.header, quality_copy.frames)
    except ValueError:
        return None
    for entry in amplitude.records:
        if entry.logical.kind not in ('effective_v1', 'legacy_amplitude_v0'):
            continue
        if entry.logical.payload.get('release') == release_id:
            return verify_pair_coverage(entry, amplitude, quality)
    return None
