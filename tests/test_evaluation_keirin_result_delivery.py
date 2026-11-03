"""Synthetic-only tests. No source HTTP or provider-rights claim."""
import copy
import hashlib
import json
import unittest

from race_ai.keirin_result_delivery import (
    FEED, KeirinDeliveryError, build_research_batch, canonical, digest, research_hit8,
)

DAY = '2026-11-03'
RID = f'keirin:{DAY}:odawara:1'
CAP = '2026-11-03T09:00:00+09:00'
CUTOFF = '2026-11-03T08:45:00+09:00'


def fixture():
    bridge = {
        'schema':'RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1',
        'mode':'OFFLINE_RESEARCH_COVERAGE_LINK',
        'event_date_jst':DAY,'formal_hit_at_8_all':None,
        'records':[{'race_id':RID,'sport':'keirin','event_date_jst':DAY,
                    'venue':'odawara','race_no':1,'archive_slots':[]}],
    }
    feed = {
        'schema':FEED, 'event_date_jst':DAY,
        'source_url':'https://keirin.jp/pc/dfw/portal/guest/result/00001',
        'source_published_at':'2026-11-03T08:55:00+09:00',
        'captured_at':CAP,
        'results':[{'race_id':RID,'starters':[1,2,3,4,5,6,7],
                    'status':'FINAL_NORMAL','winning_triples':[[5,1,4]],
                    'payouts_100yen':[{'triple':[5,1,4],'yen':1520}],
                    'refund_status':'NONE','provider_revision_ref':'v1',
                    'official_cutoff_at':CUTOFF}],
    }
    raw=canonical(feed)
    admission={
        'source_id':'research-synthetic-source',
        'source_url':feed['source_url'],
        'source_sha256':hashlib.sha256(raw).hexdigest(),
        'rights_ref':'synthetic-local-test-only',
        'verified_purposes':['result_collection','private_retention','result_analysis'],
        'checked_at':'2026-11-03T08:30:00+09:00',
        'expires_at':'2026-11-03T12:00:00+09:00',
    }
    return bridge,feed,raw,admission


def batch_for(bridge,raw,admission,**opts):
    return build_research_batch(bridge,raw,admission=admission,
               reviewed_at='2026-11-03T09:01:00+09:00',**opts)


