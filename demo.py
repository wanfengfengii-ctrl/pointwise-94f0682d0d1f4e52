import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from issue.publish import publish
from prepare.batch import prepare_batch
from prepare.catalog import PreparedCatalog
from recording.catalog import RecordingCatalog
from recording.intake import accept_recording
from recording.models import DeviceSource
from reels.copy import copy_prefix
from reels.records import ReelHeader
from reels.storage import FileReelStore
from review.read import read_release


PROJECT = Path(__file__).resolve().parent


def _expect(actual, expected) -> None:
    if actual != expected:
        raise AssertionError(f'expected {expected!r}, got {actual!r}')


def run_day(directory: Path) -> dict:
    samples = json.loads((PROJECT / 'examples/day.json').read_text(encoding='utf-8'))
    reel_root = directory / 'reels'
    shutil.copytree(PROJECT / 'fixtures/legacy-reels', reel_root)
    store = FileReelStore(reel_root)
    store.initialize_reel(ReelHeader('AMP', 'amplitude', 'track-amp-001'))
    store.initialize_reel(ReelHeader('QUAL', 'quality', 'track-qual-001'))
    old = read_release('legacy-201', copy_prefix(store, 'AMP'), copy_prefix(store, 'QUAL'))
    _expect(old.available, True)
    _expect([(row.position, row.amplitude_uv) for row in old.rows], [(14, 9), (2, None)])

    recordings = RecordingCatalog(directory / 'recordings')
    prepared = PreparedCatalog(directory / 'prepared')
    source = DeviceSource(**samples['source'])
    batches = {}
    for name in ('A', 'B'):
        item = samples[name]
        frozen = accept_recording(recordings, item['submission'], source, item['rows'])
        batches[name] = prepare_batch(recordings, prepared, frozen.recording_id)

    def stop_after_first_quality(stage, detail, release_id):
        if stage == 'quality_written':
            raise InterruptedError('first quality row persisted')

    try:
        publish(store, prepared, 'request-A', batches['A'].prepared_id, 'AMP', 'QUAL', stop_after_first_quality)
    except InterruptedError:
        short_quality = copy_prefix(store, 'QUAL')
    else:
        raise AssertionError('expected interruption after the first quality row')

    first_reply = None

    def drop_reply(stage, detail, release_id):
        nonlocal first_reply
        if stage == 'before_reply':
            first_reply = detail
            raise InterruptedError('reply dropped')

    store = FileReelStore(reel_root)
    prepared = PreparedCatalog(directory / 'prepared')
    try:
        publish(store, prepared, 'request-A', batches['A'].prepared_id, 'AMP', 'QUAL', drop_reply)
    except InterruptedError:
        _expect(first_reply is not None, True)
    else:
        raise AssertionError('expected reply interruption')

    store = FileReelStore(reel_root)
    receipt = publish(store, prepared, 'request-A', batches['A'].prepared_id, 'AMP', 'QUAL')
    _expect(receipt, first_reply)
    publish(store, prepared, 'request-B', batches['B'].prepared_id, 'AMP', 'QUAL')
    shutil.rmtree(recordings.directory)
    shutil.rmtree(prepared.directory)
    amplitude_copy = copy_prefix(store, 'AMP')
    quality_copy = copy_prefix(store, 'QUAL')
    shutil.rmtree(reel_root)

    short = read_release(receipt.release_id, amplitude_copy, short_quality)
    ready = read_release(receipt.release_id, amplitude_copy, quality_copy)
    _expect(ready.available, True)
    _expect(read_release('legacy-201', amplitude_copy, quality_copy), old)
    expected = {
        'short_available': False,
        'rows': [[30, 17, '合格'], [9, 23, '复检']],
        'receipt_matches_original_addresses': True,
    }
    actual = {
        'short_available': short.available,
        'rows': [[row.position, row.amplitude_uv, row.quality] for row in ready.rows],
        'receipt_matches_original_addresses': (
            tuple(row.amplitude_address for row in ready.rows) == receipt.amplitude_addresses
            and tuple(row.quality_address for row in ready.rows) == receipt.quality_addresses
        ),
    }
    expected_totals = {'合格': [1, 17], '复检': [1, 23]}
    actual_totals = {total.quality: [total.row_count, total.amplitude_sum_uv] for total in ready.totals}
    _expect(actual, expected)
    _expect(actual_totals, expected_totals)
    return {
        'case_id': 'V7',
        'input': {
            'source': samples['source'], 'recording': samples['A'],
            'short_quality_records': len(short_quality.frames),
            'received_records': [len(amplitude_copy.frames), len(quality_copy.frames)],
        },
        'expected': expected,
        'actual': actual,
        'downstream_expected': expected_totals,
        'downstream_actual': actual_totals,
        'code_paths': [
            'recording/intake.py', 'prepare/amplitude.py', 'issue/publish.py',
            'reels/copy.py', 'review/coverage.py', 'review/read.py', 'review/reconcile.py',
        ],
        'oracle': '0.017 毫伏乘 1000 得 17 微伏，23 微伏原值保留。每码各一行。短质控卷少一条必要记录，完整结果的两侧原址与首次回执逐行比较。',
    }


def main() -> None:
    with TemporaryDirectory(prefix='track-archive-demo-') as temporary:
        scenario = run_day(Path(temporary))
    print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
