"""Reel-switch mode: one prepared batch split across two quality reels.

The day shift opens an unload permit once the first quality segment is
verified on the departing reel Q1.  After Q1 leaves, the whole-batch
release is continued with only the amplitude reel A, the continuation
reel Q2 and the fixed prepared batch.  All mode state (binding, permit,
effective record) lives on the amplitude reel, so an unmounted Q1 never
blocks re-claim or continuation.
"""
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from issue.allocate import ReleaseReceipt
from issue.requests import RequestConflict
from prepare.catalog import PreparedBatch, PreparedCatalog
from reels.append import append_record
from reels.records import LogicalRecord, ReelHeader, RecordAddress
from reels.scan import ReelPrefix, record_at, scan_reel
from reels.storage import FileReelStore


Checkpoint = Callable[[str, object, str | None], None]

REQUEST_KIND = 'request_unload_v1'
PERMIT_KIND = 'permit_unload_v1'
EFFECTIVE_KIND = 'effective_unload_v1'
AMPLITUDE_KIND = 'amplitude_unload_v1'
QUALITY_KIND = 'quality_unload_v1'


@dataclass(frozen=True)
class UnloadPermit:
    request_id: str
    prepared_id: str
    release_id: str
    quality_addresses: tuple[RecordAddress, ...]


@dataclass(frozen=True)
class UnloadBinding:
    request_id: str
    prepared_id: str
    cut: int
    amplitude: ReelHeader
    first_quality: ReelHeader
    next_quality: ReelHeader

    def __post_init__(self) -> None:
        for name in (self.request_id, self.prepared_id):
            if not isinstance(name, str) or not name.strip():
                raise ValueError('request and prepared ids must be nonempty text')
        if type(self.cut) is not int or self.cut <= 0:
            raise ValueError('cut must be a positive integer')
        if self.amplitude.role != 'amplitude':
            raise ValueError('unload request requires an amplitude reel')
        if self.first_quality.role != 'quality' or self.next_quality.role != 'quality':
            raise ValueError('unload request requires two quality reels')
        reel_ids = (self.amplitude.reel_id, self.first_quality.reel_id, self.next_quality.reel_id)
        serials = (self.amplitude.serial, self.first_quality.serial, self.next_quality.serial)
        if len(set(reel_ids)) != 3 or len(set(serials)) != 3:
            raise ValueError('unload request requires three distinct physical reels')

    def payload(self) -> dict:
        return {
            'request': self.request_id,
            'prepared': self.prepared_id,
            'cut': self.cut,
            'amplitude': self.amplitude.identity(),
            'first': self.first_quality.identity(),
            'next': self.next_quality.identity(),
        }

    def parameters(self) -> tuple:
        return (
            self.prepared_id, self.amplitude.reel_id,
            self.first_quality.reel_id, self.next_quality.reel_id, self.cut,
        )


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _notify(callback: Checkpoint | None, stage: str, detail: object, release_id: str | None) -> None:
    if callback is not None:
        callback(stage, detail, release_id)


def unload_release_number(binding: UnloadBinding) -> str:
    encoded = json.dumps(binding.payload(), sort_keys=True, separators=(',', ':')).encode('ascii')
    return 'rel-' + hashlib.sha256(encoded).hexdigest()


def _identity(value: object, role: str) -> ReelHeader:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('invalid stored reel identity')
    return ReelHeader(value[0], role, value[1])


