"""Synthetic-only result event -> PDCA -> next-race outbox tests."""
import copy
import hashlib
import unittest

from race_ai.keirin_result_delivery import BATCH, SCOPE, canonical, build_research_batch
from race_ai.keirin_result_reactor import react_to_result_delivery, ReactorError

DAY = '2026-11-03'
RID = f'keirin:{DAY}:odawara:1'
NEXT = f'keirin:{DAY}:odawara:2'
FAR = f'keirin:{DAY}:odawara:3'
NOW = '2026-11-03T09:04:00+09:00'


def case():
    obs = {
        'race_id':RID,'revision':1,'previous_observation_sha256':None,
        'observed_at':'2026-11-03T09:00:00+09:00',
        'source_id':'synthetic','source_url':'https://keirin.jp/example',
        'source_sha256':'a'*64,'source_published_at':'2026-11-03T08:54:00+09:00',
        'provider_revision_ref':'test-v1','status':'FINAL_NORMAL',
        'winning_triples':[[5,1,4]],
        'payouts_100yen':[{'triple':[5,1,4],'yen':1520}],
        'refund_status':'NONE',
    }
    batch = {'schema':BATCH,'scope':SCOPE,'event_date_jst':DAY,'observations':[obs]}
    reference = {RID:{
        'top8':[[5,1,4],[1,5,4]],
        'original_generated_at':'2026-11-03T08:10:00+09:00',
        'original_cutoff_at':'2026-11-03T08:45:00+09:00',
        'model_version':'reference-v1',
    }}
    races = [
        {'race_id':NEXT,'official_cutoff_at':'2026-11-03T09:05:00+09:00'},
        {'race_id':FAR,'official_cutoff_at':'2026-11-03T09:31:00+09:00'},
    ]
    return batch, reference, races


def auth_result(obs, fingerprint):
    return {'race_id':obs['race_id'],'observation_sha256':fingerprint,
            'provider_receipt_sha256':'b'*64,
            'verified_purposes':['result_collection','result_analysis']}


def authorized_future(row):
    return {
        'race_id':row['race_id'],
        'official_cutoff_at':row['official_cutoff_at'],
        'pre_race_snapshot_sha256':'c'*64,
        'snapshot_captured_at':'2026-11-03T09:01:00+09:00',
        'permission_ref':'SYNTHETIC-FIXTURE-NOT-A-LICENSE',
        'verified_purposes':['schedule','pre_race','private_retention'],
    }


