import copy
from datetime import datetime
import hashlib
import json
import sqlite3
import unittest
from unittest.mock import patch

from race_ai.core import SourceError
from race_ai.race_update_merge import merge_race_updates
from race_ai.official_observation_store import setup_store,save_observation,latest_observation
from race_ai.official_race_updates import parse_update,endpoint
from tests.test_official_race_updates import DAY,page,preview,odds,results
from tests.test_today_blob_reader import payload


class RaceUpdateMergeTests(unittest.TestCase):
    def rehash(self,record):
        raw={key:value for key,value in record.items() if key not in {'snapshot_id','saved_at','storage_eligible_pre_race'}}
        record['snapshot_id']=hashlib.sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()
        return record

    def observation(self,kind='beforeinfo',capture='2026-10-15T07:00:00+09:00',saved='2026-10-15T07:01:00+09:00',body=None):
        body=body or {'beforeinfo':preview,'odds3t':odds,'raceresult':results}[kind]()
        parsed=parse_update(page(kind,body),kind=kind,day=DAY,venue='18',race_no=1,
            source_url=endpoint(DAY,'18',1,kind),captured_at=capture)
        with sqlite3.connect(':memory:') as db:
            setup_store(db)
            with patch('race_ai.official_observation_store.utc_now',return_value=datetime.fromisoformat(saved)):
                save_observation(db,parsed)
            return latest_observation(db,parsed['race_id'],kind,as_of='2026-10-15T10:00:00+09:00')

    def feed(self):
        data=payload()
        for boat in data['venues'][0]['races'][0]['boats']: boat['name']='選手'+str(boat['lane'])
        data['sources']=[{key:data[key] for key in ('source_url','source_sha256','first_observed_at')}]
        return data

    def merge(self,data,observations,**kwargs):
        return merge_race_updates(data,observations,now=datetime.fromisoformat('2026-10-15T10:00:00+09:00'),**kwargs)

    def test_default_summary_preserves_program_and_global_sources(self):
        original=self.feed();unchanged=copy.deepcopy(original)
        merged=self.merge(original,[self.observation()])
        self.assertEqual(original,unchanged)
        self.assertEqual(merged['sources'],original['sources'])
        race=merged['venues'][0]['races'][0]
        self.assertEqual(race['boats'],original['venues'][0]['races'][0]['boats'])
        self.assertTrue(race['official_updates']['summary_only'])
        self.assertNotIn('data',race['official_updates']['records'][0])

    def test_full_bundle_keeps_revision_history_and_latest_per_kind(self):
        first=self.observation();second=self.observation(capture='2026-10-15T07:02:00+09:00',saved='2026-10-15T07:03:00+09:00',body=preview().replace('6.92','6.93'))
        merged=self.merge(self.feed(),[second,first],summary_only=False)
        bundle=merged['venues'][0]['races'][0]['official_updates']
        self.assertEqual(set(bundle),{'schema_version','race_id','records','latest'})
        self.assertEqual(len(bundle['records']),2)
        self.assertEqual(bundle['latest']['beforeinfo'],second['snapshot_id'])
        repeated=self.merge(merged,[first],summary_only=False)
        self.assertEqual(len(repeated['venues'][0]['races'][0]['official_updates']['records']),2)
        self.assertEqual(len(repeated['sources']),1)

    def test_cross_race_registration_cutoff_and_hash_conflicts_fail_closed(self):
        for change in (lambda o:o.update(race_id='20261015-17-01'),
                       lambda o:o['data']['boats'][0].update(racer_registration_id='4999'),
                       lambda o:o.update(closed_at='2026-10-15T09:43:00+09:00'),
                       lambda o:o.update(snapshot_id='b'*64)):
            record=self.observation();change(record)
            with self.subTest(change=change),self.assertRaises(SourceError): self.merge(self.feed(),[record])

    def test_odds_source_names_bind_to_program_registration_without_inventing_ids(self):
        record=self.observation('odds3t')
        merged=self.merge(self.feed(),[record],summary_only=False)
        saved=merged['venues'][0]['races'][0]['official_updates']['records'][0]
        self.assertIsNone(saved['data']['racers'][0]['racer_registration_id'])
        feed=self.feed();feed['venues'][0]['races'][0]['boats'][0]['name']='別の選手'
        with self.assertRaises(SourceError): self.merge(feed,[record])

    def test_final_odds_late_saved_preview_and_results_remain_outside_prerace(self):
        observations=[self.observation('odds3t',body=odds(final=True)),
            self.observation(capture='2026-10-15T09:00:00+09:00',saved='2026-10-15T09:01:00+09:00'),
            self.observation('raceresult',capture='2026-10-15T09:00:00+09:00',saved='2026-10-15T09:01:00+09:00')]
        merged=self.merge(self.feed(),observations,summary_only=False)
        records=merged['venues'][0]['races'][0]['official_updates']['records']
        self.assertTrue(all(not record['storage_eligible_pre_race'] for record in records))
        self.assertEqual({record['kind'] for record in records},{'beforeinfo','odds3t','raceresult'})

    def test_summary_is_small_even_with_all120_odds(self):
        summary=self.merge(self.feed(),[self.observation('odds3t')])
        full=self.merge(self.feed(),[self.observation('odds3t')],summary_only=False)
        self.assertLess(len(json.dumps(summary)),len(json.dumps(full))/2)

    def test_summary_remerge_keeps_latest_and_requires_full_history_to_expand(self):
        first=self.observation();second=self.observation(capture='2026-10-15T07:02:00+09:00',saved='2026-10-15T07:03:00+09:00',body=preview().replace('6.92','6.93'))
        summary=self.merge(self.feed(),[first,second])
        again=self.merge(summary,[first])['venues'][0]['races'][0]['official_updates']
        self.assertEqual(len(again['records']),1)
        self.assertEqual(again['latest']['beforeinfo'],second['snapshot_id'])
        self.assertIsNone(again['source_record_count'])
        with self.assertRaises(SourceError): self.merge(summary,[first],summary_only=False)

    def test_valid_content_hash_cannot_override_phase_or_actual_save_boundary(self):
        for field,value in (('information_phase','official_result'),('storage_eligible_pre_race',False),
                            ('upstream_published_at','2026-10-15T06:59:00+09:00')):
            record=self.observation();record[field]=value;self.rehash(record)
            with self.subTest(field=field),self.assertRaises(SourceError): self.merge(self.feed(),[record])

    def test_existing_summary_cannot_relabel_final_odds_as_prerace(self):
        summary=self.merge(self.feed(),[self.observation('odds3t',body=odds(final=True))])
        existing=summary['venues'][0]['races'][0]['official_updates']['records'][0]
        existing['eligible_pre_race']=True;existing['storage_eligible_pre_race']=True
        with self.assertRaises(SourceError): self.merge(summary,[self.observation()])

    def test_invalid_batch_leaves_original_unchanged(self):
        original=self.feed();unchanged=copy.deepcopy(original)
        invalid=self.observation('odds3t');invalid['data']['odds'][0]['combination']=[1,1,2];self.rehash(invalid)
        with self.assertRaises(SourceError): self.merge(original,[self.observation(),invalid])
        self.assertEqual(original,unchanged)
