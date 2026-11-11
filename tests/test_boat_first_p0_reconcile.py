"""Invented native P0/AES fixtures replay through real retained-result readers."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from race_ai import boat_private_original_vault as V
from race_ai import saved_view_feed as F
from race_ai.boat_pdca_github_handoff import TRANSFER_REF
from race_ai.boat_pdca_recipient import receiver_document
from race_ai.boat_saved_view_intake import append_views
from race_ai.racer_intraday_handoff import load_intraday, save_intraday
from tests.intraday_fixture import packet
from tests.test_boat_first_p0_readback import retain_bundle
from tests.test_boat_private_original_vault import KEY, NOW, LocalGit, wire
from tests.test_boat_sp_settlement import document
from tests.test_racer_intraday_handoff import FixtureGit
from tests.test_racer_result_bridge import FixtureFeed, saved_view

try:
    reconcile = importlib.import_module('scripts.boat_first_p0_reconcile')
except ModuleNotFoundError:
    reconcile = None


class FirstP0ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(reconcile, 'source-free first-P0 reconciliation is absent')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remote = self.root/'remote.git'
        for cmd in (['git', 'init', '--bare', str(self.remote)],
                    ['git', '--git-dir', str(self.remote), 'config', 'uploadpack.allowFilter', 'true']):
            subprocess.run(cmd, check=True, capture_output=True)
        writer = self.git('vault-writer', LocalGit, V.VAULT_REF)
        reader = self.git('vault-retention-reader', LocalGit, V.VAULT_REF)
        self.vault = self.git('independent-runner', LocalGit, V.VAULT_REF)
        self.repo = self.vault.repo
        parent = writer.commit({'unrelated.enc': b'existing ciphertext'}, None)
        writer.push(parent, None)
        self.bundle = retain_bundle(writer, reader, parent)
        self.feed = FixtureFeed(self.repo)
        self.intraday = FixtureGit(self.repo, ref=TRANSFER_REF)
        state_parent = self.intraday.commit({'state/unrelated.enc': b'old encrypted state'}, None)
        self.intraday.push(state_parent, None)
        self.env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_RUN_ID='99', GITHUB_SHA='d'*40, GH_TOKEN='fixture-not-a-credential',
            RUNNER_TEMP=str(self.root), RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        environment = patch.dict(os.environ, self.env, clear=True)
        environment.start(); self.addCleanup(environment.stop)
        auth = patch('scripts.boat_saved_view_feed.git_auth')
        auth.start(); self.addCleanup(auth.stop)
        network = patch('urllib.request.urlopen', side_effect=AssertionError('source request forbidden'))
        network.start(); self.addCleanup(network.stop)
        self.seed_feed(('2030-03-31',))
        self.loaded = load_intraday(self.repo, initialize=True, key=KEY,
                                    transport=self.intraday, now=NOW)
        self.receipts = []

    def git(self, name, cls, ref):
        repo = self.root/name
        subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin', str(self.remote)],
                       check=True, capture_output=True)
        return cls(repo, ref=ref)

    def seed_feed(self, days):
        view = saved_view(days)
        for row in view['records']:
            row['prediction']['prediction_sha256'] = sha256(wire(row['prediction'])).hexdigest()
        view = append_views(view)
        self.bootstrap = dict(key=b'x'*32, view_id='a'*64, cipher_sha256='c'*64,
                              forecast_sha256=F.forecast_anchor(view), pages_commit='d'*40)
        raw = F.encrypt_view(view, self.bootstrap['key'], view_id=self.bootstrap['view_id'],
                             source_sha='c'*64, generation=1, previous='d'*64)
        ident = sha256(raw).hexdigest()
        parent = self.feed.head()
        commit = self.feed.commit({'latest.json': wire(dict(header=json.loads(raw)['header'],
            cipher_sha256=ident))+b'\n', 'views/'+ident+'.json': raw}, parent)
        self.feed.push(commit, parent)
        parent, previous, generation, before = F.current_view(self.feed, self.bootstrap)
        F.publish_view(self.feed, self.bootstrap, before, parent=parent, previous=previous,
                       generation=generation, history=True)
        receiver = receiver_document(key=KEY, run_id='99', source_head='d'*40)
        encoded = F.seal_bootstrap(self.bootstrap['key'], self.bootstrap['view_id'],
            self.bootstrap['cipher_sha256'], self.bootstrap['pages_commit'],
            self.bootstrap['forecast_sha256'], receiver)
        config = dict(schema='RACE_AI_SAVED_VIEW_INPUT_V1', bootstrap=base64.b64encode(encoded).decode(),
            bootstrap_sha256=sha256(encoded).hexdigest(), catchup_artifact_id=123,
            catchup_sha256='e'*64)
        path = self.repo/'audit/state/boat-saved-view-input.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(wire(config))

    def capture(self, *, bucket='results', pending=False, at=None, wrong_roster=False):
        doc = document(day='20300401', pending=pending)
        doc['raceheader']['rlinklist'][0]['deadline'] = '10:59'
        if wrong_roster:
            doc['maindata']['teiinfolist'][0]['registno'] = '9999'
        raw, receipt = packet(doc, captured=(at or NOW-timedelta(hours=1)).isoformat())
        pointer = self.loaded['state'].remember('RESULT', raw, receipt)
        self.loaded['state'].control.setdefault(bucket, {})['20300401-01-01'] = pointer
        self.receipts.append(receipt)
        return pointer

    def save_results(self):
        self.source_saved = save_intraday(self.loaded, catalogue_sha256='a'*64, now=NOW, key=KEY)
        return self.source_saved

    def receipt_get(self, path, *, ref):
        self.assertEqual(path, 'docs/evidence/2030-04-01/p0-first-receipt.json')
        self.assertEqual(ref, self.bundle['receipt_commit'])
        return deepcopy(self.bundle['receipt_file'])

    def run_reconcile(self, **changes):
        arguments = {key: self.bundle[key] for key in (
            'vault_commit', 'receipt_commit', 'day', 'p0_artifact', 'companion_artifacts')}
        arguments.update(changes)
        return reconcile.reconcile(self.repo, transport=self.vault,
            receipt_get=self.receipt_get, feed_transport=self.feed,
            intraday_transport=self.intraday, now=NOW+timedelta(minutes=1), **arguments)

    def test_statistics_capture_scores_original_and_appends_new_v5_day(self):
        old_parent, old_cipher, _, old = F.current_view(self.feed, self.bootstrap, day='2030-03-31')
        old_wire = self.feed.read(old_parent, 'views/'+old_cipher+'.json', F.MAX_WIRE)
        self.capture(bucket='results')
        source = self.save_results()
        report = self.run_reconcile()
        self.assertEqual(report['status'], 'FIRST_P0_RECONCILED')
        self.assertEqual(report['scored_forecasts'], 2)
        self.assertEqual(report['held_forecasts'], 0)
        self.assertEqual(report['scored_races'], 1)
        self.assertEqual(report['retained_result_captures'], 1)
        self.assertEqual(report['retained_result_races'], 1)
        self.assertEqual(report['results_source_commit'], source['source_commit'])
        self.assertEqual(report['provider_requests'], 0)
        self.assertEqual(report['new_forecasts_created'], 0)
        self.assertFalse(report['source_state_saved'])
        self.assertFalse(report['source_complete'])
        self.assertEqual(report['coverage_scope'], 'EXPLICIT_ARTIFACTS_ONLY')
        self.assertTrue(report['originals_unchanged'])
        self.assertTrue(report['feed_changed'])
        parent, _, generation, updated = F.current_view(self.feed, self.bootstrap, day='2030-04-01')
        self.assertEqual(parent, report['feed_commit'])
        self.assertEqual(generation, report['feed_generation'])
        self.assertEqual(updated['records'][0]['result']['status'], 'final')
        native = [updated['records'][0]['prediction'], *updated['records'][0]['comparison_predictions']]
        self.assertEqual(len(native), 2)
        self.assertTrue(all(p['artifact_id'] == 101 and p['external_receipt_verified'] for p in native))
        self.assertTrue(all(p['original_json_sha256'] == report['json_sha256'] for p in native))
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-03-31')[3]['records'], old['records'])
        self.assertEqual(self.feed.read(old_parent, 'views/'+old_cipher+'.json', F.MAX_WIRE), old_wire)
        self.assertEqual(self.intraday.head(), source['source_commit'])
        self.assertEqual(self.vault.head(), self.bundle['vault_commit'])
        public = wire(report).decode()
        for forbidden in ('top8', 'ranked', 'racername', '4001', '20300401-01-01', '架空', 'per_forecast'):
            self.assertNotIn(forbidden, public)

    def test_missing_results_publishes_exact_original_with_hold_and_replay_is_quiet(self):
        self.save_results()
        report = self.run_reconcile()
        self.assertEqual(report['status'], 'HOLD_OFFICIAL_RESULTS_INCOMPLETE')
        self.assertEqual(report['scored_forecasts'], 0)
        self.assertEqual(report['held_forecasts'], 2)
        self.assertEqual(report['retained_result_captures'], 0)
        parent, previous, generation, view = F.current_view(self.feed, self.bootstrap, day='2030-04-01')
        self.assertIsNone(view['records'][0]['result'])
        again = self.run_reconcile()
        self.assertFalse(again['feed_changed'])
        self.assertEqual((self.feed.head(), again['feed_commit'], again['feed_generation']),
                         (parent, parent, generation))
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-04-01')[1], previous)
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3], view)

    def test_newer_pending_settlement_does_not_reuse_older_final_statistics(self):
        self.capture(bucket='results', at=NOW-timedelta(hours=2))
        self.capture(bucket='settlement_captures', pending=True, at=NOW-timedelta(hours=1))
        self.save_results()
        report = self.run_reconcile()
        self.assertEqual(report['retained_result_captures'], 2)
        self.assertEqual(report['scored_forecasts'], 0)
        self.assertEqual(report['held_forecasts'], 2)
        self.assertEqual(report['status'], 'HOLD_OFFICIAL_RESULTS_INCOMPLETE')
        view = F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3]
        self.assertEqual(view['records'][0]['result']['status'], 'pending')
        self.assertEqual(len(view['records'][0]['result_observations']), 2)

    def test_wrong_roster_is_rejected_by_existing_scorer_and_cannot_become_a_miss(self):
        self.capture(wrong_roster=True)
        self.save_results()
        report = self.run_reconcile()
        self.assertEqual(report['scored_forecasts'], 0)
        self.assertEqual(report['held_forecasts'], 2)
        self.assertEqual(report['rejected_forecasts'], 2)
        self.assertEqual(report['status'], 'HOLD_OFFICIAL_RESULTS_INCOMPLETE')
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3]
                         ['records'][0]['result']['status'], 'unsupported')

    def test_newer_saved_pending_or_rejected_observation_blocks_older_retained_final(self):
        self.capture(at=NOW-timedelta(hours=2))
        self.save_results()
        self.assertEqual(self.run_reconcile()['scored_forecasts'], 2)
        for offset, pending in enumerate((True, False)):
            with self.subTest(pending=pending):
                doc = document(day='20300401', pending=pending)
                doc['raceheader']['rlinklist'][0]['deadline'] = '10:59'
                if not pending:
                    doc['maindata']['infolist3t'][0]['winno'] = '3-2-1'
                raw, receipt = packet(doc, captured=(NOW-timedelta(minutes=30-offset)).isoformat())
                parent, previous, generation, view = F.current_view(
                    self.feed, self.bootstrap, day='2030-04-01')
                updated = F.update_view(view, [], captures=[(raw, receipt)], synced_at=NOW.isoformat())
                F.publish_view(self.feed, self.bootstrap, updated, parent=parent,
                               previous=previous, generation=generation)
                report = self.run_reconcile()
                self.assertEqual(report['status'], 'HOLD_OFFICIAL_RESULTS_INCOMPLETE')
                self.assertEqual(report['scored_forecasts'], 0)
                self.assertEqual(report['held_forecasts'], 2)
                self.assertEqual(report['newer_saved_observation_races'], 1)
                after = F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3]
                self.assertEqual(after['records'][0]['result']['status'],
                                 'pending' if pending else 'unsupported')
                self.assertEqual(after['records'][0]['result_observations'],
                                 updated['records'][0]['result_observations'])

    def test_partial_new_day_cannot_inherit_old_days_completeness_claim(self):
        parent, previous, generation, view = F.current_view(self.feed, self.bootstrap)
        view.update(source_complete=True, coverage_scope='INVENTED_PREVIOUS_DAY_COMPLETE')
        F.publish_view(self.feed, self.bootstrap, view, parent=parent,
                       previous=previous, generation=generation)
        old = F.current_view(self.feed, self.bootstrap, day='2030-03-31')[3]
        self.save_results()
        self.run_reconcile()
        new = F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3]
        self.assertFalse(new['source_complete'])
        self.assertEqual(new['coverage_scope'], 'EXPLICIT_ARTIFACTS_ONLY')
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-03-31')[3], old)

    def test_future_saved_journal_is_rejected_before_scoring_or_publication(self):
        self.capture()
        self.save_results()
        self.run_reconcile()
        doc = document(day='20300401', pending=True)
        doc['raceheader']['rlinklist'][0]['deadline'] = '10:59'
        raw, receipt = packet(doc, captured=(NOW+timedelta(minutes=30)).isoformat())
        parent, previous, generation, view = F.current_view(
            self.feed, self.bootstrap, day='2030-04-01')
        future = F.update_view(view, [], captures=[(raw, receipt)],
                               synced_at=(NOW+timedelta(minutes=31)).isoformat())
        F.publish_view(self.feed, self.bootstrap, future, parent=parent,
                       previous=previous, generation=generation)
        before = F.current_view(self.feed, self.bootstrap, day='2030-04-01')
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_RECONCILE_RESULT_JOURNAL_FUTURE'):
            self.run_reconcile()
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-04-01'), before)
        self.assertEqual(self.intraday.head(), self.source_saved['source_commit'])
        self.assertEqual(self.vault.head(), self.bundle['vault_commit'])

    def test_existing_historical_target_and_later_day_keep_all_prior_predictions(self):
        self.seed_feed(('2030-03-31', '2030-04-01', '2030-04-02'))
        old_target = F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3]
        later = F.current_view(self.feed, self.bootstrap, day='2030-04-02')[3]
        self.capture(bucket='settlement_captures')
        self.save_results()
        report = self.run_reconcile()
        self.assertEqual(report['scored_forecasts'], 2)
        updated = F.current_view(self.feed, self.bootstrap, day='2030-04-01')[3]
        self.assertEqual(updated['records'][0]['prediction'], old_target['records'][0]['prediction'])
        self.assertEqual(len(updated['records'][0]['comparison_predictions']), 2)
        self.assertEqual(F.current_view(self.feed, self.bootstrap, day='2030-04-02')[3], later)

    def test_corrupt_authenticated_capture_pointer_aborts_before_feed_publication(self):
        pointer = self.capture()
        pointer['source_sha256'] = 'f'*64
        self.save_results()
        before = self.feed.head()
        with self.assertRaisesRegex(ValueError, 'FIRST_P0_RECONCILE_RETAINED_RESULTS_REJECTED'):
            self.run_reconcile()
        self.assertEqual(self.feed.head(), before)

    def test_count_only_cli_and_private_output_path_are_validated_before_publish(self):
        self.capture()
        self.save_results()
        args = ['--repo-root', str(self.repo), '--vault-commit', self.bundle['vault_commit'],
            '--receipt-commit', self.bundle['receipt_commit'], '--day', self.bundle['day'],
            '--p0-artifact', '101', '--companion-artifact', '801', '--companion-artifact', '802']
        before = self.feed.head()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = reconcile.main(args+['--output', str(self.repo/'forbidden.json')],
                transport=self.vault, receipt_get=self.receipt_get, feed_transport=self.feed,
                intraday_transport=self.intraday, now=NOW+timedelta(minutes=1))
        self.assertEqual(status, 2)
        self.assertEqual(self.feed.head(), before)
        self.assertNotIn(str(self.repo), stdout.getvalue())
        output = self.root/'counts.json'
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = reconcile.main(args+['--output', str(output)],
                transport=self.vault, receipt_get=self.receipt_get, feed_transport=self.feed,
                intraday_transport=self.intraday, now=NOW+timedelta(minutes=1))
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.read_bytes()), json.loads(stdout.getvalue()))
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('fixture-not-a-credential', stdout.getvalue())
        self.assertNotIn('ordered_top8', stdout.getvalue())


if __name__ == '__main__':
    unittest.main()