def _binding_from_payload(body: dict) -> UnloadBinding:
    if not isinstance(body, dict):
        raise ValueError('invalid stored unload request')
    try:
        return UnloadBinding(
            body['request'], body['prepared'], body['cut'],
            _identity(body['amplitude'], 'amplitude'),
            _identity(body['first'], 'quality'),
            _identity(body['next'], 'quality'),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('invalid stored unload request') from exc


def find_unload_request(store: FileReelStore, request_id: str) -> UnloadBinding | None:
    found = None
    for reel_id in store.list_reels():
        prefix = scan_reel(store, reel_id)
        if prefix.header.role != 'amplitude':
            continue
        for stored in prefix.records:
            if stored.logical.kind != REQUEST_KIND:
                continue
            body = stored.logical.payload
            if body.get('request') != request_id:
                continue
            if body.get('amplitude') != prefix.header.identity():
                raise ValueError(f'invalid stored unload request origin for {request_id}')
            binding = _binding_from_payload(body)
            if found is not None and found != binding:
                raise ValueError(f'multiple stored unload bindings for {request_id}')
            found = binding
    return found


def _find_permit_record(
    amplitude: ReelPrefix, binding: UnloadBinding, release_id: str,
) -> object | None:
    found = None
    for stored in amplitude.records:
        if stored.logical.kind != PERMIT_KIND:
            continue
        body = stored.logical.payload
        if body.get('release') != release_id:
            continue
        expected = {
            **binding.payload(), 'release': release_id,
            'recording': body.get('recording'), 'first_start': body.get('first_start'),
        }
        if body != expected or not _text(body.get('recording')) or not _positive(body.get('first_start')):
            raise ValueError(f'stored unload permit differs for request {binding.request_id}')
        if found is None:
            found = stored
    return found


def _permit_from_record(binding: UnloadBinding, release_id: str, stored) -> UnloadPermit:
    first_start = stored.logical.payload['first_start']
    addresses = tuple(
        RecordAddress(binding.first_quality.reel_id, first_start + index)
        for index in range(binding.cut)
    )
    return UnloadPermit(binding.request_id, binding.prepared_id, release_id, addresses)


def _row_record(kind: str, release_id: str, row) -> LogicalRecord:
    value = row.quality if kind == QUALITY_KIND else row.amplitude_uv
    return LogicalRecord(kind, {
        'release': release_id,
        'recording': row.raw_ref.recording_id,
        'index': row.raw_ref.row_index,
        'position': row.position,
        'value': value,
    })


def _segment_matches(
    prefix: ReelPrefix, kind: str, release_id: str, rows: tuple, start_ordinal: int,
) -> bool:
    if start_ordinal + len(rows) - 1 > len(prefix.records):
        return False
    for offset, row in enumerate(rows):
        address = RecordAddress(prefix.header.reel_id, start_ordinal + offset)
        stored = record_at(prefix, address)
        if stored is None or stored.logical != _row_record(kind, release_id, row):
            return False
    return True


def _find_segment(prefix: ReelPrefix, kind: str, release_id: str, rows: tuple) -> int | None:
    first_index = rows[0].raw_ref.row_index
    for stored in reversed(prefix.records):
        if stored.logical.kind != kind:
            continue
        body = stored.logical.payload
        if body.get('release') != release_id or body.get('index') != first_index:
            continue
        if _segment_matches(prefix, kind, release_id, rows, stored.address.ordinal):
            return stored.address.ordinal
    return None


def _ensure_segment(
    store: FileReelStore, prefix: ReelPrefix, kind: str, release_id: str,
    rows: tuple, checkpoint: Checkpoint | None,
) -> tuple[int, ReelPrefix]:
    start = _find_segment(prefix, kind, release_id, rows)
    if start is not None:
        return start, prefix
    start = len(prefix.records) + 1
    for offset, row in enumerate(rows):
        address = append_record(
            store, prefix.header.reel_id, _row_record(kind, release_id, row), start + offset,
        )
        if kind == QUALITY_KIND:
            _notify(checkpoint, 'quality_written', address, release_id)
    refreshed = scan_reel(store, prefix.header.reel_id)
    if _find_segment(refreshed, kind, release_id, rows) != start:
        raise ValueError('new segment did not persist at its allocated addresses')
    return start, refreshed


def _scan_bound_reels(store: FileReelStore, binding: UnloadBinding) -> tuple[ReelPrefix, ReelPrefix, ReelPrefix]:
    amplitude = scan_reel(store, binding.amplitude.reel_id)
    first = scan_reel(store, binding.first_quality.reel_id)
    nextq = scan_reel(store, binding.next_quality.reel_id)
    headers = (amplitude.header, first.header, nextq.header)
    if headers != (binding.amplitude, binding.first_quality, binding.next_quality):
        raise RequestConflict(f'reel identity differs for request {binding.request_id}')
    return amplitude, first, nextq


def _check_parameters(binding: UnloadBinding | None, request_id: str, parameters: tuple) -> None:
    if binding is not None and parameters != binding.parameters():
        raise RequestConflict(f'parameters differ for request {request_id}')


def _load_batch(prepared: PreparedCatalog, binding: UnloadBinding) -> PreparedBatch:
    batch = prepared.get(binding.prepared_id)
    if binding.cut >= len(batch.rows):
        raise ValueError('cut must lie strictly inside the prepared row count')
    return batch


def _build_unload_receipt(
    binding: UnloadBinding, release_id: str, attempt: int,
    first_start: int, next_start: int, count: int,
) -> ReleaseReceipt:
    cut = binding.cut
    amplitude_addresses = tuple(
        RecordAddress(binding.amplitude.reel_id, attempt + index) for index in range(count)
    )
    quality_addresses = tuple(
        RecordAddress(binding.first_quality.reel_id, first_start + index) for index in range(cut)
    ) + tuple(
        RecordAddress(binding.next_quality.reel_id, next_start + index)
        for index in range(count - cut)
    )
    return ReleaseReceipt(
        binding.request_id, binding.prepared_id, release_id, amplitude_addresses, quality_addresses,
    )


def issue_unload_permit(
    store: FileReelStore,
    prepared: PreparedCatalog,
    request_id: str,
    prepared_id: str,
    amplitude_reel_id: str,
    first_quality_reel_id: str,
    next_quality_reel_id: str,
    cut: int,
    checkpoint: Checkpoint | None = None,
) -> UnloadPermit:
    if not _text(request_id):
        raise ValueError('request id must be nonempty text')
    if type(cut) is not int or cut <= 0:
        raise ValueError('cut must be a positive integer')
    existing = find_unload_request(store, request_id)
    _check_parameters(
        existing, request_id,
        (prepared_id, amplitude_reel_id, first_quality_reel_id, next_quality_reel_id, cut),
    )
    if existing is not None:
        binding = existing
        release_id = unload_release_number(binding)
        amplitude = scan_reel(store, binding.amplitude.reel_id)
        permit_record = _find_permit_record(amplitude, binding, release_id)
        if permit_record is not None:
            return _permit_from_record(binding, release_id, permit_record)
    else:
        binding = UnloadBinding(
            request_id, prepared_id, cut,
            scan_reel(store, amplitude_reel_id).header,
            scan_reel(store, first_quality_reel_id).header,
            scan_reel(store, next_quality_reel_id).header,
        )
        release_id = unload_release_number(binding)

    amplitude, first, _ = _scan_bound_reels(store, binding)
    batch = _load_batch(prepared, binding)
    if existing is None:
        append_record(store, binding.amplitude.reel_id, LogicalRecord(REQUEST_KIND, binding.payload()))
    first_start, first = _ensure_segment(
        store, first, QUALITY_KIND, release_id, batch.rows[:binding.cut], checkpoint,
    )
    permit_body = {
        **binding.payload(), 'release': release_id,
        'recording': batch.recording_id, 'first_start': first_start,
    }
    append_record(store, binding.amplitude.reel_id, LogicalRecord(PERMIT_KIND, permit_body))
    permit = UnloadPermit(
        binding.request_id, binding.prepared_id, release_id,
        tuple(
            RecordAddress(binding.first_quality.reel_id, first_start + index)
            for index in range(binding.cut)
        ),
    )
    _notify(checkpoint, 'permit_effective', permit, release_id)
    return permit


def _receipt_from_effective(
    binding: UnloadBinding, permit_record, effective, batch: PreparedBatch,
    amplitude: ReelPrefix, nextq: ReelPrefix,
) -> ReleaseReceipt:
    release_id = unload_release_number(binding)
    body = effective.logical.payload
    count = len(batch.rows)
    first_start = permit_record.logical.payload['first_start']
    attempt = body.get('attempt')
    next_start = body.get('next_start')
    expected = {
        **binding.payload(), 'release': release_id, 'recording': batch.recording_id,
        'attempt': attempt, 'first_start': first_start, 'next_start': next_start, 'count': count,
    }
    if body != expected:
        raise ValueError('committed unload release differs from the bound request')
    if not _positive(attempt) or not _positive(next_start):
        raise ValueError('committed unload release has invalid addresses')
    if effective.address.ordinal <= max(attempt + count - 1, permit_record.address.ordinal):
        raise ValueError('committed unload release precedes its own data')
    if not _segment_matches(amplitude, AMPLITUDE_KIND, release_id, batch.rows, attempt):
        raise ValueError('committed unload release is missing its original amplitude data')
    if not _segment_matches(nextq, QUALITY_KIND, release_id, batch.rows[binding.cut:], next_start):
        raise ValueError('committed unload release is missing its original quality data')
    return _build_unload_receipt(binding, release_id, attempt, first_start, next_start, count)


def publish_after_unload(
    store: FileReelStore,
    prepared: PreparedCatalog,
    request_id: str,
    prepared_id: str,
    amplitude_reel_id: str,
    first_quality_reel_id: str,
    next_quality_reel_id: str,
    cut: int,
    checkpoint: Checkpoint | None = None,
) -> ReleaseReceipt:
    if not _text(request_id):
        raise ValueError('request id must be nonempty text')
    if type(cut) is not int or cut <= 0:
        raise ValueError('cut must be a positive integer')
    binding = find_unload_request(store, request_id)
    if binding is None:
        raise ValueError(f'no unload permit for request {request_id}')
    _check_parameters(
        binding, request_id,
        (prepared_id, amplitude_reel_id, first_quality_reel_id, next_quality_reel_id, cut),
    )
    release_id = unload_release_number(binding)
    amplitude = scan_reel(store, binding.amplitude.reel_id)
    permit_record = _find_permit_record(amplitude, binding, release_id)
    if permit_record is None:
        raise ValueError(f'unload permit is not effective for request {request_id}')
    nextq = scan_reel(store, binding.next_quality.reel_id)
    if amplitude.header != binding.amplitude or nextq.header != binding.next_quality:
        raise RequestConflict(f'reel identity differs for request {request_id}')
    batch = _load_batch(prepared, binding)
    count = len(batch.rows)
    first_start = permit_record.logical.payload['first_start']

    for stored in amplitude.records:
        if stored.logical.kind == EFFECTIVE_KIND and stored.logical.payload.get('release') == release_id:
            return _receipt_from_effective(binding, permit_record, stored, batch, amplitude, nextq)

    attempt, amplitude = _ensure_segment(
        store, amplitude, AMPLITUDE_KIND, release_id, batch.rows, checkpoint,
    )
    next_start, nextq = _ensure_segment(
        store, nextq, QUALITY_KIND, release_id, batch.rows[binding.cut:], checkpoint,
    )
    effective_body = {
        **binding.payload(), 'release': release_id, 'recording': batch.recording_id,
        'attempt': attempt, 'first_start': first_start, 'next_start': next_start, 'count': count,
    }
    address = append_record(store, binding.amplitude.reel_id, LogicalRecord(EFFECTIVE_KIND, effective_body))
    _notify(checkpoint, 'release_effective', address, release_id)
    return _build_unload_receipt(binding, release_id, attempt, first_start, next_start, count)
