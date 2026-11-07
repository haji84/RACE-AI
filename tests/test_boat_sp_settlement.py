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
        late=deepcopy(row);late['comparison_predictions']=[dict(persisted_at='2026-11-07T10:02:00+09:00')]
        out=Feed.update_view(dict(view,records=[late]),[],captures=[(raw,meta)],synced_at=NOW.isoformat());self.assertEqual(out['records'][0]['result']['status'],'unsupported')
