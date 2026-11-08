"""Real local encrypted feed publication, with invented forecasts/results only."""
from copy import deepcopy
from unittest.mock import patch
from datetime import timedelta
from pathlib import Path
import json,subprocess,tempfile,unittest
from race_ai import saved_view_feed as F
from race_ai.racer_daily_handoff import _DailyFilteredFetch
from race_ai.racer_intraday import IntradayState
from race_ai.boat_sp_settlement import parse_settlement,settlement_digest
from race_ai.racer_daily import sha,wire
from tests.intraday_fixture import packet
from tests.test_boat_sp_settlement import document,no_contest_document
from tests.test_racer_daily import NOW
try:
    from race_ai.racer_result_bridge import SavedResultBridge
except ImportError:SavedResultBridge=None

class FixtureFeed(_DailyFilteredFetch,F.FeedRepository):
    def _check_remote(self):self.fetch_url=self.push_url=self._run(['remote','get-url','origin']).decode().strip()

def saved_view(days=('2026-11-07',)):
    rows=[]
    for day in days:
        rid=day.replace('-','')+'-01-01';p=dict(model_id='INVENTED_TEST_ONLY',model_version='1',stage='P0',persisted_at=day+'T00:00:00Z',as_of=day+'T00:00:00Z',cutoff_at=day+'T10:00:00+09:00',ordered_top8=[[1,2,3],[1,3,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1],[1,2,4],[1,3,4]])
        rows.append(dict(race_id=rid,sport='boat',scope='research',race_no=1,event_date_jst=day,cutoff_at=p['cutoff_at'],saved_cutoff_variants=[p['cutoff_at']],prediction=p,comparison_predictions=[],participants=[dict(number=n,registration_no=str(4000+n)) for n in range(1,7)],result=None,result_observations=[],result_observation_rejections=[],result_revisions=[],missing_reasons=[]))
    return dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1',dataset_status='REAL_REPORTED',records=rows)

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(SavedResultBridge),'result collection must update the actual existing encrypted feed independently')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name);self.repo=root/'repo';self.repo.mkdir();remote=root/'remote.git'
        for cmd in (['git','init','--bare',str(remote)],['git','-C',str(remote),'config','uploadpack.allowFilter','true'],['git','init',str(self.repo)],['git','-C',str(self.repo),'remote','add','origin',remote.as_uri()]):subprocess.run(cmd,check=True,capture_output=True)
        self.git=FixtureFeed(self.repo);self.view=saved_view();self.boot=dict(key=b'x'*32,view_id='a'*64,cipher_sha256='c'*64,forecast_sha256=F.originals_sha(self.view),pages_commit='d'*40)
        self.seed(self.view)
    def seed(self,view):
        self.boot['forecast_sha256']=F.originals_sha(view);raw=F.encrypt_view(view,self.boot['key'],view_id=self.boot['view_id'],source_sha='c'*64,generation=1,previous='d'*64);h=json.loads(raw)['header'];digest=sha(raw)
        parent=self.git.head();commit=self.git.commit({'latest.json':(wire(dict(header=h,cipher_sha256=digest))+'\n').encode(),'views/'+digest+'.json':raw},parent);self.git.push(commit,parent)
    def bridge(self):return SavedResultBridge(self.repo,now=NOW,transport=self.git,bootstrap=self.boot)
    def capture(self,state,day='20261107',price='1250',at=NOW):
        d=document(day=day);d['maindata']['infolist3t'][0]['dividend']=price;raw,r=packet(d,captured=at.isoformat());out=parse_settlement(raw,r,now=at);p=state.remember('RESULT',raw,r);p.update(settlement_sha256=settlement_digest(out),settlement_status=out['status']);state.control.setdefault('settlement_captures',{})[out['race_id']]=p
    def test_live_beforeinfo_reaches_the_encrypted_feed_when_no_result_has_arrived(self):
        from tests.test_racer_beforeinfo import preview_view,html,AT,URL
        from race_ai.racer_beforeinfo import collect_beforeinfo
        self.view=preview_view();self.seed(self.view);pin=F.originals_sha(self.view);inventory=F.forecast_inventory(self.view)
        state=IntradayState()
        collect_beforeinfo(state,self.view['records'],now=AT,fetch=lambda u:(html(),AT.isoformat()),max_requests=4)
        bridge=SavedResultBridge(self.repo,now=AT,transport=self.git,bootstrap=self.boot)
        report=bridge.publish(state,now=AT);self.assertEqual(report['changed_races'],1)
        _,_,_,readback=F.current_view(self.git,self.boot)
        self.assertEqual(readback['records'][0]['live_boat_observation']['context']['beforeinfo']['participants'][0]['display_time'],6.72)
        self.assertIsNone(readback['records'][0]['result']);self.assertEqual(readback['records'][0]['result_observations'],[])
        self.assertEqual(F.originals_sha(readback),pin);self.assertEqual(F.forecast_inventory(readback),inventory)
        parent=self.git.head();report=bridge.publish(state,now=AT+timedelta(minutes=1))
        self.assertEqual(report['changed_races'],0);self.assertEqual(self.git.head(),parent)
    def test_confirmed_result_reaches_saved_forecast_without_intake_and_quiet_replay_is_identical(self):
        bridge=self.bridge();self.assertEqual(len(bridge.targets()),1);state=IntradayState();self.capture(state);pin=F.forecast_inventory(self.view)
        report=bridge.publish(state,now=NOW);self.assertEqual(report['confirmed'],1);self.assertEqual(report['pending'],0)
        parent,_,generation,view=F.current_view(self.git,self.boot);self.assertEqual(view['records'][0]['result']['winning_combinations'],[[1,2,3]]);self.assertEqual(F.forecast_inventory(view),pin)
        again=self.bridge().publish(state,now=NOW+timedelta(minutes=5));self.assertEqual(again['changed_races'],0);self.assertEqual(self.git.head(),parent)
        self.capture(state,price='1500',at=NOW+timedelta(minutes=10));self.bridge().publish(state,now=NOW+timedelta(minutes=10));_,_,new_generation,new=F.current_view(self.git,self.boot);self.assertEqual(new_generation,generation+1);self.assertEqual(new['records'][0]['result']['payout_yen_per_100'],1500)
    def test_repaired_parser_replays_retained_bytes_without_replacing_the_original_observation(self):
        raw,receipt=packet(no_contest_document(),captured=NOW.isoformat())
        with patch.object(F,'parse_capture',side_effect=ValueError('RESULT_WINNER_INVALID')):
            old=F.update_view(self.view,[],captures=[(raw,receipt)],synced_at=NOW.isoformat())
        self.assertEqual(old['records'][0]['result']['status'],'unsupported');self.seed(old)
        parent,previous,_,retained=F.current_view(self.git,self.boot)
        old_cipher=self.git.read(parent,'views/'+previous+'.json',F.MAX_WIRE)
        observations=deepcopy(retained['records'][0]['result_observations']);revisions=deepcopy(retained['records'][0]['result_revisions'])
        state=IntradayState();parsed=parse_settlement(raw,receipt,now=NOW);pointer=state.remember('RESULT',raw,receipt)
        pointer.update(settlement_sha256=settlement_digest(parsed),settlement_status=parsed['status'])
        state.control['settlement_captures']={parsed['race_id']:pointer}
        controls=deepcopy(state.control);sources=deepcopy(state.new_captures)
        from scripts import racer_intraday_refresh as R
        bridge=self.bridge()
        with patch.object(R,'load_intraday',return_value=dict(previous={},state=state)),\
             patch.object(R,'OfficialClient',side_effect=AssertionError('no source')),\
             patch.object(R,'load_daily',side_effect=AssertionError('no base state')),\
             patch.object(R,'save_intraday',side_effect=AssertionError('no state writes')),\
             patch.object(R,'publish_daily_catalogue',side_effect=AssertionError('no public writes')),\
             patch.object(state,'advance',side_effect=AssertionError('no collection')),\
             patch.object(bridge,'prepare',side_effect=AssertionError('no control mutation')):
            report=R.replay_retained_results(self.repo,now=NOW+timedelta(minutes=1),bridge=bridge)
        self.assertEqual(report['result_sync']['confirmed'],1);self.assertEqual(report['changed_races'],1)
        self.assertTrue(report['readback_verified']);self.assertTrue(report['original_observations_preserved'])
        self.assertEqual(report['source_requests'],0);self.assertFalse(report['source_state_saved'])
        head,_,_,out=F.current_view(self.git,self.boot);row=out['records'][0]
        self.assertEqual(row['result']['status'],'void');self.assertEqual(row['result']['observed_at'],receipt['captured_at'])
        self.assertEqual(row['result']['source_sha256'],receipt['source_sha256'])
        self.assertEqual(row['result_observations'],observations);self.assertEqual(row['result_revisions'],revisions)
        self.assertEqual(F.originals_sha(out),F.originals_sha(retained));self.assertEqual(state.control,controls);self.assertEqual(state.new_captures,sources)
        self.assertEqual(self.git.read(parent,'views/'+previous+'.json',F.MAX_WIRE),old_cipher)
        self.assertEqual(self.bridge().publish(state,now=NOW+timedelta(minutes=2))['changed_races'],0);self.assertEqual(self.git.head(),head)
    def test_same_clock_with_a_different_hash_or_url_cannot_be_repaired_as_the_same_capture(self):
        raw,receipt=packet(no_contest_document(),captured=NOW.isoformat())
        state=IntradayState();parsed=parse_settlement(raw,receipt,now=NOW);pointer=state.remember('RESULT',raw,receipt)
        pointer.update(settlement_sha256=settlement_digest(parsed),settlement_status=parsed['status'])
        state.control['settlement_captures']={parsed['race_id']:pointer}
        with patch.object(F,'parse_capture',side_effect=ValueError('RESULT_WINNER_INVALID')):
            old=F.update_view(self.view,[],captures=[(raw,receipt)],synced_at=NOW.isoformat())
        for field,value in [('source_sha256','f'*64),('source_url',receipt['source_url']+'&foreign=1')]:
            with self.subTest(field=field):
                wrong=deepcopy(old);wrong['records'][0]['result_observations'][0][field]=value;self.seed(wrong);head=self.git.head()
                with self.assertRaisesRegex(ValueError,'RESULT_CAPTURE_CONFLICT'):
                    self.bridge().publish(state,now=NOW+timedelta(minutes=1))
                self.assertEqual(self.git.head(),head)
    def test_a_foreign_writer_is_read_before_result_application_and_originals_stay_unchanged(self):
        bridge=self.bridge();state=IntradayState();self.capture(state);p,old,g,view=F.current_view(self.git,self.boot);other=deepcopy(view);other['safe_display_note']='OTHER_WRITER';F.publish_view(self.git,self.boot,other,parent=p,previous=old,generation=g)
        bridge.publish(state,now=NOW);_,_,_,out=F.current_view(self.git,self.boot);self.assertEqual(out['safe_display_note'],'OTHER_WRITER');self.assertEqual(out['records'][0]['prediction'],self.view['records'][0]['prediction'])
    def test_month_boundary_history_updates_both_latest_saved_dates(self):
        view=saved_view(('2026-10-31','2026-11-01'));self.seed(view);p,old,g,flat=F.current_view(self.git,self.boot);F.publish_view(self.git,self.boot,flat,parent=p,previous=old,generation=g,history=True)
        bridge=self.bridge();self.assertEqual({v['race_id'][:8] for v in bridge.targets()},{'20261031','20261101'})
        state=IntradayState();self.capture(state,'20261031');self.capture(state,'20261101');r=bridge.publish(state,now=NOW);self.assertEqual(r['confirmed'],2)
        for day in ('2026-10-31','2026-11-01'):
            _,_,_,out=F.current_view(self.git,self.boot,day=day);self.assertEqual(out['records'][0]['result']['status'],'final')
    def test_lost_compare_and_swap_leaves_sources_replayable(self):
        from unittest.mock import patch
        bridge=self.bridge();state=IntradayState();self.capture(state);original=self.git.head()
        with patch.object(self.git,'push',side_effect=ValueError('FEED_CONCURRENT_UPDATE')):
            with self.assertRaises(ValueError):bridge.publish(state,now=NOW)
        self.assertEqual(self.git.head(),original);self.assertEqual(len(state.control['settlement_captures']),1)
        self.assertEqual(self.bridge().publish(state,now=NOW+timedelta(minutes=5))['confirmed'],1)
    def test_only_verified_old_publications_can_leave_the_active_capture_index(self):
        bridge=self.bridge();state=IntradayState();self.capture(state);bridge.publish(state,now=NOW)
        self.assertTrue(callable(getattr(bridge,'prepare',None)),'verified feed acknowledgement must bound the private capture index')
        self.bridge().prepare(state);self.capture(state,day='20261105')
        p,old,g,view=F.current_view(self.git,self.boot);new=deepcopy(view);new['records'].extend(saved_view(('2026-11-08','2026-11-09'))['records']);new['forecast_base_sha256']=self.boot['forecast_sha256'];F.publish_view(self.git,self.boot,new,parent=p,previous=old,generation=g)
        later=SavedResultBridge(self.repo,now=NOW+timedelta(days=2),transport=self.git,bootstrap=self.boot);later.prepare(state)
        self.assertNotIn('20261107-01-01',state.control['settlement_captures']);self.assertIn('20261105-01-01',state.control['settlement_captures'],'unpublished evidence must never be pruned')
    def test_old_pending_day_is_kept_and_later_result_is_reconciled_without_source_get(self):
        view=saved_view(('2026-11-04','2026-11-07','2026-11-08'));self.seed(view)
        at=NOW+timedelta(days=1);state=IntradayState()
        first=SavedResultBridge(self.repo,now=at,transport=self.git,bootstrap=self.boot)
        first.prepare(state)
        self.assertIn('20261104-01-01',[t['race_id'] for t in first.targets()])
        self.assertEqual(first.publish(state,now=at)['races'],2)
        self.assertEqual(first.ledger_summary['older_unresolved'],1)
        self.capture(state,day='20261104',at=at)
        later=SavedResultBridge(self.repo,now=at+timedelta(minutes=5),transport=self.git,bootstrap=self.boot)
        later.prepare(state);later.publish(state,now=at+timedelta(minutes=5))
        _,_,_,out=F.current_view(self.git,self.boot)
        self.assertEqual([r for r in out['records'] if r['race_id']=='20261104-01-01'][0]['result']['status'],'final')
        final=SavedResultBridge(self.repo,now=at+timedelta(minutes=10),transport=self.git,bootstrap=self.boot)
        final.prepare(state)
        self.assertNotIn('2026-11-04',state.control['result_due_ledger']['pending_days'])
        self.assertEqual(final.publish(state,now=at+timedelta(minutes=10))['races'],2)

    def test_restored_identical_bytes_with_a_new_receipt_do_not_block_result_publication(self):
        from tests.test_racer_intraday_handoff import FixtureGit
        from race_ai.boat_pdca_github_handoff import TRANSFER_REF
        from race_ai.racer_intraday_handoff import load_intraday,save_intraday
        from race_ai.racer_intraday_source import parse_result
        from race_ai.racer_daily import DailyStore
        git=FixtureGit(self.repo,ref=TRANSFER_REF);root=git.commit({'state/other.enc':b'UNCHANGED_OTHER'},None);git.push(root,None);key=bytes(range(32));base=DailyStore(clock=lambda:NOW+timedelta(minutes=10));self.addCleanup(base.close)
        first=load_intraday(self.repo,initialize=True,key=key,transport=git,now=NOW);state=first['state'];self.capture(state);doc=document();doc['maindata']['infolist3t'][0]['dividend']='1250';raw,receipt=packet(doc,captured=NOW.isoformat());facts=parse_result(raw,receipt,now=NOW);rid=facts['race_id'];old=state.remember('RESULT',raw,receipt);old.update(fact_sha256=facts['fact_sha256'],statistics_sha256=facts['statistics_sha256']);state.control['results'][rid]=old
        save_intraday(first,catalogue_sha256='a'*64,now=NOW,key=key)
        later=NOW+timedelta(minutes=5);second=load_intraday(self.repo,key=key,transport=git,now=later);second['state'].extra_rows(base,now=later);self.capture(second['state'],at=later);save_intraday(second,catalogue_sha256='a'*64,now=later,key=key)
        replay=load_intraday(self.repo,key=key,transport=git,now=later);state=replay['state'];state.extra_rows(base,now=later)
        self.assertEqual(state.control['results'][rid]['capture_id'],state.control['settlement_captures'][rid]['capture_id'],'immutable capture IDs remain compatible')
        report=self.bridge().publish(state,now=later);self.assertEqual(report['confirmed'],1);feed_head=self.git.head()
        self.bridge().prepare(state);save_intraday(replay,catalogue_sha256='a'*64,now=later,key=key)
        quiet=load_intraday(self.repo,key=key,transport=git,now=later+timedelta(minutes=5));quiet['state'].extra_rows(base,now=later+timedelta(minutes=5));report=self.bridge().publish(quiet['state'],now=later+timedelta(minutes=5));self.assertEqual(report['changed_races'],0);self.assertEqual(self.git.head(),feed_head)
