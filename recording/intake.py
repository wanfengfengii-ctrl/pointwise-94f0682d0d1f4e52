from collections.abc import Iterable, Mapping

from recording.catalog import RecordingCatalog
from recording.identity import make_recording_id
from recording.models import DeviceSource, FrozenRecording
from recording.validation import validate_submission


def accept_recording(
    catalog: RecordingCatalog,
    submission: str,
    source: DeviceSource,
    rows: Iterable[Mapping],
) -> FrozenRecording:
    validated = validate_submission(submission, source, rows)
    recording_id = make_recording_id(submission, source, validated)
    recording = FrozenRecording(recording_id, submission, source, validated)
    catalog.save(recording)
    return recording
