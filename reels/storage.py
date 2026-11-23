import json
import os
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile

from reels.records import ReelHeader, RecordAddress, check_reel_id, decode_record, encode_record


_BASE = 'base.json'


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _install_complete_file(path: Path, data: bytes) -> None:
    with NamedTemporaryFile(dir=path.parent, prefix='.pending-', delete=False) as handle:
        staged = Path(handle.name)
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.link(staged, path)
            _sync_directory(path.parent)
        finally:
            staged.unlink()


def _read_base(path: Path) -> tuple[ReelHeader, tuple[bytes, ...]]:
    base = json.loads(path.read_bytes())
    if not isinstance(base, dict) or base.keys() != {'version', 'header', 'records'}:
        raise ValueError(f'invalid reel base {path.name}')
    if type(base['version']) is not int or base['version'] != 1:
        raise ValueError('unsupported reel base version')
    header = base['header']
    if not isinstance(header, dict) or header.keys() != {'reel_id', 'role', 'serial'}:
        raise ValueError('invalid reel header')
    records = base['records']
    if not isinstance(records, list):
        raise ValueError('invalid reel base records')
    frames = tuple(
        encode_record(decode_record(json.dumps(record, ensure_ascii=True).encode('ascii')))
        for record in records
    )
    return ReelHeader(**header), frames


def _slot_name(ordinal: int) -> str:
    return f'{ordinal:020d}.frame'


class FileReelStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _folder(self, reel_id: str) -> Path:
        check_reel_id(reel_id)
        return self.root / reel_id

    def initialize_reel(self, header: ReelHeader) -> ReelHeader:
        if not isinstance(header, ReelHeader):
            raise ValueError('expected a ReelHeader')
        folder = self._folder(header.reel_id)
        base = folder / _BASE
        if not base.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            folder.mkdir(exist_ok=True)
            if any(folder.glob('*.frame')):
                raise ValueError('cannot initialize a reel with records but no header')
            contents = {'version': 1, 'header': asdict(header), 'records': []}
            data = json.dumps(contents, ensure_ascii=True, sort_keys=True).encode('ascii')
            try:
                _install_complete_file(base, data)
            except FileExistsError:
                pass
            _sync_directory(self.root)
            _sync_directory(self.root.parent)
        stored, frames = self.read_frames(header.reel_id)
        if stored != header:
            raise ValueError(f'identity differs for reel {header.reel_id}')
        for frame in frames:
            decode_record(frame)
        return stored

    def list_reels(self) -> tuple[str, ...]:
        if not self.root.exists():
            return ()
        return tuple(sorted(
            folder.name for folder in self.root.iterdir()
            if folder.is_dir() and (folder / _BASE).is_file()
        ))

    def read_frames(self, reel_id: str) -> tuple[ReelHeader, tuple[bytes, ...]]:
        folder = self._folder(reel_id)
        header, base_frames = _read_base(folder / _BASE)
        if header.reel_id != reel_id:
            raise ValueError(f'reel header does not match {reel_id}')
        frames = list(base_frames)
        files = sorted(folder.glob('*.frame'))
        for ordinal, path in enumerate(files, start=len(base_frames) + 1):
            if path.name != _slot_name(ordinal):
                raise ValueError(f'invalid physical sequence on reel {reel_id}')
            frames.append(path.read_bytes())
        return header, tuple(frames)

    def append_frame(
        self, reel_id: str, frame: bytes, expected_ordinal: int | None = None,
    ) -> RecordAddress:
        encoded = encode_record(decode_record(frame))
        _, current = self.read_frames(reel_id)
        ordinal = len(current) + 1
        if expected_ordinal is not None:
            if type(expected_ordinal) is not int or expected_ordinal != ordinal:
                raise ValueError('append must target the next physical address')
        path = self._folder(reel_id) / _slot_name(ordinal)
        _install_complete_file(path, encoded)
        return RecordAddress(reel_id, ordinal)
