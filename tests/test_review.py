import shutil

from reels.append import append_record
from reels.copy import copy_prefix
from reels.records import LogicalRecord, RecordAddress, ReelHeader
from reels.scan import record_at, scan_prefix
from reels.storage import FileReelStore
from review.read import read_release
from review.reconcile import QualityTotals
from tests.support import StopAt, Workspace, WorkspaceCase


class ReviewTests(WorkspaceCase):
    def test_independent_prefixes(self):
        work = self.workspace
        receipt = work.publish(work.batch())
        left, right = work.copies()
        self.assertUnavailable(read_release(receipt.release_id, left, copy_prefix(work.reels, 'QUAL', 1)))
        other = FileReelStore(self.root / 'other-medium')
        other.initialize_reel(ReelHeader('QUAL', 'quality', 'other-physical-serial'))
        for frame in right.frames:
            other.append_frame('QUAL', frame)
        wrong = copy_prefix(other, 'QUAL')
        self.assertEqual(len(wrong.frames), len(right.frames))
        self.assertEqual(wrong.frames, right.frames)
        self.assertUnavailable(read_release(receipt.release_id, left, wrong))
        self.assertUnavailable(read_release(receipt.release_id, right, left))
        self.assertUnavailable(read_release('unknown-release', left, right))
        actual = read_release(receipt.release_id, left, right)
        self.assertEqual([(row.amplitude_uv, row.quality) for row in actual.rows], [(17, '合格'), (23, '复检')])
        self.assertEqual(actual.totals, (QualityTotals('合格', 1, 17), QualityTotals('复检', 1, 23)))
        self.assertReceiptAddresses(actual, receipt)

    def test_invalid_cut(self):
        work = self.workspace
        work.publish(work.batch())
        _, right = work.copies()
        for cut in (-1, len(right.frames) + 1, True, 1.0):
            with self.subTest(cut=cut), self.assertRaises(ValueError):
                copy_prefix(work.reels, 'QUAL', cut)
        with self.assertRaises(FileNotFoundError):
            copy_prefix(work.reels, 'ABSENT')
        with self.assertRaises(ValueError):
            copy_prefix(work.reels, '../QUAL')
        self.assertEqual(copy_prefix(work.reels, 'QUAL', 0).frames, ())
        self.assertEqual(copy_prefix(work.reels, 'QUAL'), right)

    def test_mixed_attempts_and_snapshot_isolation(self):
        work = self.workspace
        batch = work.batch()
        short_stop = StopAt('quality_written', 1)
        with self.assertRaises(InterruptedError):
            work.publish(batch, checkpoint=short_stop)
        old_left, old_right = work.copies()
        self.assertUnavailable(read_release(short_stop.release_id, old_left, old_right))
        reopened = Workspace(work.root)
        receipt = reopened.publish(batch)
        left, right = reopened.copies()
        mixed_cut = receipt.quality_addresses[-1].ordinal - 1
        mixed_right = copy_prefix(reopened.reels, 'QUAL', mixed_cut)
        self.assertEqual(mixed_right.frames[:len(old_right.frames)], old_right.frames)
        self.assertUnavailable(read_release(receipt.release_id, left, mixed_right))
        self.assertUnavailable(read_release(receipt.release_id, left, old_right))
        self.assertUnavailable(read_release(receipt.release_id, old_left, right))
        self.assertEqual(len(old_right.frames), short_stop.detail.ordinal)
        shutil.rmtree(reopened.reels.root)
        self.assertUnavailable(read_release(receipt.release_id, left, old_right))
        self.assertUnavailable(read_release(receipt.release_id, left, mixed_right))
        actual = read_release(receipt.release_id, left, right)
        self.assertEqual([(row.amplitude_uv, row.quality) for row in actual.rows], [(17, '合格'), (23, '复检')])
        self.assertEqual(actual.totals, (QualityTotals('合格', 1, 17), QualityTotals('复检', 1, 23)))
        self.assertReceiptAddresses(actual, receipt)

    def test_ready_unpublished_has_no_partial_payload(self):
        work = self.workspace
        batch = work.batch()
        stop = StopAt('quality_written', 2)
        with self.assertRaises(InterruptedError):
            work.publish(batch, checkpoint=stop)
        left, right = work.copies()
        self.assertEqual(len(right.frames), stop.detail.ordinal)
        self.assertUnavailable(read_release(stop.release_id, left, right))
        receipt = Workspace(work.root).publish(batch)
        self.assertUnavailable(read_release(receipt.release_id, left, right))
        self.assertReceiptAddresses(read_release(receipt.release_id, *work.copies()), receipt)

    def test_native_historical_pair_without_issuance(self):
        work = Workspace(self.root / 'history').initialize(legacy=True)
        left, right = work.copies()
        actual = read_release('legacy-201', left, right)
        self.assertEqual([(row.position, row.amplitude_uv, row.quality) for row in actual.rows], [
            (14, 9, '合格'), (2, None, '复检'),
        ])
        self.assertEqual(actual.totals, (QualityTotals('合格', 1, 9), QualityTotals('复检', 1, 0)))
        self.assertEqual([row.amplitude_address for row in actual.rows], [RecordAddress('AMP', 2)] * 2)
        self.assertEqual([row.quality_address for row in actual.rows], [RecordAddress('QUAL', 1)] * 2)
        self.assertUnavailable(read_release('legacy-201', left, copy_prefix(work.reels, 'QUAL', 0)))
        self.assertUnavailable(read_release('legacy-201', copy_prefix(work.reels, 'AMP', 1), right))

    def test_prior_release_after_later_append(self):
        work = Workspace(self.root / 'preceded').initialize(legacy=True)
        append_record(work.reels, 'AMP', LogicalRecord('note', {'entry': 'preflight'}))
        batch_a = work.batch('B')
        receipt_a = work.publish(batch_a)
        first_left, first_right = work.copies()
        first = read_release(receipt_a.release_id, first_left, first_right)
        work.publish(work.batch('A'), 'request-B')
        shutil.rmtree(work.recordings.directory)
        shutil.rmtree(work.prepared.directory)
        left, right = work.copies()
        shutil.rmtree(work.reels.root)
        actual = read_release(receipt_a.release_id, left, right)
        self.assertEqual(actual, first)
        self.assertEqual(read_release(receipt_a.release_id, left, first_right), first)
        self.assertEqual(read_release(receipt_a.release_id, first_left, right), first)
        self.assertReceiptAddresses(actual, receipt_a)
        self.assertEqual([(row.position, row.amplitude_uv, row.quality) for row in actual.rows], [
            (47, None, '合格'), (2, 0, '合格'), (31, 23, '复检'), (18, None, '无效'),
        ])
        self.assertEqual([row.row_ref for row in actual.rows], [(batch_a.recording_id, index) for index in range(4)])
        self.assertEqual(actual.totals, (
            QualityTotals('合格', 2, 0), QualityTotals('复检', 1, 23), QualityTotals('无效', 1, 0),
        ))
        amplitude = scan_prefix(left.header, left.frames)
        quality = scan_prefix(right.header, right.frames)
        for row in actual.rows:
            self.assertGreater(row.amplitude_address.ordinal, 3)
            self.assertGreater(row.quality_address.ordinal, 1)
            self.assertEqual(record_at(amplitude, row.amplitude_address).address, row.amplitude_address)
            self.assertEqual(record_at(quality, row.quality_address).address, row.quality_address)
