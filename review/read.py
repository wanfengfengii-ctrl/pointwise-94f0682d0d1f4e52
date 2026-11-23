from reels.copy import ReelCopy
from review.coverage import resolve_release
from review.reconcile import reconcile_quality
from review.result import ReviewResult, ReviewUnavailable, build_review_result


def read_release(
    release_id: str, amplitude_copy: ReelCopy, quality_copy: ReelCopy,
) -> ReviewResult | ReviewUnavailable:
    rows = resolve_release(release_id, amplitude_copy, quality_copy)
    if rows is None:
        return ReviewUnavailable(release_id)
    return build_review_result(release_id, rows, reconcile_quality(rows))
