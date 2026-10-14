"""Synthetic durable prediction evidence, retries and cutoff boundaries."""
import copy
from datetime import timedelta
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from tests.test_live_research_contract import fixture, NOW
from tests.test_race_cloud_store import Blob

ROOT = Path(__file__).resolve().parents[1]


class PredictionCloudTests(unittest.TestCase):
    def setUp(self):
        with patch.object(sys, 'path', [str(ROOT/'web')] + sys.path):
            self.store = importlib.import_module('api.prediction_store')
        self.feed, self.race = fixture()
        self.client = Blob()
        self.request = dict(publication_review=self.store.REVIEW, race_id=self.race['race_id'], request_id='123456-1')

    def publish(self, now=NOW, clock=None, request=None):
        return self.store.publish_prediction(request or self.request, self.feed, self.race,
            client=self.client, now=now, clock=clock or (lambda:now))

    def read(self, now=NOW, request_id=None):
        return self.store.read_prediction(self.race, client=self.client, now=now, request_id=request_id)

    def test_raw_readback_precedes_actual_cloud_clock(self):
        def clock():
            self.assertTrue(any('/prediction-versions/' in key for key in self.client.data))
            return NOW + timedelta(seconds=1)
        report = self.publish(clock=clock)
        receipt = self.read(NOW+timedelta(seconds=2))
        self.assertEqual(receipt['cloud_saved_at'], (NOW+timedelta(seconds=1)).astimezone(self.store.UTC).isoformat(timespec='microseconds'))
        self.assertTrue(receipt['cloud_eligible_pre_race'])
        self.assertEqual(receipt['snapshot']['program_sha256'], receipt['program_sha256'])
        self.assertEqual(report['sha256'], self.store.digest(receipt))
        self.assertEqual(len(self.client.puts), 3)

    def test_retry_after_close_preserves_first_receipt_and_recovers_manifest(self):
        report = self.publish()
        original = self.read()
        del self.client.data[report['pathname']]
        after = self.store.instant(self.race['closed_at'])+timedelta(minutes=1)
        self.publish(now=after)
        self.assertEqual(self.read(after), original)

    def test_new_request_at_or_after_cutoff_writes_nothing(self):
        for now in (self.store.instant(self.race['closed_at']), self.store.instant(self.race['closed_at'])+timedelta(seconds=1)):
            with self.assertRaises(ValueError):self.publish(now=now)
            self.assertEqual(self.client.puts, [])

    def test_cross_cutoff_raw_orphan_cannot_be_backdated_by_retry(self):
        close = self.store.instant(self.race['closed_at'])
        with self.assertRaises(ValueError):self.publish(now=close-timedelta(seconds=1), clock=lambda:close)
        self.assertEqual(len(self.client.data),1)
        self.assertTrue(all('/prediction-versions/' in key for key in self.client.data))
        with self.assertRaises(ValueError):self.publish(now=close+timedelta(seconds=1))
        self.assertIsNone(self.read(close+timedelta(seconds=2)))

    def test_older_retry_never_rolls_back_newer_prediction(self):
        self.publish()
        second={**self.request,'request_id':'123457-1'}
        self.publish(now=NOW+timedelta(seconds=2), request=second)
        latest=self.read(NOW+timedelta(seconds=3))
        self.publish(now=NOW+timedelta(seconds=4))
        self.assertEqual(self.read(NOW+timedelta(seconds=4)), latest)
        self.assertEqual(self.read(NOW+timedelta(seconds=4),self.request['request_id'])['request_id'],'123456-1')

    def test_rating_revision_does_not_relabel_frozen_inputs(self):
        self.publish()
        original=self.read()
        self.race['boats'][0]['national_win_rate']=1.1
        self.race['program_source_sha256']='b'*64
        self.assertEqual(self.read(),original)
        self.race['boats'][0]['racer_registration_id']='4999'
        with self.assertRaises(ValueError):self.read()

    def test_malformed_requests_no_writes(self):
        for changes in (dict(request_id='../escape'),dict(request_id=True),dict(publication_review='unknown'),dict(race_id='20261015-02-01'),dict(now=NOW.isoformat())):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.publish(request={**self.request,**changes})
            self.assertEqual(self.client.puts,[])

    def test_corrupt_receipt_or_missing_raw_is_rejected(self):
        self.publish()
        key=next(key for key in self.client.data if '/prediction-receipts/' in key)
        original=self.client.data[key]
        value=self.store.decode(original);value['cloud_saved_at']=self.race['closed_at']
        self.client.data[key]=self.store.canonical(value)
        with self.assertRaises(ValueError):self.read()
        self.client.data[key]=original
        del self.client.data[next(key for key in self.client.data if '/prediction-versions/' in key)]
        with self.assertRaises(ValueError):self.read()

    def test_midnight_crossing_keeps_current_manifest(self):
        self.publish()
        key=self.store.manifest_key(self.race['race_id']);original=self.client.data[key]
        self.race['closed_at']='2026-10-15T23:59:59.999999+09:00'
        nextday=self.store.instant('2026-10-16T00:00:00+09:00')
        with self.assertRaises(ValueError):self.publish(clock=lambda:nextday,request={**self.request,'request_id':'123458-1'})
        self.assertEqual(self.client.data[key],original)


if __name__=='__main__':unittest.main()
