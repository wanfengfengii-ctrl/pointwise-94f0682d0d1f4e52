from dataclasses import dataclass

from prepare.amplitude import convert_amplitude
from prepare.profile import ConversionProfile
from prepare.quality import normalize_quality
from recording.identity import make_raw_row_ref
from recording.models import FrozenRecording, RawRowRef


@dataclass(frozen=True)
class PreparedRow:
    raw_ref: RawRowRef
    position: int
    amplitude_uv: int | None
    quality: str


def prepare_rows(recording: FrozenRecording, profile: ConversionProfile) -> tuple[PreparedRow, ...]:
    prepared = []
    for index, raw in enumerate(recording.rows):
        prepared.append(PreparedRow(
            make_raw_row_ref(recording.recording_id, index),
            raw.position,
            convert_amplitude(raw.amplitude, raw.unit, profile),
            normalize_quality(raw.status, profile),
        ))
    return tuple(prepared)
