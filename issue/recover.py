from dataclasses import dataclass
from typing import Literal

from issue.allocate import CandidateRelease, ReleaseReceipt, allocate_candidate, build_receipt, release_number
from issue.requests import RequestBinding
from prepare.catalog import PreparedBatch
from reels.records import RecordAddress
from reels.scan import ReelPrefix, record_at


@dataclass(frozen=True)
class RecoveryState:
    phase: Literal['pending', 'ready', 'effective']
    candidate: CandidateRelease | None = None
    quality_start: int | None = None
    receipt: ReleaseReceipt | None = None


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


def _require_bound_reels(binding: RequestBinding, amplitude: ReelPrefix, quality: ReelPrefix) -> None:
    if amplitude.header != binding.amplitude or quality.header != binding.quality:
        raise ValueError('recovery requires the original target reel pair')


def _has_candidate_rows(
    candidate: CandidateRelease, batch: PreparedBatch, quality_start: int,
    amplitude: ReelPrefix, quality: ReelPrefix,
) -> bool:
    if candidate.attempt + candidate.count - 1 > len(amplitude.records):
        return False
    if quality_start + candidate.count - 1 > len(quality.records):
        return False
    for index, row in enumerate(batch.rows):
        left = record_at(amplitude, RecordAddress(amplitude.header.reel_id, candidate.attempt + index))
        right = record_at(quality, RecordAddress(quality.header.reel_id, quality_start + index))
        if left is None or right is None:
            return False
        if (left.logical, right.logical) != candidate.row_records(row):
            return False
    return True


def find_effective_release(
    binding: RequestBinding, batch: PreparedBatch, amplitude: ReelPrefix, quality: ReelPrefix,
) -> ReleaseReceipt | None:
    _require_bound_reels(binding, amplitude, quality)
    for entry in amplitude.records:
        if entry.logical.kind != 'effective_v1':
            continue
        body = entry.logical.payload
        if body.get('request') != binding.request_id:
            continue
        first_amplitude = body.get('attempt')
        first_quality = body.get('right_start')
        if not _positive(first_amplitude) or not _positive(first_quality):
            raise ValueError('committed release has invalid addresses')
        candidate = allocate_candidate(binding, batch, first_amplitude)
        if entry.logical != candidate.effective_record(first_quality):
            raise ValueError('committed release differs from the bound request')
        if entry.address.ordinal < candidate.attempt + candidate.count:
            raise ValueError('committed release precedes its own data')
        if not _has_candidate_rows(candidate, batch, first_quality, amplitude, quality):
            raise ValueError('committed release is missing its original data')
        return build_receipt(candidate, first_quality)
    return None


def recover_request(
    binding: RequestBinding, batch: PreparedBatch, amplitude: ReelPrefix, quality: ReelPrefix,
) -> RecoveryState:
    receipt = find_effective_release(binding, batch, amplitude, quality)
    if receipt is not None:
        return RecoveryState('effective', receipt=receipt)
    release_id = release_number(binding)
    for entry in reversed(quality.records):
        if entry.logical.kind != 'quality_v1':
            continue
        body = entry.logical.payload
        if body.get('release') != release_id or body.get('index') != 0 or not _positive(body.get('attempt')):
            continue
        candidate = allocate_candidate(binding, batch, body['attempt'])
        if _has_candidate_rows(candidate, batch, entry.address.ordinal, amplitude, quality):
            return RecoveryState('ready', candidate=candidate, quality_start=entry.address.ordinal)
    return RecoveryState('pending')
