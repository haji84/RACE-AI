"""Synthetic end-to-end caller evidence; no official network or wagers."""
import copy
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from tests.test_exhibition_contract import fixture, NOW
from web.exhibition_contract import build_post_exhibition_bundle
from web.race_contract import canonical, program_digest

ROOT = Path(__file__).resolve().parents[1]


class ExhibitionCallerTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('exhibition_caller', ROOT/'scripts/publish_exhibition_prediction.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.baseline, self.source, self.race = fixture()
        snapshot = build_post_exhibition_bundle(self.baseline, self.source, self.race, NOW)
        self.receipt = dict(schema_version=1,request_id='123457-1',snapshot=snapshot,
            cloud_saved_at=NOW.isoformat(),cloud_eligible_pre_race=True,program_identity_sha256=program_digest(self.race))
        self.report = dict(status='verified',commit_sha='a'*40,race_id=self.race['race_id'],request_id='123457-1',
            snapshot_id=snapshot['snapshot_id'],sha256=self.module.canonical_sha(self.receipt),cloud_saved_at=self.receipt['cloud_saved_at'],
            cloud_eligible_pre_race=True,models=1,program_identity_sha256=program_digest(self.race),
            baseline_snapshot_id=self.baseline['snapshot']['snapshot_id'],beforeinfo_snapshot_id=self.source['latest']['beforeinfo'])
        self.feed = dict(date_jst='2026-10-15',schedule_verified=True,redistribution_authorized=True,
            venues=[dict(venue=f'{i:02}',status='NO_EVENT',races=[]) for i in range(1,25)])
        self.feed['venues'][int(self.race['race_id'][9:11])-1].update(status='READY',races=[self.race])
        self.env = dict(RACE_AI_EXHIBITION_PUBLISH_URL='https://race-ai-preview-synthetic-qq1130034-1738.vercel.app/api/publish-exhibition-prediction',
            RACE_AI_EXHIBITION_COMMIT_SHA='a'*40,GITHUB_RUN_ID='123457',GITHUB_RUN_ATTEMPT='1')

    def test_dry_run_does_not_read_files_or_network(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(self.module,'workflow_session',side_effect=AssertionError('network')):
            self.module.run(Path(folder)/'absent.json',Path(folder)/'output')
            self.assertEqual(list(Path(folder).iterdir()),[])

    def call(self, folder, *, missing_baseline=False, hook=None):
        calls=[]
        def get_json(opener,request,*,limit):
            calls.append(request)
            if request.full_url.endswith('/today'):return self.feed
            if '/race?' in request.full_url:return self.source
            if request.full_url.endswith('/api/publish-prediction'):
                self.assertEqual(json.loads(request.data)['race_id'],self.race['race_id'])
                return self.base_report
            if '/prediction?' in request.full_url:
                if missing_baseline and 'request_id=' not in request.full_url:raise RuntimeError('DAY_PUBLISH_HTTP_404')
                return self.baseline
            if request.get_method()=='POST':
                self.assertEqual(json.loads(request.data),dict(publication_review='user-confirmation-2026-10-15-official-facts',race_id=self.race['race_id'],request_id='123457-1'))
                return self.report
            if '/exhibition-prediction?' in request.full_url:
                self.assertIn('request_id=123457-1',request.full_url)
                return self.receipt
            raise AssertionError(request.full_url)
        source_path=Path(folder)/'input.json';source_path.write_bytes(canonical(self.source))
        with patch.dict('os.environ',self.env),patch.object(self.module,'workflow_session',return_value=(object(),{})),patch.object(self.module,'get_json',side_effect=get_json),patch.object(self.module,'datetime',types.SimpleNamespace(now=lambda tz:NOW)):
            if hook:hook()
            self.module.run(source_path,Path(folder)/'output',execute=True)
        return calls

    def test_preserves_existing_baseline_and_backs_up_complete_pinned_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            calls=self.call(folder)
            self.assertEqual(len([r for r in calls if r.get_method()=='POST']),1)
            output=Path(folder)/'output'
            self.assertEqual(json.loads((output/'baseline.json').read_bytes()),self.baseline)
            self.assertEqual(json.loads((output/'source.json').read_bytes()),self.source)
            self.assertEqual(json.loads((output/'post.json').read_bytes()),self.receipt)
            self.assertTrue((output/'manifest.json').exists())

    def test_missing_baseline_is_saved_by_server_and_replayed_by_own_nonce(self):
        self.baseline['request_id']='123457-1'
        snapshot=build_post_exhibition_bundle(self.baseline,self.source,self.race,NOW)
        self.receipt['snapshot']=snapshot
        self.report.update(snapshot_id=snapshot['snapshot_id'],sha256=self.module.canonical_sha(self.receipt))
        self.base_report=dict(status='verified',commit_sha='a'*40,race_id=self.race['race_id'],request_id='123457-1',
            snapshot_id=self.baseline['snapshot']['snapshot_id'],cloud_saved_at=self.baseline['cloud_saved_at'],
            cloud_eligible_pre_race=True,models=2,sha256=self.module.canonical_sha(self.baseline))
        with tempfile.TemporaryDirectory() as folder:
            calls=self.call(folder,missing_baseline=True)
            posts=[r for r in calls if r.get_method()=='POST']
            self.assertEqual(len(posts),2)
            self.assertTrue(posts[0].full_url.endswith('/api/publish-prediction'))
            self.assertEqual(json.loads((Path(folder)/'output'/'baseline.json').read_bytes())['request_id'],'123457-1')

    def test_corrupt_existing_baseline_is_rejected_without_replacing_it(self):
        self.baseline['snapshot']['models'][1]['triples'][0]['probability']=.99
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):self.call(folder)
        # call() raises on any unexpected POST to the baseline endpoint; only a
        # literal404 authorizes creation, never malformed existing evidence.

    def test_rehashed_wrong_probability_or_links_are_rejected(self):
        for mutate in [lambda x:x['snapshot']['model']['triples'][0].update(probability=.99),
                       lambda x:x['snapshot']['baseline_link'].update(request_id='999999-1'),
                       lambda x:x.update(cloud_saved_at=self.race['closed_at'])]:
            value=copy.deepcopy(self.receipt);mutate(value)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                self.module.verify_receipt(value,self.baseline,self.source,self.race,self.report,'a'*40,'123457-1',NOW)

    def test_cutoff_consumed_by_backup_io_never_posts(self):
        with tempfile.TemporaryDirectory() as folder:
            source_path=Path(folder)/'input.json';source_path.write_bytes(canonical(self.source));calls=[]
            def get_json(opener,request,*,limit):
                calls.append(request)
                if request.full_url.endswith('/today'):return self.feed
                if '/race?' in request.full_url:return self.source
                if '/prediction?' in request.full_url:return self.baseline
                raise AssertionError('publication must stop before network POST')
            times=iter([NOW]*3+[datetime.fromisoformat(self.race['closed_at'])-timedelta(seconds=119)]*10)
            with patch.dict('os.environ',self.env),patch.object(self.module,'workflow_session',return_value=(object(),{})),patch.object(self.module,'get_json',side_effect=get_json),patch.object(self.module,'datetime',types.SimpleNamespace(now=lambda tz:next(times))):
                with self.assertRaisesRegex(ValueError,'CUTOFF_MARGIN'):self.module.run(source_path,Path(folder)/'output',execute=True)
            self.assertFalse(any(r.get_method()=='POST' for r in calls))


if __name__=='__main__':unittest.main()
