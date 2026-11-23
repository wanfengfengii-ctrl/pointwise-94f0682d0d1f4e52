from dataclasses import dataclass

from reels.records import ReelHeader
from reels.scan import scan_prefix
from reels.storage import FileReelStore


@dataclass(frozen=True)
class ReelCopy:
    header: ReelHeader
    frames: tuple[bytes, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.header, ReelHeader):
            raise ValueError('expected a reel header')
        frames = tuple(self.frames)
        if any(not isinstance(frame, bytes) for frame in frames):
            raise ValueError('copy requires immutable complete frames')
        object.__setattr__(self, 'frames', frames)


def copy_prefix(store: FileReelStore, reel_id: str, count: int | None = None) -> ReelCopy:
    header, frames = store.read_frames(reel_id)
    if count is None:
        count = len(frames)
    if type(count) is not int or not 0 <= count <= len(frames):
        raise ValueError(f'not a valid complete-record cut on reel {reel_id}')
    selected = frames[:count]
    scan_prefix(header, selected)
    return ReelCopy(header, selected)
