"""No network: orchestration regressions, not real-race performance."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from scripts.keirin_cloud_owner_inputs import collect_owner_inputs, SourceSession

NOW = datetime.fromisoformat('2030-01-15T09:00:00+09:00')

def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()

def card(root, rid='203001151201', cutoff='2030-01-15T10:00:00+09:00', source=None, captured=None):
    obj = {'race_id':rid, 'source_url':source or 'https://www.winticket.jp/keirin/aomori/racecard/2030011512/1/1',
           'source_capture_at_utc':captured or NOW.isoformat(), 'source_published_cutoff_at_utc':cutoff,
           'riders':[{'car_number':x} for x in range(1,8)]}
    body=raw(obj); folder=Path(root)/'winticket_racecard_partial'; folder.mkdir(exist_ok=True)
    (folder/(sha256(body).hexdigest()+'.json')).write_bytes(body)
    return obj

class OwnerInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.clock=lambda:NOW
        self.network=[]; self.probed=[]
    def capture(self, root, **kwargs):
        card(root)
        return {'source_day_schedule_race_count':78,
                'future_7_or_9_source_linked_in_window':1,
                'selected_in_this_cycle':1, 'private_partial_racecards_staged':1,
                'private_full_odds_races_staged':1}
    def probe(self, **kwargs):
        self.probed.append(kwargs['race_id'])
        self.assertTrue(Path(kwargs['private_evidence_dir']).is_dir())
        return {'race_id':kwargs['race_id'], 'required_model_slots':93,
                'observed_or_derived_model_A_slots':23, 'remaining_model_A_slots':70,
                'observed_or_derived_model_B_slots':26, 'remaining_model_B_slots':67,
                'existing_private_partial_input_staged':True,
                'private_candidate_replay_verified':True,
                'full_model_input_admitted':False,
                'actual_four_model_forecast_saved':False,
                'private_rider_name':'must never leave private function',
                'matched_prior_event_counts':[3,5,7]}
    def invoke(self, **kw):
        return collect_owner_inputs(self.root, owner_auto_confirmed=True,
            capture=kw.pop('capture',self.capture), probe=kw.pop('probe',self.probe),
            fetch=lambda url:self.network.append(url) or b'ordinary page',
            clock=self.clock, monotonic=lambda:0.0, **kw)
    def test_uses_existing_capture_and_history_without_promoting_partial_data(self):
        r=self.invoke()
        self.assertEqual(self.probed,['203001151201'])
        self.assertEqual(r['source_day_schedule_race_count'],78)
        self.assertEqual(r['races'][0]['remaining_model_A_slots'],70)
        self.assertEqual(r['races'][0]['remaining_model_B_slots'],67)
        self.assertEqual(r['new_pre_race_inputs'],0)
        self.assertFalse(r['actual_four_model_forecast_saved'])
        self.assertFalse(r['provider_machine_rights_independently_verified'])
        self.assertFalse((self.root/'pre').exists())
        self.assertNotIn('must never leave',json.dumps(r))
    def test_owner_attestation_required_before_any_capture(self):
        with self.assertRaises(ValueError):
            collect_owner_inputs(self.root,owner_auto_confirmed=False,
                capture=lambda *a,**kw:self.fail('unexpected capture'))
    def test_expired_card_never_enters_feature_calculation(self):
        def expired(root,**kw):
            card(root,cutoff='2030-01-15T08:59:00+09:00',captured='2030-01-15T08:30:00+09:00')
            return {'source_day_schedule_race_count':78}
        r=self.invoke(capture=expired)
        self.assertEqual(self.probed,[])
        self.assertEqual(r['expired_or_too_close'],1)
    def test_all_distinct_eligible_cards_not_arbitrary_one_race_cap(self):
        def several(root,**kw):
            self.assertEqual(kw['max_races'],120)
            card(root)
            card(root,rid='203001151202',source='https://www.winticket.jp/keirin/aomori/racecard/2030011512/1/2')
            return {'source_day_schedule_race_count':78}
        r=self.invoke(capture=several)
        self.assertEqual(len(self.probed),2)
        self.assertEqual(r['history_races_processed'],2)
    def test_bad_source_card_id_and_hash_are_not_used(self):
        def tamper(root,**kw):
            card(root)
            f=next((Path(root)/'winticket_racecard_partial').glob('*.json'))
            f.write_text('{}')
            return {'source_day_schedule_race_count':78}
        r=self.invoke(capture=tamper)
        self.assertEqual(self.probed,[])
        self.assertEqual(r['invalid_partial_records'],1)
    def test_no_source_can_override_inbox_privacy(self):
        link=self.root/'link'; link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):
            collect_owner_inputs(link,owner_auto_confirmed=True,
                capture=lambda *a,**kw:self.fail('unexpected capture'))
    def test_invalid_counts_do_not_become_full_model_success(self):
        def invalid(**kw):
            out=self.probe(**kw); out['remaining_model_A_slots']=0
            return out
        r=self.invoke(probe=invalid)
        self.assertEqual(r['history_races_processed'],0)
        self.assertEqual(r['history_races_held'],1)
    def test_empty_source_does_not_claim_acquisition_or_predictions(self):
        r=self.invoke(capture=lambda *a,**kw:{'source_day_schedule_race_count':0})
        self.assertEqual(r['history_races_processed'],0)
        self.assertEqual(r['new_pre_race_inputs'],0)
        self.assertEqual(self.network,[])

class SourceSessionTests(unittest.TestCase):
    def test_429_denial_stops_all_later_real_requests(self):
        calls=[]
        def denied(url):
            calls.append(url)
            raise ValueError('PUBLIC_PAGE_BLOCKED_OR_RATE_LIMITED_NO_RETRY')
        session=SourceSession(denied,monotonic=lambda:0,budget_seconds=240)
        for _ in range(3):
            with self.assertRaises(ValueError):
                session('https://www.winticket.jp/keirin/odds/20300115')
        self.assertEqual(len(calls),1)
        self.assertTrue(session.host_denied)
    def test_time_budget_stops_fetch_before_external_call(self):
        ticks=iter([0,241])
        session=SourceSession(lambda url:self.fail('late GET'),
            monotonic=lambda:next(ticks),budget_seconds=240)
        with self.assertRaises(ValueError):
            session('https://www.winticket.jp/keirin/odds/20300115')
        self.assertEqual(session.requests,0)
        self.assertTrue(session.budget_exhausted)
    def test_unapproved_host_is_never_requested(self):
        session=SourceSession(lambda url:self.fail('bad host'),
            monotonic=lambda:0,budget_seconds=240)
        for url in ['http://www.winticket.jp/x','https://www.winticket.jp.evil.invalid/x',
                    'https://private.invalid/','https://user:pass@www.winticket.jp/x']:
            with self.assertRaises(ValueError):
                session(url)
        self.assertEqual(session.requests,0)

if __name__=='__main__':
    unittest.main()
