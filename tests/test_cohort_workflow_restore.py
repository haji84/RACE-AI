"""Execute the actual workflow restore block against normalized local artifacts."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class CohortWorkflowRestoreTests(unittest.TestCase):
    def execute_restore(self, **changes):
        source = (ROOT/'.github/workflows/boat-blob-e2e.yml').read_text(encoding='utf-8')
        step = source.split('- name: Verify every normalized cohort backup byte and receipt digest', 1)[1]
        block = textwrap.dedent(step.split("python - <<'PY'\n", 1)[1].split('\n          PY', 1)[0])
        manifest = dict(schema_version=2, status='COMPLETED', selection='all-upcoming',
            selected_race_ids=[], attempted_race_ids=[], not_attempted_race_ids=[], pending_race_ids=[],
            saved=[], preserved=[], skipped=[], request_backups=[], posts_attempted=0, write_slots_used=0,
            max_races=24, reads_used=1, max_reads=313, max_seconds=480,
            validation_status='UNVALIDATED', purchase_decision='skip', purchase_recommendations=[],
            official_source_requests=0)
        manifest.update(changes)
        raw = json.dumps(manifest).encode('utf-8')
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', RUNNER_TEMP=folder), contextlib.redirect_stdout(io.StringIO()) as output:
            for name in ('race-ai-cohort', 'race-ai-cohort-restored'):
                path = Path(folder)/name
                path.mkdir()
                (path/'manifest.json').write_bytes(raw)
            exec(compile(block, 'cohort-workflow-restore', 'exec'), {})
            return output.getvalue()

    def test_actual_restore_accepts_extended_all_upcoming_and_original_default_budgets(self):
        for selection, seconds in (('all-upcoming', 480), ('next-per-venue', 240)):
            with self.subTest(selection=selection, seconds=seconds):
                try:
                    output = self.execute_restore(selection=selection, max_seconds=seconds)
                except SystemExit as error:
                    self.fail(f'valid scoped restore budget rejected: {error}')
                self.assertIn('COHORT_MANIFEST_RESTORE_VERIFIED', output)

    def test_actual_restore_rejects_scope_time_read_and_write_budget_excess(self):
        for changes in ({'selection':'next-per-venue','max_seconds':241},
                        {'selection':'all-upcoming','max_seconds':481},
                        {'selection':'unknown','max_seconds':240},
                        {'max_reads':314}, {'max_races':25}):
            with self.subTest(changes=changes):
                with self.assertRaises(SystemExit) as error:
                    self.execute_restore(**changes)
                self.assertEqual(str(error.exception), 'COHORT_MANIFEST_BUDGET_CONFLICT')
