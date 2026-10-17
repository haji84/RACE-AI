"""Immutable synthetic post forecasts and pinned input recovery."""
import copy
from datetime import timedelta
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from tests.test_exhibition_contract import fixture, refresh, NOW
from tests.test_race_cloud_store import Blob
from web import race_contract as facts, research_contract

ROOT = Path(__file__).resolve().parents[1]


def seed_baseline(client, baseline):
    race = baseline['snapshot']['race_id']; request = baseline['request_id']; identifier = baseline['snapshot']['snapshot_id']
    client.data[f'race-ai/prediction-receipts/{race}/{request}.json'] = facts.canonical(baseline)
    client.data[f'race-ai/prediction-versions/{race}/{identifier}.json'] = facts.canonical(baseline['snapshot'])
    client.data[f'race-ai/predictions/{race}.json'] = facts.canonical(dict(schema_version=1,race_id=race,
        request_id=request,snapshot_id=identifier,program_sha256=baseline['program_sha256'],published_at=baseline['cloud_saved_at']))


def seed_preview(client, bundle):
    race = bundle['race_id']
    client.data[f'race-ai/races/{race}.json'] = facts.canonical({k:v for k,v in bundle.items() if k!='records'})
    for receipt in bundle['records']:
        record = receipt['record']; identifier = record['snapshot_id']
        client.data[f'race-ai/observations/{race}/{identifier}.json'] = facts.canonical(record)
        client.data[f'race-ai/receipts/{race}/{identifier}.json'] = facts.canonical(receipt)


class ExhibitionStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            with patch.object(sys,'path',[str(ROOT/'web')]+sys.path): cls.store=importlib.import_module('api.exhibition_store')
        except ModuleNotFoundError: cls.store=None

    def setUp(self):
        self.assertIsNotNone(self.store, 'separate post-exhibition store must exist')
        self.baseline,self.bundle,self.race=fixture(); self.client=Blob()
        seed_baseline(self.client,self.baseline); seed_preview(self.client,self.bundle)
        # Sentinel independent baseline keys model preservation of the existing
        # cohort; no production data or forecast is created by this test.
        for number in range(14): self.client.data[f'race-ai/predictions/sentinel-{number}.json']=b'unchanged-baseline'
        self.original_baselines={k:v for k,v in self.client.data.items() if '/prediction' in k}
        self.request=dict(publication_review=self.store.REVIEW,race_id=self.race['race_id'],request_id='123457-1')

    def publish(self, now=NOW, clock=None, request=None):
        return self.store.publish_exhibition_prediction(request or self.request,self.race,
            client=self.client,now=now,clock=clock or (lambda:now))

    def read(self, now=NOW, request_id=None):
        return self.store.read_exhibition_prediction(self.race,client=self.client,now=now,request_id=request_id)

    def test_actual_readback_precedes_clock_and_baseline_objects_never_change(self):
        def clock():
            self.assertTrue(any('/post-exhibition-versions/' in key for key in self.client.data))
            return NOW+timedelta(seconds=1)
        metadata=self.publish(clock=clock); receipt=self.read(NOW+timedelta(seconds=2))
        self.assertEqual(set(receipt),{'schema_version','request_id','snapshot','cloud_saved_at','cloud_eligible_pre_race','program_identity_sha256'})
        self.assertEqual(receipt['cloud_saved_at'],facts.stamp(NOW+timedelta(seconds=1)))
        self.assertEqual(metadata['sha256'],self.store.digest(receipt))
        self.assertEqual(metadata['models'],1)
        self.assertEqual(len(self.client.puts),3)
        self.assertTrue(all('/post-exhibition' in key for key,_ in self.client.puts))
        self.assertEqual({k:v for k,v in self.client.data.items() if '/prediction' in k},self.original_baselines)

    def test_retry_after_close_recovers_pointer_without_changing_original_receipt(self):
        metadata=self.publish(); original=self.read(); del self.client.data[metadata['pathname']]
        after=facts._time(self.race['closed_at'])+timedelta(seconds=1)
        self.publish(now=after)
        self.assertEqual(self.read(after),original)
        self.assertEqual(self.read(after,self.request['request_id']),original)

    def test_new_nonce_at_close_cannot_publish_or_resurrect_orphan(self):
        close=facts._time(self.race['closed_at'])
        for now in [close,close+timedelta(seconds=1)]:
            with self.assertRaisesRegex(ValueError,'^CUTOFF_PASSED$'): self.publish(now=now)
        self.assertEqual(self.client.puts,[])
        with self.assertRaises(ValueError): self.publish(now=close-timedelta(seconds=1),clock=lambda:close)
        self.assertEqual(len(self.client.puts),1)
        with self.assertRaises(ValueError): self.publish(now=close+timedelta(seconds=1))
        self.assertIsNone(self.read(close+timedelta(seconds=1)))

    def test_old_input_receipts_replay_after_latest_baseline_and_preview_revisions(self):
        self.publish(); original=self.read(); pinned_id=original['snapshot']['beforeinfo_link']['snapshot_id']
        changed=copy.deepcopy(self.bundle)
        changed['records'][0]['record']['data']['boats'][0]['display_time']=6.1
        refresh(changed); seed_preview(self.client,changed)
        baseline=copy.deepcopy(self.baseline); baseline['request_id']='123458-1'
        frozen=baseline['snapshot']; boats=copy.deepcopy(frozen['program_boats']); boats[0]['national_win_rate']=.2
        frozen=research_contract._assemble(frozen['race_id'],facts._program(self.race)[0],frozen['closed_at'],frozen['as_of'],
            frozen['generated_at'],frozen['program_source'],boats)
        baseline['snapshot']=frozen; seed_baseline(self.client,baseline)
        self.assertEqual(self.read(),original)
        self.assertNotEqual(changed['latest']['beforeinfo'],pinned_id)
        self.assertEqual(self.read(NOW,self.request['request_id']),original)

    def test_correction_appends_and_older_retry_cannot_roll_back_latest(self):
        self.publish(); old=self.read()
        self.bundle['records'][0]['record']['data']['boats'][0]['display_time']=6.1
        refresh(self.bundle); seed_preview(self.client,self.bundle)
        request={**self.request,'request_id':'123459-1'}
        self.publish(now=NOW+timedelta(seconds=1),request=request)
        newer=self.read(NOW+timedelta(seconds=2))
        self.assertNotEqual(newer['snapshot']['snapshot_id'],old['snapshot']['snapshot_id'])
        self.publish(now=NOW+timedelta(seconds=3))
        self.assertEqual(self.read(NOW+timedelta(seconds=3)),newer)
        self.assertEqual(self.read(NOW+timedelta(seconds=3),self.request['request_id']),old)

    def test_missing_or_incomplete_inputs_have_fixed_reason_and_no_post_objects(self):
        del self.client.data[f"race-ai/predictions/{self.race['race_id']}.json"]
        with self.assertRaisesRegex(ValueError,'^BASELINE_MISSING$'): self.publish()
        seed_baseline(self.client,self.baseline)
        del self.client.data[f"race-ai/races/{self.race['race_id']}.json"]
        with self.assertRaisesRegex(ValueError,'^PREVIEW_NOT_OBTAINED$'): self.publish()
        for row in self.bundle['records'][0]['record']['data']['boats']: row['display_time']=None
        refresh(self.bundle); seed_preview(self.client,self.bundle)
        with self.assertRaisesRegex(ValueError,'^DISPLAY_INCOMPLETE$'): self.publish()
        self.assertEqual(self.client.puts,[])

    def test_rehashed_post_tampering_missing_pinned_receipt_or_raw_is_rejected(self):
        self.publish(); saved=copy.deepcopy(self.client.data)
        post_key=self.store.receipt_key(self.race['race_id'],self.request['request_id'])
        for kind in ['post_time','baseline_missing','beforeinfo_missing','raw_missing','oversized']:
            self.client.data=copy.deepcopy(saved)
            if kind=='post_time':
                value=self.store.decode(self.client.data[post_key]); value['cloud_saved_at']=self.race['closed_at']
                self.client.data[post_key]=facts.canonical(value)
            elif kind=='baseline_missing': del self.client.data[f"race-ai/prediction-receipts/{self.race['race_id']}/{self.baseline['request_id']}.json"]
            elif kind=='beforeinfo_missing': del self.client.data[f"race-ai/receipts/{self.race['race_id']}/{self.bundle['latest']['beforeinfo']}.json"]
            elif kind=='oversized': self.client.data[post_key]=b' ' * 256001
            else: del self.client.data[next(k for k in self.client.data if '/post-exhibition-versions/' in k)]
            with self.subTest(kind=kind),self.assertRaises(ValueError): self.read()

    def test_nonce_extra_fields_and_client_probability_clock_injection_write_nothing(self):
        for changes in [dict(request_id='../escape'),dict(request_id=True),dict(now=NOW.isoformat()),
                        dict(probabilities=[]),dict(publication_review='unknown'),dict(race_id='20261015-18-02')]:
            with self.subTest(changes=changes),self.assertRaises(ValueError): self.publish(request={**self.request,**changes})
        self.assertEqual(self.client.puts,[])

    def test_midnight_and_backward_measured_clock_cannot_establish_cloud_receipt(self):
        for saved in [NOW-timedelta(seconds=1),NOW+timedelta(days=1)]:
            self.client.data={k:v for k,v in self.client.data.items() if '/post-exhibition' not in k}
            with self.assertRaises(ValueError): self.publish(clock=lambda:saved)
            self.assertFalse(any('/post-exhibition-receipts/' in k or '/post-exhibition/' in k for k in self.client.data))

    def test_manifest_clock_digest_latest_and_extra_fields_rejected(self):
        self.publish(); key=self.store.manifest_key(self.race['race_id']); original=self.client.data[key]
        for changes in [dict(snapshot_id='b'*64),dict(program_identity_sha256='b'*64),
                        dict(published_at='2026-10-15T07:33:00+09:00'),dict(extra=True),dict(schema_version=True)]:
            value=self.store.decode(original); value.update(changes); self.client.data[key]=facts.canonical(value)
            with self.subTest(changes=changes),self.assertRaises(ValueError): self.read()


if __name__=='__main__': unittest.main()
