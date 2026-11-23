from collections.abc import Iterable
from dataclasses import dataclass

from review.coverage import MatchedRow


@dataclass(frozen=True)
class QualityTotals:
    quality: str
    row_count: int
    amplitude_sum_uv: int


def reconcile_quality(rows: Iterable[MatchedRow]) -> tuple[QualityTotals, ...]:
    groups: dict[str, tuple[int, int]] = {}
    for row in rows:
        count, total = groups.get(row.quality, (0, 0))
        if row.amplitude_uv is not None:
            total += row.amplitude_uv
        groups[row.quality] = (count + 1, total)
    return tuple(QualityTotals(quality, *groups[quality]) for quality in sorted(groups))
