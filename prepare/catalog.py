from dataclasses import asdict, dataclass
from pathlib import Path

from prepare.rows import PreparedRow
from recording.catalog import _SnapshotDirectory
from recording.models import RawRowRef


@dataclass(frozen=True)
class PreparedBatch:
    prepared_id: str
    recording_id: str
    profile_name: str
    rows: tuple[PreparedRow, ...]


class PreparedCatalog:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self._files = _SnapshotDirectory(self.directory, 'prep')

    def save(self, batch: PreparedBatch) -> None:
        self._files.store(batch.prepared_id, {
            'recording_id': batch.recording_id,
            'profile_name': batch.profile_name,
            'rows': [asdict(row) for row in batch.rows],
        })

    def get(self, prepared_id: str) -> PreparedBatch:
        contents = self._files.load(prepared_id)
        rows = tuple(
            PreparedRow(RawRowRef(**row['raw_ref']), row['position'], row['amplitude_uv'], row['quality'])
            for row in contents['rows']
        )
        return PreparedBatch(prepared_id, contents['recording_id'], contents['profile_name'], rows)