class ReactorTests(unittest.TestCase):
    def run_case(self, *, batch=None, auth=auth_result, verify=authorized_future,
                 frozen=lambda rid:{'race_id':rid,'state':'ABSENT_VERIFIED_BY_OWNER'},
                 queue=True, at=NOW, races=None, reference=None):
        default_batch, default_reference, default_races = case()
        batch = batch if batch is not None else default_batch
        reference = reference if reference is not None else default_reference
        races = races if races is not None else default_races
        store = {}
        def enqueue(intent):
            key = intent['idempotency_key']
            if key in store and store[key] != intent:
                return None
            store.setdefault(key, copy.deepcopy(intent))
            return {'idempotency_key':key,'state':'CREATED_OR_EXISTS'}
        out = react_to_result_delivery(
            batch, races, now=at, forecast_reference=reference,
            authenticate_result=auth, verify_next=verify,
            frozen_readback=frozen,
            enqueue_once=enqueue if queue else None,
            enqueue_readback=lambda key:store.get(key) if queue else None,
        )
        return out, store

    def test_result_event_to_next_race_queue(self):
        out, store = self.run_case()
        self.assertEqual(out['simple_final_events'], 1)
        self.assertEqual(out['queued_count'], 1)
        self.assertEqual(out['queue'][0]['state'], 'CUTOFF_TOO_CLOSE_OR_PASSED')
        self.assertEqual(out['queue'][1]['state'], 'DURABLY_QUEUED_FOR_APPROVED_MODEL')
        self.assertEqual(next(iter(store.values()))['max_trifecta_picks'],8)
        self.assertTrue(out['reference_hit8']['rows'][0]['research_hit8'])
        self.assertIsNone(out['formal_hit_at_8_all'])
        self.assertFalse(out['forecast_generated'])

    def test_provided_feed_normalization_to_queue(self):
        feed = {
            'schema':'RACE_AI_KEIRIN_NORMALIZED_RESULT_DELIVERY_V1',
            'event_date_jst':DAY,
            'source_url':'https://keirin.jp/example',
            'source_published_at':'2026-11-03T08:54:00+09:00',
            'captured_at':'2026-11-03T09:00:00+09:00',
            'results':[{
                'race_id':RID,'starters':[1,2,3,4,5,6,7],
                'status':'FINAL_NORMAL','winning_triples':[[5,1,4]],
                'payouts_100yen':[{'triple':[5,1,4],'yen':1520}],
                'refund_status':'NONE','provider_revision_ref':'v1',
                'official_cutoff_at':'2026-11-03T08:45:00+09:00',
            }],
        }
        raw = canonical(feed)
        admission = {
            'source_id':'synthetic-fixture',
            'source_url':feed['source_url'],
            'source_sha256':hashlib.sha256(raw).hexdigest(),
            'rights_ref':'synthetic-only',
            'verified_purposes':['result_collection','private_retention','result_analysis'],
            'checked_at':'2026-11-03T08:30:00+09:00',
            'expires_at':'2026-11-03T11:00:00+09:00',
        }
        bridge = {
            'schema':'RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1',
            'mode':'OFFLINE_RESEARCH_COVERAGE_LINK',
            'event_date_jst':DAY,
            'formal_hit_at_8_all':None,
            'records':[{'race_id':RID,'sport':'keirin','event_date_jst':DAY,
                        'venue':'odawara','race_no':1}],
        }
        normalized = build_research_batch(bridge, raw,
                   admission=admission, reviewed_at=NOW)
        _, reference, races = case()
        out, store = self.run_case(batch=normalized, reference=reference, races=races)
        self.assertEqual(out['queued_count'],1)
        self.assertTrue(out['reference_hit8']['rows'][0]['research_hit8'])
        self.assertEqual(len(store),1)

    def test_pending_is_not_a_final_result(self):
        batch,_,_ = case()
        batch['observations'][0].update(
            status='PENDING', winning_triples=[], payouts_100yen=[], refund_status='UNKNOWN')
        out, store = self.run_case(batch=batch)
        self.assertEqual(out['dispatch_state'],'NO_VERIFIED_FINAL_RESULT_EVENT')
        self.assertFalse(store)

    def test_no_auth_result_no_dispatch(self):
        out, store = self.run_case(auth=None)
        self.assertFalse(store)
        self.assertEqual(out['independently_attested_events_by_callback'],0)

    def test_invalid_result_receipt_cannot_dispatch(self):
        out, store = self.run_case(auth=lambda obs,sha:{
            **auth_result(obs,sha),'observation_sha256':'0'*64})
        self.assertFalse(store)

    def test_no_pre_race_permission_no_dispatch(self):
        out, store = self.run_case(verify=None)
        self.assertFalse(store)
        self.assertEqual(out['queue'][1]['state'],
                         'PRE_RACE_AUTHORITY_OR_SNAPSHOT_UNVERIFIED')

    def test_existing_frozen_forecast_never_overwritten(self):
        out, store = self.run_case(frozen=lambda rid:{
            'race_id':rid,'state':'FROZEN'})
        self.assertFalse(store)
        self.assertEqual(out['queue'][1]['state'],
                         'FROZEN_OR_PRIVATE_READBACK_UNVERIFIED')

    def test_no_private_queue_write_is_not_success(self):
        out, store = self.run_case(queue=False)
        self.assertFalse(store)
        self.assertEqual(out['queue'][1]['state'],
                         'OUTBOX_WRITE_OR_READBACK_UNCERTAIN_NO_RETRY')

    def test_no_duplicate_races(self):
        _,_,races = case()
        with self.assertRaisesRegex(ReactorError,'DUPLICATE_FUTURE_RACE'):
            self.run_case(races=races+[races[1]])

    def test_no_future_result_observation(self):
        batch,_,_ = case()
        batch['observations'][0]['observed_at'] = '2026-11-03T11:00:00+09:00'
        with self.assertRaisesRegex(ReactorError,'FUTURE_RESULT_OBSERVATION'):
            self.run_case(batch=batch)

    def test_future_snapshot_not_trusted(self):
        def late(row):
            return {**authorized_future(row),
                    'snapshot_captured_at':'2026-11-03T09:10:00+09:00'}
        out, store = self.run_case(verify=late)
        self.assertFalse(store)

    def test_callback_exception_does_not_leak_source_secret(self):
        def bad(_):
            raise RuntimeError('SECRET_NEVER_PRINT')
        out,_ = self.run_case(verify=bad)
        self.assertNotIn('SECRET_NEVER_PRINT',str(out))

    def test_cutoff_must_match_jst_race_day(self):
        _,_,races = case()
        races[1]['official_cutoff_at'] = '2026-11-04T09:31:00+09:00'
        with self.assertRaisesRegex(ReactorError,
                                   'NEXT_CUTOFF_RACE_DATE_MISMATCH'):
            self.run_case(races=races)

    def test_cancelled_is_not_miss_or_trigger(self):
        batch,_,_ = case()
        batch['observations'][0].update(status='CANCELLED',
            winning_triples=[], payouts_100yen=[],refund_status='FULL')
        out, store = self.run_case(batch=batch)
        self.assertIsNone(out['reference_hit8']['rows'][0]['research_hit8'])
        self.assertEqual(out['simple_final_events'],0)
        self.assertFalse(store)

    def test_idempotent_repeated_event(self):
        batch,reference,races = case()
        durable = {}
        writes = []
        def enqueue(intent):
            key = intent['idempotency_key']
            writes.append(key)
            durable.setdefault(key,copy.deepcopy(intent))
            return {'idempotency_key':key,'state':'CREATED_OR_EXISTS'}
        def run():
            return react_to_result_delivery(batch,races,now=NOW,
                 forecast_reference=reference,
                 authenticate_result=auth_result,verify_next=authorized_future,
                 frozen_readback=lambda rid:{
                     'race_id':rid,'state':'ABSENT_VERIFIED_BY_OWNER'},
                 enqueue_once=enqueue,
                 enqueue_readback=lambda k:durable.get(k))
        self.assertEqual(run()['queued_count'],1)
        self.assertEqual(run()['queued_count'],1)
        self.assertEqual(len(durable),1)
        self.assertEqual(writes[0],writes[1])


if __name__=='__main__':
    unittest.main()
