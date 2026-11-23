"""Night-shift verification of a release split across two quality reels.

Only the release number and three independently copied prefixes are
available: the amplitude reel A, the departed first quality reel Q1 and
the continuation quality reel Q2.  The final effective record on the A
copy anchors the check; the stored binding and permit on the same copy
must agree with it, and every claimed row is re-read at its physical
address on the corresponding copy before any account is produced.
"""
from reels.copy import ReelCopy
from reels.records import RecordAddress
from reels.scan import ReelPrefix, record_at, scan_prefix
from review.coverage import MatchedRow


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


def _scan_copy(copy: ReelCopy | None) -> ReelPrefix | None:
    if not isinstance(copy, ReelCopy):
        return None
    try:
        return scan_prefix(copy.header, copy.frames)
    except ValueError:
        return None


def _find_record(prefix: ReelPrefix, kind: str, release_id: str):
    for stored in prefix.records:
        if stored.logical.kind == kind and stored.logical.payload.get('release') == release_id:
            return stored
    return None


def _find_binding_record(prefix: ReelPrefix, body: dict):
    expected = {key: body.get(key) for key in ('request', 'prepared', 'cut', 'amplitude', 'first', 'next')}
    for stored in prefix.records:
        if stored.logical.kind != 'request_unload_v1':
            continue
        if stored.logical.payload.get('request') != body.get('request'):
            continue
        return stored if stored.logical.payload == expected else None
    return None


def _row_at(prefix: ReelPrefix, kind: str, release_id: str, recording: str, index: int, ordinal: int):
    stored = record_at(prefix, RecordAddress(prefix.header.reel_id, ordinal))
    if stored is None or stored.logical.kind != kind:
        return None
    body = stored.logical.payload
    if body.get('release') != release_id or body.get('recording') != recording:
        return None
    if body.get('index') != index or not _positive(body.get('position')) or 'value' not in body:
        return None
    return body


def _verify_split(effective, amplitude: ReelPrefix, first: ReelPrefix, nextq: ReelPrefix):
    if record_at(amplitude, effective.address) != effective:
        return None
    body = effective.logical.payload
    release_id = body.get('release')
    recording = body.get('recording')
    cut = body.get('cut')
    count = body.get('count')
    attempt = body.get('attempt')
    first_start = body.get('first_start')
    next_start = body.get('next_start')
    if not _text(release_id) or not _text(recording):
        return None
    if not _text(body.get('request')) or not _text(body.get('prepared')):
        return None
    if not all(_positive(value) for value in (count, attempt, first_start, next_start)):
        return None
    if type(cut) is not int or not 0 < cut < count:
        return None
    if body.get('amplitude') != amplitude.header.identity():
        return None
    if body.get('first') != first.header.identity() or body.get('next') != nextq.header.identity():
        return None
    binding = _find_binding_record(amplitude, body)
    if binding is None:
        return None
    permit = _find_record(amplitude, 'permit_unload_v1', release_id)
    if permit is None:
        return None
    expected_permit = {
        key: body.get(key)
        for key in ('request', 'prepared', 'cut', 'amplitude', 'first', 'next', 'recording', 'first_start')
    }
    expected_permit['release'] = release_id
    if permit.logical.payload != expected_permit:
        return None
    if not binding.address.ordinal < permit.address.ordinal < effective.address.ordinal:
        return None
    if attempt + count > effective.address.ordinal:
        return None

    rows = []
    for index in range(count):
        left = _row_at(amplitude, 'amplitude_unload_v1', release_id, recording, index, attempt + index)
        if left is None:
            return None
        if index < cut:
            right_ordinal = first_start + index
            right = _row_at(first, 'quality_unload_v1', release_id, recording, index, right_ordinal)
            right_address = RecordAddress(first.header.reel_id, right_ordinal)
        else:
            right_ordinal = next_start + index - cut
            right = _row_at(nextq, 'quality_unload_v1', release_id, recording, index, right_ordinal)
            right_address = RecordAddress(nextq.header.reel_id, right_ordinal)
        if right is None or left['position'] != right['position']:
            return None
        value = left['value']
        code = right['value']
        if (value is not None and type(value) is not int) or not _text(code):
            return None
        rows.append(MatchedRow(
            recording, index, left['position'], value, code,
            RecordAddress(amplitude.header.reel_id, attempt + index), right_address,
        ))
    if len({row.position for row in rows}) != len(rows):
        return None
    return tuple(rows)


def resolve_split_release(
    release_id: str,
    amplitude_copy: ReelCopy | None,
    first_quality_copy: ReelCopy | None,
    next_quality_copy: ReelCopy | None,
) -> tuple[MatchedRow, ...] | None:
    if not _text(release_id):
        return None
    amplitude = _scan_copy(amplitude_copy)
    first = _scan_copy(first_quality_copy)
    nextq = _scan_copy(next_quality_copy)
    if amplitude is None or first is None or nextq is None:
        return None
    if amplitude.header.role != 'amplitude':
        return None
    if first.header.role != 'quality' or nextq.header.role != 'quality':
        return None
    reel_ids = (amplitude.header.reel_id, first.header.reel_id, nextq.header.reel_id)
    serials = (amplitude.header.serial, first.header.serial, nextq.header.serial)
    if len(set(reel_ids)) != 3 or len(set(serials)) != 3:
        return None
    effective = _find_record(amplitude, 'effective_unload_v1', release_id)
    if effective is None:
        return None
    return _verify_split(effective, amplitude, first, nextq)
