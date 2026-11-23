import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from demo import run_day


class EndToEndTests(unittest.TestCase):
    def test_shift_handoff_from_original_input_to_offline_accounting(self):
        with TemporaryDirectory(prefix='track-archive-e2e-') as temporary:
            scenario = run_day(Path(temporary))
        self.assertEqual(scenario['case_id'], 'V7')
        self.assertEqual(scenario['input']['recording']['rows'][0]['amplitude'], '0.017')
        self.assertEqual(scenario['actual']['rows'], [[30, 17, '合格'], [9, 23, '复检']])
        self.assertFalse(scenario['actual']['short_available'])
        self.assertTrue(scenario['actual']['receipt_matches_original_addresses'])
        self.assertEqual(scenario['downstream_actual'], {'合格': [1, 17], '复检': [1, 23]})
