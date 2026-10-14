"""Synthetic authenticated publication boundary; live proof recorded separately."""
from datetime import date, datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 14, 19, 0, tzinfo=timezone.utc)


def snapshot():
    return {'date_jst': '2026-10-15', 'source_url': 'https://www1.mbrace.or.jp/od2/B/202610/b261015.lzh',
            'source_sha256': 'a'*64, 'first_observed_at': '2026-10-15T03:00:00+09:00',
            'redistribution_authorized': True, 'publication_review': 'user-confirmation-2026-10-15-official-facts',
            'races': 1, 'complete_six_boat_races': 1, 'venues': [{'venue': '02', 'races': [{
                'race_id':'20261015-02-01','closed_at':'2026-10-15T12:00:00+09:00',
                'boats':[{'lane':n,'racer_registration_id':str(4000+n),'motor_no':n,'name':'試験選手'} for n in range(1,7)]}]}]}


class Client:
    def __init__(self): self.data={}; self.puts=[]
    def get(self,key,**kwargs):
        return types.SimpleNamespace(status_code=200, content=self.data[key]) if key in self.data else None
    def put(self,key,data,**kwargs):
        if key in self.data and not kwargs.get('overwrite'): raise RuntimeError('already exists')
        self.puts.append((key, kwargs))
        self.data[key]=data
        return types.SimpleNamespace(pathname=key)


class DayPublicationTests(unittest.TestCase):
    def setUp(self):
        path=ROOT/'web/api/publish-day.py'
        self.assertTrue(path.exists(), 'server-side approved day publisher must exist')
        spec=importlib.util.spec_from_file_location('day_publish',path)
        self.module=importlib.util.module_from_spec(spec)
        with patch.object(sys,'path',[str(ROOT/'web')]+sys.path): spec.loader.exec_module(self.module)

    def test_versioned_write_fixed_key_private_and_sha_readback(self):
        client=Client()
        result=self.module.publish_snapshot(snapshot(),now=NOW,client=client)
        self.assertEqual(result['status'],'verified')
        self.assertEqual(result['pathname'],'race-ai/day/2026-10-15.json')
        self.assertEqual(len(client.puts),2)
        self.assertTrue(client.puts[0][0].startswith('race-ai/versions/2026-10-15/'))
        for _,options in client.puts:
            self.assertEqual(options['access'],'private')
            self.assertIs(options['add_random_suffix'],False)

    def test_duplicate_publication_is_idempotent(self):
        client=Client()
        first=self.module.publish_snapshot(snapshot(),now=NOW,client=client)
        second=self.module.publish_snapshot(snapshot(),now=NOW,client=client)
        self.assertEqual(first['sha256'],second['sha256'])
        self.assertEqual(len(client.puts),2)

    def test_stale_unapproved_or_wrong_source_data_never_writes(self):
        for change in [{'date_jst':'2026-10-14'},{'publication_review':'synthetic-approval'},{'source_url':'https://attacker.example/feed'}, {'redistribution_authorized':False}]:
            with self.subTest(change=change):
                client=Client(); data={**snapshot(),**change}
                with self.assertRaises(ValueError):self.module.publish_snapshot(data,now=NOW,client=client)
                self.assertEqual(client.puts,[])

    def test_older_observation_cannot_replace_newer_day(self):
        client=Client()
        data=snapshot();data['first_observed_at']='2026-10-15T03:30:00+09:00'
        self.module.publish_snapshot(data,now=NOW,client=client)
        with self.assertRaisesRegex(ValueError,'NEWER_SNAPSHOT_EXISTS'):
            self.module.publish_snapshot(snapshot(),now=NOW,client=client)
        self.assertEqual(len(client.puts),2)

    def test_matching_sha_is_required(self):
        class BrokenClient(Client):
            def get(self,key,**kwargs):
                result=super().get(key,**kwargs)
                if result is not None:result.content=b'corrupted'
                return result
        with self.assertRaises(ValueError):self.module.publish_snapshot(snapshot(),now=NOW,client=BrokenClient())

    def test_nested_source_cannot_escape_approved_origin_or_race_identity(self):
        for url in ['https://attacker.example/program', 'https://www.boatrace.jp/owpc/pc/race/racelist?hd=20261015&jcd=18&rno=1']:
            data=snapshot(); data['venues'][0]['races'][0]['boats'][0]['detail_source_url']=url
            client=Client()
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.module.publish_snapshot(data,now=NOW,client=client)
            self.assertEqual(client.puts,[])

    def test_idempotent_day_recovers_missing_immutable_version(self):
        client=Client()
        report=self.module.publish_snapshot(snapshot(),now=NOW,client=client)
        del client.data[report['version_pathname']]
        self.module.publish_snapshot(snapshot(),now=NOW,client=client)
        self.assertIn(report['version_pathname'],client.data)
