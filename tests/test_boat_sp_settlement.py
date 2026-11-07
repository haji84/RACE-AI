"""Invented SP results verify outcome/payout integrity, never actual accuracy."""
from copy import deepcopy
from datetime import timedelta
import unittest
from tests.intraday_fixture import result_document,packet
from tests.test_racer_daily import NOW
from race_ai import saved_result_sync as Sync,saved_view_feed as Feed
try:
    from race_ai.boat_sp_settlement import parse_settlement,settlement_digest
except ImportError:parse_settlement=settlement_digest=None

def document(**kwargs):
    d=result_document(**kwargs)
    if d['maindata'] is not None:d['maindata'].update(infolist3t=[dict(winno='1-2-3',dividend='&yen;1,250',pop='1')],returnlist=[])
    return d

def no_contest_document():
    d=document();body=d['maindata'];body['infolist3t']=[dict(winno='不成立',dividend='100',pop='')]
    body['returnlist']=['1','2','3','4']
    for row in body['teiinfolist']:
        n=int(row['teino']);row['chk']='F' if n<=4 else str(n-4)
    for row in body['stinfolist']:
        if int(row['teino'])<=4:row['st']='F.01'
    return d

class SettlementTests(unittest.TestCase):
    def parse(self,doc=None):
        self.assertTrue(callable(parse_settlement),'SP confirmed results need a strict settlement adapter')
        raw,meta=packet(document() if doc is None else doc,captured=NOW.isoformat());return parse_settlement(raw,meta,now=NOW)
    def test_explicit_roster_and_trifecta_price_become_a_bound_observation(self):
        o=self.parse();self.assertEqual(o['status'],'AVAILABLE');self.assertTrue(o['body_identity_verified']);self.assertEqual(o['data']['top3'],[1,2,3]);self.assertEqual(o['data']['payouts'][0]['payout_per_100_yen'],1250);self.assertEqual(o['data']['results'][0]['racer_registration_id'],'4001')
        raw,meta=packet(document(),captured=NOW.isoformat());self.assertEqual(Sync.parse_capture(raw,meta),o)
    def test_missing_finish_or_payout_stays_pending_and_never_fabricates_a_miss(self):
        self.assertEqual(self.parse(document(pending=True))['status'],'PENDING')
        d=document();d['maindata']['infolist3t']=[];self.assertEqual(self.parse(d)['status'],'PENDING')

    def test_explicit_no_contest_refunds_every_trifecta_without_a_winning_ticket(self):
        out=self.parse(no_contest_document())
        self.assertEqual(out['status'],'AVAILABLE');self.assertEqual(out['data']['status'],'no_contest')
        self.assertEqual(out['data']['confirmed_scope'],'TRIFECTA_ONLY')
        self.assertEqual(out['data']['payouts'],[]);self.assertIsNone(out['data']['top3'])
        self.assertEqual(out['data']['refund_boats'],[1,2,3,4]);self.assertEqual(len(out['data']['results']),6)

    def test_no_contest_requires_100_yen_and_all_trifecta_coverage(self):
        for mutate in [lambda d:d['maindata']['infolist3t'][0].update(dividend='70'),
                       lambda d:d['maindata'].update(returnlist=['1','2','3']),
                       lambda d:d['maindata']['infolist3t'][0].update(winno='特払')]:
            d=no_contest_document();mutate(d)
            with self.subTest(),self.assertRaises(ValueError):self.parse(d)

    def test_no_contest_cannot_refund_numeric_or_nonrefundable_finishers(self):
        d=document();d['maindata'].update(infolist3t=[dict(winno='不成立',dividend='100')],returnlist=['1','2','3','4'])
        with self.assertRaises(ValueError):self.parse(d)
        d=no_contest_document()
        d['maindata']['teiinfolist'][0]['chk']='転'
        next(r for r in d['maindata']['stinfolist'] if r['teino']=='1')['st']='.10'
        with self.assertRaises(ValueError):self.parse(d)

    def test_no_contest_projection_refunds_the_1000_yen_plan_without_a_hit_or_miss(self):
        import json,subprocess
        from pathlib import Path
        top=[[1,2,3],[1,2,4],[1,3,2],[1,3,4],[2,1,3],[2,1,4],[2,3,1],[2,3,4]]
        p=dict(model_id='fixture-one',model_version='fixture-v1',stage='P0',variant='HISTORY_BASELINE',
               cutoff_at='2026-11-07T01:00:00Z',as_of='2026-11-07T00:00:00Z',
               generated_at='2026-11-07T00:00:01Z',persisted_at='2026-11-07T00:00:02Z',ordered_top8=top)
        peer={**deepcopy(p),'model_id':'fixture-two'}
        row=dict(race_id='20261107-01-01',sport='boat',scope='research',event_date_jst='2026-11-07',
                 cutoff_at=p['cutoff_at'],saved_cutoff_variants=[p['cutoff_at']],prediction=p,comparison_predictions=[peer],
                 participants=[dict(number=n,registration_no=str(4000+n)) for n in range(1,7)],
                 result=None,result_observations=[],result_revisions=[],missing_reasons=[])
        view=dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1',records=[row]);original=Feed.originals_sha(view)
        raw,receipt=packet(no_contest_document(),captured=NOW.isoformat())
        updated=Feed.update_view(view,[],captures=[(raw,receipt)],synced_at=NOW.isoformat())
        self.assertEqual(updated['records'][0]['result']['status'],'void');self.assertEqual(Feed.originals_sha(updated),original)
        group=dict(scope='research',sport='boat',model_id=p['model_id'],model_version=p['model_version'],stage='P0',variant=p['variant'])
        code="""const assert=require('node:assert/strict'),P=require('./web/saved-performance.js');let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>{const d=JSON.parse(s),stats=P.summarize(d.records,d.group),cash=P.simulate(d.records,d.group,10000,{raceBudget:1000});assert.equal(stats.void,1);assert.equal(stats.hits,0);assert.equal(stats.misses,0);assert.equal(cash.spent,1000);assert.equal(cash.refund,1000);assert.equal(cash.net,0);assert.equal(cash.balance,10000);});"""
        result=subprocess.run(['node','-e',code],cwd=Path(__file__).resolve().parents[1],input=json.dumps(dict(records=updated['records'],group=group)),text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
    def test_refund_and_dead_heat_keep_every_winning_combination(self):
        d=document();d['maindata']['teiinfolist'][-1]['chk']='欠';d['maindata']['stinfolist'][0].update(csdisp='0',st='');d['maindata']['returnlist']=['6']
        self.assertEqual(self.parse(d)['data']['refund_boats'],[6])
        d=document();d['maindata']['teiinfolist'][1]['chk']='1';d['maindata']['teiinfolist'][2]['chk']='3';d['maindata']['infolist3t']=[dict(winno='1-2-3',dividend='1250円'),dict(winno='2-1-3',dividend='1500円')]
        o=self.parse(d);self.assertTrue(o['data']['dead_heat']);self.assertEqual(len(o['data']['payouts']),2)
    def test_explicit_cancellation_does_not_create_a_race_start(self):
        d=document();d['maindata'].update(rstop=1,teiinfolist=[],stinfolist=[],infolist3t=[])
        self.assertEqual(self.parse(d)['data']['status'],'cancelled')
    def test_wrong_winner_partial_refund_special_payout_or_identity_is_rejected(self):
        for mutate in [lambda d:d['maindata']['infolist3t'][0].update(winno='3-2-1'),lambda d:d['maindata'].update(returnlist=['1']),lambda d:d['maindata']['infolist3t'][0].update(winno='特払'),lambda d:d['maindata']['teiinfolist'][1].update(registno='4001'),lambda d:d['maindata']['teiinfolist'][-1].update(chk='F')]:
            d=document();mutate(d)
            with self.subTest(),self.assertRaises(ValueError):self.parse(d)
    def test_captured_clock_is_not_result_identity_but_payout_and_refunds_are(self):
        o=self.parse();later=deepcopy(o);later['captured_at']=(NOW+timedelta(minutes=5)).isoformat();self.assertEqual(settlement_digest(o),settlement_digest(later))
        for change in ('payout','refund','roster'):
            revised=deepcopy(o)
            if change=='payout':revised['data']['payouts'][0]['payout_per_100_yen']=1500
            elif change=='refund':revised['data']['refund_boats']=[6]
            else:revised['data']['results'][0]['racer_registration_id']='5001'
            self.assertNotEqual(settlement_digest(o),settlement_digest(revised))
    def test_future_capture_or_wrong_url_cannot_become_an_outcome(self):
        self.assertTrue(callable(parse_settlement))
        raw,meta=packet(document(),captured=(NOW+timedelta(minutes=1)).isoformat())
        with self.assertRaises(ValueError):parse_settlement(raw,meta,now=NOW)
        raw,meta=packet(document(),captured=NOW.isoformat());meta['source_url']=meta['source_url'].replace('rno=1','rno=2')
        with self.assertRaises(ValueError):parse_settlement(raw,meta,now=NOW)
    def test_raw_bound_schedule_change_can_display_without_changing_original_clock(self):
        raw,meta=packet(document(),captured=NOW.isoformat());rid='20261107-01-01';p=dict(persisted_at='2026-11-07T00:00:00Z')
        row=dict(race_id=rid,sport='boat',event_date_jst='2026-11-07',cutoff_at='2026-11-07T10:05:00+09:00',saved_cutoff_variants=['2026-11-07T10:05:00+09:00'],participants=[dict(number=n,registration_no=str(4000+n)) for n in range(1,7)],prediction=p,comparison_predictions=[],result=None,result_observations=[],result_revisions=[],missing_reasons=[])
        view=dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1',records=[row]);pin=Feed.originals_sha(view)
        out=Feed.update_view(view,[],captures=[(raw,meta)],synced_at=NOW.isoformat());r=out['records'][0]
        self.assertIsNotNone(r['result']);self.assertEqual(r['result']['status'],'final');self.assertFalse(r['result']['cutoff_reference']['formal_eligible']);self.assertEqual(r['cutoff_at'],row['cutoff_at']);self.assertEqual(Feed.originals_sha(out),pin)
        late=deepcopy(row);late['prediction']['persisted_at']='2026-11-07T10:02:00+09:00'
        out=Feed.update_view(dict(view,records=[late]),[],captures=[(raw,meta)],synced_at=NOW.isoformat());self.assertEqual(out['records'][0]['result']['status'],'unsupported')
    def test_saved_native_projection_and_SP_schedule_reference_reach_the_browser_parser(self):
        import json,subprocess,tempfile
        from pathlib import Path
        from race_ai.racer_daily import clock,JST
        from race_ai.boat_pdca_state import PdcaState
        from race_ai.boat_pdca_projection import project_pdca
        from tests.test_boat_pdca_github_handoff import invented_research_state
        with tempfile.TemporaryDirectory() as folder:
            path,_=invented_research_state(Path(folder));state=PdcaState(path)
            try:view=project_pdca(state)
            finally:state.close()
            row=view['records'][0];rid=row['race_id'];doc=document(day=rid[:8],venue=rid[9:11],number=int(rid[-2:]));shifted=clock(row['cutoff_at'])+timedelta(minutes=5);doc['raceheader']['rlinklist'][int(rid[-2:])-1]['deadline']=shifted.astimezone(JST).strftime('%H:%M')
            for entry,person in zip(doc['maindata']['teiinfolist'],row['participants']):entry['registno']=person['registration_no']
            at=max([shifted,*[clock(o['captured_at']) for o in row['result_observations']]])+timedelta(minutes=5);raw,meta=packet(doc,captured=at.isoformat());updated=Feed.update_view(view,[],captures=[(raw,meta)],synced_at=at.isoformat())
            self.assertEqual(updated['records'][0]['result']['status'],'final');self.assertFalse(updated['records'][0]['result']['cutoff_reference']['formal_eligible'])
            code="let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>{const d=require('./web/product-data.js').parse(JSON.parse(s));if(d.records[0].result.status!=='final')process.exit(2);});"
            result=subprocess.run(['node','-e',code],cwd=Path(__file__).resolve().parents[1],input=json.dumps(updated),text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
        late=deepcopy(row);late['comparison_predictions']=[dict(persisted_at='2026-11-07T10:02:00+09:00')]
        out=Feed.update_view(dict(view,records=[late]),[],captures=[(raw,meta)],synced_at=NOW.isoformat());self.assertEqual(out['records'][0]['result']['status'],'unsupported')
