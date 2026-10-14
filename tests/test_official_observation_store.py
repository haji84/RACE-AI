import copy
from datetime import datetime,timezone
import sqlite3
import unittest
from unittest.mock import patch

from race_ai.core import SourceError
from race_ai.official_observation_store import setup_store,save_observation,latest_observation
from race_ai.official_race_updates import parse_update,endpoint
from tests.test_official_race_updates import DAY,page,preview,odds


class OfficialObservationStoreTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');setup_store(self.db)

    def observation(self,kind='beforeinfo',stamp='2026-10-15T07:00:00+09:00',body=None):
        return parse_update(page(kind,body or (preview() if kind=='beforeinfo' else odds())),kind=kind,
            day=DAY,venue='18',race_no=1,source_url=endpoint(DAY,'18',1,kind),captured_at=stamp)

    def save(self,data,now='2026-10-15T07:01:00+09:00'):
        with patch('race_ai.official_observation_store.utc_now',return_value=datetime.fromisoformat(now)):
            return save_observation(self.db,data)

    def test_idempotent_snapshot_retries_and_append_only_corrections(self):
        data=self.observation();first=self.save(data);self.assertEqual(first,self.save(data))
        corrected=self.observation(stamp='2026-10-15T07:02:00+09:00',body=preview().replace('6.92','6.93'))
        second=self.save(corrected,now='2026-10-15T07:03:00+09:00')
        self.assertNotEqual(first,second)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM official_observations').fetchone()[0],2)
        for sql in ('UPDATE official_observations SET kind="raceresult"','DELETE FROM official_observations'):
            with self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)

    def test_asof_respects_capture_availability_and_actual_server_save_time(self):
        data=self.observation();self.save(data,now='2026-10-15T07:05:00+09:00')
        self.assertIsNone(latest_observation(self.db,data['race_id'],'beforeinfo',as_of='2026-10-15T07:04:59+09:00'))
        self.assertEqual(latest_observation(self.db,data['race_id'],'beforeinfo',as_of='2026-10-15T07:05:00+09:00')['data']['boats'][0]['display_time'],6.92)

    def test_future_backdated_and_cross_identity_snapshots_are_rejected(self):
        for field,value in (('captured_at','2026-10-15T08:00:00+09:00'),('available_at','2026-10-15T06:00:00+09:00'),
                            ('race_id','20261015-17-01'),('saved_at','2026-10-15T06:00:00+09:00')):
            data=self.observation();data[field]=value
            with self.subTest(field=field),self.assertRaises(SourceError): self.save(data)

    def test_final_market_and_post_cutoff_preview_never_enter_prerace_query(self):
        final=self.observation('odds3t',body=odds(final=True));self.save(final)
        self.assertIsNone(latest_observation(self.db,final['race_id'],'odds3t',as_of='2026-10-15T07:05:00+09:00',pre_race_only=True))
        after=self.observation(stamp='2026-10-15T09:00:00+09:00');self.save(after,now='2026-10-15T09:01:00+09:00')
        self.assertIsNone(latest_observation(self.db,after['race_id'],'beforeinfo',as_of='2026-10-15T09:05:00+09:00',pre_race_only=True))
        bad=copy.deepcopy(final);bad['eligible_pre_race']=True
        with self.assertRaises(SourceError): self.save(bad)

    def test_actual_fields_cannot_be_smuggled_into_preview_evidence(self):
        data=self.observation();data['data']['boats'][0]['actual_st']=0.10
        with self.assertRaises(SourceError): self.save(data)

    def test_importing_an_earlier_capture_after_closing_cannot_create_prerace_evidence(self):
        data=self.observation();self.save(data,now='2026-10-15T09:00:00+09:00')
        result=latest_observation(self.db,data['race_id'],'beforeinfo',as_of='2026-10-15T09:01:00+09:00')
        self.assertFalse(result['storage_eligible_pre_race'])
        self.assertIsNone(latest_observation(self.db,data['race_id'],'beforeinfo',as_of='2026-10-15T09:01:00+09:00',pre_race_only=True))
