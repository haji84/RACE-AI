"""Forecast-first publication with invented inputs and encrypted local Git only."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from race_ai import boat_all_model_cycle as engine, boat_all_model_store as store
from race_ai import saved_view_feed as F
from race_ai.actions_contract import digest
from race_ai.boat_history_store import HistoryStore, wire
from race_ai.boat_pdca_projection import project_pdca
from race_ai.boat_pdca_recipient import receiver_document
from race_ai.boat_pdca_state import PdcaState, sha
from scripts import boat_saved_site_context as site_context
from scripts import boat_saved_view_feed as cli
from tests.test_boat_all_model_cycle import HEAD, NOW, receipt, source_context
from tests.test_boat_all_model_recovery import ActualResponses, zipped
from tests.test_boat_history_store import archives, DAY
from tests.test_boat_model_runtime import local_repos
from tests.test_boat_pdca_github_handoff import invented_research_state

KEY = bytes(range(32))  # Public invented-data key, never an operator secret.
DISPLAY_KEY = b'f' * 32


class LocalFeed(F.FeedRepository):
    def _check_remote(self):
        self.fetch_url = self.push_url = self._run(['remote', 'get-url', 'origin']).decode().strip()


class LocalForecast(store.GitForecastRepository):
    def _check_remote(self):
        self.fetch_url = self.push_url = self._run(['remote', 'get-url', 'origin']).decode().strip()


class ForecastOnlyPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.repo = local_repos(self.root)
        (self.repo / 'web').symlink_to(Path(__file__).resolve().parents[1] / 'web', target_is_directory=True)
        self.private = self.root / 'private'; self.private.mkdir(mode=0o700)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            'RUNNER_TEMP': str(self.private), 'GITHUB_RUN_ID': '42',
            'RACE_AI_STATE_KEY': base64.b64encode(KEY).decode(),
            'RACE_AI_ORIGINAL_VAULT_ENABLED': 'true',
        }))
        self.stack.enter_context(patch.object(cli, 'ROOT', self.repo))
        self.stack.enter_context(patch.object(cli, 'git_auth'))
        self.stack.enter_context(patch.object(F, 'FeedRepository', LocalFeed))
        self.stack.enter_context(patch.object(store, 'GitForecastRepository', LocalForecast))

        old = self.root / 'old'; old.mkdir()
        path, _ = invented_research_state(old)
        state = PdcaState(path)
        try: self.before = project_pdca(state)
        finally: state.close()
        self.before['frozen_cash_policy'] = {'schema': 'INVENTED_FROZEN_POLICY', 'stake_yen': 800,
                                             'allocation': [100] * 8, 'actual_purchases': False}
        self.anchor = F.originals_sha(self.before)
        self.seed = F.encrypt_view(self.before, DISPLAY_KEY, view_id='b' * 64,
                                   source_sha='c' * 64, generation=1, previous='d' * 64)
        self.seed_id = sha(self.seed); self.feed = LocalFeed(self.repo)
        header = json.loads(self.seed)['header']
        self.parent = self.feed.commit({'views/' + self.seed_id + '.json': self.seed,
                                       'latest.json': wire({'header': header, 'cipher_sha256': self.seed_id}).encode()}, None)
        self.feed.push(self.parent, None)
        bootstrap = F.seal_bootstrap(DISPLAY_KEY, 'b' * 64, self.seed_id, self.parent,
                                     self.anchor, receiver_document(key=KEY, run_id='42', source_head=HEAD))
        config = self.repo / 'audit/state'; config.mkdir(parents=True)
        (config / 'boat-saved-view-input.json').write_text(wire({
            'schema': 'RACE_AI_SAVED_VIEW_INPUT_V1', 'bootstrap': base64.b64encode(bootstrap).decode(),
            'bootstrap_sha256': sha(bootstrap), 'catchup_artifact_id': 999, 'catchup_sha256': '9' * 64,
        }))

        history = self.private / 'history.sqlite'; db = HistoryStore(history)
        raw, proof = archives(); db.ingest_day(DAY, raw['B'], raw['K'], proof['B'], proof['K']); db.close()
        metadata = self.private / 'metadata.json'; metadata.write_text(wire({'schema': 'INVENTED_RUNTIME'})); metadata.chmod(0o600)
        ranker = self.private / 'ranker.json'; ranker.write_text('null'); ranker.chmod(0o600)
        files = {'history.sqlite': str(history), 'metadata.json': str(metadata), 'ranker.json': str(ranker),
                 'verified_runtime': True, 'history_identity_verified': True, 'owner_reviewed': True,
                 'source_code_commit': HEAD, 'run_id': '42'}
        self.payload = engine.forecast_round([source_context()], files, now=NOW)
        self.receipt = receipt(self.payload, artifact=101)
        cipher = store.seal_forecasts(self.payload, run_id='42', round_no=1, key=KEY)
        native_archive = zipped(cipher)
        self.native_metadata = dict(id=101, name='boat-all-model-forecasts-42-r1',
            expired=False, digest='sha256:' + sha(native_archive), size_in_bytes=len(native_archive),
            created_at=self.receipt['created_at'], expires_at='2030-04-08T18:00:20+09:00',
            workflow_run=dict(id=42, head_sha=HEAD, repository_id=1416489937, head_repository_id=1416489937))
        original_git = LocalForecast(self.repo)
        pointer = store.publish_forecasts(cipher, self.repo, expected_parent=None, transport=original_git)
        self.reference = self.private / 'boat-all-model-readback.json'
        self.reference.write_text(wire({'run_id': '42', 'pointer': pointer, 'receipt': self.receipt}))
        self.reference.chmod(0o600)
        self.native = engine.project_round(self.payload, self.receipt)
        self.clock = datetime.fromisoformat('2030-04-01T18:00:30+09:00')
        self.github = ActualResponses([self.native_metadata], {
            'actions/artifacts/101': wire(self.native_metadata).encode(),
            'actions/artifacts/101/zip': native_archive,
        })

    def execute(self, args=(), *, protection=None):
        output = io.StringIO(); errors = io.StringIO()
        def forbidden(*_, **__):
            raise AssertionError('result access is forbidden; PRIVATE_RESULT_SENTINEL')
        with patch.object(cli, 'observations', side_effect=forbidden), \
             patch.object(cli, 'gh', self.github), \
             patch.object(F, 'update_view', side_effect=forbidden), \
             patch.object(F, 'load_captures', side_effect=forbidden), \
             patch('race_ai.boat_saved_result_recovery.recover_saved_results', side_effect=forbidden), \
             patch('race_ai.boat_all_model_recovery._observed_clock', return_value=self.clock), \
             patch('scripts.boat_original_maintenance.protect_new_forecast_originals',
                   return_value=protection or {'complete': True, 'status': 'BOAT_FORECAST_ORIGINALS_PROTECTED'}), \
             redirect_stdout(output), redirect_stderr(errors):
            try: code = cli.main(['--forecasts-only', *args])
            except SystemExit as error: code = error.code
        return code, output.getvalue(), errors.getvalue()

    def published(self):
        latest = json.loads(self.feed.read(self.feed.head(), 'latest.json', 4096))
        raw = self.feed.read(self.feed.head(), 'views/' + latest['cipher_sha256'] + '.json', F.MAX_WIRE)
        return raw, F.decrypt_view(raw, DISPLAY_KEY, view_id='b' * 64)[1]

    def test_native_is_visible_before_cutoff_without_result_archive_and_history_is_exact(self):
        # Adding results from an authenticated continuity projection must neither
        # replace an old result nor smuggle a result into the new forecast row.
        incoming = deepcopy(self.before)
        incoming['records'][0]['result']['status'] = 'pending'
        incoming['records'][0]['result_observations'][0]['source_sha256'] = 'f' * 64
        incoming['records'][0]['result_revisions'] = [{'revision': 1, 'source_sha256': 'e' * 64}]
        incoming['records'].extend(deepcopy(self.native['records']))
        incoming['event_date_jst'] = None
        incoming['results_synced_at'] = '2030-04-01T21:00:00+09:00'
        fresh = incoming['records'][-1]
        fresh.update(result={'status': 'final', 'observed_at': '2030-04-01T21:00:00+09:00'},
                     result_observations=[{'race_id': fresh['race_id'], 'captured_at': '2030-04-01T21:00:00+09:00'}],
                     result_revisions=[{'revision': 2}])
        continuity = self.repo / 'cycle_recovery_output'; continuity.mkdir()
        (continuity / 'continuity.json').write_text('{}')
        with patch.object(cli, 'project_native_state', return_value=incoming):
            code, output, errors = self.execute(['--hydrate-originals', '--recover-model-run', '42'])
        self.assertEqual(code, 0, output + errors)
        raw, after = self.published()
        old = next(row for row in after['records'] if row['race_id'] == self.before['records'][0]['race_id'])
        for field in ('result', 'result_revisions', 'result_observations', 'result_observation_rejections'):
            self.assertEqual(old[field], self.before['records'][0][field])
        self.assertEqual(after['results_synced_at'], self.before['results_synced_at'])
        self.assertEqual(after['frozen_cash_policy'], self.before['frozen_cash_policy'])
        self.assertEqual(F.forecast_anchor(after), self.anchor)
        F.ensure_append_only(self.before, after)
        new = next(row for row in after['records'] if row['race_id'] == self.native['records'][0]['race_id'])
        self.assertIsNone(new['result']); self.assertEqual(new['result_observations'], [])
        self.assertEqual(new['result_revisions'], []); self.assertEqual(new['result_observation_rejections'], [])
        context = site_context.build_context({'key': DISPLAY_KEY, 'view_id': 'b' * 64}, after, 2,
                                              now=self.clock, require_future=True)
        self.assertEqual(context['future_native']['race_id'], new['race_id'])
        self.assertEqual(self.payload['generated_at'], NOW.isoformat())
        self.assertEqual(store.restore_forecasts(json.loads(self.reference.read_text())['pointer'], self.repo, key=KEY), self.payload)
        self.assertNotIn(b'INVENTED_FROZEN_POLICY', raw)
        self.assertEqual(set(self.github.calls), {'actions/artifacts/101', 'actions/artifacts/101/zip',
                                                 'actions/runs/42', 'actions/runs/42/artifacts?per_page=100'})
        for private in (base64.b64encode(KEY).decode(), DISPLAY_KEY.decode(), 'PRIVATE_RESULT_SENTINEL', new['race_id']):
            self.assertNotIn(private, output + errors)

    def test_missing_existing_feed_holds_without_initializing_a_new_generation(self):
        self.feed._run(['push', 'origin', ':' + self.feed.ref])
        self.assertIsNone(self.feed.head())
        code, output, errors = self.execute()
        self.assertEqual(code, 2, output + errors)
        self.assertIn('FEED_FORECASTS_ONLY_EXISTING_FEED_REQUIRED', output)
        self.assertIsNone(self.feed.head())

    def test_conflicting_modes_hold_before_any_publication(self):
        for args in (['--seed-only'], ['--result-artifact', '999']):
            with self.subTest(args=args):
                code, output, errors = self.execute(args)
                self.assertEqual(code, 2, output + errors)
                self.assertIn('FEED_FORECASTS_ONLY_OPTION_CONFLICT', output)
                self.assertEqual(self.feed.head(), self.parent)

    def test_incomplete_original_protection_keeps_the_previous_encrypted_feed(self):
        code, output, errors = self.execute(protection={'complete': False})
        self.assertEqual(code, 2, output + errors)
        self.assertIn('FEED_NEW_FORECAST_ORIGINALS_INCOMPLETE', output)
        self.assertEqual(self.feed.head(), self.parent)

    def test_forecast_only_never_restores_history_or_fitted_runtime(self):
        (self.repo / 'audit/state/boat-model-runtime-input.json').write_text('{}')
        with patch('scripts.boat_all_model_cycle.prepare_runtime',
                   side_effect=AssertionError('PRIVATE_RUNTIME_SENTINEL')):
            code, output, errors = self.execute()
        self.assertEqual(code, 0, output + errors)
        _, after = self.published()
        self.assertTrue(any(row['race_id'] == self.native['records'][0]['race_id'] for row in after['records']))
        self.assertNotIn('PRIVATE_RUNTIME_SENTINEL', output + errors)

    def test_new_cutoff_cannot_leave_an_existing_result_reference_invalid(self):
        from race_ai.boat_saved_model_view import merge_saved_views
        from tests.test_boat_saved_model_view import reconciled_views
        base, second = reconciled_views(); self.before = merge_saved_views(base, [second])
        self.anchor = F.originals_sha(self.before)
        seed = F.encrypt_view(self.before, DISPLAY_KEY, view_id='b' * 64, source_sha='c' * 64,
                              generation=2, previous=self.seed_id)
        ident = sha(seed)
        self.parent = self.feed.commit({'views/' + ident + '.json': seed,
            'latest.json': wire({'header': json.loads(seed)['header'], 'cipher_sha256': ident}).encode()}, self.parent)
        self.feed.push(self.parent, self.feed.head())
        bootstrap = F.seal_bootstrap(DISPLAY_KEY, 'b' * 64, ident, self.parent,
            self.anchor, receiver_document(key=KEY, run_id='42', source_head=HEAD))
        config = self.repo / 'audit/state/boat-saved-view-input.json'
        document = json.loads(config.read_text()); document.update(bootstrap=base64.b64encode(bootstrap).decode(), bootstrap_sha256=sha(bootstrap))
        config.write_text(wire(document))
        # Verify the starting reference against the actual product reader.
        parsed = subprocess.run(['node', '-e', "require('./web/product-data.js').parse(require('node:fs').readFileSync(0,'utf8'))"],
            cwd=self.repo, input=wire(self.before).encode(), capture_output=True, timeout=15)
        self.assertEqual(parsed.returncode, 0)
        self.reference.unlink()
        incoming = deepcopy(second); row = incoming['records'][0]
        row['cutoff_at'] = '2030-04-01T10:02:00+09:00'
        row['saved_cutoff_variants'] = [row['cutoff_at']]
        row['prediction'].update(cutoff_at=row['cutoff_at'], model_version='new-cutoff', prediction_sha256='1' * 64)
        continuity = self.repo / 'cycle_recovery_output'; continuity.mkdir()
        (continuity / 'continuity.json').write_text('{}')
        with patch.object(cli, 'project_native_state', return_value=incoming):
            code, output, errors = self.execute()
        self.assertEqual(code, 2, output + errors)
        self.assertIn('FEED_FORECASTS_ONLY_READER_REJECTED', output)
        self.assertEqual(self.feed.head(), self.parent)
        _, after = self.published()
        self.assertEqual(after, self.before)


if __name__ == '__main__': unittest.main()
