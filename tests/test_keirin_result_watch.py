"""Offline runner integration: genuine parsers, synthetic bytes, no provider I/O."""
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import copy
import json
import re
import unittest

from scripts import keirin_result_watch as watch
from race_ai import keirin_official_public_source as official
from race_ai import keirin_nationwide_auto_storage as storage
from tests.test_keirin_official_public_source import fixtures, transport, DAY, RACE, NOW
from tests.test_keirin_result_observer import Clock


class ResultWatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.public = key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.private = key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        cls.pin = sha256(key.public_key().public_bytes(serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        self.private_root = self.root / 'private'; self.private_root.mkdir(mode=0o700)
        self.safe = self.root / 'safe'; self.safe.mkdir()
        self.pem = self.repo / 'owner.pem'; self.pem.write_bytes(self.public)
        self.clock = Clock()
        self.events = []
        self.calls = []
        self.published = []
        self.denied = False
        self.stop_code = 'PROVIDER_DENIED_OR_RATE_LIMITED_STOP'
        self.known = [DAY]
        self.report = {}
        source = transport(fixtures())
        self.schedule = official.fetch_day_schedule(DAY, fetcher=source, clock=lambda: NOW)
        self.record = official.fetch_race_result(RACE, schedule=self.schedule,
            fetcher=source, clock=lambda: NOW)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(storage, 'PINNED_OWNER_SPKI_SHA256', self.pin))
        self.stack.enter_context(patch.dict('os.environ', {
            'GITHUB_REPOSITORY': 'haji84/RACE-AI', 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_WORKSPACE': str(self.repo),
            'GITHUB_TOKEN': '', 'RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED': 'true',
            'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'true',
        }, clear=True))
        self.stop = self.stack.enter_context(patch(
            'race_ai.keirin_github_provider_stop.read_for_observed_day',
            side_effect=lambda **_: {'code': self.stop_code} if self.denied else None))
        self.discover = self.stack.enter_context(patch(
            'scripts.keirin_official_backlog_days.discover_days', side_effect=lambda _: self.known))
        self.settle = self.stack.enter_context(patch(
            'scripts.keirin_official_day_pipeline.run_settlement', side_effect=self.settlement))
        self.load = self.stack.enter_context(patch(
            'scripts.keirin_official_day_pipeline.load_day_evidence', side_effect=self.evidence))
        self.originals = self.stack.enter_context(patch(
            'scripts.keirin_official_day_pipeline.read_originals', return_value={RACE: {}}))
        self.publisher = self.stack.enter_context(patch(
            'race_ai.keirin_result_updates.publish_updates', side_effect=self.publication))
        self.http = self.stack.enter_context(patch(
            'race_ai.keirin_official_public_source._http_get',
            side_effect=AssertionError('UNEXPECTED_REAL_PROVIDER_REQUEST')))

    def evidence(self, repo, day, key):
        return {'schedule': self.schedule if day == DAY else None,
                'official_records': {RACE: copy.deepcopy(self.record)} if day == DAY else {},
                'safe_report': dict(self.report)}

    def settlement(self, **kwargs):
        self.calls.append(kwargs)
        self.events.append(('settle', kwargs['day']))
        Path(kwargs['private_root'], 'PRIVATE_SOURCE.html').write_text('PRIVATE_RAW_SOURCE')
        return dict(self.report)

    def publication(self, repo, doc, source_commit, *, clock, owner_private_pem):
        self.assertEqual(owner_private_pem, self.private)
        self.published.append(copy.deepcopy(doc))
        self.events.append(('publish', doc['races'][0]['race_id']))
        return {'state': 'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED',
                'published_races': len(doc['races'])}

    def run_case(self, mode='observe', **options):
        return watch.run_watch(repo=self.repo, private_root=self.private_root,
            mode=mode, owner_public_path=self.pem, owner_private_pem=self.private,
            clock=lambda: NOW, monotonic=self.clock.monotonic, sleep=self.clock.sleep,
            source_commit='c' * 40, **options)

    def test_observe_uses_existing_eight_race_budget_and_publishes_each_tick(self):
        out = self.run_case(max_ticks=1)
        self.assertEqual([e[0] for e in self.events], ['settle', 'publish'])
        self.assertEqual(self.calls[0]['max_races'], 8)
        self.assertTrue(self.calls[0]['collect_official'])
        self.assertEqual(self.published[0]['races'][0]['authority'], 'official')
        self.assertEqual(self.published[0]['races'][0]['winning_triples'], ['1-2-3'])
        self.assertEqual(self.published[0]['races'][0]['arms']['A']['state'], 'unverifiable')
        self.assertEqual(out['published_races'], 1)
        self.assertFalse(Path(self.calls[0]['private_root']).exists())
        self.assertNotIn('1-2-3', json.dumps(out))
        self.assertNotIn('PRIVATE_RAW_SOURCE', json.dumps(out))

    def test_stop_at_start_is_zero_provider_ticks(self):
        self.denied = True
        out = self.run_case(max_ticks=1)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.published, [])
        self.http.assert_not_called()
        self.assertEqual(out['state'], 'HOLD_RESULT_OBSERVER_PROVIDER_STOP')
        self.assertTrue(out['no_provider_tick'])
        self.assertEqual(out['provider_requests'], 0)

    def test_approved_sp_watch_uses_its_guarded_tick_without_enabling_legacy_json(self):
        from scripts import keirin_official_nationwide_continuation as continuation
        with patch.dict('os.environ',{
            'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY_ID':'1416489937',
            'GITHUB_WORKFLOW_REF':continuation.WATCH_WORKFLOW,'GITHUB_JOB':'observe-results',
            'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED':'false'}), \
             patch.object(continuation,'settle_tick',return_value=dict(
                state='OFFICIAL_SP_RESULT_POLL_COMPLETE',source_requests=3,provider_denied=False,
                source_unavailable=False,publication_acks=1,published_races=1,published_originals=1,
                original_publication_acks=1,published_day_status=1,safe_diagnostics=[],updates=None)) as tick:
            out=self.run_case(max_ticks=2)
        self.assertEqual(tick.call_count,2)
        self.assertIs(tick.call_args_list[0].kwargs['context'],tick.call_args_list[1].kwargs['context'])
        self.assertEqual(out['provider_requests'],6)
        self.assertEqual(out['published_races'],2)
        self.assertEqual(out['published_originals'],2)
        self.assertEqual(out['original_publication_acks'],2)
        self.assertEqual(out['published_day_status'],2)
        self.settle.assert_not_called();self.http.assert_not_called()
        self.assertNotIn('updates',out)

    def test_sp_gate_failure_stops_without_legacy_fallback_or_source_claim(self):
        from scripts import keirin_official_nationwide_continuation as continuation
        with patch.dict('os.environ',{
            'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY_ID':'1416489937',
            'GITHUB_WORKFLOW_REF':continuation.WATCH_WORKFLOW,'GITHUB_JOB':'observe-results'}), \
             patch.object(continuation,'settle_tick',return_value=dict(
                state='HOLD_OFFICIAL_SP_RESULT_GATE_OR_SOURCE_FAILED',source_requests=0,provider_denied=False,
                source_unavailable=True,publication_acks=0,published_races=0,safe_diagnostics=[],updates=None)) as tick:
            out=self.run_case(max_ticks=3)
        self.assertEqual(tick.call_count,1);self.assertTrue(out['no_provider_tick'])
        self.assertEqual(out['provider_requests'],0)
        self.assertEqual(out['state'],'HOLD_OFFICIAL_SP_RESULT_GATE_OR_SOURCE_FAILED')
        self.settle.assert_not_called();self.http.assert_not_called()

    def test_manual_saved_slots_use_the_official_guard_and_hide_slot_identity(self):
        from scripts import keirin_official_nationwide_continuation as continuation
        slot = 'd' * 64
        with self.assertRaisesRegex(watch.ResultWatchError, 'SLOT_OBSERVATION_SCOPE'):
            self.run_case(max_ticks=1, observation_day=DAY, observation_slots=slot)
        with patch.dict('os.environ', {
            'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY_ID': '1416489937',
            'GITHUB_WORKFLOW_REF': continuation.WATCH_WORKFLOW, 'GITHUB_JOB': 'observe-results'}), \
             patch.object(continuation, 'settle_tick', return_value=dict(
                 state='OFFICIAL_SP_RESULT_POLL_COMPLETE', source_requests=1, provider_denied=False,
                 source_unavailable=False, publication_acks=0, published_races=0, safe_diagnostics=[],
                 safe_holds=[dict(code='HOLD', stage='RESULT', race_id=RACE)], updates=None)) as tick:
            out = self.run_case(max_ticks=1, observation_day=DAY, observation_slots=slot)
            with patch.dict('os.environ', {'GITHUB_EVENT_NAME': 'schedule'}), self.assertRaisesRegex(
                    watch.ResultWatchError, 'SLOT_OBSERVATION_SCOPE'):
                self.run_case(max_ticks=1, observation_day=DAY, observation_slots=slot)
            self.assertEqual(tick.call_count, 1)
        self.assertEqual(tick.call_args.kwargs['days'], (DAY,))
        self.assertEqual(tick.call_args.kwargs['slot_hashes'], frozenset({slot}))
        self.assertEqual(out['requested_slot_count'], 1)
        self.assertNotIn(RACE, json.dumps(out))
        self.assertNotIn(slot, json.dumps(out))
        self.settle.assert_not_called();self.http.assert_not_called()

    def test_sp_saved_only_restores_original_and_result_packets_without_source_lease(self):
        from scripts import keirin_official_nationwide_continuation as continuation
        from race_ai import keirin_official_nationwide_records as records
        with patch.dict('os.environ',{
            'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY_ID':'1416489937',
            'GITHUB_WORKFLOW_REF':continuation.WATCH_WORKFLOW,'GITHUB_JOB':'observe-results',
            'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED':'false'}), \
                patch.object(records,'discover_days',return_value=[DAY]),\
                patch.object(continuation,'replay_results',return_value=dict(published_races=1,
                    publication_acks=1,results_held=0,published_originals=1,original_publication_acks=1)) as replay,\
                patch.object(continuation,'_begin_lease',side_effect=AssertionError('NO_SOURCE_LEASE')):
            out=self.run_case(mode='saved-only')
        replay.assert_called_once()
        self.assertEqual(out['published_originals'],1)
        self.assertEqual(out['original_publication_acks'],1)
        self.assertEqual(out['published_races'],2)
        self.assertEqual(out['provider_requests'],0)
        self.http.assert_not_called()

    def test_prior_transient_stop_is_not_reported_as_provider_denial(self):
        self.denied = True
        self.stop_code = 'PUBLIC_PROVIDER_HTTP_ERROR_STOP'
        out = self.run_case(max_ticks=1)
        self.assertEqual(out['state'], 'HOLD_RESULT_WATCH_SOURCE_UNAVAILABLE')
        self.assertFalse(out['provider_denied'])
        self.assertTrue(out['no_provider_tick'])
        self.assertEqual(out['provider_requests'], 0)
        self.settle.assert_not_called()

    def test_503_preserves_result_then_stops_without_claiming_access_denial(self):
        self.http.side_effect = official.OfficialSourceError('OFFICIAL_HTTP_503')

        def mark(**kwargs):
            self.denied = True
            self.stop_code = kwargs['code']

        def collect(**kwargs):
            self.settlement(**kwargs)
            try:
                kwargs['shared_official_fetch']('https://keirin.jp/pc/json?type=JSJ057&kday=20261002')
            except official.OfficialSourceError:
                return {'provider_state': 'HOLD_OFFICIAL_PROVIDER_STOPPED_THIS_POLL'}
            self.fail('The synthetic503 must stop its tick')

        self.settle.side_effect = collect
        with patch('race_ai.keirin_github_provider_stop.record_denial', side_effect=mark):
            out = self.run_case(max_ticks=4)
        self.assertEqual([e[0] for e in self.events], ['settle', 'publish'])
        self.assertEqual(out['state'], 'HOLD_RESULT_WATCH_SOURCE_UNAVAILABLE')
        self.assertFalse(out['provider_denied'])
        self.assertEqual(out['published_races'], 1)
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(self.http.call_count, 1)

    def test_parser_hold_stops_without_retrying_even_without_transport_latch(self):
        self.report = {'provider_state': 'HOLD_OFFICIAL_PROVIDER_STOPPED_THIS_POLL'}
        out = self.run_case(max_ticks=4)
        self.assertEqual(out['state'], 'HOLD_RESULT_WATCH_SOURCE_UNAVAILABLE')
        self.assertFalse(out['provider_denied'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(out['published_races'], 1)
        self.assertEqual(self.clock.sleeps, [])

    def test_disabled_opt_in_does_not_create_source_fetcher(self):
        with patch.dict('os.environ', {'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false'}), \
                patch('scripts.keirin_official_day_pipeline.official_fetcher') as factory:
            out = self.run_case(max_ticks=1)
        self.assertEqual(out['state'], 'HOLD_RESULT_WATCH_SOURCE_DISABLED')
        factory.assert_not_called()
        self.settle.assert_not_called()
        self.http.assert_not_called()

    def test_saved_only_with_store_authorization_ignores_source_gate_and_stop(self):
        self.denied = True
        with patch.dict('os.environ', {
                'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false',
                'RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED': 'true'}), \
                patch('scripts.keirin_official_day_pipeline.official_fetcher') as factory:
            out = self.run_case(mode='saved-only')
        self.assertEqual(out['state'], 'RESULT_WATCH_SAVED_COMPLETE')
        self.assertEqual(out['provider_requests'], 0)
        self.assertFalse(self.calls[0]['collect_official'])
        self.assertIsNone(self.calls[0]['shared_official_fetch'])
        factory.assert_not_called()
        self.http.assert_not_called()

    def workflow_store_flag(self, *, event='workflow_dispatch', mode='saved-only',
                            ref='refs/heads/main', repo='haji84/RACE-AI', store='',
                            result='success', cancelled=False, s3=''):
        path = Path(__file__).resolve().parents[1] / '.github/workflows/keirin-result-live.yml'
        job = path.read_text().split('  observe-results:\n', 1)[1]
        value = re.search(r'^      RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED: (.*)',job,re.M)[1]
        expression=re.search(r'^    if: >-\n((?:      .*\n)+)',job,re.M)[1]
        expression = ' '.join(expression.split()).replace('&&', ' and ').replace('||', ' or ').replace('!cancelled()', 'not cancelled()')
        context = dict(github=SimpleNamespace(event_name=event, ref=ref, repository=repo,
            repository_id='1416489937'), inputs=SimpleNamespace(mode=mode),
            vars=SimpleNamespace(RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED=store,RACE_AI_AB_SOURCE_S3_PREFIX=s3),
            needs=SimpleNamespace(tests=SimpleNamespace(result=result)),
            always=lambda:True,cancelled=lambda:cancelled)
        return value.strip("'\"") if eval(expression, {'__builtins__': {}}, context) else ''

    def test_manual_saved_only_workflow_authorization_reaches_real_archive_preflight(self):
        from race_ai import keirin_nationwide_cipher_history as archive
        (self.repo / '.git').mkdir()

        def discover(repo):
            archive._remote(repo, synthetic_local=False)
            return self.known

        self.discover.side_effect = discover
        self.denied = True
        with patch.dict('os.environ', {
                'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY_ID': '1416489937',
                'RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED': self.workflow_store_flag(),
                'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': ''}), \
                patch.object(archive, '_cmd', return_value=(0, 'https://github.com/haji84/RACE-AI')), \
                patch.object(watch, 'TickOfficialFetcher', side_effect=AssertionError('NO_PROVIDER')):
            try:
                result = self.run_case(mode='saved-only')
            except ValueError as error:
                self.fail('The explicit saved-only job failed archive authorization: ' + str(error))
        self.assertEqual(result['state'], 'RESULT_WATCH_SAVED_COMPLETE')
        self.assertEqual(result['published_races'], 1)
        self.assertEqual(result['provider_requests'], 0)
        self.assertFalse(self.calls[0]['collect_official'])
        self.http.assert_not_called()

    def test_saved_only_authorization_does_not_enable_other_workflow_contexts(self):
        for changes in ({'mode':'test'}, {'result':'failure'}, {'cancelled':True}, {'s3':'not-empty'},
                        {'event': 'pull_request'}, {'ref': 'refs/heads/feature'}, {'repo': 'fork/RACE-AI'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.workflow_store_flag(**changes), '')
        self.assertEqual(self.workflow_store_flag(event='schedule', store='true'), 'true')
        self.assertEqual(self.workflow_store_flag(event='schedule'), 'true')
        self.assertEqual(self.workflow_store_flag(mode='observe'), 'true')

    def test_main_identifies_missing_saved_store_authorization_without_archive_io(self):
        out = self.safe / 'summary.json'
        with patch.dict('os.environ', {
                'RACE_AI_KEIRIN_PRIVATE_RSA_PEM': self.private.decode(),
                'RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED': ''}), \
                patch.object(watch, 'current_commit', return_value='c' * 40), \
                patch.object(watch, 'utc_now', return_value=NOW), redirect_stdout(StringIO()):
            status = watch.main(['--mode', 'saved-only', '--repo', str(self.repo),
                '--private-root', str(self.private_root), '--owner-public-pem', str(self.pem),
                '--report', str(out)])
        self.assertEqual(status, 2)
        summary = json.loads(out.read_bytes())
        self.assertEqual(summary['failure_stage'], 'ARCHIVE_AUTHORIZATION')
        self.assertEqual(summary['failure_reason'], 'RESULT_WATCH_SAVED_GIT_STORE_REQUIRED')
        self.assertEqual(summary['provider_requests'], 0)
        self.discover.assert_not_called()
        self.http.assert_not_called()

    def test_main_key_failure_names_stage_without_exposing_exception(self):
        out = self.safe / 'summary.json'
        with patch.object(watch.pipeline, 'check_owner_private_key',
                          side_effect=ValueError('SECRET_KEY_CONTEXT')), \
                redirect_stdout(StringIO()) as stdout:
            status = watch.main(['--mode', 'saved-only', '--repo', str(self.repo),
                '--private-root', str(self.private_root), '--owner-public-pem', str(self.pem),
                '--report', str(out)])
        self.assertEqual(status, 2)
        summary = json.loads(out.read_bytes())
        self.assertEqual(summary.get('failure_stage'), 'OWNER_KEY')
        self.assertEqual(summary.get('failure_reason'), 'RESULT_WATCH_PREFLIGHT_CHECK_FAILED')
        self.assertNotIn('SECRET_KEY_CONTEXT', out.read_text() + stdout.getvalue())
        self.discover.assert_not_called()
        self.http.assert_not_called()

    def test_saved_day_discovery_failure_has_a_safe_stage(self):
        self.discover.side_effect = ValueError('SECRET_GIT_CONTEXT')
        try:
            result = self.run_case(mode='saved-only')
        except ValueError:
            self.fail('Saved-day discovery failed without a safe stage report')
        self.assertEqual(result['state'], 'HOLD_RESULT_WATCH_SAVED_DAY_DISCOVERY_FAILED')
        self.assertEqual(result['failure_stage'], 'SAVED_DAY_DISCOVERY')
        self.assertEqual(result['provider_requests'], 0)
        self.assertNotIn('SECRET_GIT_CONTEXT', json.dumps(result))
        self.settle.assert_not_called()

    def test_canary_only_saved_history_republishes_without_generic_schedule_or_provider(self):
        from race_ai import keirin_result_updates as updates
        self.known = ['2026-11-20']
        document = updates.from_official_records({RACE: self.record}, {})

        def frozen(repo, key, commit):
            self.assertEqual((repo, key, commit), (self.repo, self.private, 'c' * 40))
            self.events.append(('frozen', '202611208105'))
            return dict(state='KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED',
                        published_originals=1, provider_requests=0)

        with (patch('scripts.keirin_official_backlog_days.select_days', return_value=['2026-11-20']),
              patch('race_ai.keirin_result_updates.saved_canary_updates', return_value=document) as replay,
              patch('race_ai.keirin_frozen_forecast_view.saved_frozen_forecast', side_effect=frozen),
              patch.object(watch, 'TickOfficialFetcher', side_effect=AssertionError('NO_PROVIDER_FETCHER'))):
            out = self.run_case(mode='saved-only')
        replay.assert_called_once_with(self.repo, self.private)
        self.settle.assert_not_called()
        self.http.assert_not_called()
        self.assertEqual(out['days_held'], 0)
        self.assertEqual(out['published_races'], 1)
        self.assertEqual([event[0] for event in self.events], ['frozen', 'publish'])
        self.assertEqual(out.get('published_originals'), 1)
        self.assertEqual(out.get('original_publication_acks'), 1)
        self.assertEqual(out['publication_acks'], 1)
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(len(self.published), 1)

    def test_frozen_display_requires_an_admitted_saved_canary_result(self):
        self.known = ['2026-11-20']
        with (patch('scripts.keirin_official_backlog_days.select_days', return_value=['2026-11-20']),
              patch('race_ai.keirin_result_updates.saved_canary_updates', return_value=None),
              patch('race_ai.keirin_frozen_forecast_view.saved_frozen_forecast',
                    side_effect=AssertionError('NO_ADMITTED_SAVED_CANARY')) as frozen):
            out = self.run_case(mode='saved-only')
        self.assertEqual(out['days_held'], 1)
        self.assertEqual(out.get('published_originals'), 0)
        self.assertEqual(self.published, [])
        frozen.assert_not_called()
        self.http.assert_not_called()

    def test_backlog_rotation_is_sparse_when_current_due_originals_are_finished(self):
        self.known = ['2026-09-29', '2026-10-01', DAY]
        out = self.run_case(max_ticks=21, duration_seconds=2000)
        self.assertEqual([c['day'] for c in self.calls],
                         [DAY] * 9 + ['2026-10-01'] + [DAY] * 9 + ['2026-09-29', DAY])
        self.assertIs(self.calls[0]['github_client'], self.calls[-1]['github_client'])
        self.assertIs(self.calls[0]['shared_official_fetch'], self.calls[-1]['shared_official_fetch'])
        self.assertEqual(out['ticks'], 21)
        self.assertEqual(len(self.published), 1)
        self.assertEqual(out['target_interval_seconds'], 60)
        self.assertEqual(out['result_race_budget'], 8)
        self.assertEqual(out['backlog_check_every_ticks'], 10)

    def test_due_current_day_originals_never_wait_behind_old_results(self):
        self.known = ['2026-09-29', '2026-10-01', DAY]
        # Race2 is in the parsed official schedule, cutoff has passed, and an
        # original exists, but there is no final official result for it yet.
        self.originals.return_value = {'202610022602': {}}
        out = self.run_case(max_ticks=12, duration_seconds=1000)
        self.assertEqual([c['day'] for c in self.calls], [DAY] * 12)
        self.assertEqual(out['due_current_originals'], 1)
        self.assertTrue(out['current_day_priority'])

    def test_verified_result_is_published_before_newly_persisted_denial_stops(self):
        def collect(**kwargs):
            self.denied = True
            return self.settlement(**kwargs)
        self.settle.side_effect = collect
        out = self.run_case(max_ticks=4)
        self.assertEqual([e[0] for e in self.events], ['settle', 'publish'])
        self.assertEqual(out['state'], 'HOLD_RESULT_OBSERVER_PROVIDER_STOP')
        self.assertEqual(out['published_races'], 1)
        self.assertEqual(self.clock.sleeps, [])

    def test_saved_only_reuse_ack_does_not_count_another_git_write(self):
        self.publisher.side_effect = lambda *a, **kw: {
            'state': 'EXISTING_RESULT_DISPLAY_REUSED', 'published_races': 0}
        out = self.run_case(mode='saved-only')
        self.assertEqual(out['publication_acks'], 1)
        self.assertEqual(out['published_races'], 0)
        self.assertEqual(out['published_snapshots'], 0)

    def test_saved_day_failure_retains_prior_publication_counters(self):
        self.known = ['2026-10-01', DAY]

        def load(repo, day, key):
            if day == '2026-10-01':
                raise ValueError('SECRET_CORRUPT_HISTORY_CONTEXT')
            return self.evidence(repo, day, key)

        self.load.side_effect = load
        try:
            out = self.run_case(mode='saved-only')
        except ValueError:
            self.fail('A later saved-day failure discarded the already-published counters')
        self.assertEqual(out['state'], 'HOLD_RESULT_WATCH_SAVED_DAY_FAILED')
        self.assertEqual(out['published_races'], 1)
        self.assertEqual(out['publication_acks'], 1)
        self.assertEqual(out['days_held'], 1)
        self.assertNotIn('SECRET', json.dumps(out))

    def test_reused_publication_ack_cannot_claim_new_published_races(self):
        self.publisher.side_effect = lambda *a, **kw: {
            'state': 'EXISTING_RESULT_DISPLAY_REUSED', 'published_races': 1}
        out = self.run_case(max_ticks=1)
        self.assertEqual(out['state'], 'HOLD_RESULT_OBSERVER_PUBLICATION_FAILED')
        self.assertEqual(out['published_races'], 0)

    def test_source_cache_refreshes_each_tick_but_refusal_latch_does_not(self):
        from scripts import keirin_official_day_pipeline as pipeline
        values = iter([b'first-published-state', b'corrected-published-state'])
        self.http.side_effect = lambda _: next(values)
        seen = []
        fetch = watch.TickOfficialFetcher(self.repo, lambda: NOW)
        fetch.begin_tick()
        seen += [fetch('https://keirin.jp/pc/json?type=JSJ057&kday=20261002') for _ in range(2)]
        fetch.begin_tick()
        seen.append(fetch('https://keirin.jp/pc/json?type=JSJ057&kday=20261002'))
        self.assertEqual(seen, [b'first-published-state', b'first-published-state', b'corrected-published-state'])
        self.assertEqual(self.http.call_count, 2)
        self.http.side_effect = official.OfficialProviderStop(403)
        with patch('race_ai.keirin_github_provider_stop.record_denial') as save:
            fetch.begin_tick()
            with self.assertRaises(official.OfficialProviderStop):
                fetch('https://keirin.jp/pc/json?type=JSJ057&kday=20261002')
            with self.assertRaises(official.OfficialProviderStop):
                fetch.begin_tick()
            with self.assertRaises(official.OfficialProviderStop):
                fetch('https://keirin.jp/pc/json?type=JSJ057&kday=20261001')
        self.assertEqual(save.call_count, 1)
        self.assertEqual(self.http.call_count, 3)

    def test_unbound_or_tampered_official_data_never_publishes(self):
        self.record['result']['payouts_100yen'][0]['yen'] += 100
        out = self.run_case(max_ticks=1)
        self.assertEqual(out['state'], 'HOLD_RESULT_OBSERVER_TICK_FAILED')
        self.assertEqual(self.published, [])
        self.http.assert_not_called()

    def test_invalid_key_is_rejected_before_git_or_source_reads(self):
        with patch.object(storage, 'PINNED_OWNER_SPKI_SHA256', '0' * 64), \
                self.assertRaises(ValueError):
            self.run_case(max_ticks=1)
        self.stop.assert_not_called()
        self.discover.assert_not_called()
        self.http.assert_not_called()

    def test_untrusted_event_is_rejected_before_key_and_io(self):
        with patch.dict('os.environ', {'GITHUB_EVENT_NAME': 'pull_request'}), \
                patch('scripts.keirin_official_day_pipeline.check_owner_private_key') as key, \
                self.assertRaisesRegex(ValueError, 'TRUSTED_MAIN_EVENT'):
            self.run_case(max_ticks=1)
        key.assert_not_called()
        self.stop.assert_not_called()

    def test_naive_clock_cannot_pick_a_race_day(self):
        with self.assertRaises(ValueError):
            watch.run_watch(repo=self.repo, private_root=self.private_root,
                mode='saved-only', owner_public_path=self.pem, owner_private_pem=self.private,
                clock=lambda: datetime(2026, 10, 2), source_commit='c' * 40)
        self.discover.assert_not_called()

    def test_private_plaintext_cannot_be_staged_inside_repository(self):
        unsafe = self.repo / 'private'; unsafe.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            watch.run_watch(repo=self.repo, private_root=unsafe,
                mode='saved-only', owner_public_path=self.pem, owner_private_pem=self.private,
                clock=lambda: NOW, source_commit='c' * 40)
        self.discover.assert_not_called()

    def test_main_persists_safe_report_outside_ephemeral_private_folder(self):
        out = self.safe / 'summary.json'
        with patch.dict('os.environ', {'RACE_AI_KEIRIN_PRIVATE_RSA_PEM': self.private.decode()}), \
                patch.object(watch, 'current_commit', return_value='c' * 40), \
                patch.object(watch, 'utc_now', return_value=NOW), redirect_stdout(StringIO()) as stdout:
            status = watch.main(['--mode', 'saved-only', '--repo', str(self.repo),
                '--private-root', str(self.private_root), '--owner-public-pem', str(self.pem),
                '--report', str(out)])
        self.assertEqual(status, 0)
        summary = json.loads(out.read_bytes())
        self.assertEqual(summary['published_races'], 1)
        self.assertNotIn('PRIVATE_RAW_SOURCE', out.read_text() + stdout.getvalue())
        self.assertNotIn('BEGIN PRIVATE KEY', out.read_text() + stdout.getvalue())
        self.assertNotIn('1-2-3', out.read_text() + stdout.getvalue())

    def test_main_rejects_report_inside_private_cleanup_directory(self):
        with redirect_stdout(StringIO()):
            status = watch.main(['--mode', 'saved-only', '--repo', str(self.repo),
                '--private-root', str(self.private_root), '--owner-public-pem', str(self.pem),
                '--report', str(self.private_root / 'summary.json')])
        self.assertEqual(status, 2)
        self.assertFalse((self.private_root / 'summary.json').exists())
        self.settle.assert_not_called()


if __name__ == '__main__':
    unittest.main()
