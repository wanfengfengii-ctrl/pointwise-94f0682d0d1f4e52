from dataclasses import dataclass

from reels.append import append_record
from reels.records import LogicalRecord, ReelHeader, RecordAddress
from reels.scan import scan_reel
from reels.storage import FileReelStore


class RequestConflict(ValueError):
    """The request number is already bound to different parameters."""


@dataclass(frozen=True)
class RequestBinding:
    request_id: str
    prepared_id: str
    amplitude: ReelHeader
    quality: ReelHeader

    def __post_init__(self) -> None:
        for name in (self.request_id, self.prepared_id):
            if not isinstance(name, str) or not name.strip():
                raise ValueError('request and prepared ids must be nonempty text')
        if self.amplitude.role != 'amplitude' or self.quality.role != 'quality':
            raise ValueError('request requires an ordered amplitude and quality reel pair')
        if self.amplitude.reel_id == self.quality.reel_id or self.amplitude.serial == self.quality.serial:
            raise ValueError('request requires two distinct physical reels')

    def payload(self) -> dict:
        return {
            'request': self.request_id,
            'prepared': self.prepared_id,
            'left': self.amplitude.identity(),
            'right': self.quality.identity(),
        }


def find_request(store: FileReelStore, request_id: str) -> RequestBinding | None:
    found = None
    for reel_id in store.list_reels():
        prefix = scan_reel(store, reel_id)
        if prefix.header.role != 'amplitude':
            continue
        for stored in prefix.records:
            if stored.logical.kind != 'request_v1':
                continue
            body = stored.logical.payload
            if body.get('request') != request_id:
                continue
            if body.get('left') != prefix.header.identity():
                raise ValueError(f'invalid stored request origin for {request_id}')
            right_id, right_serial = body['right']
            binding = RequestBinding(
                request_id, body['prepared'], prefix.header,
                ReelHeader(right_id, 'quality', right_serial),
            )
            if found is not None and found != binding:
                raise ValueError(f'multiple stored bindings for request {request_id}')
            found = binding
    return found


def bind_request(store: FileReelStore, binding: RequestBinding) -> RecordAddress | None:
    current = find_request(store, binding.request_id)
    if current is not None:
        if current != binding:
            raise RequestConflict(f'parameters differ for request {binding.request_id}')
        return None
    for expected in (binding.amplitude, binding.quality):
        actual, _ = store.read_frames(expected.reel_id)
        if actual != expected:
            raise ValueError(f'request reel identity differs for {expected.reel_id}')
    return append_record(
        store, binding.amplitude.reel_id, LogicalRecord('request_v1', binding.payload()),
    )
