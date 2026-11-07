"""Historical handoff checkpoint is a subset of the append-only day registry."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from race_ai.boat_freeze_index import load_original_race_ids
from race_ai.boat_deadline_queue import select_due_races

ROOT=Path(__file__).resolve().parents[1]
REAL=ROOT/'docs/evidence/2026-11-03/boat-canonical-freeze-index.json'
CHECK_AT='2026-11-04T09:00:00+09:00'

class CrossChatFreezeIndexTest(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(REAL.read_text(encoding='utf-8'))
        self.check_at=(max(datetime.fromisoformat(x['server_created_at'].replace('Z','+00:00')) for x in self.data['entries'])+timedelta(seconds=1)).isoformat()

    def check(self,change,clock=None):
        document=deepcopy(self.data); change(document)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'registry.json'; p.write_text(json.dumps(document,ensure_ascii=False),encoding='utf-8')
            return load_original_race_ids(p,as_of=clock or self.check_at)

    def test_verified_checkpoint_remains_present_as_registry_grows(self):
        ids=load_original_race_ids(REAL,as_of=self.check_at)
        expected={'17-02','17-03','17-04','17-07','04-06','22-06','09-07','06-07','02-07','04-07','21-11','22-07','17-08','18-11'}
        self.assertTrue({'20261103-'+x for x in expected}<=ids)
        self.assertEqual(len(ids),len(self.data['entries']))
        for rid in ('20261103-17-08','20261103-18-11'):
            row=next(r for r in self.data['entries'] if r['race_id']==rid)
            self.assertEqual((row['run_id'],row['artifact_id'],row['server_created_at']),(41577960865,13204251708,'2026-11-03T04:24:58Z'))
        self.assertEqual(sum(r['race_id']=='20261103-04-07' for r in self.data['entries']),1)

    def test_national_queue_deduplicates_other_chat_before_close(self):
        as_of='2026-11-03T13:37:00+09:00'
        def historic(d):
            d['entries']=[r for r in d['entries'] if datetime.fromisoformat(r['server_created_at'].replace('Z','+00:00'))<=datetime.fromisoformat(as_of)]
        originals=self.check(historic,as_of)
        def entry(venue,close):
            return {'race_id':f'20261103-{venue}-07','cutoff_at':f'2026-11-03T{close}:00+09:00','schedule_captured_at':'2026-11-03T13:36:00+09:00','source_sha256':'a'*64}
        result=select_due_races([entry('04','13:40'),entry('22','13:46'),entry('10','13:50')],as_of,already_frozen=originals)
        self.assertEqual([r['race_id'] for r in result['eligible']],['20261103-10-07'])
        self.assertEqual([r['reason'] for r in result['rejected']],['ALREADY_FROZEN','ALREADY_FROZEN'])
        self.assertFalse(result['freeze_proven'])

    def test_no_duplicate_or_aftercutoff_backfill(self):
        for mutation in (lambda d:d['entries'].append(deepcopy(d['entries'][0])),lambda d:d['entries'][0].update(server_created_at=d['entries'][0]['cutoff_at']),lambda d:d['entries'][0].update(server_created_at='2026-11-03T10:54:30+09:00'),lambda d:d['entries'][0].update(race_id='20261103-99-02'),lambda d:d['entries'][0].update(bundle_sha256='a'),lambda d:d.update(scope='ALL_NATIONAL'),lambda d:d['entries'][0].update(predicted_hit=1),lambda d:d['entries'][4].update(json_sha256='0'*64)):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): self.check(mutation)

    def test_next_day_uses_same_original_index_only_as_dedup(self):
        self.assertEqual(load_original_race_ids(REAL,as_of=self.check_at),load_original_race_ids(REAL,as_of=(datetime.fromisoformat(self.check_at)+timedelta(days=1)).isoformat()))
        with self.assertRaises(ValueError):load_original_race_ids(REAL,as_of='2026-11-03T10:00:00+09:00')

    def test_duplicate_json_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'registry.json';p.write_text('{"schema":"A","schema":"B"}')
            with self.assertRaises(ValueError):load_original_race_ids(p,as_of=self.check_at)

if __name__=='__main__':unittest.main()
