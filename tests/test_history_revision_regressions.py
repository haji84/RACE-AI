"""Importer-based regressions using synthetic K text, never official originals."""
from pathlib import Path
import tempfile
import unittest

from race_ai.core import connect, histories, import_official
from race_ai.prediction import build_history_baseline
from tests.test_core import k_file


class HistoryRevisionRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = connect(':memory:')
        self.addCleanup(self.db.close)

    def import_text(self, name, raw, stamp):
        path = Path(self.temp.name) / name
        path.write_bytes(raw)
        return import_official(self.db, path, 'K', '2020-07-14', stamp, stamp)

    def test_imported_capture_after_subsecond_cutoff_is_excluded(self):
        self.import_text('synthetic-K200714.TXT', k_file(racer='4001'),
                         '2026-10-15T02:10:00.900+00:00')
        cutoff = '2026-10-15T02:10:00.100+00:00'
        entries = [dict(lane=lane, racer_id=str(4000 + lane), predicted_course=lane)
                   for lane in range(1, 7)]
        forecast = build_history_baseline(self.db, race_id='20261015-18-01', entries=entries,
            race_start_at='2026-10-15T03:00:00+00:00', as_of=cutoff,
            generated_at='2026-10-15T02:11:00+00:00')
        with self.subTest(consumer='research prediction'):
            self.assertEqual(forecast['explanations'][0]['sample_n'], 0)
        with self.subTest(consumer='historical statistics'):
            self.assertEqual(histories(self.db, '4001', 1, 1, cutoff)['overall_10']['n'], 0)

    def test_latest_absence_correction_does_not_revive_previous_start(self):
        raw = k_file(racer='4001')
        self.import_text('synthetic-K200714-original.TXT', raw, '2026-10-15T02:00:00+00:00')
        lines = raw.decode('cp932').splitlines()
        corrected = '\n'.join(
            ' 欠 1 4001 仮名' if line.strip().split()[1:3] == ['1', '4001'] else line
            for line in lines).encode('cp932')
        self.import_text('synthetic-K200714-correction.TXT', corrected,
                         '2026-10-15T02:05:00+00:00')
        # The original still exists for an earlier as-of, while its later
        # official revision must remove the start from participation counts.
        self.assertEqual(histories(self.db, '4001', 1, 1,
            '2026-10-15T02:03:00+00:00')['overall_10']['n'], 1)
        self.assertEqual(histories(self.db, '4001', 1, 1,
            '2026-10-15T02:10:00+00:00')['overall_10']['n'], 0)


if __name__ == '__main__':
    unittest.main()
