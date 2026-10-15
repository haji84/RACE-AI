"""Synthetic controlled transports; never create actual race predictions."""
import copy
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
