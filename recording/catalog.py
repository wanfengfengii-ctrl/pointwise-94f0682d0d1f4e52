import json
import os
import re
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile

from recording.models import DeviceSource, FrozenRecording, RawReading


class _SnapshotDirectory:
    """Immutable, content-addressed JSON files for both catalogs."""

    def __init__(self, directory: Path, prefix: str):
        self.directory = directory
        self._pattern = re.compile(re.escape(prefix) + r'-[0-9a-f]{64}')

    def _path(self, identity: str) -> Path:
        if not isinstance(identity, str) or not self._pattern.fullmatch(identity):
            raise KeyError(identity)
        return self.directory / (identity + '.json')

    def load(self, identity: str) -> dict:
        try:
            return json.loads(self._path(identity).read_bytes())
        except FileNotFoundError:
            raise KeyError(identity) from None

    def store(self, identity: str, contents: dict) -> None:
        destination = self._path(identity)
        data = json.dumps(contents, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
        self.directory.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=self.directory, prefix='.snapshot-', delete=False) as handle:
            staged = Path(handle.name)
            try:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                try:
                    os.link(staged, destination)
                except FileExistsError:
                    if destination.read_bytes() != data:
                        raise ValueError(f'conflicting immutable snapshot {identity}')
                descriptor = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                staged.unlink()


class RecordingCatalog:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self._files = _SnapshotDirectory(self.directory, 'rec')

    def save(self, recording: FrozenRecording) -> None:
        self._files.store(recording.recording_id, {
            'submission': recording.submission,
            'source': {'device_id': recording.source.device_id, 'section': recording.source.section},
            'rows': [row.snapshot() for row in recording.rows],
        })

    def get(self, recording_id: str) -> FrozenRecording:
        contents = self._files.load(recording_id)
        rows = tuple(
            RawReading(
                row['position'],
                None if row['amplitude'] is None else Decimal(row['amplitude']),
                row['unit'],
                row['status'],
            )
            for row in contents['rows']
        )
        return FrozenRecording(recording_id, contents['submission'], DeviceSource(**contents['source']), rows)
