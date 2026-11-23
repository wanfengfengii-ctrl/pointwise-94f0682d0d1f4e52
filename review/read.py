from reels.copy import ReelCopy
from review.coverage import resolve_release
from review.reconcile import reconcile_quality
from review.result import ReviewResult, ReviewUnavailable, build_review_result
from review.split import resolve_split_release


def read_release(
    release_id: str, amplitude_copy: ReelCopy, quality_copy: ReelCopy,
) -> ReviewResult | ReviewUnavailable:
    rows = resolve_release(release_id, amplitude_copy, quality_copy)
    if rows is None:
        return ReviewUnavailable(release_id)
    return build_review_result(release_id, rows, reconcile_quality(rows))


def read_split_release(
    release_id: str,
    amplitude_copy: ReelCopy | None,
    first_quality_copy: ReelCopy | None,
    next_quality_copy: ReelCopy | None,
) -> ReviewResult | ReviewUnavailable:
    rows = resolve_split_release(release_id, amplitude_copy, first_quality_copy, next_quality_copy)
    if rows is None:
        return ReviewUnavailable(release_id)
    return build_review_result(release_id, rows, reconcile_quality(rows))
