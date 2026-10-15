"""Immutable original numeric facts and a separate frozen original model."""
import copy
from datetime import timedelta
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from tests.test_original_prediction_contract import fixture,NOW,sha
from tests.test_exhibition_store import seed_baseline,seed_preview
from tests.test_race_cloud_store import Blob
from web.race_contract import canonical,stamp,_time

ROOT=Path(__file__).resolve().parents[1]


class OriginalStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            with patch.object(sys,'path',[str(ROOT/'web')]+sys.path):
                cls.source=importlib.import_module('api.original_exhibition_store')
                cls.post=importlib.import_module('api.original_prediction_store')
        except ModuleNotFoundError:cls.source=cls.post=None

    def setUp(self):
        self.assertIsNotNone(self.source,'separate original stores required')
        self.base,self.bundle,self.receipt,self.race=fixture();self.client=Blob()
        seed_baseline(self.client,self.base);seed_preview(self.client,self.bundle)
        for n in range(14):self.client.data[f'race-ai/predictions/sentinel{n}.json']=b'unchanged'
        self.client.data['race-ai/post-exhibition/sentinel.json']=b'legacy-v1'
        self.old=copy.deepcopy(self.client.data)
        self.request=dict(publication_review=self.source.REVIEW,race_id=self.race['race_id'],request_id='223456-1',
            observation=self.receipt['observation'],runner_saved_at=self.receipt['runner_saved_at'])
        self.post_request=dict(publication_review=self.post.REVIEW,race_id=self.race['race_id'],request_id='323456-1')

    def publish_source(self,now=NOW,clock=None,request=None):
        return self.source.publish_original_exhibition(request or self.request,self.race,client=self.client,now=now,clock=clock or (lambda:now))

    def read_source(self,now=NOW,request_id=None):return self.source.read_original_exhibition(self.race,client=self.client,now=now,request_id=request_id)
    def publish_post(self,now=NOW,clock=None,request=None):
        return self.post.publish_original_prediction(request or self.post_request,self.race,client=self.client,now=now,clock=clock or (lambda:now))
    def read_post(self,now=NOW):return self.post.read_original_prediction(self.race,client=self.client,now=now)

    def test_actual_source_readback_and_post_prefixes_preserve_all_old_objects(self):
        def clock():
            self.assertTrue(any('/original-exhibition-versions/' in k for k in self.client.data))
            return NOW
        meta=self.publish_source(clock=clock);receipt=self.read_source()
        self.assertEqual(meta['sha256'],sha(receipt));self.assertEqual(len(self.client.puts),3)
        post_meta=self.publish_post();post=self.read_post()
        self.assertEqual(post['snapshot']['variant'],'original-v1');self.assertEqual(post_meta['models'],1)
        self.assertTrue(all('/original-exhibition' in k or '/post-exhibition-original' in k for k,_ in self.client.puts))
        self.assertEqual({k:self.client.data[k] for k in self.old},self.old)

    def test_late_source_facts_have_false_eligibility_and_cannot_mint_post(self):
        late=_time(self.race['closed_at'])+timedelta(seconds=1)
        self.publish_source(now=late);receipt=self.read_source(late)
        self.assertFalse(receipt['cloud_eligible_pre_race'])
        with self.assertRaisesRegex(ValueError,'CUTOFF_PASSED'):self.publish_post(now=late)
        self.assertFalse(any('/post-exhibition-original' in k for k in self.client.data))

    def test_source_nonce_retry_preserves_receipt_and_conflicting_payload_rejected(self):
        meta=self.publish_source();old=self.read_source();del self.client.data[meta['pathname']]
        self.publish_source(now=NOW+timedelta(seconds=1));self.assertEqual(self.read_source(NOW+timedelta(seconds=1)),old)
        bad=copy.deepcopy(self.request);bad['runner_saved_at']=stamp(NOW)
        with self.assertRaises(ValueError):self.publish_source(request=bad)

    def test_post_pins_old_original_after_source_correction_and_baseline_latest_change(self):
        self.publish_source();self.publish_post();old=self.read_post()
        request=copy.deepcopy(self.request);request['request_id']='223457-1'
        request['observation']['boats'][0]['original_times']['lap_s']=35.42
        observation=request['observation'];observation['snapshot_id']=sha({k:v for k,v in observation.items() if k!='snapshot_id'})
        self.publish_source(now=NOW+timedelta(seconds=1),request=request)
        baseline_pointer=f"race-ai/predictions/{self.race['race_id']}.json"
        self.client.data[baseline_pointer]=b'corrupt latest is not pinned input'
        self.assertEqual(self.read_post(NOW+timedelta(seconds=2)),old)

    def test_partial_source_retained_but_never_generates_missing_original_model(self):
        observation=self.request['observation'];observation['boats'][0]['original_times']['lap_s']=None
        observation['boats'][0]['missing_reasons']['lap_s']='SOURCE_NOT_PUBLISHED';observation['status']='PARTIAL'
        observation['snapshot_id']=sha({k:v for k,v in observation.items() if k!='snapshot_id'})
        self.publish_source()
        self.assertEqual(self.read_source()['observation']['status'],'PARTIAL')
        with self.assertRaisesRegex(ValueError,'ORIGINAL_TIMINGS_INCOMPLETE'):self.publish_post()
        self.assertFalse(any('/post-exhibition-original' in k for k in self.client.data))

    def test_invalid_source_runner_future_extra_and_nonce_fail_before_any_write(self):
        for changes in [dict(runner_saved_at=stamp(NOW+timedelta(seconds=1))),dict(runner_saved_at='2026-10-14T07:00:00+09:00'),
                        dict(request_id='../escape'),dict(probabilities=[]),dict(publication_review='unreviewed')]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.publish_source(request={**self.request,**changes})
        self.assertEqual(self.client.puts,[])

    def test_source_midnight_or_backward_cloud_clock_leaves_no_receipt_or_manifest(self):
        for clock in [NOW+timedelta(days=1),NOW-timedelta(seconds=1)]:
            with self.assertRaises(ValueError):self.publish_source(clock=lambda:clock)
            self.assertFalse(any('/original-exhibition-receipts/' in k or '/original-exhibition/' in k for k in self.client.data))

    def test_corrupt_original_receipt_raw_or_pinned_post_is_rejected(self):
        self.publish_source();self.publish_post();saved=copy.deepcopy(self.client.data)
        for key in [self.source.receipt_key(self.race['race_id'],'223456-1'),
                    self.source.version_key(self.race['race_id'],self.receipt['observation']['snapshot_id'])]:
            self.client.data=copy.deepcopy(saved);self.client.data[key]=b'{}'
            with self.assertRaises(ValueError):self.read_post()

    def test_post_orphan_cutoff_cannot_gain_receipt_by_retry_after_close(self):
        self.publish_source();close=_time(self.race['closed_at'])
        with self.assertRaises(ValueError):self.publish_post(now=close-timedelta(seconds=1),clock=lambda:close)
        with self.assertRaises(ValueError):self.publish_post(now=close+timedelta(seconds=1))
        self.assertFalse(any('/post-exhibition-original-receipts/' in k for k in self.client.data))

    def test_newer_post_correction_preserves_older_nonce_retry_after_close(self):
        self.publish_source();first=self.publish_post();old=self.read_post()
        request={**self.post_request,'request_id':'323457-1'}
        self.publish_post(now=NOW+timedelta(seconds=1),request=request);latest=self.read_post(NOW+timedelta(seconds=2))
        after=_time(self.race['closed_at'])+timedelta(seconds=1)
        self.publish_post(now=after)
        self.assertEqual(self.read_post(after),latest)
        pinned=self.post.read_original_prediction(self.race,client=self.client,now=after,request_id=first['request_id'])
        self.assertEqual(pinned,old)


if __name__=='__main__':unittest.main()
