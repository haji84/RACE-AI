"""Synthetic controlled transports; never create actual race predictions."""
import copy
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from tests.test_live_research_contract import fixture, NOW
from web.research_contract import build_research_bundle

ROOT = Path(__file__).resolve().parents[1]


class CohortCallerTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'scripts/publish_research_cohort.py'
        self.assertTrue(path.exists(), 'bounded national cohort publisher is missing')
        spec = importlib.util.spec_from_file_location('cohort_caller', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def values(self):
        feed, first = fixture()
        feed['schedule_verified'] = True
        feed['venues'] = [dict(venue=f'{i:02}', status='NO_EVENT', races=[]) for i in range(1, 25)]
        for index in (0, 1):
            race = copy.deepcopy(first)
            race['race_id'] = f"20261015-{index+1:02}-01"
            race['closed_at'] = (NOW + timedelta(minutes=20+index)).isoformat()
            for boat in race['boats']:
                if 'race_id' in boat:
                    boat['race_id'] = race['race_id']
            feed['venues'][index].update(status='READY', races=[race])
        return feed

    def session(self, folder, transport, clock=NOW):
        env = dict(RACE_AI_RESEARCH_PUBLISH_URL='https://race-ai-preview-synthetic-qq1130034-1738.vercel.app/api/publish-prediction',
                   RACE_AI_RESEARCH_COMMIT_SHA='a'*40, GITHUB_RUN_ID='123456', GITHUB_RUN_ATTEMPT='1')
        return patch.multiple(self.module, workflow_session=lambda commit: (object(), {}),
                              get_json=transport,
                              datetime=types.SimpleNamespace(now=lambda tz: clock() if callable(clock) else clock))

    def environment(self):
        return patch.dict('os.environ', dict(RACE_AI_RESEARCH_PUBLISH_URL='https://race-ai-preview-synthetic-qq1130034-1738.vercel.app/api/publish-prediction',
                    RACE_AI_RESEARCH_COMMIT_SHA='a'*40, GITHUB_RUN_ID='123456', GITHUB_RUN_ATTEMPT='1'))

    def receipt(self, feed, race, request_id='123456-1'):
        snapshot = build_research_bundle(feed, race, NOW)
        return dict(schema_version=1, request_id=request_id, snapshot=snapshot, cloud_saved_at=snapshot['generated_at'],
                    cloud_eligible_pre_race=True, program_sha256=snapshot['program_sha256'])

    def transport(self, feed, existing=None, fail_race=None):
        self.calls = []
        def get(opener, request, *, limit):
            self.calls.append(request)
            if request.full_url.endswith('/today'):
                return feed
            from urllib.parse import urlsplit, parse_qs
            if request.get_method() == 'POST':
                body = json.loads(request.data)
                if body['race_id'] == fail_race:
                    raise RuntimeError('DAY_PUBLISH_HTTP_503')
                race = next(r for v in feed['venues'] for r in v['races'] if r['race_id'] == body['race_id'])
                receipt = self.receipt(feed, race)
                return dict(status='verified', commit_sha='a'*40, race_id=race['race_id'], request_id='123456-1',
                    snapshot_id=receipt['snapshot']['snapshot_id'], cloud_saved_at=receipt['cloud_saved_at'],
                    cloud_eligible_pre_race=True, models=2, sha256=self.module.canonical_sha(receipt))
            query = parse_qs(urlsplit(request.full_url).query)
            race = next(r for v in feed['venues'] for r in v['races'] if r['race_id'] == query['race_id'][0])
            if 'request_id' in query:
                return self.receipt(feed, race)
            if existing is not None and race['race_id'] in existing:
                return existing[race['race_id']]
            raise RuntimeError('DAY_PUBLISH_HTTP_404')
        return get

    def queue(self, venues=3, races=12):
        feed = self.values()
        template = feed['venues'][0]['races'][0]
        for index, venue in enumerate(feed['venues']):
            venue.update(status='READY' if index < venues else 'NO_EVENT', races=[])
            if index < venues:
                for number in range(1, races+1):
                    race = copy.deepcopy(template)
                    race.update(race_id=f'20261015-{index+1:02}-{number:02}',
                                closed_at=(NOW+timedelta(minutes=20+index*12+number)).isoformat())
                    venue['races'].append(race)
        return feed

    def test_all_upcoming_selects_later_same_venue_in_cutoff_order_without_write_cap_truncation(self):
        feed = self.queue(2, 3)
        feed['venues'][0]['races'].reverse()
        feed['venues'][1]['races'][0]['closed_at'] = (NOW+timedelta(minutes=21)).isoformat()
        selected = self.module.choose_cohort(feed, NOW, 1, selection='all-upcoming')
        self.assertEqual([r['race_id'] for r in selected], [
            '20261015-01-01', '20261015-02-01', '20261015-01-02',
            '20261015-01-03', '20261015-02-02', '20261015-02-03'])
        self.assertEqual([r['race_id'] for r in self.module.choose_cohort(feed, NOW, 1)], ['20261015-01-01'])

    def test_all_upcoming_supports_full_288_queue_but_rejects_unbounded_program(self):
        feed = self.queue(24, 12)
        self.assertEqual(len(self.module.choose_cohort(feed, NOW, selection='all-upcoming')), 288)
        feed['venues'][0]['races'].append(copy.deepcopy(feed['venues'][0]['races'][0]))
        with self.assertRaises(ValueError):
            self.module.choose_cohort(feed, NOW, selection='all-upcoming')

    def test_all_upcoming_second_batch_advances_preserved_prefix_without_cursor(self):
        feed = self.queue(3, 12)
        existing = {}
        original = self.transport(feed, existing)
        def transport(opener, request, *, limit):
            response = original(opener, request, limit=limit)
            if request.get_method() == 'POST':
                identifier = json.loads(request.data)['race_id']
                race = next(r for v in feed['venues'] for r in v['races'] if r['race_id'] == identifier)
                existing[identifier] = self.receipt(feed, race)
            return response
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport):
            first = self.module.run(Path(folder)/'first', execute=True, selection='all-upcoming')
            self.assertEqual(first['status'], 'BATCH_LIMIT_REACHED')
            self.assertEqual(len(first['selected_race_ids']), 36)
            self.assertEqual(len(first['saved']), 24)
            self.assertEqual(len(first['not_attempted_race_ids']), 12)
            self.assertEqual(len(list((Path(folder)/'first').glob('*.json'))), 49)
            prior = copy.deepcopy(existing)
            second = self.module.run(Path(folder)/'second', execute=True, selection='all-upcoming')
            self.assertEqual(second['status'], 'COMPLETED')
            self.assertEqual([r['race_id'] for r in second['preserved']], first['attempted_race_ids'])
            self.assertEqual([r['race_id'] for r in second['saved']], first['not_attempted_race_ids'])
            self.assertEqual(second['not_attempted_race_ids'], [])
            self.assertEqual(len([r for r in self.calls if r.get_method() == 'POST']), 36)
            self.assertEqual({k: existing[k] for k in prior}, prior)

    def test_default_run_keeps_next_per_venue_selection(self):
        feed = self.queue(2, 3)
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, self.transport(feed)):
            result = self.module.run(Path(folder)/'cohort', execute=True)
            self.assertEqual(result['selected_race_ids'], ['20261015-01-01', '20261015-02-01'])
            self.assertEqual(result['selection'], 'next-per-venue')

    def test_all_upcoming_extended_budget_reaches_new_tail_after_132_slow_preserved_reads(self):
        feed = self.queue(13, 12)
        races = [race for venue in feed['venues'] for race in venue['races']]
        existing = {race['race_id']: self.receipt(feed, race, '987654-1') for race in races[:132]}
        prior = copy.deepcopy(existing)
        for seconds, expected_saved in ((240, 0), (480, 24)):
            elapsed = [0.0]
            original = self.transport(feed, existing)
            def transport(opener, request, *, limit):
                try:
                    return original(opener, request, limit=limit)
                finally:
                    elapsed[0] += 2.0
            with self.subTest(seconds=seconds), tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport), patch.object(self.module, 'monotonic', side_effect=lambda: elapsed[0]):
                try:
                    result = self.module.run(Path(folder)/'cohort', execute=True, selection='all-upcoming', max_seconds=seconds)
                except ValueError as error:
                    self.fail(f'bounded all-upcoming tail scan rejected: {error}')
                self.assertEqual(len(result['saved']), expected_saved)
                self.assertEqual(result['posts_attempted'], expected_saved)
                self.assertEqual(existing, prior)
                if seconds == 240:
                    self.assertEqual(result['status'], 'TIME_LIMIT_REACHED')
                    self.assertEqual(len(list((Path(folder)/'cohort').glob('*.json'))), 1)
                else:
                    self.assertEqual(result['status'], 'COMPLETED')
                    self.assertEqual(len(result['preserved']), 132)
                    self.assertEqual(result['pending_race_ids'], [])
                    self.assertEqual(result['reads_used'], 181)
                    self.assertEqual(result['elapsed_seconds'], 410.0)
                    self.assertEqual(len(list((Path(folder)/'cohort').glob('*.json'))), 49)

    def test_extended_all_upcoming_budget_still_stops_on_monotonic_expiry(self):
        feed = self.queue(1, 3)
        existing = {race['race_id']: self.receipt(feed, race) for race in feed['venues'][0]['races']}
        elapsed = [0.0]
        original = self.transport(feed, existing)
        def transport(opener, request, *, limit):
            response = original(opener, request, limit=limit)
            if '/prediction?' in request.full_url:
                elapsed[0] = 480.0
            return response
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport), patch.object(self.module, 'monotonic', side_effect=lambda: elapsed[0]):
            try:
                result = self.module.run(Path(folder)/'cohort', execute=True, selection='all-upcoming', max_seconds=480)
            except ValueError as error:
                self.fail(f'extended monotonic stop could not run: {error}')
            self.assertEqual(result['status'], 'TIME_LIMIT_REACHED')
            self.assertEqual(result['reads_used'], 2)
            self.assertEqual(result['posts_attempted'], 0)
            self.assertEqual(len(result['preserved']), 1)
            self.assertEqual(result['pending_race_ids'], ['20261015-01-02', '20261015-01-03'])
            self.assertEqual(result['elapsed_seconds'], 480.0)

    def test_extended_run_renews_same_commit_session_before_short_lived_headers_expire(self):
        feed = self.queue(13, 12)
        races = [race for venue in feed['venues'] for race in venue['races']]
        existing = {race['race_id']: self.receipt(feed, race, '987654-1') for race in races[:132]}
        elapsed, issued = [0.0], {}
        original = self.transport(feed, existing)
        def session(commit):
            self.assertEqual(commit, 'a'*40)
            token = 'Bearer synthetic-session-'+str(len(issued)+1)
            issued[token] = elapsed[0]+300
            return object(), {'Authorization':token, 'X-Race-AI-Commit':commit}
        def transport(opener, request, *, limit):
            token = request.get_header('Authorization')
            if token not in issued or elapsed[0] >= issued[token]:
                raise RuntimeError('SYNTHETIC_OIDC_EXPIRED')
            try:
                return original(opener, request, limit=limit)
            finally:
                elapsed[0] += 2.0
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport), patch.object(self.module, 'workflow_session', side_effect=session), patch.object(self.module, 'monotonic', side_effect=lambda: elapsed[0]):
            try:
                result = self.module.run(Path(folder)/'cohort', execute=True, selection='all-upcoming', max_seconds=480)
            except RuntimeError as error:
                self.fail(f'extended run reused expired headers: {error}')
            self.assertEqual(result['status'], 'COMPLETED')
            self.assertEqual(len(result['saved']), 24)
            self.assertEqual(result['reads_used'], 181)
            self.assertEqual(result['posts_attempted'], 24)
            self.assertEqual(result['oidc_session_attempts'], 3)
            self.assertEqual(result['oidc_sessions_ready'], 3)

    def test_failed_session_renewal_stops_before_new_lookup_or_post_and_redacts_failure(self):
        feed = self.queue(1, 2)
        first = feed['venues'][0]['races'][0]
        elapsed = [0.0]
        original = self.transport(feed, {first['race_id']:self.receipt(feed, first)})
        def transport(opener, request, *, limit):
            response = original(opener, request, limit=limit)
            if '/prediction?' in request.full_url:
                elapsed[0] = 180.0
            return response
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport), patch.object(self.module, 'workflow_session', side_effect=[(object(), {}), RuntimeError('PRIVATE_ISSUER_DETAIL')]), patch.object(self.module, 'monotonic', side_effect=lambda: elapsed[0]):
            path = Path(folder)/'cohort'
            with self.assertRaises(RuntimeError):
                self.module.run(path, execute=True, selection='all-upcoming', max_seconds=480)
            manifest = json.loads((path/'manifest.json').read_bytes())
            self.assertEqual(manifest['status'], 'STOPPED')
            self.assertEqual(manifest['failure'], 'RuntimeError')
            self.assertEqual(manifest['reads_used'], 2)
            self.assertEqual(manifest['posts_attempted'], 0)
            self.assertEqual(manifest['oidc_session_attempts'], 2)
            self.assertEqual(manifest['oidc_sessions_ready'], 1)
            self.assertNotIn('PRIVATE_ISSUER_DETAIL', json.dumps(manifest))

    def test_session_renewal_crossing_cutoff_keeps_request_backup_without_post(self):
        feed = self.queue(1, 1)
        elapsed, clock = [0.0], [NOW]
        original = self.transport(feed)
        sessions = [0]
        def session(commit):
            sessions[0] += 1
            if sessions[0] == 2:
                clock[0] = NOW+timedelta(hours=1)
            return object(), {}
        def transport(opener, request, *, limit):
            try:
                return original(opener, request, limit=limit)
            finally:
                if '/prediction?' in request.full_url:
                    elapsed[0] = 180.0
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport, clock=lambda:clock[0]), patch.object(self.module, 'workflow_session', side_effect=session), patch.object(self.module, 'monotonic', side_effect=lambda: elapsed[0]):
            path = Path(folder)/'cohort'
            result = self.module.run(path, execute=True, selection='all-upcoming', max_seconds=480)
            self.assertEqual(result['status'], 'COMPLETED')
            self.assertEqual(result['posts_attempted'], 0)
            self.assertEqual(result['saved'], [])
            self.assertEqual(result['skipped'], [{'race_id':'20261015-01-01','reason':'JST_DAY_OR_CUTOFF_MARGIN_CHANGED'}])
            self.assertEqual(len(list(path.glob('*.request.json'))), 1)
            self.assertEqual(result['oidc_sessions_ready'], 2)

    def test_issuer_404_during_renewal_is_not_a_missing_forecast_and_never_allocates_a_write(self):
        feed = self.queue(1, 2)
        first = feed['venues'][0]['races'][0]
        elapsed = [0.0]
        original = self.transport(feed, {first['race_id']:self.receipt(feed, first)})
        def transport(opener, request, *, limit):
            response = original(opener, request, limit=limit)
            if '/prediction?' in request.full_url:
                elapsed[0] = 180.0
            return response
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport), patch.object(self.module, 'workflow_session', side_effect=[(object(), {}), RuntimeError('DAY_PUBLISH_HTTP_404'), (object(), {})]), patch.object(self.module, 'monotonic', side_effect=lambda: elapsed[0]):
            path = Path(folder)/'cohort'
            try:
                self.module.run(path, execute=True, selection='all-upcoming', max_seconds=480)
            except (ValueError, RuntimeError):
                pass
            manifest = json.loads((path/'manifest.json').read_bytes())
            self.assertEqual(manifest['status'], 'STOPPED')
            self.assertEqual(manifest['reads_used'], 2)
            self.assertEqual(manifest['posts_attempted'], 0)
            self.assertEqual(manifest['write_slots_used'], 0)
            self.assertEqual(manifest['request_backups'], [])
            self.assertEqual(manifest['oidc_session_attempts'], 2)
            self.assertEqual(manifest['oidc_sessions_ready'], 1)

    def test_preserved_reads_have_independent_cap_and_honest_unattempted_tail(self):
        feed = self.queue(1, 4)
        existing = {r['race_id']: self.receipt(feed, r, '987654-1') for r in feed['venues'][0]['races']}
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, self.transport(feed, existing)):
            result = self.module.run(Path(folder)/'cohort', execute=True, selection='all-upcoming', max_races=1, max_reads=3)
            self.assertEqual(result['status'], 'READ_LIMIT_REACHED')
            self.assertEqual(result['reads_used'], 3)
            self.assertEqual(result['write_slots_used'], 0)
            self.assertEqual([r['race_id'] for r in result['preserved']], ['20261015-01-01', '20261015-01-02'])
            self.assertEqual(result['not_attempted_race_ids'], ['20261015-01-03', '20261015-01-04'])
            self.assertEqual(len(list((Path(folder)/'cohort').glob('*.json'))), 1)

    def test_read_budget_reserves_pinned_receipt_before_any_post(self):
        feed = self.queue(1, 2)
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, self.transport(feed)):
            result = self.module.run(Path(folder)/'cohort', execute=True, selection='all-upcoming', max_reads=2)
            self.assertEqual(result['status'], 'READ_LIMIT_REACHED')
            self.assertEqual(result['reads_used'], 2)
            self.assertEqual(result['write_slots_used'], 0)
            self.assertFalse(any(r.get_method() == 'POST' for r in self.calls))
            self.assertEqual(result['pending_race_ids'], ['20261015-01-01', '20261015-01-02'])

    def test_monotonic_budget_stops_after_preserved_lookup_even_if_wall_clock_does_not_advance(self):
        feed = self.queue(1, 3)
        existing = {r['race_id']: self.receipt(feed, r) for r in feed['venues'][0]['races']}
        elapsed = [0.0]
        original = self.transport(feed, existing)
        def transport(opener, request, *, limit):
            result = original(opener, request, limit=limit)
            if '/prediction?' in request.full_url:
                elapsed[0] = 240.0
            return result
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport), patch.object(self.module, 'monotonic', side_effect=lambda: elapsed[0]):
            result = self.module.run(Path(folder)/'cohort', execute=True, selection='all-upcoming')
            self.assertEqual(result['status'], 'TIME_LIMIT_REACHED')
            self.assertEqual(result['attempted_race_ids'], ['20261015-01-01'])
            self.assertEqual(len(result['preserved']), 1)
            self.assertEqual(result['not_attempted_race_ids'], ['20261015-01-02', '20261015-01-03'])
            self.assertEqual(result['elapsed_seconds'], 240.0)

    def test_time_budget_after_backup_io_never_posts_and_preserves_request_evidence(self):
        feed = self.queue(1, 3)
        elapsed = [0.0]
        writer = self.module._write
        def delayed_write(path, value):
            result = writer(path, value)
            if path.name.endswith('.request.json'):
                elapsed[0] = 240.0
            return result
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, self.transport(feed)), patch.object(self.module, 'monotonic', side_effect=lambda: elapsed[0]), patch.object(self.module, '_write', side_effect=delayed_write):
            path = Path(folder)/'cohort'
            result = self.module.run(path, execute=True, selection='all-upcoming')
            self.assertEqual(result['status'], 'TIME_LIMIT_REACHED')
            self.assertEqual(result['write_slots_used'], 1)
            self.assertEqual(result['posts_attempted'], 0)
            self.assertTrue((path/'20261015-01-01.request.json').exists())
            self.assertEqual(result['pending_race_ids'], result['selected_race_ids'])

    def test_initial_auth_latency_is_inside_budget_and_does_not_start_late_feed_read(self):
        elapsed = [0.0]
        def session(commit):
            elapsed[0] = 211.0
            return object(), {}
        with tempfile.TemporaryDirectory() as folder, self.environment(), patch.object(self.module, 'workflow_session', side_effect=session), patch.object(self.module, 'get_json', side_effect=AssertionError('late read')), patch.object(self.module, 'monotonic', side_effect=lambda: elapsed[0]):
            path = Path(folder)/'cohort'
            result = self.module.run(path, execute=True, selection='all-upcoming')
            self.assertEqual(result['status'], 'TIME_LIMIT_REACHED')
            self.assertEqual(result['reads_used'], 0)
            self.assertEqual(result['selected_race_ids'], [])
            self.assertEqual(json.loads((path/'manifest.json').read_bytes()), result)

    def test_post_and_readback_phase_requires_60_seconds_and_rejects_response_overrun(self):
        for stage in ('lookup', 'post', 'readback'):
            feed = self.queue(1, 2)
            elapsed = [0.0]
            original = self.transport(feed)
            def transport(opener, request, *, limit):
                try:
                    result = original(opener, request, limit=limit)
                except RuntimeError:
                    if stage == 'lookup':
                        elapsed[0] = 181.0
                    raise
                if stage == 'post' and request.get_method() == 'POST':
                    elapsed[0] = 211.0
                if stage == 'readback' and 'request_id=' in request.full_url:
                    elapsed[0] = 241.0
                return result
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport), patch.object(self.module, 'monotonic', side_effect=lambda: elapsed[0]):
                result = self.module.run(Path(folder)/'cohort', execute=True, selection='all-upcoming')
                self.assertEqual(result['status'], 'TIME_LIMIT_REACHED')
                self.assertEqual(result['posts_attempted'], 0 if stage == 'lookup' else 1)
                self.assertEqual(result['reads_used'], 3 if stage == 'readback' else 2)
                self.assertEqual(result['not_attempted_race_ids'], ['20261015-01-02'])

    def test_budget_options_reject_invalid_or_oversized_values_without_side_effects(self):
        for options in ({'selection':'any'}, {'max_seconds':0}, {'max_seconds':241},
                        {'selection':'all-upcoming','max_seconds':481}, {'max_seconds':True},
                        {'max_seconds':float('nan')}, {'max_seconds':float('inf')},
                        {'max_reads':0}, {'max_reads':314}, {'max_reads':True}, {'max_reads':1.5}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as folder, patch.object(self.module, 'workflow_session', side_effect=AssertionError('network')):
                with self.assertRaises(ValueError):
                    self.module.run(Path(folder)/'cohort', execute=True, **options)
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_request_tamper_after_backup_stops_before_post_and_keeps_partial_manifest(self):
        feed = self.queue(1, 2)
        writer = self.module._write
        def tampered_write(path, value):
            result = writer(path, value)
            if path.name.endswith('.request.json'):
                path.write_bytes(b'{}')
            return result
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, self.transport(feed)), patch.object(self.module, '_write', side_effect=tampered_write):
            path = Path(folder)/'cohort'
            with self.assertRaises(ValueError):
                self.module.run(path, execute=True, selection='all-upcoming')
            manifest = json.loads((path/'manifest.json').read_bytes())
            self.assertEqual(manifest['status'], 'STOPPED')
            self.assertEqual(manifest['failure_race_id'], '20261015-01-01')
            self.assertEqual(manifest['not_attempted_race_ids'], ['20261015-01-02'])
            self.assertFalse(any(r.get_method() == 'POST' for r in self.calls))

    def test_backup_writer_detects_full_byte_readback_tamper_and_never_replaces_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'receipt.json'
            original = Path.open
            def corrupt_read(target, mode='r', *args, **kwargs):
                if target == path and mode == 'rb':
                    with original(target, mode, *args, **kwargs) as handle:
                        return io.BytesIO(handle.read()[:-1]+b' ')
                return original(target, mode, *args, **kwargs)
            with patch.object(Path, 'open', corrupt_read), self.assertRaises(ValueError):
                self.module._write(path, {'evidence':'saved'})
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                self.module._write(path, {'evidence':'replacement'})
            self.assertEqual(path.read_bytes(), before)

    def test_oversized_tampered_backup_is_rejected_without_unbounded_file_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'receipt.json'
            path.write_bytes(b'x'*256001)
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded read')), self.assertRaises(ValueError):
                self.module._read_backup(path, {'evidence':'saved'})

    def test_successful_null_lookup_is_invalid_evidence_and_never_authorizes_post(self):
        feed = self.queue(1, 2)
        original = self.transport(feed)
        def transport(opener, request, *, limit):
            if '/prediction?' in request.full_url:
                return None
            return original(opener, request, limit=limit)
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport):
            path = Path(folder)/'cohort'
            with self.assertRaises(ValueError):
                self.module.run(path, execute=True, selection='all-upcoming')
            manifest = json.loads((path/'manifest.json').read_bytes())
            self.assertEqual(manifest['status'], 'STOPPED')
            self.assertEqual(manifest['posts_attempted'], 0)
            self.assertEqual(manifest['pending_race_ids'], ['20261015-01-01', '20261015-01-02'])

    def test_invalid_publication_report_stops_and_preserves_honest_partial_manifest(self):
        for report in (None, [], 'unknown'):
            feed = self.queue(1, 2)
            original = self.transport(feed)
            def transport(opener, request, *, limit):
                result = original(opener, request, limit=limit)
                return report if request.get_method() == 'POST' else result
            with self.subTest(report=report), tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport):
                path = Path(folder)/'cohort'
                with self.assertRaises(ValueError):
                    self.module.run(path, execute=True, selection='all-upcoming')
                manifest = json.loads((path/'manifest.json').read_bytes())
                self.assertEqual(manifest['status'], 'STOPPED')
                self.assertEqual(manifest['posts_attempted'], 1)
                self.assertEqual(manifest['saved'], [])
                self.assertEqual(manifest['pending_race_ids'], ['20261015-01-01', '20261015-01-02'])

    def test_deep_preserved_prefix_uses_313_read_cap_to_reach_last_24_new_races(self):
        feed = self.queue(24, 12)
        races = [r for v in feed['venues'] for r in v['races']]
        existing = {r['race_id']: self.receipt(feed, r, '987654-1') for r in races[:264]}
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, self.transport(feed, existing)):
            path = Path(folder)/'cohort'
            result = self.module.run(path, execute=True, selection='all-upcoming')
            self.assertEqual(result['status'], 'COMPLETED')
            self.assertEqual(result['max_reads'], 313)
            self.assertEqual(result['reads_used'], 313)
            self.assertEqual(len(result['preserved']), 264)
            self.assertEqual([r['race_id'] for r in result['saved']], [f'20261015-{venue:02}-{number:02}' for venue in (23, 24) for number in range(1, 13)])
            self.assertEqual(result['pending_race_ids'], [])
            self.assertEqual(len(list(path.glob('*.json'))), 49)

    def test_abandoned_request_consumes_write_slot_without_exceeding_file_cap(self):
        feed = self.queue(1, 3)
        current = [NOW]
        writer = self.module._write
        def delayed_write(path, value):
            result = writer(path, value)
            if path.name.endswith('.request.json'):
                current[0] = NOW+timedelta(hours=3)
            return result
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, self.transport(feed), lambda:current[0]), patch.object(self.module, '_write', side_effect=delayed_write):
            path = Path(folder)/'cohort'
            result = self.module.run(path, execute=True, selection='all-upcoming', max_races=1)
            self.assertEqual(result['status'], 'BATCH_LIMIT_REACHED')
            self.assertEqual(result['write_slots_used'], 1)
            self.assertEqual(result['posts_attempted'], 0)
            self.assertEqual(len(result['skipped']), 1)
            self.assertEqual(result['not_attempted_race_ids'], ['20261015-01-02', '20261015-01-03'])
            self.assertEqual(len(list(path.glob('*.json'))), 2)

    def test_new_backup_pairs_restore_complete_verified_receipts_using_manifest_bytes(self):
        feed = self.queue(1, 2)
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, self.transport(feed)):
            path = Path(folder)/'cohort'
            result = self.module.run(path, execute=True, selection='all-upcoming')
            self.assertEqual(json.loads((path/'manifest.json').read_bytes()), result)
            for saved in result['saved']:
                identifier = saved['race_id']
                for kind in ('request', 'receipt'):
                    raw = (path/f'{identifier}.{kind}.json').read_bytes()
                    metadata = saved[f'{kind}_backup']
                    self.assertEqual(len(raw), metadata['bytes'])
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), metadata['sha256'])
                    self.assertEqual(raw, json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8'))
                receipt = json.loads((path/f'{identifier}.receipt.json').read_bytes())
                race = next(r for r in feed['venues'][0]['races'] if r['race_id'] == identifier)
                self.module._checked_prediction(receipt, race, NOW, NOW.date(), datetime.fromisoformat(race['closed_at']))

    def test_auth_error_stops_with_partial_manifest_and_no_later_candidate_reads(self):
        feed = self.queue(1, 3)
        original = self.transport(feed)
        def transport(opener, request, *, limit):
            if '/prediction?' in request.full_url:
                raise RuntimeError('DAY_PUBLISH_HTTP_403')
            return original(opener, request, limit=limit)
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport):
            path = Path(folder)/'cohort'
            with self.assertRaises(RuntimeError):
                self.module.run(path, execute=True, selection='all-upcoming')
            manifest = json.loads((path/'manifest.json').read_bytes())
            self.assertEqual(manifest['failure'], 'DAY_PUBLISH_HTTP_403')
            self.assertEqual(manifest['attempted_race_ids'], ['20261015-01-01'])
            self.assertEqual(manifest['not_attempted_race_ids'], ['20261015-01-02', '20261015-01-03'])

    def test_selects_one_earliest_per_venue_with_margin_and_explicit_cap(self):
        feed = self.values()
        first = feed['venues'][0]['races'][0]
        near = copy.deepcopy(first)
        near.update(race_id='20261015-01-02', closed_at=(NOW+timedelta(seconds=120)).isoformat())
        later = copy.deepcopy(first)
        later.update(race_id='20261015-01-03', closed_at=(NOW+timedelta(hours=2)).isoformat())
        feed['venues'][0]['races'] += [near, later]
        before = copy.deepcopy(feed)
        self.assertEqual([r['race_id'] for r in self.module.choose_cohort(feed, NOW, 24)], ['20261015-01-01','20261015-02-01'])
        self.assertEqual(len(self.module.choose_cohort(feed, NOW, 1)), 1)
        self.assertEqual(feed, before)
        for cap in (0, 25, True, 1.5):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                self.module.choose_cohort(feed, NOW, cap)
        for mutation in (lambda f: f.update(date_jst='2026-10-14'),
                         lambda f: f['venues'].__setitem__(23, copy.deepcopy(f['venues'][0])),
                         lambda f: f['venues'][0]['races'][0].update(race_id='20261015-02-12')):
            broken = copy.deepcopy(feed); mutation(broken)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.module.choose_cohort(broken, NOW, 24)

    def test_dry_run_creates_no_files_or_network(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(self.module, 'workflow_session', side_effect=AssertionError('network')):
            self.module.run(Path(folder)/'cohort')
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_invalid_feed_shape_is_rejected_with_bounded_error(self):
        for raw in (None, [], 'unexpected', {'venues':[None]*24}):
            with self.subTest(raw=type(raw).__name__), self.assertRaises(ValueError):
                self.module.choose_cohort(raw, NOW)

    def test_malformed_program_fields_stop_with_partial_manifest_before_receipt_reads(self):
        for mutation in (lambda f:f['venues'][0].update(venue=[]),
                         lambda f:f['venues'][0]['races'][0].update(boats=None)):
            feed = self.values()
            mutation(feed)
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, self.transport(feed)):
                path = Path(folder)/'cohort'
                with self.assertRaises(ValueError):
                    self.module.run(path, execute=True, selection='all-upcoming')
                manifest = json.loads((path/'manifest.json').read_bytes())
                self.assertEqual(manifest['status'], 'STOPPED')
                self.assertEqual(manifest['reads_used'], 1)
                self.assertEqual(manifest['posts_attempted'], 0)

    def test_new_predictions_use_actual_server_receipts_and_exclusive_normalized_backup(self):
        feed = self.values(); transport = self.transport(feed)
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport):
            path = Path(folder)/'cohort'; result = self.module.run(path, execute=True)
            self.assertEqual(result['status'], 'COMPLETED')
            self.assertEqual(len(result['saved']), 2)
            self.assertEqual(len([r for r in self.calls if r.get_method()=='POST']), 2)
            self.assertEqual(len(list(path.glob('*.json'))), 5)
            self.assertEqual(json.loads((path/'20261015-01-01.receipt.json').read_bytes()), self.receipt(feed,feed['venues'][0]['races'][0]))
            with self.assertRaises(ValueError):
                self.module.run(path, execute=True)
            self.assertEqual(len([r for r in self.calls if r.get_method()=='POST']), 2)

    def test_verified_existing_forecast_is_preserved_without_post_or_replacement(self):
        feed = self.values(); race = feed['venues'][0]['races'][0]
        existing = {race['race_id']: self.receipt(feed, race, '987654-1')}
        transport = self.transport(feed, existing)
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport):
            path = Path(folder)/'cohort'; result = self.module.run(path, execute=True)
            self.assertEqual([r['race_id'] for r in result['preserved']], [race['race_id']])
            self.assertEqual(len(result['saved']), 1)
            self.assertFalse((path/(race['race_id']+'.request.json')).exists())
            self.assertFalse(any(r.get_method()=='POST' and json.loads(r.data)['race_id']==race['race_id'] for r in self.calls))

    def test_corrupt_existing_evidence_stops_before_any_prediction_write(self):
        feed = self.values(); race = feed['venues'][0]['races'][0]
        receipt = self.receipt(feed, race); receipt['cloud_saved_at']=race['closed_at']
        transport = self.transport(feed, {race['race_id']: receipt})
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport):
            path = Path(folder)/'cohort'
            with self.assertRaises(ValueError): self.module.run(path, execute=True)
            self.assertFalse(any(r.get_method()=='POST' for r in self.calls))
            self.assertEqual(json.loads((path/'manifest.json').read_bytes())['status'], 'STOPPED')

    def test_partial_failure_preserves_first_receipt_and_failed_request_manifest(self):
        feed = self.values(); transport = self.transport(feed, fail_race='20261015-02-01')
        with tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder, transport):
            path = Path(folder)/'cohort'
            with self.assertRaises(RuntimeError): self.module.run(path, execute=True)
            manifest = json.loads((path/'manifest.json').read_bytes())
            self.assertEqual([r['race_id'] for r in manifest['saved']], ['20261015-01-01'])
            self.assertEqual(manifest['status'], 'STOPPED')
            self.assertEqual(manifest['failure'], 'DAY_PUBLISH_HTTP_503')
            self.assertTrue((path/'20261015-02-01.request.json').exists())
            self.assertFalse((path/'20261015-02-01.receipt.json').exists())

    def test_actual_clock_recheck_prevents_late_or_next_day_posts(self):
        feed = self.values()
        for changed in (NOW+timedelta(days=1), NOW+timedelta(hours=2)):
            calls=[0]
            def clock():
                calls[0]+=1
                return NOW if calls[0]==1 else changed
            transport=self.transport(feed)
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder,transport,clock):
                result=self.module.run(Path(folder)/'cohort',execute=True)
                self.assertEqual(len(result['saved']),0)
                self.assertEqual(len(result['skipped']),2)
                self.assertFalse(any(r.get_method()=='POST' for r in self.calls))

    def test_filesystem_delay_cannot_send_a_post_after_margin_or_day_rollover(self):
        feed=self.values()
        feed['venues'][0]['races'][0]['closed_at']=(NOW+timedelta(seconds=121)).isoformat()
        for changed in (NOW+timedelta(seconds=2), NOW+timedelta(days=1)):
            current=[NOW]; transport=self.transport(feed); writer=self.module._write
            def delayed_write(path, value):
                result=writer(path,value)
                if path.name.endswith('.request.json'):current[0]=changed
                return result
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder, self.environment(), self.session(folder,transport,lambda:current[0]), patch.object(self.module,'_write',side_effect=delayed_write):
                result=self.module.run(Path(folder)/'cohort',execute=True,max_races=1)
                self.assertEqual(result['saved'],[])
                self.assertEqual(len(result['skipped']),1)
                self.assertFalse(any(r.get_method()=='POST' for r in self.calls))


if __name__ == '__main__':
    unittest.main()
