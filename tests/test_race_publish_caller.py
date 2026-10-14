import importlib.util
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from tests import test_race_update_merge as merge_fixtures

ROOT=Path(__file__).resolve().parents[1]
with patch.object(sys,'path',[str(ROOT/'scripts')]+sys.path):
    spec=importlib.util.spec_from_file_location('race_caller',ROOT/'scripts/publish_race_updates.py')
    CALLER=importlib.util.module_from_spec(spec);spec.loader.exec_module(CALLER)


class RacePublishCallerTests(unittest.TestCase):
    def feed(self):
        races=[{'race_id':'20261015-18-'+str(n).zfill(2),'closed_at':f'2026-10-15T{8+n:02d}:00:00+09:00',
            'boats':[{'lane':i} for i in range(1,7)]} for n in (1,2)]
        return {'date_jst':'2026-10-15','schedule_verified':True,'redistribution_authorized':True,
            'venues':[{'status':'READY','races':races}]+[{'status':'NO_EVENT','races':[]} for _ in range(23)]}

    def test_first_upcoming_race_and_only_two_bounded_kinds(self):
        race,kinds=CALLER.select_race(self.feed(),datetime.fromisoformat('2026-10-15T09:00:00+09:00'))
        self.assertEqual(race['race_id'],'20261015-18-02')
        self.assertEqual(kinds,('beforeinfo','odds3t'))

    def test_all_closed_selects_one_result_without_backdating(self):
        race,kinds=CALLER.select_race(self.feed(),datetime.fromisoformat('2026-10-15T11:00:00+09:00'))
        self.assertEqual(race['race_id'],'20261015-18-02');self.assertEqual(kinds,('raceresult',))

    def test_stale_unapproved_or_incomplete_program_rejected(self):
        for field,value in [('date_jst','2026-10-14'),('redistribution_authorized',False),('schedule_verified',False),('venues',[])]:
            feed=self.feed();feed[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                CALLER.select_race(feed,datetime.fromisoformat('2026-10-15T07:00:00+09:00'))

    def test_dry_run_has_no_http_or_file_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'never-written.json'
            with patch.dict('os.environ',{'RACE_AI_RACE_PUBLISH_URL':'https://race-ai-preview-test-qq1130034-1738.vercel.app/api/publish-race'}),patch.object(CALLER,'workflow_session') as session:
                CALLER.run(Path(folder)/'missing-review.json',target)
            session.assert_not_called();self.assertFalse(target.exists())

    def test_out_of_scope_target_fails_before_credentials_or_source_gets(self):
        with patch.dict('os.environ',{'RACE_AI_RACE_PUBLISH_URL':'https://attacker.example/api/publish-race'}),patch.object(CALLER,'workflow_session') as session:
            with self.assertRaises(ValueError):CALLER.run(Path('missing'),Path('unused'),execute=True)
            session.assert_not_called()

    def test_one_failed_kind_does_not_fabricate_or_discard_other_valid_observation(self):
        helper=merge_fixtures.RaceUpdateMergeTests();feed=helper.feed();feed['schedule_verified']=True
        feed['venues'][0]['status']='READY';feed['venues'] += [{'status':'NO_EVENT','races':[]} for _ in range(23)]
        record=helper.observation('odds3t');raw={key:value for key,value in record.items() if key not in {'snapshot_id','saved_at','storage_eligible_pre_race'}}
        now=datetime.fromisoformat('2026-10-15T07:02:00+09:00')
        calls=[]
        def collector(day,venue,number,kind,**kwargs):
            calls.append(kind);return {'status':'SOURCE_UNAVAILABLE'} if kind=='beforeinfo' else raw
        with patch('race_ai.official_observation_store.utc_now',return_value=now):
            bundle,failed=CALLER.collect_bundle(feed,{},now=now,collector=collector,clock=lambda:now)
        self.assertEqual(calls,['beforeinfo','odds3t']);self.assertEqual(failed,{'beforeinfo':'SOURCE_UNAVAILABLE'})
        self.assertEqual([r['kind'] for r in bundle['records']],['odds3t'])

    def test_all_failed_sources_never_produce_a_publishable_bundle(self):
        def collector(*args,**kwargs):return {'status':'SOURCE_INVALID'}
        with self.assertRaisesRegex(ValueError,'RACE_ALL_SOURCES_UNAVAILABLE'):
            CALLER.collect_bundle(self.feed(),{},now=datetime.fromisoformat('2026-10-15T07:00:00+09:00'),collector=collector)


if __name__=='__main__':unittest.main()
