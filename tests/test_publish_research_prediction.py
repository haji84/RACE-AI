import importlib.util
from pathlib import Path
import tempfile
import copy
import json
import types
import unittest
from unittest.mock import patch
from datetime import datetime,timedelta

from tests.test_live_research_contract import fixture,NOW
from web.research_contract import build_research_bundle

ROOT=Path(__file__).resolve().parents[1]


class ResearchRunnerTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('research_runner',ROOT/'scripts/publish_research_prediction.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)

    def test_dry_run_has_no_network_or_files(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(self.module,'workflow_session',side_effect=AssertionError('network')):
            path=Path(folder)/'research.json'
            self.module.run(path)
            self.assertFalse(path.exists());self.assertEqual(list(Path(folder).iterdir()),[])

    def test_selection_never_uses_closed_or_nearly_closed_race(self):
        feed,race=fixture()
        feed.update(schedule_verified=True)
        feed['venues']=[dict(venue=f'{i:02}',status='NO_EVENT',races=[]) for i in range(1,25)]
        feed['venues'][0].update(status='READY',races=[race])
        self.assertEqual(self.module.choose_race(feed,NOW)['race_id'],race['race_id'])
        close=self.module.instant(race['closed_at'])
        self.assertIsNone(self.module.choose_race(feed,close-timedelta(seconds=60)))
        self.assertIsNone(self.module.choose_race(feed,close+timedelta(seconds=1)))
        feed['date_jst']='2026-10-14'
        with self.assertRaises(ValueError):self.module.choose_race(feed,NOW)

    def values(self):
        feed,race=fixture();feed['schedule_verified']=True
        feed['venues']=[dict(venue=f'{i:02}',status='NO_EVENT',races=[]) for i in range(1,25)]
        feed['venues'][0].update(status='READY',races=[race])
        snapshot=build_research_bundle(feed,race,NOW)
        receipt=dict(schema_version=1,request_id='123456-1',snapshot=snapshot,
            cloud_saved_at=snapshot['generated_at'],cloud_eligible_pre_race=True,program_sha256=snapshot['program_sha256'])
        report=dict(status='verified',commit_sha='a'*40,race_id=race['race_id'],request_id='123456-1',
            snapshot_id=snapshot['snapshot_id'],cloud_saved_at=receipt['cloud_saved_at'],cloud_eligible_pre_race=True,
            models=2,sha256=self.module.canonical_sha(receipt))
        return feed,race,receipt,report

    def test_signed_server_generation_is_read_back_by_own_nonce_and_backed_up(self):
        feed,race,receipt,report=self.values();calls=[]
        def get_json(opener,request,*,limit):
            calls.append(request)
            if request.full_url.endswith('/today'):return feed
            if request.get_method()=='POST':
                self.assertEqual(json.loads(request.data),dict(publication_review='user-confirmation-2026-10-15-official-facts',race_id=race['race_id'],request_id='123456-1'))
                return report
            self.assertTrue(request.full_url.endswith('/prediction?race_id='+race['race_id']+'&request_id=123456-1'))
            return receipt
        env=dict(RACE_AI_RESEARCH_PUBLISH_URL='https://race-ai-preview-synthetic-qq1130034-1738.vercel.app/api/publish-prediction',
            RACE_AI_RESEARCH_COMMIT_SHA='a'*40,GITHUB_RUN_ID='123456',GITHUB_RUN_ATTEMPT='1')
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',env),patch.object(self.module,'workflow_session',return_value=(object(),{})),patch.object(self.module,'get_json',side_effect=get_json),patch.object(self.module,'datetime',types.SimpleNamespace(now=lambda tz:NOW,fromisoformat=datetime.fromisoformat)):
            path=Path(folder)/'research.json';self.module.run(path,execute=True)
            self.assertEqual(json.loads(path.read_bytes()),receipt)
            self.assertEqual(len(calls),3)
            self.assertTrue(path.with_suffix('.request.json').exists())

    def test_rehashed_tampered_probability_and_late_receipt_fail(self):
        feed,race,receipt,report=self.values()
        for mutate in (lambda r:r['snapshot']['models'][1]['triples'][0].update(probability=.99),lambda r:r.update(cloud_saved_at=race['closed_at']),lambda r:r.update(cloud_eligible_pre_race=False)):
            value=copy.deepcopy(receipt);mutate(value)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.module.verify_receipt(value,race,report,'a'*40,'123456-1',NOW)

    def test_malformed_offset_cannot_be_normalized_into_cloud_save_evidence(self):
        feed,race,receipt,report=self.values()
        receipt['cloud_saved_at']='2026-10-15T09:12:00+09:99'
        report.update(cloud_saved_at=receipt['cloud_saved_at'],sha256=self.module.canonical_sha(receipt))
        with self.assertRaises(ValueError):self.module.verify_receipt(receipt,race,report,'a'*40,'123456-1',NOW)


if __name__=='__main__':unittest.main()
