"""Automatic prior-day history shares source guards and never changes inference."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError
import zipfile

from tests.test_boat_entry_observations import daily_pair, uncompressed_lzh
from scripts import boat_nationwide_ab_pilot as pilot
from race_ai.source_retry_policy import SourceWait, plan_http_wait

DAY = date(2026, 11, 5)
NOW = datetime.fromisoformat('2026-11-05T19:00:00+09:00')
AT = NOW - timedelta(seconds=1)
RID = '20261105-17-12'
CUTOFF = '2026-11-05T21:00:00+09:00'


def collector(test):
    try:
        from race_ai import boat_entry_source_collection
    except ImportError:
        test.fail('automatic historical source collector is missing')
    return boat_entry_source_collection


def archives():
    b, k = daily_pair()
    return {'B': uncompressed_lzh(b, 'B261104.TXT'), 'K': uncompressed_lzh(k, 'K261104.TXT')}


def fetcher(calls):
    payloads = archives()
    def fetch(url):
        calls.append(url)
        raw = payloads['K' if '/K/' in url else 'B']
        return raw, AT, hashlib.sha256(raw).hexdigest()
    return fetch


def ready(test):
    return collector(test).collect_previous_day_history(DAY, now=NOW, fetch=fetcher([]))


def forecast_document(cache=None):
    from tests.test_observed_p1_connection import inputs
    from race_ai.boat_ab_shadow import build_pair
    from race_ai.boat_live_feature_shadow import build_live_feature_shadow
    base,extra,_=inputs()
    base.update(race_id=RID,cutoff_at=CUTOFF,captured_at=AT.isoformat())
    extra.update(race_id=RID,observed_at=AT.isoformat())
    out=dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',day_jst=DAY.isoformat(),
        observed_at=NOW.isoformat(),paired_forecasts=[build_pair(base,NOW.isoformat())],
        additional_official_feature_shadows=[build_live_feature_shadow(base,extra,NOW.isoformat())])
    if cache is not None:out['entry_observation_history']=cache
    return out


def context():
    return dict(schema='RACE_AI_BOAT_SUPPLEMENTAL_CONTEXT_V1',race_id=RID,cutoff_at=CUTOFF,
        roster=[dict(lane=i,registration_number=str(4000+i)) for i in range(1,7)],
        beforeinfo={'status':'PARSED'},pitreport=None,entry_history=None,forecast_inputs_used=False)


class EntrySourceCollectorTests(unittest.TestCase):
    def test_prior_day_archives_are_validated_once_then_cache_avoids_all_gets(self):
        calls=[]
        out=collector(self).collect_previous_day_history(DAY,now=NOW,fetch=fetcher(calls))
        self.assertEqual(calls,[
            'https://www1.mbrace.or.jp/od2/K/202611/k261104.lzh',
            'https://www1.mbrace.or.jp/od2/B/202611/b261104.lzh'])
        self.assertEqual(out['status'],'READY')
        self.assertEqual(out['history_day'],'2026-11-04')
        self.assertEqual(len(out['history']['records']),3)
        self.assertEqual(out['history']['source_proofs']['K']['captured_at'],AT.isoformat())
        no_fetch=Mock(side_effect=AssertionError('cached source was requested'))
        again=collector(self).collect_previous_day_history(DAY,now=NOW+timedelta(minutes=1),fetch=no_fetch,cache=out)
        self.assertEqual(again,out)
        no_fetch.assert_not_called()

    def test_publication_404_is_missing_until_actual_server_retry_then_retried(self):
        wait=plan_http_wait(404,{'Retry-After':'3600'},NOW,not_yet_published=True)
        def missing(url):raise pilot._PublicationWait(wait)
        out=collector(self).collect_previous_day_history(DAY,now=NOW,fetch=missing)
        self.assertEqual(out['status'],'WAITING_PUBLICATION')
        self.assertIsNone(out['history'])
        self.assertEqual(out['missing_sources'],['https://www1.mbrace.or.jp/od2/K/202611/k261104.lzh'])
        blocked=Mock(side_effect=AssertionError('publication retry bypassed'))
        self.assertEqual(collector(self).collect_previous_day_history(DAY,now=NOW+timedelta(minutes=5),fetch=blocked,cache=out),out)
        blocked.assert_not_called()
        calls=[]
        retried=collector(self).collect_previous_day_history(DAY,now=NOW+timedelta(hours=1),fetch=fetcher(calls),cache=out)
        self.assertEqual(retried['status'],'READY')
        self.assertEqual(len(calls),2)

    def test_authorization_rate_limit_and_handoff_propagate_without_alternate_get(self):
        for error in (SourceWait('SOURCE_AUTHORIZATION_REQUIRED',state='AUTHORIZATION_WAIT'),
                      SourceWait('HTTP_RATE_LIMIT',(NOW+timedelta(hours=1)).isoformat(),state='RATE_LIMIT_WAIT'),
                      ValueError('WORKER_HANDOFF')):
            with self.subTest(reason=str(error)):
                fetch=Mock(side_effect=error)
                with self.assertRaises(type(error)):
                    collector(self).collect_previous_day_history(DAY,now=NOW,fetch=fetch)
                self.assertEqual(fetch.call_count,1)

    def test_cache_and_input_cannot_claim_future_capture_or_target_day_results(self):
        c=ready(self)
        with self.assertRaises(ValueError):
            collector(self).validate_entry_history_cache(c,day=DAY,as_of=AT)
        wrong=deepcopy(c);wrong['history_day']=DAY.isoformat()
        with self.assertRaises(ValueError):
            collector(self).validate_entry_history_cache(wrong,day=DAY,as_of=NOW)
        wrong=deepcopy(c);wrong['history']['source_proofs']['K']['source_sha256']='0'*64
        calls=[]
        replaced=collector(self).collect_previous_day_history(DAY,now=NOW,fetch=fetcher(calls),cache=wrong)
        self.assertEqual(replaced['status'],'READY')
        self.assertEqual(len(calls),2)
        def bad_hash(url):
            raw=archives()['K'];return raw,AT,'0'*64
        with self.assertRaisesRegex(ValueError,'HASH'):
            collector(self).collect_previous_day_history(DAY,now=NOW,fetch=bad_hash)

    def test_legacy_document_has_no_cache_and_new_document_validates_sources(self):
        self.assertIsNone(collector(self).cache_from_document({},day=DAY,as_of=NOW))
        c=ready(self)
        self.assertEqual(collector(self).cache_from_document({'entry_observation_history':c},day=DAY,as_of=NOW),c)
        bad=deepcopy(c);bad['history']['records'][0]['entries'][0]['racer_id']='9999'
        with self.assertRaises(ValueError):
            collector(self).cache_from_document({'entry_observation_history':bad},day=DAY,as_of=NOW)


class ArchiveTransportTests(unittest.TestCase):
    def test_archive_get_charges_existing_guard_counter_and_checks_media(self):
        raw=archives()['K']
        class Response:
            status=200
            headers={'content-type':'application/octet-stream'}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def geturl(self):return 'https://www1.mbrace.or.jp/od2/K/202611/k261104.lzh'
            def read(self,limit):self.limit=limit;return raw
        response=Response();guard=Mock()
        with patch.object(pilot,'_clock',return_value=NOW),patch.object(pilot,'SOURCE_GUARD',guard),patch.object(pilot,'requests_used',0),patch.object(pilot.request,'build_opener',return_value=Mock(open=Mock(return_value=response))),patch.object(pilot.time,'sleep'):
            body,at,digest=pilot.get(response.geturl(),day=DAY,media='archive',not_yet_published=True)
            self.assertEqual((body,at,digest),(raw,NOW,hashlib.sha256(raw).hexdigest()))
            self.assertEqual(pilot.requests_used,1)
            guard.charge.assert_called_once_with('forecast')
            guard.http_success.assert_called_once()
            response.headers={'content-type':'text/html'}
            with self.assertRaises(ValueError):pilot.get(response.geturl(),day=DAY,media='archive')
            self.assertEqual(pilot.requests_used,2)

    def test_archive_url_is_prior_day_official_and_paused_guard_blocks_network(self):
        guard=Mock();guard.charge.side_effect=SourceWait('HTTP_RATE_LIMIT',state='RATE_LIMIT_WAIT')
        with patch.object(pilot,'_clock',return_value=NOW),patch.object(pilot,'SOURCE_GUARD',guard),patch.object(pilot.request,'build_opener') as opener,patch.object(pilot,'requests_used',0):
            with self.assertRaises(ValueError):pilot.get('https://www1.mbrace.or.jp/od2/K/202611/k261105.lzh',day=DAY,media='archive')
            guard.charge.assert_not_called()
            with self.assertRaises(SourceWait):pilot.get('https://www1.mbrace.or.jp/od2/K/202611/k261104.lzh',day=DAY,media='archive')
            opener.assert_not_called()
            self.assertEqual(pilot.requests_used,0)


    def test_archive_429_latches_shared_guard_and_counts_only_issued_request(self):
        from race_ai import repeated_cycle
        class FixedClock(datetime):
            @classmethod
            def now(cls,tz=None):return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'session.json'
            repeated_cycle.start(path,day=DAY.isoformat(),run_id=99,now=NOW)
            guard=repeated_cycle.SourceGuard(path,clock=lambda:NOW)
            urls=[]
            def denied(req,**kwargs):
                urls.append(req.full_url)
                raise HTTPError(req.full_url,429,'wait',{'Retry-After':'1800'},None)
            with patch.object(pilot,'_clock',return_value=NOW),patch.object(pilot,'datetime',FixedClock),patch.object(pilot,'SOURCE_GUARD',guard),patch.object(pilot,'requests_used',0),patch.object(pilot.request,'build_opener',return_value=Mock(open=Mock(side_effect=denied))):
                fetch=lambda url:pilot.get(url,day=DAY,media='archive',not_yet_published=True)
                for _ in range(2):
                    with self.assertRaises(SourceWait):collector(self).collect_previous_day_history(DAY,now=NOW,fetch=fetch)
                self.assertEqual(pilot.requests_used,1)
            state=repeated_cycle.load(path)
        self.assertEqual(len(urls),1)
        self.assertEqual(state['requests_used'],1)
        self.assertEqual(state['source_wait']['state'],'RATE_LIMIT_WAIT')
        self.assertEqual(datetime.fromisoformat(state['source_wait']['retry_at']),NOW+timedelta(seconds=1800))

    def test_archive_404_remains_missing_without_quarantining_shared_guard(self):
        from race_ai import repeated_cycle
        class FixedClock(datetime):
            @classmethod
            def now(cls,tz=None):return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'session.json'
            repeated_cycle.start(path,day=DAY.isoformat(),run_id=99,now=NOW)
            guard=repeated_cycle.SourceGuard(path,clock=lambda:NOW)
            urls=[]
            def missing(req,**kwargs):
                urls.append(req.full_url)
                raise HTTPError(req.full_url,404,'not yet',{'Retry-After':'1800'},None)
            with patch.object(pilot,'_clock',return_value=NOW),patch.object(pilot,'datetime',FixedClock),patch.object(pilot,'SOURCE_GUARD',guard),patch.object(pilot,'requests_used',0),patch.object(pilot.request,'build_opener',return_value=Mock(open=Mock(side_effect=missing))):
                fetch=lambda url:pilot.get(url,day=DAY,media='archive',not_yet_published=True)
                cache=collector(self).collect_previous_day_history(DAY,now=NOW,fetch=fetch)
                again=collector(self).collect_previous_day_history(DAY,now=NOW,fetch=fetch,cache=cache)
                self.assertEqual(pilot.requests_used,1)
            state=repeated_cycle.load(path)
        self.assertEqual(cache,again)
        self.assertEqual(len(urls),1)
        self.assertIsNone(state['source_wait'])
        self.assertIsNone(cache['history'])
        self.assertEqual(datetime.fromisoformat(cache['source_wait']['retry_at']),NOW+timedelta(seconds=1800))


class PipelineHistoryTests(unittest.TestCase):
    def test_context_gets_six_descriptive_profiles_and_cache_stops_next_get(self):
        calls=[];fetch=fetcher(calls)
        def transport(url,**kwargs):
            self.assertEqual(kwargs,dict(day=DAY,media='archive',not_yet_published=True))
            return fetch(url)
        with patch.object(pilot,'_clock',return_value=NOW),patch.object(pilot,'ENTRY_OBSERVATION_HISTORY',None,create=True),patch.object(pilot,'get',side_effect=transport):
            ctx=context();self.assertIsNone(pilot.collect_entry_history(ctx,DAY))
            self.assertEqual(len(ctx['entry_history']['profiles']),6)
            self.assertEqual(ctx['entry_history']['profiles'][0]['sample_races'],3)
            self.assertFalse(ctx['forecast_inputs_used'])
            self.assertIsNone(pilot.collect_entry_history(context(),DAY))
            self.assertEqual(len(calls),2)
            with tempfile.TemporaryDirectory() as directory,patch.object(pilot,'OUTPUT',Path(directory)):
                out=pilot.stop('HISTORY_ONLY')
                self.assertEqual(out['entry_observation_history']['status'],'READY')

    def test_absent_context_wait_or_small_margin_does_not_request_history(self):
        with patch.object(pilot,'get') as get,patch.object(pilot,'_clock',return_value=NOW):
            self.assertIsNone(pilot.collect_entry_history(None,DAY))
            wait={'state':'RATE_LIMIT_WAIT','reason':'HTTP_RATE_LIMIT','retry_at':None}
            self.assertEqual(pilot.collect_entry_history(context(),DAY,paused=wait),wait)
            late=context();late['cutoff_at']=(NOW+pilot.MIN_TO_CUTOFF).isoformat()
            self.assertIsNone(pilot.collect_entry_history(late,DAY))
            get.assert_not_called()

    def test_worker_handoff_and_http_wait_keep_observed_context_and_pause(self):
        for error in (ValueError('WORKER_HANDOFF'),SourceWait('HTTP_RATE_LIMIT',state='RATE_LIMIT_WAIT')):
            with self.subTest(reason=str(error)),patch.object(pilot,'ENTRY_OBSERVATION_HISTORY',None,create=True),patch.object(pilot,'get',side_effect=error),patch.object(pilot,'_clock',return_value=NOW):
                ctx=context();out=pilot.collect_entry_history(ctx,DAY)
                self.assertEqual(out['reason'],str(error))
                self.assertEqual(ctx['beforeinfo']['status'],'PARSED')
                self.assertFalse(ctx['forecast_inputs_used'])

    def test_pending_exhibition_collects_history_after_pitreport(self):
        order=[];boats=[dict(lane=i,racer_registration_id=str(4000+i),entry_status='listed') for i in range(1,7)]
        with patch.object(pilot,'_clock',return_value=NOW),patch.object(pilot,'get',side_effect=[(b'program',AT,'a'*64),(b'preview',AT,'b'*64)]),patch.object(pilot,'parse_official_racelist',return_value=dict(race_id=RID,closed_at=CUTOFF,boats=boats)),patch.object(pilot,'motor_top2',return_value={}),patch.object(pilot,'capture_before_context',return_value=context()),patch.object(pilot,'parse_update',return_value=dict(status='PENDING',data=None)),patch.object(pilot,'collect_pitreport',side_effect=lambda *a,**k:order.append('pit')),patch.object(pilot,'collect_entry_history',side_effect=lambda *a,**k:order.append('history')):
            out=pilot.make_pair(DAY,dict(race_id=RID,cutoff_at=CUTOFF))
        self.assertEqual(order,['pit','history'])
        self.assertIsNone(out[1])

    def test_history_worker_handoff_preserves_ready_pair_after_odds_and_pit(self):
        from tests.test_observed_p1_connection import inputs
        base,extra,_=inputs()
        program=dict(race_id=RID,closed_at=CUTOFF,boats=[dict(lane=r['lane'],
            racer_registration_id=r['racer_id'],national_win_rate=r['national_win_rate'],
            entry_status='listed',local_win_rate=5.,average_st=.15) for r in base['boats']])
        preview=dict(status='AVAILABLE',data=dict(boats=[dict(lane=r['lane'],
            racer_registration_id=r['racer_id'],display_time=r['exhibition_time_seconds'],
            preview_st=.12,preview_st_status='OK') for r in base['boats']]))
        order=[]
        def transport(url,**kwargs):
            if '/racelist?' in url:return b'program',AT,'a'*64
            if '/beforeinfo?' in url:return b'preview',AT,'b'*64
            if '/odds3t?' in url:
                order.append('odds');raise pilot.SourceError('ODDS_UNAVAILABLE')
            order.append('history');raise ValueError('WORKER_HANDOFF')
        with patch.object(pilot,'_clock',return_value=NOW),patch.object(pilot,'get',side_effect=transport),patch.object(pilot,'parse_official_racelist',return_value=program),patch.object(pilot,'parse_update',return_value=preview),patch.object(pilot,'capture_before_context',return_value=context()),patch.object(pilot,'motor_top2',return_value={i:30+i for i in range(1,7)}),patch.object(pilot,'observed_timestamp',return_value=NOW.isoformat()),patch.object(pilot,'collect_pitreport',side_effect=lambda *a,**k:order.append('pit')),patch.object(pilot,'ENTRY_OBSERVATION_HISTORY',None),patch.object(pilot,'OBSERVED_HISTORY_CONTEXT',None),patch.dict('os.environ',{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true'}):
            result=pilot.make_pair(DAY,dict(race_id=RID,cutoff_at=CUTOFF))
        self.assertEqual(order,['odds','pit','history'])
        self.assertEqual(result[0]['source_wait']['state'],'WORKER_HANDOFF')
        self.assertEqual(len(result[1]['models']),2)
        self.assertIn('model_id',result[2])
        self.assertIn('suite',result[4])

    def test_unsupported_program_stats_still_collect_strict_roster_bound_context(self):
        from tests.test_boat_observation_context import sg_program,frame,before_table,starts,RACE_ID as race_id
        at=datetime.fromisoformat('2030-04-01T18:00:00+09:00')
        program=sg_program();preview=frame(before_table()+starts())
        order=[]
        with patch.object(pilot,'_clock',return_value=at),patch.object(pilot,'get',side_effect=[(program,at,hashlib.sha256(program).hexdigest()),(preview,at,hashlib.sha256(preview).hexdigest())]),patch.object(pilot,'supplemental_contexts',{}),patch.object(pilot,'collect_pitreport',side_effect=lambda *a,**k:order.append('pit')),patch.object(pilot,'collect_entry_history',side_effect=lambda *a,**k:order.append('history')),patch.object(pilot.model,'build_pair',side_effect=AssertionError('unsupported program must not forecast')):
            result=pilot.make_pair(date(2030,4,1),dict(race_id=race_id,cutoff_at='2030-04-01T20:30:00+09:00'))
            ctx=pilot.supplemental_contexts[race_id]
        self.assertEqual(result[0]['state'],'PROGRAM_STATS_UNSUPPORTED_CONTEXT_ONLY')
        self.assertEqual(result[1:],(None,None,None,None))
        self.assertEqual(order,['pit','history'])
        self.assertEqual(ctx['roster'][0],dict(lane=1,registration_number='4001'))
        self.assertEqual(ctx['beforeinfo']['roster_binding_status'],'VERIFIED')
        self.assertFalse(ctx['forecast_inputs_used'])

    def test_fresh_sg_schedule_discovery_routes_all_twelve_printed_races_to_context_only(self):
        from tests.test_boat_observation_context import sg_program
        table,tabs=sg_program().decode().split('<div class="tab3">',1)
        table=table.replace('<th class="is-thColor2"><a href="/owpc/pc/race/racelist?rno=1&amp;', '<th class=""><a href="/owpc/pc/race/racelist?rno=1&amp;',1)
        table=table.replace('<th class=""><a href="/owpc/pc/race/racelist?rno=12&amp;', '<th class="is-thColor2"><a href="/owpc/pc/race/racelist?rno=12&amp;',1)
        body=(table+'<div class="tab3">'+tabs.replace('rno=12&amp;','rno=1&amp;')).encode()
        at=datetime.fromisoformat('2030-04-01T20:18:00+09:00')
        seen=[]
        def candidate(day,race):
            seen.append(race['race_id'])
            return dict(race_id=race['race_id'],state='PROGRAM_STATS_UNSUPPORTED_CONTEXT_ONLY'),None,None,None,None
        with tempfile.TemporaryDirectory() as directory,patch.object(pilot,'OUTPUT',Path(directory)),patch.object(pilot,'_clock',return_value=at),patch.object(pilot,'official_schedule',return_value=(dict(active_venues=['12']),at,'a'*64,'https://www.boatrace.jp/owpc/pc/race/index?hd=20300401')),patch.object(pilot,'get',return_value=(body,at,hashlib.sha256(body).hexdigest())) as get,patch.object(pilot,'load_original_race_ids',return_value=frozenset()),patch.object(pilot,'make_pair',side_effect=candidate),patch.dict('os.environ',{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true','RACE_AI_EVENT_DAY':'2030-04-01'}):
            result=pilot.run()
        self.assertEqual(len(result['official_race_registry']),12)
        self.assertEqual(seen,[f'20300401-12-{n:02d}' for n in range(1,13)])
        self.assertEqual({r['cutoff_at'] for r in result['official_race_registry']},{'2030-04-01T20:30:00+09:00'})
        self.assertEqual(result['paired_forecasts'],[])
        self.assertEqual(get.call_count,1)
        self.assertTrue(any(row.get('state')=='VENUE_PROGRAM_STATS_UNSUPPORTED_CONTEXT_ONLY' for row in result['candidate_attempts']))

    def test_malformed_hydrated_cache_shape_cannot_abort_ready_forecast_run(self):
        snapshot=dict(official_day_source=dict(url='https://www.boatrace.jp/owpc/pc/race/index?hd=20261105',source_sha256='a'*64,captured_at=NOW.isoformat()),verified_active_venues=['17'],official_race_registry=[dict(race_id=RID,cutoff_at=(NOW+timedelta(minutes=12)).isoformat(),schedule_captured_at=NOW.isoformat(),source_sha256='b'*64)])
        status=dict(race_id=RID,state='AB_GENERATED_NOT_YET_EXTERNAL_FROZEN')
        with tempfile.TemporaryDirectory() as directory,patch.object(pilot,'OUTPUT',Path(directory)),patch.object(pilot,'_clock',return_value=NOW),patch.object(pilot,'ENTRY_OBSERVATION_HISTORY',[]),patch.object(pilot,'load_original_race_ids',return_value=frozenset()),patch.object(pilot,'make_pair',return_value=(status,{'race_id':RID},None,None,None)),patch.dict('os.environ',{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true','RACE_AI_EVENT_DAY':DAY.isoformat()}):
            result=pilot.run(schedule_snapshot=snapshot)
        self.assertEqual(result['paired_forecast_count'],1)
        self.assertIsNone(result['entry_observation_history'])

    def test_checkpoint_retains_verified_history_for_the_next_forecast_process(self):
        from race_ai.repeated_cycle import checkpoint
        cache=ready(self)
        previous=dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1',day_jst=DAY.isoformat(),excluded_repeats=[],index_entries=[])
        receipt={'id':9,'created_at':(NOW+timedelta(seconds=1)).isoformat(),'workflow_run':{'id':8},'digest':'sha256:'+'a'*64}
        with tempfile.TemporaryDirectory() as folder:
            state=checkpoint(Path(folder)/'continuity.json',previous,[],[],[receipt],p1_doc={'entry_observation_history':cache},p1_receipt=receipt)
        self.assertEqual(state['entry_observation_history'],cache)


class AuthenticatedHistoryRecoveryTests(unittest.TestCase):
    def documents(self, caches, *, with_forecasts=False):
        from race_ai import cycle_recovery as recovery
        records={};runs=[]
        for index,cache in enumerate(caches,10):
            doc=dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',day_jst=DAY.isoformat(),
                     observed_at=(NOW+timedelta(seconds=index)).isoformat(),paired_forecasts=[])
            if with_forecasts:doc=forecast_document(cache)
            elif cache is not None:doc['entry_observation_history']=cache
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w') as archive:archive.writestr('national.json',json.dumps(doc))
            raw=out.getvalue()
            meta=dict(id=100+index,name=f'boat-national-cutoff-{index}',expired=False,
                created_at=(NOW+timedelta(seconds=index)).isoformat(),
                digest='sha256:'+hashlib.sha256(raw).hexdigest(),
                workflow_run=dict(id=index,head_repository_id=1416489937))
            runs.append(dict(id=index,created_at=meta['created_at'],head_branch=recovery.BRANCH,event='push',status='completed'))
            records[f'actions/runs/{index}/artifacts?per_page=100']=json.dumps(dict(total_count=1,artifacts=[meta])).encode()
            records[f'actions/artifacts/{meta["id"]}']=json.dumps(meta).encode()
            records[f'actions/artifacts/{meta["id"]}/zip']=raw
        records[f'actions/workflows/{recovery.WORKFLOW}/runs?per_page=100&page=1']=json.dumps(dict(workflow_runs=runs)).encode()
        return records

    def test_recovery_selects_latest_valid_authenticated_same_day_cache_and_keeps_legacy(self):
        from race_ai import cycle_recovery as recovery
        early=ready(self);latest=deepcopy(early);latest['checked_at']=(NOW+timedelta(seconds=1)).isoformat()
        records=self.documents([early,latest,None])
        with tempfile.TemporaryDirectory() as folder:
            state=recovery.recover(lambda path:records[path],DAY.isoformat(),current_run=20,out=Path(folder),clock=lambda:NOW+timedelta(minutes=1))
        self.assertEqual(state.get('entry_observation_history'),latest)
        self.assertEqual(state['rows'],[])

    def test_recovery_rejects_only_bad_optional_cache_and_preserves_verified_originals(self):
        from race_ai import cycle_recovery as recovery
        good=ready(self);bad=deepcopy(good);bad['history']['source_proofs']['B']['source_sha256']='0'*64
        records=self.documents([good,bad],with_forecasts=True)
        with tempfile.TemporaryDirectory() as folder:
            state=recovery.recover(lambda path:records[path],DAY.isoformat(),current_run=20,out=Path(folder),clock=lambda:NOW+timedelta(minutes=1))
        self.assertEqual(len(state['rows']),3)
        self.assertEqual(len(state['index_entries']),2)
        self.assertEqual(state['entry_observation_history'],good)
        self.assertEqual(state['entry_observation_history_rejections'],1)
        self.assertEqual(state['entry_observation_history_rejection_reason'],'ENTRY_HISTORY_CACHE_REJECTED')

    def test_checkpoint_bad_optional_cache_keeps_verified_p1_rows_and_index(self):
        from race_ai.repeated_cycle import checkpoint
        from race_ai.frozen_day_cycle import read_p1
        from tests.test_observed_p1_connection import archive
        good=ready(self);bad=deepcopy(good);bad['history']['source_proofs']['B']['source_sha256']='0'*64
        raw,receipt=archive(forecast_document(bad),saved=(NOW+timedelta(seconds=1)).isoformat())
        doc,rows=read_p1(raw,receipt)
        previous=dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1',day_jst=DAY.isoformat(),
            excluded_repeats=[],index_entries=[],entry_observation_history=good)
        with tempfile.TemporaryDirectory() as directory:
            state=checkpoint(Path(directory)/'state.json',previous,rows,[],[receipt],p1_doc=doc,p1_receipt=receipt)
        self.assertEqual({row['model_id']:row for row in state['rows']},{row['model_id']:row for row in rows})
        self.assertEqual(len(state['index_entries']),1)
        self.assertEqual(state['entry_observation_history'],good)
        self.assertEqual(state['entry_observation_history_rejections'],1)
        self.assertEqual(state['entry_observation_history_rejection_reason'],'ENTRY_HISTORY_CACHE_REJECTED')

    def test_forecast_process_hydrates_cache_before_running_existing_predictor(self):
        from scripts import github_existing_cycle as runner
        cache=ready(self)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'cycle_recovery_output').mkdir();output=root/'national-output';output.mkdir()
            index=root/'index.json';index.write_text(json.dumps(dict(entries=[])))
            state=dict(index_entries=[],entry_observation_history=cache)
            def run(**kwargs):return dict(entry_observation_history=pilot.ENTRY_OBSERVATION_HISTORY)
            with patch.object(runner,'ROOT',root),patch.object(runner,'load_state',return_value=state),patch.object(pilot,'FROZEN_INDEX',index),patch.object(pilot,'OUTPUT',output),patch.object(pilot,'ENTRY_OBSERVATION_HISTORY',None),patch.object(pilot,'run',side_effect=run):
                runner.forecast(DAY.isoformat())
            saved=json.loads((output/'national.json').read_text())
        self.assertEqual(saved['entry_observation_history'],cache)


if __name__=='__main__':unittest.main()
