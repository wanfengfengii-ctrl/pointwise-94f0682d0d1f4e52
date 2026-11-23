from reels.records import LogicalRecord, RecordAddress, encode_record
from reels.storage import FileReelStore


def append_record(
    store: FileReelStore,
    reel_id: str,
    logical: LogicalRecord,
    expected_ordinal: int | None = None,
) -> RecordAddress:
    return store.append_frame(reel_id, encode_record(logical), expected_ordinal)
