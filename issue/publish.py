from collections.abc import Callable

from issue.allocate import CandidateRelease, ReleaseReceipt, allocate_candidate, build_receipt
from issue.recover import recover_request
from issue.requests import RequestBinding, RequestConflict, bind_request, find_request
from issue.unload import issue_unload_permit, publish_after_unload
from prepare.catalog import PreparedBatch, PreparedCatalog
from reels.append import append_record
from reels.records import RecordAddress
from reels.scan import scan_reel
from reels.storage import FileReelStore


Checkpoint = Callable[[str, RecordAddress | ReleaseReceipt, str | None], None]


def _notify(
    callback: Checkpoint | None, stage: str, detail: RecordAddress | ReleaseReceipt, release_id: str | None,
) -> None:
    if callback is not None:
        callback(stage, detail, release_id)


def _append_candidate(
    store: FileReelStore, batch: PreparedBatch, candidate: CandidateRelease,
    quality_start: int, checkpoint: Checkpoint | None,
) -> None:
    rows = [candidate.row_records(row) for row in batch.rows]
    for index, (amplitude, _) in enumerate(rows):
        address = append_record(store, candidate.binding.amplitude.reel_id, amplitude, candidate.attempt + index)
        _notify(checkpoint, 'amplitude_written', address, candidate.release_id)
    for index, (_, quality) in enumerate(rows):
        address = append_record(store, candidate.binding.quality.reel_id, quality, quality_start + index)
        _notify(checkpoint, 'quality_written', address, candidate.release_id)


def publish(
    store: FileReelStore,
    prepared: PreparedCatalog,
    request_id: str,
    prepared_id: str,
    amplitude_reel_id: str,
    quality_reel_id: str,
    checkpoint: Checkpoint | None = None,
) -> ReleaseReceipt:
    existing = find_request(store, request_id)
    if existing is not None:
        parameters = (prepared_id, amplitude_reel_id, quality_reel_id)
        original = (existing.prepared_id, existing.amplitude.reel_id, existing.quality.reel_id)
        if parameters != original:
            raise RequestConflict(f'parameters differ for request {request_id}')

    amplitude = scan_reel(store, amplitude_reel_id)
    quality = scan_reel(store, quality_reel_id)
    binding = RequestBinding(request_id, prepared_id, amplitude.header, quality.header)
    if existing is not None and binding != existing:
        raise RequestConflict(f'reel identity differs for request {request_id}')
    batch = prepared.get(prepared_id)
    if existing is None:
        address = bind_request(store, binding)
        if address is not None:
            _notify(checkpoint, 'request_bound', address, None)
        amplitude = scan_reel(store, amplitude_reel_id)

    recovered = recover_request(binding, batch, amplitude, quality)
    if recovered.receipt is not None:
        _notify(checkpoint, 'before_reply', recovered.receipt, recovered.receipt.release_id)
        return recovered.receipt

    if recovered.phase == 'pending':
        candidate = allocate_candidate(binding, batch, len(amplitude.records) + 1)
        quality_start = len(quality.records) + 1
        _append_candidate(store, batch, candidate, quality_start, checkpoint)
        recovered = recover_request(
            binding, batch, scan_reel(store, amplitude_reel_id), scan_reel(store, quality_reel_id),
        )
        if recovered.candidate != candidate or recovered.quality_start != quality_start:
            raise ValueError('new candidate did not persist at its allocated addresses')

    candidate = recovered.candidate
    quality_start = recovered.quality_start
    if recovered.phase != 'ready' or candidate is None or quality_start is None:
        raise ValueError('candidate is not ready to take effect')
    address = append_record(store, amplitude_reel_id, candidate.effective_record(quality_start))
    _notify(checkpoint, 'release_effective', address, candidate.release_id)
    receipt = build_receipt(candidate, quality_start)
    _notify(checkpoint, 'before_reply', receipt, receipt.release_id)
    return receipt
