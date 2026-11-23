import json
import shutil
import unittest
from dataclasses import dataclass
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


PROJECT = Path(__file__).resolve().parents[1]
AMPLITUDE = ReelHeader('AMP', 'amplitude', 'track-amp-001')
QUALITY = ReelHeader('QUAL', 'quality', 'track-qual-001')
ALT_AMPLITUDE = ReelHeader('AMP2', 'amplitude', 'track-amp-002')
ALT_QUALITY = ReelHeader('QUAL2', 'quality', 'track-qual-002')


class StopAt:
    def __init__(self, stage, occurrence=1):
        self.stage = stage
        self.remaining = occurrence
        self.detail = None
        self.release_id = None

    def __call__(self, stage, detail, release_id):
        if stage != self.stage:
            return
        self.remaining -= 1
        if self.remaining == 0:
            self.detail = detail
            self.release_id = release_id
            raise InterruptedError(stage)


@dataclass
class Workspace:
    root: Path

    def __post_init__(self):
        self.reels = FileReelStore(self.root / 'reels')
        self.recordings = RecordingCatalog(self.root / 'recordings')
        self.prepared = PreparedCatalog(self.root / 'prepared')

    def initialize(self, *, legacy=False):
        if legacy:
            shutil.copytree(PROJECT / 'fixtures/legacy-reels', self.reels.root)
        self.reels.initialize_reel(AMPLITUDE)
        self.reels.initialize_reel(QUALITY)
        return self

    def batch(self, name='A'):
        day = json.loads((PROJECT / 'examples/day.json').read_text(encoding='utf-8'))
        sample = day[name]
        recording = accept_recording(
            self.recordings, sample['submission'], DeviceSource(**day['source']), sample['rows'],
        )
        return prepare_batch(self.recordings, self.prepared, recording.recording_id)

    def publish(self, batch, request='request-A', checkpoint=None):
        return publish(self.reels, self.prepared, request, batch.prepared_id, 'AMP', 'QUAL', checkpoint)

    def copies(self, *, left=None, right=None):
        return copy_prefix(self.reels, 'AMP', left), copy_prefix(self.reels, 'QUAL', right)


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='track-archive-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = Workspace(self.root / 'work').initialize()

    def assertUnavailable(self, result):
        self.assertFalse(result.available)
        self.assertFalse(hasattr(result, 'rows'))
        self.assertFalse(hasattr(result, 'totals'))

    def assertReceiptAddresses(self, result, receipt):
        self.assertEqual(result.release_id, receipt.release_id)
        self.assertEqual(tuple(row.amplitude_address for row in result.rows), receipt.amplitude_addresses)
        self.assertEqual(tuple(row.quality_address for row in result.rows), receipt.quality_addresses)