class AdmissionTests(unittest.TestCase):
    def test_admitted_synthetic_result_normalizes_without_formal_claim(self):
        b,f,raw,a=fixture(); out=batch_for(b,raw,a)
        self.assertEqual(out['schema'],'RACE_AI_OFFLINE_RESULT_OBSERVATIONS_V1')
        self.assertEqual(out['scope'],'OPERATOR_SUPPLIED_UNAUTHENTICATED_RESEARCH')
        self.assertEqual(out['observations'][0]['winning_triples'],[[5,1,4]])
        self.assertEqual(out['observations'][0]['payouts_100yen'][0]['yen'],1520)
        self.assertEqual(out['observations'][0]['revision'],1)
        self.assertIsNone(out['observations'][0]['previous_observation_sha256'])

    def test_missing_independent_admission_fails(self):
        b,f,raw,a=fixture()
        with self.assertRaisesRegex(KeirinDeliveryError,'INDEPENDENT_PERMISSION'):
            build_research_batch(b,raw,reviewed_at=CAP)

    def test_wrong_hash_fails(self):
        b,f,raw,a=fixture();a['source_sha256']='0'*64
        with self.assertRaisesRegex(KeirinDeliveryError,'ADMISSION_SOURCE_MISMATCH'):
            batch_for(b,raw,a)

    def test_no_training_rights_fails(self):
        b,f,raw,a=fixture();a['verified_purposes']=['result_collection']
        with self.assertRaisesRegex(KeirinDeliveryError,'PURPOSES_NOT_ADMITTED'):
            batch_for(b,raw,a)

    def test_expired_admission_fails(self):
        b,f,raw,a=fixture();a['expires_at']='2026-11-03T08:59:00+09:00'
        with self.assertRaisesRegex(KeirinDeliveryError,'ADMISSION_TIME_INVALID'):
            batch_for(b,raw,a)

    def test_untrusted_source_host_fails(self):
        b,f,raw,a=fixture();f['source_url']='https://example.com/race'
        raw=canonical(f);a['source_url']=f['source_url'];a['source_sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(KeirinDeliveryError,'NON_OFFICIAL_KEIRIN_URL'):
            batch_for(b,raw,a)

    def test_result_before_cutoff_fails(self):
        b,f,raw,a=fixture(); f['captured_at']='2026-11-03T08:40:00+09:00'; f['source_published_at']=None
        raw=canonical(f);a['source_sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(KeirinDeliveryError,'RESULT_BEFORE_CUTOFF'):
            batch_for(b,raw,a)

    def test_no_unlisted_race(self):
        b,f,raw,a=fixture(); f['results'][0]['race_id']='keirin:2026-11-03:wrong:1'
        raw=canonical(f);a['source_sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(KeirinDeliveryError,'UNKNOWN_OR_DUPLICATE'):
            batch_for(b,raw,a)

    def test_duplicate_keys_fails(self):
        b,f,raw,a=fixture()
        raw=raw.replace(b'"results":',b'"results":[],"results":')
        a['source_sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(KeirinDeliveryError,'DUPLICATE_JSON_KEY'):
            batch_for(b,raw,a)

    def test_bad_winners_no_payout_fails(self):
        b,f,raw,a=fixture(); f['results'][0]['payouts_100yen']=[]
        raw=canonical(f); a['source_sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(KeirinDeliveryError,'INCONSISTENT_FINAL_RESULT'):
            batch_for(b,raw,a)

    def test_nonfinal_winner_fails(self):
        b,f,raw,a=fixture(); f['results'][0]['status']='PENDING'
        raw=canonical(f);a['source_sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(KeirinDeliveryError,'NON_FINAL_HAS_WINNERS'):
            batch_for(b,raw,a)

    def test_nonfinal_empty_still_kept(self):
        b,f,raw,a=fixture(); f['results'][0].update(status='PENDING',winning_triples=[],payouts_100yen=[],refund_status='UNKNOWN')
        raw=canonical(f);a['source_sha256']=hashlib.sha256(raw).hexdigest()
        out=batch_for(b,raw,a)
        self.assertEqual(out['observations'][0]['status'],'PENDING')

    def test_same_source_rerun_does_not_duplicate(self):
        b,f,raw,a=fixture();prev=batch_for(b,raw,a)
        repeat=batch_for(b,raw,a,previous_batches=[prev])
        self.assertEqual(repeat['observations'],[])

    def test_official_revision_appends_not_replaces(self):
        b,f,raw,a=fixture(); prev=batch_for(b,raw,a)
        f['results'][0]['provider_revision_ref']='v2'
        f['results'][0]['winning_triples']=[[5,4,1]]
        f['results'][0]['payouts_100yen']=[{'triple':[5,4,1],'yen':3500}]
        f['source_published_at']='2026-11-03T09:02:00+09:00'
        f['captured_at']='2026-11-03T09:03:00+09:00'
        raw=canonical(f);a['source_sha256']=hashlib.sha256(raw).hexdigest()
        next_batch=build_research_batch(b,raw,admission=a,
                  reviewed_at='2026-11-03T09:04:00+09:00',previous_batches=[prev])
        ob=next_batch['observations'][0]
        self.assertEqual(ob['revision'],2)
        self.assertEqual(ob['previous_observation_sha256'],digest(prev['observations'][0]))
        self.assertEqual(prev['observations'][0]['winning_triples'],[[5,1,4]])

    def test_mutated_revision_chain_rejected(self):
        b,f,raw,a=fixture();prev=batch_for(b,raw,a)
        prev['observations'][0]['previous_observation_sha256']='0'*64
        with self.assertRaisesRegex(KeirinDeliveryError,'BROKEN_PRIOR_CHAIN'):
            batch_for(b,raw,a,previous_batches=[prev])


class ScoreTests(unittest.TestCase):
    def test_reference_hit_is_not_formal(self):
        b,f,raw,a=fixture(); batch=batch_for(b,raw,a)
        forecasts={RID:{'top8':[[5,1,4],[1,5,4]],
                'original_generated_at':'2026-11-03T08:10:00+09:00',
                'original_cutoff_at':CUTOFF,'model_version':'v1'}}
        outcome=research_hit8(batch,forecasts)
        self.assertTrue(outcome['rows'][0]['research_hit8'])
        self.assertIsNone(outcome['rows'][0]['formal_hit8'])
        self.assertIsNone(outcome['formal_hit_at_8_all'])

    def test_missing_forecast_does_not_turn_into_miss(self):
        b,f,raw,a=fixture(); batch=batch_for(b,raw,a)
        outcome=research_hit8(batch,{})
        self.assertIsNone(outcome['rows'][0]['research_hit8'])
        self.assertEqual(outcome['rows'][0]['reason'],'FORECAST_NOT_AVAILABLE')

    def test_after_cutoff_forecast_rejected(self):
        b,f,raw,a=fixture();batch=batch_for(b,raw,a)
        forecasts={RID:{'top8':[[5,1,4]],
                'original_generated_at':'2026-11-03T08:55:00+09:00',
                'original_cutoff_at':CUTOFF,'model_version':'v1'}}
        with self.assertRaisesRegex(KeirinDeliveryError,'RESEARCH_FORECAST_TIMESTAMP_INVALID'):
            research_hit8(batch,forecasts)

    def test_multiple_revisions_are_separate(self):
        b,f,raw,a=fixture();batch=batch_for(b,raw,a)
        self.assertEqual(len(batch['observations']),1)
        self.assertEqual(batch['observations'][0]['race_id'],RID)

if __name__=='__main__':
    unittest.main()
