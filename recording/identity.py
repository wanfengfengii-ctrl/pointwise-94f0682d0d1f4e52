import hashlib
import json

from recording.models import DeviceSource, RawReading, RawRowRef


def make_recording_id(
    submission: str, source: DeviceSource, rows: tuple[RawReading, ...],
) -> str:
    contents = [submission, source.device_id, source.section, [row.snapshot() for row in rows]]
    encoded = json.dumps(contents, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return 'rec-' + hashlib.sha256(encoded.encode('ascii')).hexdigest()


def make_raw_row_ref(recording_id: str, row_index: int) -> RawRowRef:
    if not isinstance(recording_id, str) or not recording_id:
        raise ValueError('recording_id must be nonempty')
    if type(row_index) is not int or row_index < 0:
        raise ValueError('row_index must be a nonnegative integer')
    return RawRowRef(recording_id, row_index)
