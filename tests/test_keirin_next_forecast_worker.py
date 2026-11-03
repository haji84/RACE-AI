"""Only synthetic input tests. No real provider page or model is accessed."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import unittest

from race_ai.keirin_result_delivery import canonical
from race_ai.keirin_next_forecast_worker import (
    OwnerForecastError, consume_next_intent
)

RID = 'keirin:2026-11-03:odawara:8'
CUTOFF = '2026-11-03T11:30:00+09:00'
NOW = '2026-11-03T10:50:00+09:00'
AFTER = '2026-11-03T10:51:00+09:00'


def fixture():
    snap = {
        'schema':'RACE_AI_KEIRIN_PRIVATE_PRE_RACE_V1',
        'race_id':RID,'as_of':'2026-11-03T10:45:00+09:00',
        'starters':[1,2,3,4,5,6,7],
        'facts':{'line_groups':[[1,2,3],[4,5],[6,7]],
                 'ability_verified':[0.6,0.7,0.3,0.4,0.5,0.2,0.1]},
        'permission_ref':'SYNTHETIC-TEST-ONLY',
        'official_cutoff_at':CUTOFF,
    }
    src = sha256(canonical(snap)).hexdigest()
    key = sha256(canonical({
        'race_id':RID,'official_cutoff_at':CUTOFF,
        'job_kind':'KEIRIN_NEXT_FORECAST_V1',
    })).hexdigest()
    intent = {
        'schema':'RACE_AI_KEIRIN_NEXT_FORECAST_INTENT_V1',
        'idempotency_key':key,'trigger_source_event_sha256':'a'*64,
        'race_id':RID,'official_cutoff_at':CUTOFF,
        'pre_race_snapshot_sha256':src,
        'pre_race_snapshot_at':snap['as_of'],
        'permission_ref':snap['permission_ref'],
        'max_trifecta_picks':8,'prediction_generated':False,
    }
    prediction = {
        'race_id':RID,'model_id':'synthetic-untrained-model',
        'model_version':'fixture-not-production',
        'generated_at':'2026-11-03T10:50:30+09:00',
        'trained_until':'2026-11-02T17:00:00+09:00',
        'snapshot_sha256':src,
        'top8':[[1,2,3],[1,3,2],[2,1,3],[2,3,1],
                [3,1,2],[3,2,1],[4,5,6],[5,4,6]],
    }
    cert = {
        'race_id':RID,'source_sha256':src,
        'permission_ref':snap['permission_ref'],
        'official_cutoff_at':CUTOFF,
        'verified_purposes':['schedule','pre_race','private_retention','model_inference'],
        'valid_until':'2026-11-03T11:40:00+09:00',
    }
    return intent,snap,prediction,cert


class PrivateWorkerTests(unittest.TestCase):
    def do_run(self, *, mutate=None, clock_times=(NOW,AFTER),
               verified=True, store_ok=True, witness=True, model_ok=True,
               source_ok=True):
        intent,snap,pred,cert=fixture()
        if mutate: mutate(intent,snap,pred,cert)
        private={}
        calls={'model':0,'write':0,'source':0}
        time_values=iter(clock_times)
        def tick():
            return next(time_values)
        def attest(_snap,_intent):
            calls['source']+=1
            return deepcopy(cert) if verified else None
        def read_snapshot(_intent):
            return deepcopy(snap) if source_ok else None
        def model(_):
            calls['model']+=1
            return deepcopy(pred) if model_ok else None
        def write(record, digest):
            calls['write']+=1
            if not store_ok: return None
            private.setdefault(RID,deepcopy(record))
            return {'race_id':RID,'forecast_sha256':digest,'state':'CREATED_ONCE'}
        def read(rid,digest):
            return private.get(rid)
        def receipt(rec,digest):
            if witness:
                return {'race_id':RID,'forecast_sha256':digest,
                        'trusted_persisted_at':'2026-11-03T10:51:01+09:00',
                        'external_witness':'SYNTHETIC_FICTION_NOT_REMOTE'}
            return None
        report=consume_next_intent(
            intent,clock=tick,
            read_queued_intent=lambda k:deepcopy(intent),
            read_snapshot=read_snapshot,attest_source=attest,
            frozen_status=lambda rid:{'race_id':rid,'state':'ABSENT_VERIFIED_BY_OWNER'},
            model_forecast=model,atomic_freeze=write,
            freeze_readback=read,independent_receipt_check=receipt)
        return report,private,calls

    def test_synthetic_end_to_end_creates_only_private_reference(self):
        report,private,calls=self.do_run()
        self.assertTrue(report['forecast_durably_saved'])
        self.assertTrue(report['independent_receipt_accepted_by_callback'])
        self.assertIsNone(report['formal_hit_at_8_all'])
        self.assertFalse(report['live_autorun_enabled'])
        self.assertEqual(len(private[RID]['top8']),8)
        self.assertFalse(private[RID]['officially_frozen'])
        self.assertEqual(calls['write'],1)

    def test_invalid_idempotency_key_rejected(self):
        with self.assertRaisesRegex(OwnerForecastError,'OUTBOX_KEY_MISMATCH'):
            self.do_run(mutate=lambda i,s,p,c:i.update(idempotency_key='0'*64))

    def test_late_cutoff_never_runs_model(self):
        report,_,calls=self.do_run(clock_times=(
            '2026-11-03T11:29:30+09:00',AFTER))
        self.assertEqual(report['state'],'CUTOFF_TOO_CLOSE_OR_PASSED')
        self.assertEqual(calls['model'],0)

    def test_unverified_source_never_runs_model(self):
        report,_,calls=self.do_run(verified=False)
        self.assertEqual(report['state'],'PRE_RACE_SOURCE_RIGHTS_OR_HASH_UNVERIFIED')
        self.assertEqual(calls['model'],0)

    def test_unavailable_snapshot_never_runs_model(self):
        report,_,calls=self.do_run(source_ok=False)
        self.assertEqual(report['state'],'PRE_RACE_SOURCE_RIGHTS_OR_HASH_UNVERIFIED')
        self.assertEqual(calls['model'],0)

    def test_source_hash_change_rejected(self):
        report,_,calls=self.do_run(mutate=lambda i,s,p,c:s['facts'].update(invented=0.9))
        self.assertEqual(report['state'],'PRE_RACE_SOURCE_RIGHTS_OR_HASH_UNVERIFIED')
        self.assertEqual(calls['model'],0)

    def test_odds_in_source_hard_rejected(self):
        report,_,calls=self.do_run(mutate=lambda i,s,p,c:s['facts'].update(odds=[2.0]))
        self.assertEqual(report['state'],'PRE_RACE_SOURCE_RIGHTS_OR_HASH_UNVERIFIED')
        self.assertEqual(calls['model'],0)

    def test_model_not_connected_stops(self):
        report,_,calls=self.do_run(model_ok=False)
        self.assertEqual(report['state'],'MODEL_RUNTIME_FAILED')
        self.assertEqual(calls['write'],0)

    def test_model_wrong_snapshot_rejected(self):
        report,_,calls=self.do_run(mutate=lambda i,s,p,c:p.update(snapshot_sha256='f'*64))
        self.assertEqual(report['state'],'MODEL_OUTPUT_REJECTED')
        self.assertEqual(calls['write'],0)

    def test_model_duplicate_top8_rejected(self):
        def mutate(i,s,p,c):
            p['top8'][1]=p['top8'][0]
        report,_,calls=self.do_run(mutate=mutate)
        self.assertEqual(report['state'],'MODEL_OUTPUT_REJECTED')
        self.assertEqual(calls['write'],0)

    def test_second_clock_after_cutoff_rejects_storage(self):
        report,_,calls=self.do_run(clock_times=(
            NOW,'2026-11-03T11:29:30+09:00'))
        self.assertEqual(report['state'],'MODEL_MISSED_CUTOFF')
        self.assertEqual(calls['write'],0)

    def test_write_failure_never_retries(self):
        report,_,calls=self.do_run(store_ok=False)
        self.assertEqual(report['state'],'PRIVATE_FREEZE_WRITE_UNCERTAIN_NO_RETRY')
        self.assertEqual(calls['write'],1)

    def test_external_witness_missing_does_not_upgrade(self):
        report,private,calls=self.do_run(witness=False)
        self.assertTrue(report['forecast_durably_saved'])
        self.assertFalse(report['independent_receipt_accepted_by_callback'])
        self.assertEqual(report['state'],'EXTERNAL_PRE_CUTOFF_RECEIPT_UNVERIFIED')

    def test_untrusted_outbox_cannot_proceed(self):
        intent,snap,pred,cert=fixture()
        calls={'model':0}
        def model(_):
            calls['model']+=1
            return pred
        report=consume_next_intent(intent,clock=lambda:NOW,
            read_queued_intent=lambda k:None,
            read_snapshot=lambda _:snap,attest_source=lambda s,i:cert,
            frozen_status=lambda rid:{'race_id':rid,'state':'ABSENT_VERIFIED_BY_OWNER'},
            model_forecast=model,atomic_freeze=lambda r,d:None,
            freeze_readback=lambda r,d:None,independent_receipt_check=lambda r,d:None)
        self.assertEqual(report['state'],'PRIVATE_OUTBOX_READBACK_MISSING')
        self.assertEqual(calls['model'],0)


if __name__=='__main__':
    unittest.main()
