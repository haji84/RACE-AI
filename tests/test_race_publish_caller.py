import importlib.util
from contextlib import redirect_stdout
import copy
from datetime import datetime,timedelta
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
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

    def test_exhibition_skips_nearly_closed_and_selects_only_two_preview_kinds(self):
        now=datetime.fromisoformat('2026-10-15T08:58:00+09:00')
        race,kinds=CALLER.select_race(self.feed(),now,mode='exhibition')
        self.assertEqual(race['race_id'],'20261015-18-02')
        self.assertEqual(kinds,('beforeinfo','odds3t'))
        race,_=CALLER.select_race(self.feed(),now-timedelta(microseconds=1),mode='exhibition')
        self.assertEqual(race['race_id'],'20261015-18-01')

    def test_exhibition_explicit_identity_never_substitutes_other_race(self):
        now=datetime.fromisoformat('2026-10-15T08:58:00+09:00')
        self.assertEqual(CALLER.select_race(self.feed(),now,mode='exhibition',race_id='20261015-18-01'),(None,()))
        race,kinds=CALLER.select_race(self.feed(),now,mode='exhibition',race_id='20261015-18-02')
        self.assertEqual(race['race_id'],'20261015-18-02');self.assertEqual(kinds,('beforeinfo','odds3t'))
        self.assertEqual(CALLER.select_race(self.feed(),now,mode='exhibition',race_id='20261015-18-03'),(None,()))

    def test_exhibition_never_falls_back_to_closed_result_or_calls_collector(self):
        now=datetime.fromisoformat('2026-10-15T11:00:00+09:00');collector=Mock()
        self.assertEqual(CALLER.select_race(self.feed(),now,mode='exhibition'),(None,()))
        self.assertEqual(CALLER.collect_bundle(self.feed(),{},now=now,clock=lambda:now,collector=collector,mode='exhibition'),(None,{}))
        collector.assert_not_called()

    def test_exhibition_rechecks_actual_margin_before_first_source_fetch(self):
        selected=datetime.fromisoformat('2026-10-15T08:57:59+09:00');actual=selected+timedelta(seconds=1)
        collector=Mock()
        self.assertEqual(CALLER.collect_bundle(self.feed(),{},now=selected,clock=lambda:actual,
            collector=collector,mode='exhibition',race_id='20261015-18-01'),(None,{}))
        collector.assert_not_called()

    def test_exhibition_collection_fetches_only_exact_preview_and_odds_kinds(self):
        helper=merge_fixtures.RaceUpdateMergeTests();feed=helper.feed();feed['schedule_verified']=True
        feed['venues'][0]['status']='READY';feed['venues'] += [{'status':'NO_EVENT','races':[]} for _ in range(23)]
        now=datetime.fromisoformat('2026-10-15T07:02:00+09:00');calls=[]
        def collector(day,venue,number,kind,**kwargs):
            calls.append((venue,number,kind))
            record=helper.observation(kind)
            return {key:value for key,value in record.items() if key not in {'snapshot_id','saved_at','storage_eligible_pre_race'}}
        with patch('race_ai.official_observation_store.utc_now',return_value=now):
            bundle,failed=CALLER.collect_bundle(feed,{},now=now,clock=lambda:now,collector=collector,
                mode='exhibition',race_id='20261015-18-01')
        self.assertEqual(calls,[('18',1,'beforeinfo'),('18',1,'odds3t')])
        self.assertEqual(failed,{})
        self.assertEqual(bundle['race_id'],'20261015-18-01')
        self.assertEqual({record['kind'] for record in bundle['records']},{'beforeinfo','odds3t'})

    def test_exhibition_skips_incomplete_sixboat_program(self):
        feed=self.feed();feed['venues'][0]['races'][0]['boats'].pop()
        now=datetime.fromisoformat('2026-10-15T07:00:00+09:00')
        race,_=CALLER.select_race(feed,now,mode='exhibition')
        self.assertEqual(race['race_id'],'20261015-18-02')
        feed['venues'][0]['races'][1]['boats'][0]['lane']=2
        with self.assertRaises(ValueError):CALLER.select_race(feed,now,mode='exhibition')

    def test_exhibition_rejects_stale_invalid_duplicate_and_venue_conflicting_program(self):
        now=datetime.fromisoformat('2026-10-15T07:00:00+09:00')
        for race_id in ['20261014-18-01','20260230-18-01','../escape','20261015-25-01']:
            with self.subTest(race_id=race_id),self.assertRaises(ValueError):
                CALLER.select_race(self.feed(),now,mode='exhibition',race_id=race_id)
        mutations=[lambda f:f['venues'][0]['races'].append(copy.deepcopy(f['venues'][0]['races'][0])),
                   lambda f:f['venues'][0]['races'][0].update(race_id='20261015-25-01'),
                   lambda f:f['venues'][0].update(venue='17'),
                   lambda f:f['venues'][0]['races'][0].update(closed_at='2026-10-14T09:00:00+09:00')]
        for mutate in mutations:
            feed=self.feed();mutate(feed)
            with self.subTest(mutation=repr(mutate)),self.assertRaises(ValueError):CALLER.select_race(feed,now,mode='exhibition')

    def test_exhibition_run_no_upcoming_fetches_day_only_and_writes_nothing(self):
        now=datetime.fromisoformat('2026-10-15T11:00:00+09:00');logs=StringIO()
        with tempfile.TemporaryDirectory() as folder:
            review=Path(folder)/'review.json';review.write_text('{}',encoding='utf-8');output=Path(folder)/'unused.json'
            with patch.dict('os.environ',{'RACE_AI_RACE_PUBLISH_URL':'https://race-ai-preview-test-qq1130034-1738.vercel.app/api/publish-race'}), \
                 patch.object(CALLER,'workflow_session',return_value=(object(),{})), \
                 patch.object(CALLER,'get_json',return_value=self.feed()) as http, \
                 patch('race_ai.official_update_worker.fetch_update',side_effect=AssertionError('official source GET')) as official, \
                 patch.object(CALLER,'datetime',wraps=datetime) as clock,redirect_stdout(logs):
                clock.now.return_value=now
                CALLER.run(review,output,execute=True,mode='exhibition')
            self.assertEqual(http.call_count,1);official.assert_not_called()
            self.assertEqual(json.loads(logs.getvalue())['result'],'NO_UPCOMING_EXHIBITION_RACE')
            self.assertEqual(list(Path(folder).iterdir()),[review])

    def test_cli_exhibition_explicit_identity_dry_run_is_two_get_bound_no_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            env={**os.environ,'RACE_AI_RACE_PUBLISH_URL':'https://race-ai-preview-test-qq1130034-1738.vercel.app/api/publish-race'}
            command=[sys.executable,str(ROOT/'scripts/publish_race_updates.py'),'--mode','exhibition','--race-id','20261015-18-01',
                     '--review',str(Path(folder)/'absent.json'),'--output',str(Path(folder)/'unused.json')]
            result=subprocess.run(command,env=env,cwd=folder,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),{'result':'DRY_RUN','network_requests':0,'maximum_official_source_requests':2})
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_all_closed_selects_one_result_without_backdating(self):
        race,kinds=CALLER.select_race(self.feed(),datetime.fromisoformat('2026-10-15T11:00:00+09:00'))
        self.assertEqual(race['race_id'],'20261015-18-02');self.assertEqual(kinds,('raceresult',))

    def test_explicit_result_mode_selects_most_recent_closed_even_with_upcoming_races(self):
        feed=self.feed();future=copy.deepcopy(feed['venues'][0]['races'][1])
        future.update(race_id='20261015-18-03',closed_at='2026-10-15T11:00:00+09:00')
        feed['venues'][0]['races'].insert(0,future);now=datetime.fromisoformat('2026-10-15T10:00:00+09:00')
        race,kinds=CALLER.select_race(feed,now,mode='result')
        self.assertEqual(race['race_id'],'20261015-18-02');self.assertEqual(kinds,('raceresult',))
        auto,auto_kinds=CALLER.select_race(feed,now)
        self.assertEqual(auto['race_id'],'20261015-18-03');self.assertEqual(auto_kinds,('beforeinfo','odds3t'))

    def test_explicit_result_identity_can_select_older_closed_forecast_race(self):
        now=datetime.fromisoformat('2026-10-15T11:00:00+09:00')
        race,kinds=CALLER.select_race(self.feed(),now,mode='result',race_id='20261015-18-01')
        self.assertEqual(race['race_id'],'20261015-18-01');self.assertEqual(kinds,('raceresult',))

    def test_explicit_future_or_absent_result_identity_never_calls_collector(self):
        now=datetime.fromisoformat('2026-10-15T09:30:00+09:00')
        for race_id in ('20261015-18-02','20261015-18-03'):
            collector=Mock()
            with self.subTest(race_id=race_id):
                self.assertEqual(CALLER.select_race(self.feed(),now,mode='result',race_id=race_id),(None,()))
                self.assertEqual(CALLER.collect_bundle(self.feed(),{},now=now,collector=collector,mode='result',race_id=race_id),(None,{}))
                collector.assert_not_called()

    def test_explicit_result_identity_rejects_auto_stale_or_invalid_ids(self):
        now=datetime.fromisoformat('2026-10-15T11:00:00+09:00')
        for mode,race_id in (('auto','20261015-18-01'),('result','20261014-18-01'),('result','../escape'),('result','20261015-25-01')):
            with self.subTest(mode=mode,race_id=race_id),self.assertRaises(ValueError):
                CALLER.select_race(self.feed(),now,mode=mode,race_id=race_id)
        with patch.object(CALLER,'workflow_session') as session:
            with self.assertRaises(ValueError):CALLER.run(Path('missing'),Path('unused'),execute=True,race_id='20261015-18-01')
            session.assert_not_called()

    def test_result_selection_uses_jst_day_and_strict_timestamp_offset(self):
        feed=self.feed();feed['venues'][0]['races'][0]['closed_at']='2026-10-14T23:00:00Z'
        race,kinds=CALLER.select_race(feed,datetime.fromisoformat('2026-10-14T23:10:00+00:00'),mode='result')
        self.assertEqual(race['race_id'],'20261015-18-01');self.assertEqual(kinds,('raceresult',))
        feed['venues'][0]['races'][0]['closed_at']='2026-10-15T08:00:00+09:99'
        with self.assertRaises(ValueError):CALLER.select_race(feed,datetime.fromisoformat('2026-10-15T07:00:00+09:00'),mode='result')

    def test_result_mode_all_future_is_noop_and_never_calls_collector(self):
        now=datetime.fromisoformat('2026-10-15T07:00:00+09:00');collector=Mock()
        self.assertEqual(CALLER.select_race(self.feed(),now,mode='result'),(None,()))
        self.assertEqual(CALLER.collect_bundle(self.feed(),{},now=now,collector=collector,mode='result'),(None,{}))
        collector.assert_not_called()

    def test_result_mode_never_selects_prior_day_or_incomplete_nested_race(self):
        feed=self.feed();now=datetime.fromisoformat('2026-10-15T07:00:00+09:00')
        stale=copy.deepcopy(feed['venues'][0]['races'][0]);stale.update(race_id='20261014-18-01',closed_at='2026-10-14T23:00:00+09:00')
        incomplete=copy.deepcopy(stale);incomplete.update(race_id='20261015-18-03',closed_at='2026-10-15T06:00:00+09:00',boats=[{'lane':1}])
        feed['venues'][0]['races'] += [stale,incomplete]
        self.assertEqual(CALLER.select_race(feed,now,mode='result'),(None,()))
        with self.assertRaises(ValueError):CALLER.select_race(feed,now,mode='unknown')

    def test_result_collection_is_one_get_and_preserves_actual_observation_metadata(self):
        helper=merge_fixtures.RaceUpdateMergeTests();feed=helper.feed();feed['schedule_verified']=True
        feed['venues'][0]['status']='READY';feed['venues'] += [{'status':'NO_EVENT','races':[]} for _ in range(23)]
        future=copy.deepcopy(feed['venues'][0]['races'][0]);future.update(race_id='20261015-18-02',closed_at='2026-10-15T10:00:00+09:00')
        feed['venues'][0]['races'].append(future)
        newer=copy.deepcopy(future);newer.update(race_id='20261015-18-03',closed_at='2026-10-15T09:01:00+09:00')
        feed['venues'][0]['races'].append(newer)
        record=helper.observation('raceresult',capture='2026-10-15T09:00:00+09:00',saved='2026-10-15T09:01:00+09:00')
        raw={key:value for key,value in record.items() if key not in {'snapshot_id','saved_at','storage_eligible_pre_race'}}
        now=datetime.fromisoformat('2026-10-15T09:02:00+09:00');collector=Mock(return_value=raw)
        with patch('race_ai.official_observation_store.utc_now',return_value=now):
            bundle,failed=CALLER.collect_bundle(feed,{},now=now,collector=collector,clock=lambda:now,mode='result',race_id='20261015-18-01')
        self.assertEqual(failed,{})
        args,kwargs=collector.call_args
        self.assertEqual(args,(datetime(2026,10,15).date(),'18',1,'raceresult'))
        self.assertEqual(kwargs,{'review':{},'execute':True,'entries':feed['venues'][0]['races'][0]['boats']})
        collector.assert_called_once()
        saved=bundle['records'][0]
        self.assertEqual(saved['captured_at'],raw['captured_at']);self.assertEqual(saved['source_sha256'],raw['source_sha256'])
        self.assertEqual(saved['source_url'],raw['source_url']);self.assertEqual(saved['data'],raw['data'])
        self.assertFalse(saved['eligible_pre_race']);self.assertFalse(saved['storage_eligible_pre_race'])
        self.assertEqual(saved['saved_at'],'2026-10-15T00:02:00.000000+00:00')
        collector.reset_mock();collector.return_value={**raw,'race_id':'20261015-18-02'}
        with patch('race_ai.official_observation_store.utc_now',return_value=now),self.assertRaises(ValueError):
            CALLER.collect_bundle(feed,{},now=now,collector=collector,clock=lambda:now,mode='result',race_id='20261015-18-01')
        collector.assert_called_once()

    def test_result_run_all_future_fetches_day_only_and_writes_no_output(self):
        now=datetime.fromisoformat('2026-10-15T07:00:00+09:00');logs=StringIO()
        with tempfile.TemporaryDirectory() as folder:
            review=Path(folder)/'review.json';review.write_text('{}',encoding='utf-8');output=Path(folder)/'unused.json'
            with patch.dict('os.environ',{'RACE_AI_RACE_PUBLISH_URL':'https://race-ai-preview-test-qq1130034-1738.vercel.app/api/publish-race'}), \
                 patch.object(CALLER,'workflow_session',return_value=(object(),{})), \
                 patch.object(CALLER,'get_json',return_value=self.feed()) as http, \
                 patch('race_ai.official_update_worker.fetch_update',side_effect=AssertionError('official source GET')) as official, \
                 patch.object(CALLER,'datetime',wraps=datetime) as clock,redirect_stdout(logs):
                clock.now.return_value=now
                CALLER.run(review,output,execute=True,mode='result')
            self.assertEqual(http.call_count,1)
            official.assert_not_called()
            self.assertTrue(http.call_args.args[1].full_url.endswith('/api/today'))
            self.assertEqual(json.loads(logs.getvalue())['result'],'NO_CLOSED_RACE')
            self.assertEqual(list(Path(folder).iterdir()),[review])

    def test_cli_result_mode_dry_run_has_one_source_bound_and_no_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            env={**os.environ,'RACE_AI_RACE_PUBLISH_URL':'https://race-ai-preview-test-qq1130034-1738.vercel.app/api/publish-race'}
            command=[sys.executable,str(ROOT/'scripts/publish_race_updates.py'),'--mode','result','--race-id','20261015-18-01','--review',str(Path(folder)/'absent.json'),'--output',str(Path(folder)/'unused.json')]
            result=subprocess.run(command,env=env,cwd=folder,capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(result.stdout),{'result':'DRY_RUN','network_requests':0,'maximum_official_source_requests':1})
            self.assertEqual(list(Path(folder).iterdir()),[])

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
        with self.assertRaisesRegex(ValueError,'RACE_ALL_SOURCES_UNAVAILABLE') as caught:
            CALLER.collect_bundle(self.feed(),{},now=datetime.fromisoformat('2026-10-15T07:00:00+09:00'),collector=collector)
        self.assertEqual(caught.exception.failed_kinds,{'beforeinfo':'SOURCE_INVALID','odds3t':'SOURCE_INVALID'})


if __name__=='__main__':unittest.main()
