import hashlib
import json

from prepare.catalog import PreparedBatch, PreparedCatalog
from prepare.profile import get_profile
from prepare.rows import prepare_rows
from recording.catalog import RecordingCatalog


def make_prepared_id(recording_id: str, profile_name: str) -> str:
    encoded = json.dumps([recording_id, profile_name], separators=(',', ':')).encode('ascii')
    return 'prep-' + hashlib.sha256(encoded).hexdigest()


def prepare_batch(
    recordings: RecordingCatalog,
    prepared: PreparedCatalog,
    recording_id: str,
    profile_name: str = 'v1',
) -> PreparedBatch:
    recording = recordings.get(recording_id)
    profile = get_profile(profile_name)
    prepared_id = make_prepared_id(recording_id, profile.name)
    try:
        return prepared.get(prepared_id)
    except KeyError:
        pass
    batch = PreparedBatch(prepared_id, recording_id, profile.name, prepare_rows(recording, profile))
    prepared.save(batch)
    return batch
