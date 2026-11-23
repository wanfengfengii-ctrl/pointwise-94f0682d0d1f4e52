from dataclasses import dataclass
from typing import ClassVar

from reels.records import RecordAddress
from review.coverage import MatchedRow
from review.reconcile import QualityTotals


@dataclass(frozen=True)
class ReviewRow:
    row_ref: tuple[str, int]
    position: int
    amplitude_uv: int | None
    quality: str
    amplitude_address: RecordAddress
    quality_address: RecordAddress


@dataclass(frozen=True)
class ReviewResult:
    release_id: str
    rows: tuple[ReviewRow, ...]
    totals: tuple[QualityTotals, ...]
    available: ClassVar[bool] = True


@dataclass(frozen=True)
class ReviewUnavailable:
    release_id: str
    reason: str = 'insufficient_evidence'
    available: ClassVar[bool] = False


def build_review_result(
    release_id: str, rows: tuple[MatchedRow, ...], totals: tuple[QualityTotals, ...],
) -> ReviewResult:
    return ReviewResult(release_id, tuple(
        ReviewRow(
            (row.recording_id, row.row_index), row.position, row.amplitude_uv,
            row.quality, row.amplitude_address, row.quality_address,
        )
        for row in rows
    ), totals)
