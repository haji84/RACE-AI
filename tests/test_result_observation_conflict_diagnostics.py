"""Synthetic strict-conflict diagnostics; no source calls or private values."""
from copy import deepcopy
from contextlib import redirect_stdout
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from race_ai.boat_saved_model_view import SavedModelViewError, merge_saved_views
from tests.test_boat_saved_model_view import view, add_result


class ResultObservationConflictDiagnosticTests(unittest.TestCase):
    def test_actual_guard_attaches_counts_without_weakening_the_rejection(self):
        base = add_result(view()); addition = deepcopy(base)
        original = base['records'][0]['result_observations'][0]
        changed = addition['records'][0]['result_observations'][0]
        original['data'] = dict(results=[dict(lane=1, finish=1)])
        changed['data'] = dict(results=[dict(lane=1, finish=1, actual_st=0.16)])
        changed['SECRET-FIELD'] = 'SECRET-VALUE'
        before = deepcopy((base, addition))
        with self.assertRaises(SavedModelViewError) as raised:
            merge_saved_views(base, [addition])
        error = raised.exception
        self.assertEqual(error.reason_code, 'SAVED_MODEL_VIEW_CONFLICTING_RESULT_OBSERVATION')
        counts = error.conflict_counts
        self.assertEqual(counts['same_source_bytes'], True)
        self.assertEqual(counts['differing_fields'], {'OTHER': 1, 'data': 1})
        self.assertEqual(counts['differing_data_fields'], {'results': 1})
        self.assertEqual(counts['differing_finish_fields'], {'actual_st': 1})
        self.assertEqual(counts['observations_reconciled'], 0)
        self.assertNotIn('SECRET', json.dumps(counts))
        self.assertEqual((base, addition), before)

    def test_source_hash_difference_remains_a_conflict(self):
        base = add_result(view()); addition = deepcopy(base)
        addition['records'][0]['result_observations'][0]['source_sha256'] = 'b'*64
        with self.assertRaises(SavedModelViewError) as raised:
            merge_saved_views(base, [addition])
        self.assertFalse(raised.exception.conflict_counts['same_source_bytes'])
        self.assertEqual(raised.exception.conflict_counts['differing_fields'], {'source_sha256': 1})

    def test_exact_replay_still_merges_without_a_diagnostic(self):
        base = add_result(view())
        merged = merge_saved_views(base, [deepcopy(base)])
        self.assertEqual(merged['records'][0]['result_observations'], base['records'][0]['result_observations'])

    def test_cli_reports_the_actual_guard_counts_and_does_not_publish(self):
        from scripts import boat_saved_view_feed as cli
        base = add_result(view()); addition = deepcopy(base)
        addition['records'][0]['result_observations'][0]['SECRET'] = 'SECRET'
        with self.assertRaises(SavedModelViewError) as raised:
            merge_saved_views(base, [addition])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); config = root/'audit/state/boat-saved-view-input.json'
            config.parent.mkdir(parents=True)
            raw = b'synthetic-bootstrap'
            config.write_text(json.dumps(dict(schema='RACE_AI_SAVED_VIEW_INPUT_V1',
                bootstrap=base64.b64encode(raw).decode(), bootstrap_sha256=hashlib.sha256(raw).hexdigest(),
                catchup_artifact_id=1, catchup_sha256='a'*64)))
            output = io.StringIO()
            with patch.object(cli, 'ROOT', root), patch.object(cli, 'git_auth'), \
                 patch.object(cli.F, 'FeedRepository'), patch.object(cli.F, 'open_bootstrap'), \
                 patch.object(cli.F, 'current_view', side_effect=raised.exception), \
                 patch.object(cli.F, 'publish_view') as publish, redirect_stdout(output):
                self.assertEqual(cli.main([]), 2)
            publish.assert_not_called()
            report = json.loads(output.getvalue())
            self.assertEqual(report['reason'], 'SAVED_MODEL_VIEW_CONFLICTING_RESULT_OBSERVATION')
            self.assertEqual(report['conflict_counts']['differing_fields'], {'OTHER': 1})
            self.assertNotIn('SECRET', output.getvalue())


if __name__ == '__main__':
    unittest.main()
