import hashlib
import json
from dataclasses import dataclass

from issue.requests import RequestBinding
from prepare.catalog import PreparedBatch
from prepare.rows import PreparedRow
from reels.records import LogicalRecord, RecordAddress


@dataclass(frozen=True)
class CandidateRelease:
    release_id: str
    binding: RequestBinding
    recording_id: str
    attempt: int
    count: int

    def row_records(self, row: PreparedRow) -> tuple[LogicalRecord, LogicalRecord]:
        common = {
            'release': self.release_id,
            'attempt': self.attempt,
            'recording': row.raw_ref.recording_id,
            'index': row.raw_ref.row_index,
            'position': row.position,
        }
        return (
            LogicalRecord('amplitude_v1', {**common, 'value': row.amplitude_uv}),
            LogicalRecord('quality_v1', {**common, 'value': row.quality}),
        )

    def effective_record(self, quality_start: int) -> LogicalRecord:
        return LogicalRecord('effective_v1', {
            **self.binding.payload(),
            'release': self.release_id,
            'recording': self.recording_id,
            'attempt': self.attempt,
            'right_start': quality_start,
            'count': self.count,
        })


@dataclass(frozen=True)
class ReleaseReceipt:
    request_id: str
    prepared_id: str
    release_id: str
    amplitude_addresses: tuple[RecordAddress, ...]
    quality_addresses: tuple[RecordAddress, ...]


def release_number(binding: RequestBinding) -> str:
    encoded = json.dumps(binding.payload(), sort_keys=True, separators=(',', ':')).encode('ascii')
    return 'rel-' + hashlib.sha256(encoded).hexdigest()


def allocate_candidate(binding: RequestBinding, batch: PreparedBatch, amplitude_start: int) -> CandidateRelease:
    if batch.prepared_id != binding.prepared_id or not batch.rows:
        raise ValueError('candidate requires the bound nonempty prepared batch')
    if type(amplitude_start) is not int or amplitude_start <= 0:
        raise ValueError('candidate requires a positive first amplitude address')
    return CandidateRelease(release_number(binding), binding, batch.recording_id, amplitude_start, len(batch.rows))


def build_receipt(candidate: CandidateRelease, quality_start: int) -> ReleaseReceipt:
    binding = candidate.binding
    return ReleaseReceipt(
        binding.request_id, binding.prepared_id, candidate.release_id,
        tuple(RecordAddress(binding.amplitude.reel_id, candidate.attempt + i) for i in range(candidate.count)),
        tuple(RecordAddress(binding.quality.reel_id, quality_start + i) for i in range(candidate.count)),
    )
