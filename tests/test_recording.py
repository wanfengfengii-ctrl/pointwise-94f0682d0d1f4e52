from prepare.batch import prepare_batch
from recording.identity import make_recording_id
from recording.intake import accept_recording
from recording.models import DeviceSource, RawRowRef
from recording.validation import validate_raw_row
from tests.support import Workspace, WorkspaceCase


class RecordingTests(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self.source = DeviceSource('device-1', 'north-7')
        self.valid = {'position': 30, 'amplitude': '0.017', 'unit': 'mV', 'status': 'OK'}

    def test_duplicate_position(self):
        catalog = self.workspace.recordings
        before = accept_recording(catalog, 'prior', self.source, [self.valid])
        duplicate = [self.valid, {**self.valid, 'amplitude': 23}]
        rejected_id = make_recording_id('duplicate', self.source, tuple(map(validate_raw_row, duplicate)))
        with self.assertRaisesRegex(ValueError, 'duplicate position 30'):
            accept_recording(catalog, 'duplicate', self.source, duplicate)
        with self.assertRaises(KeyError):
            catalog.get(rejected_id)
        with self.assertRaises(KeyError):
            prepare_batch(catalog, self.workspace.prepared, rejected_id)
        self.assertEqual(set(catalog.directory.glob('*.json')), {catalog.directory / f'{before.recording_id}.json'})
        self.assertEqual(catalog.get(before.recording_id), before)
        self.assertFalse(self.workspace.prepared.directory.exists())

    def test_invalid_fields_leave_no_recording(self):
        bad = [
            {**self.valid, 'amplitude': 'NaN'},
            {**self.valid, 'amplitude': float('inf')},
            {**self.valid, 'amplitude': 0.017},
            {**self.valid, 'position': True},
            {**self.valid, 'status': ''},
            {'position': 30, 'unit': 'mV', 'status': 'OK'},
        ]
        for row in bad:
            with self.subTest(row=row), self.assertRaises(ValueError):
                accept_recording(self.workspace.recordings, 'invalid', self.source, [self.valid, row])
        with self.assertRaises(ValueError):
            accept_recording(self.workspace.recordings, 'empty', self.source, [])
        with self.assertRaises(ValueError):
            accept_recording(self.workspace.recordings, 'no-device', DeviceSource('', 'north-7'), [self.valid])
        self.assertFalse(self.workspace.recordings.directory.exists())

    def test_changed_input_keeps_frozen_recording_and_original_order(self):
        rows = [dict(self.valid), {**self.valid, 'position': 9, 'amplitude': None}]
        catalog = self.workspace.recordings
        old = accept_recording(catalog, 'A', self.source, rows)
        again = accept_recording(catalog, 'A', self.source, rows)
        self.assertEqual(old, again)
        rows[1]['amplitude'] = 0
        new = accept_recording(catalog, 'A', self.source, rows)
        self.assertNotEqual(old.recording_id, new.recording_id)
        reordered = accept_recording(catalog, 'A', self.source, list(reversed(rows)))
        self.assertNotEqual(reordered.recording_id, new.recording_id)
        reopened = Workspace(self.workspace.root).recordings
        self.assertEqual(reopened.get(old.recording_id), old)
        self.assertEqual(reopened.get(new.recording_id), new)
        self.assertIsNone(old.rows[1].amplitude)
        self.assertEqual(new.rows[1].amplitude, 0)
        self.assertEqual(old.source, self.source)
        self.assertEqual([row.position for row in old.rows], [30, 9])
        self.assertEqual(old.row_refs, (RawRowRef(old.recording_id, 0), RawRowRef(old.recording_id, 1)))
