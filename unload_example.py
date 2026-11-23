"""Three-reel fixture and public caller for the unload workflow."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from issue.allocate import ReleaseReceipt
from issue.publish import publish
from issue.requests import RequestConflict
from prepare.batch import prepare_batch
from recording.intake import accept_recording
from recording.models import DeviceSource
from reels.copy import ReelCopy, copy_prefix
from reels.records import ReelHeader
from reels.storage import FileReelStore
from review.read import read_release
from tests.support import StopAt, Workspace


SAMPLE = ((14, 7, 'OK'), (2, 11, 'RECHECK'), (9, 13, 'OK'))
EXPECTED_ROWS = [[14, 7, '合格'], [2, 11, '复检'], [9, 13, '合格']]
EXPECTED_TOTALS = {'合格': [2, 20], '复检': [1, 11]}


def make_batch(root):
    work = Workspace(root)
    for reel_id, role in (('A', 'amplitude'), ('Q1', 'quality'), ('Q2', 'quality')):
        work.reels.initialize_reel(ReelHeader(reel_id, role, 'track-' + reel_id))
    rows = [dict(position=p, amplitude=v, unit='uV', status=s) for p, v, s in SAMPLE]
    recording = accept_recording(work.recordings, 'transport-shift', DeviceSource('track-car-07', 'north-7'), rows)
    return work, prepare_batch(work.recordings, work.prepared, recording.recording_id)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def expect_error(error, operation, *args, **kwargs):
    try:
        operation(*args, **kwargs)
    except error:
        return
    raise AssertionError(f'{operation.__name__} did not raise {error.__name__}')


def summary(result, receipt, batch, reel_ids):
    require(result.available and result.release_id == receipt.release_id, 'release unavailable or misbound')
    rows = [[row.position, row.amplitude_uv, row.quality] for row in result.rows]
    totals = {group.quality: [group.row_count, group.amplitude_sum_uv] for group in result.totals}
    require(rows == EXPECTED_ROWS and totals == EXPECTED_TOTALS, 'unexpected rows or totals')
    require(tuple(row.row_ref for row in result.rows) == tuple((batch.recording_id, i) for i in range(3)), 'raw refs changed')
    require(tuple(row.amplitude_address for row in result.rows) == receipt.amplitude_addresses, 'wrong amplitude addresses')
    addresses = tuple(row.quality_address for row in result.rows)
    require(addresses == receipt.quality_addresses and [a.reel_id for a in addresses] == reel_ids, 'wrong quality addresses')
    return {'release': result.release_id, 'rows': rows, 'totals': totals,
            'addresses': [[[row.amplitude_address.reel_id, row.amplitude_address.ordinal],
                           [row.quality_address.reel_id, row.quality_address.ordinal]] for row in result.rows]}


def run_fixture(root):
    work, batch = make_batch(root / 'station')
    receipt = publish(work.reels, work.prepared, 'ordinary', batch.prepared_id, 'A', 'Q1')
    left, right = (copy_prefix(work.reels, reel_id) for reel_id in ('A', 'Q1'))
    shutil.rmtree(work.root)
    return summary(read_release(receipt.release_id, left, right), receipt, batch, ['Q1'] * 3)


def run_unload(root):
    from issue.publish import issue_unload_permit, publish_after_unload
    from review.read import read_split_release

    work, batch = make_batch(root / 'station')
    params = ('transport-17', batch.prepared_id, 'A', 'Q1', 'Q2', 2)
    written = []
    stop = StopAt('quality_written', 2)

    def after_write(stage, detail, release_id):
        if stage == 'quality_written':
            written.append(detail)
        stop(stage, detail, release_id)

    expect_error(InterruptedError, issue_unload_permit, work.reels, work.prepared, *params, checkpoint=after_write)
    early_left = copy_prefix(work.reels, 'A')
    parked = root / 'transport'
    parked.mkdir()
    live_path = work.reels.root / 'Q1'
    parked_path = parked / 'Q1'
    live_path.rename(parked_path)
    reopened = Workspace(work.root)
    expect_error(FileNotFoundError, issue_unload_permit, reopened.reels, reopened.prepared, *params)
    expect_error(ValueError, publish_after_unload, reopened.reels, reopened.prepared, *params)
    parked_path.rename(live_path)
    reopened = Workspace(work.root)

    permit_stop = StopAt('permit_effective')
    expect_error(InterruptedError, issue_unload_permit, reopened.reels, reopened.prepared, *params, checkpoint=permit_stop)
    live_path.rename(parked_path)
    reopened = Workspace(work.root)
    permit = issue_unload_permit(reopened.reels, reopened.prepared, *params)
    require(permit == permit_stop.detail and permit.release_id == stop.release_id, 'first permit changed')
    require((permit.request_id, permit.prepared_id) == params[:2], 'wrong permit request')
    require(permit.quality_addresses == tuple(written), 'already written Q1 addresses moved')
    before = tuple(copy_prefix(reopened.reels, reel_id) for reel_id in ('A', 'Q2'))
    for operation in (issue_unload_permit, publish_after_unload):
        expect_error(RequestConflict, operation, reopened.reels, reopened.prepared, *params[:-1], 1)
    require(tuple(copy_prefix(reopened.reels, reel_id) for reel_id in ('A', 'Q2')) == before, 'conflict rewrote mounted reels')

    release_stop = StopAt('release_effective')
    expect_error(InterruptedError, publish_after_unload, reopened.reels, reopened.prepared, *params, checkpoint=release_stop)
    reopened = Workspace(work.root)
    left, tail = (copy_prefix(reopened.reels, reel_id) for reel_id in ('A', 'Q2'))
    first = copy_prefix(FileReelStore(parked), 'Q1')
    receipt = publish_after_unload(reopened.reels, reopened.prepared, *params)
    require(isinstance(receipt, ReleaseReceipt) and receipt.release_id == permit.release_id == release_stop.release_id,
            'effective release id changed')
    require((receipt.request_id, receipt.prepared_id) == params[:2], 'wrong release request')
    require(receipt.quality_addresses[:2] == permit.quality_addresses, 'permit disagrees with final receipt')
    require((left, tail) == tuple(copy_prefix(reopened.reels, reel_id) for reel_id in ('A', 'Q2')), 'replay appended frames')
    require(issue_unload_permit(reopened.reels, reopened.prepared, *params) == permit, 'final release changed permit')
    shutil.rmtree(work.root)
    shutil.rmtree(parked)

    other, same_batch = make_batch(root / 'other-request')
    issue_unload_permit(other.reels, other.prepared, 'other-17', same_batch.prepared_id, 'A', 'Q1', 'Q2', 2)
    foreign = copy_prefix(other.reels, 'Q1')
    shutil.rmtree(other.root)
    offset = permit.quality_addresses[1].ordinal - 1
    wrong_reel = ReelCopy(ReelHeader('Q1', 'quality', 'other-serial'), first.frames)
    cases = {
        'before_release': (early_left, first, tail),
        'missing_q1': (left, None, tail),
        'short_q1': (left, ReelCopy(first.header, first.frames[:offset]), tail),
        'wrong_q1': (left, wrong_reel, tail),
        'foreign_same_value': (left, foreign, tail),
    }
    for name, copies in cases.items():
        rejected = read_split_release(receipt.release_id, *copies)
        require(not rejected.available and not hasattr(rejected, 'rows') and not hasattr(rejected, 'totals'), name)
    result = read_split_release(receipt.release_id, left, first, tail)
    return {**summary(result, receipt, batch, ['Q1', 'Q1', 'Q2']), 'unavailable': list(cases)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('fixture', 'verify', 'demo'))
    mode = parser.parse_args().mode
    if mode == 'verify':
        subprocess.run([sys.executable, '-B', 'check_project.py'], check=True)
    with TemporaryDirectory(prefix='track-unload-') as temporary:
        root = Path(temporary)
        result = run_fixture(root) if mode == 'fixture' else run_unload(root)
    print('POINTWISE_SCENARIO ' + json.dumps({'case_id': mode, 'actual': result}, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
