from issue.publish import publish
from issue.requests import RequestConflict
from reels.append import append_record
from reels.records import LogicalRecord, ReelHeader, RecordAddress
from review.read import read_release
from tests.support import ALT_AMPLITUDE, ALT_QUALITY, AMPLITUDE, QUALITY, StopAt, Workspace, WorkspaceCase


class IssuanceTests(WorkspaceCase):
    def test_complete_batch(self):
        work = self.workspace
        observed = {'amplitude_written': [], 'quality_written': []}

        def collect(stage, detail, release_id):
            if stage in observed:
                observed[stage].append(detail)

        batch = work.batch()
        receipt = work.publish(batch, checkpoint=collect)
        self.assertEqual(receipt.request_id, 'request-A')
        self.assertEqual(receipt.prepared_id, batch.prepared_id)
        self.assertEqual(receipt.amplitude_addresses, tuple(observed['amplitude_written']))
        self.assertEqual(receipt.quality_addresses, tuple(observed['quality_written']))
        result = read_release(receipt.release_id, *work.copies())
        self.assertEqual([(row.amplitude_uv, row.quality) for row in result.rows], [(17, '合格'), (23, '复检')])
        self.assertReceiptAddresses(result, receipt)
        before = work.copies()
        self.assertEqual(work.publish(batch), receipt)
        self.assertEqual(work.copies(), before)

    def test_interrupt_before_right_complete(self):
        work = self.workspace
        batch = work.batch()
        stop = StopAt('quality_written')
        with self.assertRaisesRegex(InterruptedError, 'quality_written'):
            work.publish(batch, checkpoint=stop)
        before = work.copies()
        self.assertIsNotNone(stop.release_id)
        self.assertUnavailable(read_release(stop.release_id, *before))
        reopened = Workspace(work.root)
        self.assertEqual(reopened.copies(), before)
        receipt = reopened.publish(batch)
        after = reopened.copies()
        for prior, current in zip(before, after):
            self.assertEqual(current.header, prior.header)
            self.assertEqual(current.frames[:len(prior.frames)], prior.frames)
        result = read_release(receipt.release_id, *after)
        self.assertEqual([(row.amplitude_uv, row.quality) for row in result.rows], [(17, '合格'), (23, '复检')])
        self.assertReceiptAddresses(result, receipt)

    def test_ready_unpublished_is_pending_and_keeps_prefix(self):
        work = self.workspace
        batch = work.batch()
        stop = StopAt('quality_written', occurrence=2)
        with self.assertRaises(InterruptedError):
            work.publish(batch, checkpoint=stop)
        self.assertIsNotNone(stop.release_id)
        ready = work.copies()
        self.assertUnavailable(read_release(stop.release_id, *ready))
        reopened = Workspace(work.root)
        receipt = reopened.publish(batch)
        completed = reopened.copies()
        for old, new in zip(ready, completed):
            self.assertEqual(new.frames[:len(old.frames)], old.frames)
        self.assertUnavailable(read_release(receipt.release_id, *ready))
        self.assertReceiptAddresses(read_release(receipt.release_id, *completed), receipt)

    def test_pending_request_rejects_payload_change(self):
        work = self.workspace
        batch_a, batch_b = work.batch('A'), work.batch('B')
        with self.assertRaises(InterruptedError):
            work.publish(batch_a, checkpoint=StopAt('quality_written'))
        pending = work.copies()
        reopened = Workspace(work.root)
        with self.assertRaises(RequestConflict):
            reopened.publish(batch_b)
        self.assertEqual(reopened.copies(), pending)
        receipt = reopened.publish(batch_a)
        self.assertEqual(receipt.prepared_id, batch_a.prepared_id)
        self.assertReceiptAddresses(read_release(receipt.release_id, *reopened.copies()), receipt)

    def test_lost_reply_keeps_addresses(self):
        work = self.workspace
        batch = work.batch()
        stop = StopAt('before_reply')
        with self.assertRaisesRegex(InterruptedError, 'before_reply'):
            work.publish(batch, checkpoint=stop)
        emitted = stop.detail
        first_copies = work.copies()
        first = read_release(emitted.release_id, *first_copies)
        self.assertReceiptAddresses(first, emitted)
        self.assertEqual([(row.amplitude_uv, row.quality) for row in first.rows], [(17, '合格'), (23, '复检')])
        reopened = Workspace(work.root)
        replay = reopened.publish(batch)
        self.assertEqual(replay, emitted)
        self.assertEqual(reopened.copies(), first_copies)
        reopened.publish(reopened.batch('B'), 'request-B')
        self.assertEqual(reopened.publish(batch), emitted)
        self.assertEqual(read_release(replay.release_id, *reopened.copies()), first)

    def test_request_payload_conflict(self):
        work = self.workspace
        receipt = work.publish(work.batch('A'))
        old = read_release(receipt.release_id, *work.copies())
        batch_b = work.batch('B')
        before = work.copies()
        reopened = Workspace(work.root)
        with self.assertRaises(RequestConflict):
            reopened.publish(batch_b)
        self.assertEqual(reopened.copies(), before)
        self.assertEqual(read_release(receipt.release_id, *reopened.copies()), old)

    def test_alt_reel_pair_conflicts_for_pending_and_effective_requests(self):
        work = self.workspace
        work.reels.initialize_reel(ALT_AMPLITUDE)
        work.reels.initialize_reel(ALT_QUALITY)
        batch = work.batch()
        with self.assertRaises(InterruptedError):
            work.publish(batch, checkpoint=StopAt('request_bound'))
        reopened = Workspace(work.root)
        for phase in ('pending', 'effective'):
            with self.subTest(phase=phase):
                primary = reopened.copies()
                alternate = reopened.reels.read_frames('AMP2'), reopened.reels.read_frames('QUAL2')
                with self.assertRaises(RequestConflict):
                    publish(reopened.reels, reopened.prepared, 'request-A', batch.prepared_id, 'AMP2', 'QUAL2')
                self.assertEqual(reopened.copies(), primary)
                self.assertEqual((reopened.reels.read_frames('AMP2'), reopened.reels.read_frames('QUAL2')), alternate)
            if phase == 'pending':
                receipt = reopened.publish(batch)
        self.assertReceiptAddresses(read_release(receipt.release_id, *reopened.copies()), receipt)

    def test_reinitialize_historical_media_and_reject_overwrite(self):
        work = Workspace(self.root / 'history').initialize(legacy=True)
        original = work.copies()
        mounted = Workspace(work.root)
        self.assertEqual(mounted.reels.initialize_reel(AMPLITUDE), AMPLITUDE)
        self.assertEqual(mounted.reels.initialize_reel(QUALITY), QUALITY)
        self.assertEqual(mounted.copies(), original)
        with self.assertRaises(ValueError):
            mounted.reels.initialize_reel(ReelHeader('AMP', 'amplitude', 'different-serial'))
        with self.assertRaises(ValueError):
            append_record(mounted.reels, 'AMP', LogicalRecord('note', {'x': 1}), expected_ordinal=2)
        with self.assertRaises(ValueError):
            mounted.reels.append_frame('AMP', b'{')
        with self.assertRaises(FileNotFoundError):
            append_record(mounted.reels, 'ABSENT', LogicalRecord('note', {}))
        self.assertEqual(mounted.copies(), original)
        note = append_record(mounted.reels, 'AMP', LogicalRecord('note', {'entry': 'opened'}), expected_ordinal=3)
        self.assertEqual(note, RecordAddress('AMP', 3))
        receipt = mounted.publish(mounted.batch())
        current = mounted.copies()
        self.assertEqual(current[0].frames[:2], original[0].frames)
        self.assertEqual(current[1].frames[:1], original[1].frames)
        self.assertEqual(read_release('legacy-201', *current), read_release('legacy-201', *original))
        self.assertReceiptAddresses(read_release(receipt.release_id, *current), receipt)

    def test_reopen_at_all_append_and_reply_boundaries(self):
        stops = [
            ('request_bound', 1), ('amplitude_written', 1), ('amplitude_written', 2),
            ('quality_written', 1), ('quality_written', 2), ('release_effective', 1), ('before_reply', 1),
        ]
        for stage, occurrence in stops:
            with self.subTest(stage=stage, occurrence=occurrence):
                work = Workspace(self.root / f'{stage}-{occurrence}').initialize()
                batch = work.batch()
                stop = StopAt(stage, occurrence)
                with self.assertRaises(InterruptedError):
                    work.publish(batch, checkpoint=stop)
                old = work.copies()
                first = None
                if stop.release_id is not None:
                    prior = read_release(stop.release_id, *old)
                    if stage in ('release_effective', 'before_reply'):
                        self.assertTrue(prior.available)
                        first = prior
                    else:
                        self.assertUnavailable(prior)
                reopened = Workspace(work.root)
                receipt = reopened.publish(batch)
                result = read_release(receipt.release_id, *reopened.copies())
                self.assertReceiptAddresses(result, receipt)
                if first is not None:
                    self.assertEqual(result, first)
                    self.assertEqual(reopened.copies(), old)
                for prior, current in zip(old, reopened.copies()):
                    self.assertEqual(current.frames[:len(prior.frames)], prior.frames)
