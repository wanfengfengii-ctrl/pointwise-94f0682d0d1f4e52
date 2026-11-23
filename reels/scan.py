from collections.abc import Iterable
from dataclasses import dataclass

from reels.records import ReelHeader, RecordAddress, StoredRecord, decode_record
from reels.storage import FileReelStore


@dataclass(frozen=True)
class ReelPrefix:
    header: ReelHeader
    records: tuple[StoredRecord, ...]


def scan_prefix(header: ReelHeader, frames: Iterable[bytes]) -> ReelPrefix:
    if not isinstance(header, ReelHeader):
        raise ValueError('expected a reel header')
    records = tuple(
        StoredRecord(RecordAddress(header.reel_id, ordinal), decode_record(frame))
        for ordinal, frame in enumerate(frames, start=1)
    )
    return ReelPrefix(header, records)


def scan_reel(store: FileReelStore, reel_id: str) -> ReelPrefix:
    header, frames = store.read_frames(reel_id)
    return scan_prefix(header, frames)


def record_at(prefix: ReelPrefix, address: RecordAddress) -> StoredRecord | None:
    if address.reel_id != prefix.header.reel_id or address.ordinal > len(prefix.records):
        return None
    stored = prefix.records[address.ordinal - 1]
    return stored if stored.address == address else None
