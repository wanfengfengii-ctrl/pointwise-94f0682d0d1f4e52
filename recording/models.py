from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class DeviceSource:
    device_id: str
    section: str


@dataclass(frozen=True)
class RawReading:
    position: int
    amplitude: Decimal | None
    unit: str
    status: str

    def snapshot(self) -> dict:
        return {
            'position': self.position,
            'amplitude': None if self.amplitude is None else str(self.amplitude),
            'unit': self.unit,
            'status': self.status,
        }


@dataclass(frozen=True)
class RawRowRef:
    recording_id: str
    row_index: int


@dataclass(frozen=True)
class FrozenRecording:
    recording_id: str
    submission: str
    source: DeviceSource
    rows: tuple[RawReading, ...]

    @property
    def row_refs(self) -> tuple[RawRowRef, ...]:
        return tuple(RawRowRef(self.recording_id, index) for index in range(len(self.rows)))
