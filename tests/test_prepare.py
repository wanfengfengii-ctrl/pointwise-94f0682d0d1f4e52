from decimal import localcontext

from prepare.batch import make_prepared_id, prepare_batch
from recording.intake import accept_recording
from recording.models import DeviceSource, RawRowRef
from tests.support import Workspace, WorkspaceCase


class PrepareTests(WorkspaceCase):
    def record(self, name, entries):
        return accept_recording(
            self.workspace.recordings, name, DeviceSource('device-1', 'north-7'),
            [dict(zip(('position', 'amplitude', 'unit', 'status'), entry)) for entry in entries],
        )

    def test_order_and_units(self):
        recording = self.record('mixed', [
            (30, '0.017', 'mV', 'OK'), (9, None, 'mV', 'BAD'), (21, 23, 'uV', 'RECHECK'),
        ])
        batch = prepare_batch(self.workspace.recordings, self.workspace.prepared, recording.recording_id)
        self.assertEqual(
            [(row.position, row.amplitude_uv, row.quality) for row in batch.rows],
            [(30, 17, '合格'), (9, None, '无效'), (21, 23, '复检')],
        )
        self.assertEqual(tuple(row.raw_ref for row in batch.rows), tuple(
            RawRowRef(recording.recording_id, index) for index in range(3)
        ))
        self.assertEqual(self.workspace.prepared.get(batch.prepared_id), batch)

    def test_rounding_is_exact_and_independent_of_decimal_context(self):
        recording = self.record('rounding', [
            (1, '0.0175', 'mV', 'OK'), (2, '-0.0175', 'mV', 'OK'),
            (3, '0.017499999999999999', 'mV', 'OK'), (4, '-0.017499999999999999', 'mV', 'OK'),
            (5, '2.5', 'uV', 'OK'), (6, '0', 'mV', 'OK'),
            (7, '9007199254740993.5', 'uV', 'OK'),
        ])
        with localcontext() as context:
            context.prec = 2
            batch = prepare_batch(self.workspace.recordings, self.workspace.prepared, recording.recording_id)
        self.assertEqual([row.amplitude_uv for row in batch.rows], [18, -18, 17, -17, 3, 0, 9007199254740994])

    def test_repeat_prepare_after_reopen(self):
        batch = self.workspace.batch('A')
        reopened = Workspace(self.workspace.root)
        again = prepare_batch(reopened.recordings, reopened.prepared, batch.recording_id, 'v1')
        self.assertEqual(again, batch)
        self.assertEqual([row.position for row in again.rows], [30, 9])
        self.assertEqual(len(list(reopened.prepared.directory.glob('*.json'))), 1)

    def test_unsupported_profile_and_uninterpretable_rows_leave_no_batch(self):
        good = self.record('good', [(1, 17, 'uV', 'OK')])
        bad_unit = self.record('unit', [(1, 17, 'uV', 'OK'), (2, None, 'V', 'OK')])
        bad_status = self.record('status', [(1, 17, 'uV', 'OK'), (2, 23, 'uV', 'unknown')])
        for recording, profile in [(good, 'future'), (bad_unit, 'v1'), (bad_status, 'v1')]:
            with self.subTest(recording=recording.submission, profile=profile):
                with self.assertRaises(ValueError):
                    prepare_batch(self.workspace.recordings, self.workspace.prepared, recording.recording_id, profile)
                identity = make_prepared_id(recording.recording_id, profile)
                with self.assertRaises(KeyError):
                    self.workspace.prepared.get(identity)
        self.assertFalse(self.workspace.prepared.directory.exists())
