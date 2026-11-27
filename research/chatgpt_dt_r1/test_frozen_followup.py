"""Regression checks for the frozen followup boundary and immutable source."""
import tempfile
import unittest
from hashlib import sha1, sha256
from pathlib import Path
from unittest.mock import patch
from research.chatgpt_dt_r1.frozen_followup import (
    DAYS, select_records, file_pins, blind_target, target_features)
from research.chatgpt_dt_r1.data import input_digest


class FollowupTests(unittest.TestCase):
    def test_new_interval_never_replaces_old_history(self):
        old=[{'day':'2026-11-22','race_id':'old'}]
        new=[{'day':'2026-11-22','race_id':'old','changed':True}]
        new += [{'day':d,'race_id':d} for d in DAYS]
        new.append({'day':'2026-11-27','race_id':'later'})
        records, targets=select_records(old,new)
        self.assertEqual(records[0],old[0])
        self.assertEqual(len(targets),4)
        self.assertEqual(len(records),5)
        with self.assertRaisesRegex(ValueError,'NEW_WINDOW_INCOMPLETE'):
            select_records(old,new[:-2])

    def test_pin_matches_git_object_and_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test'; raw=b'abc'; p.write_bytes(raw)
            pin=sha1(b'blob 3\0'+raw).hexdigest()
            self.assertEqual(file_pins(p,3,pin),sha256(raw).hexdigest())
            with self.assertRaisesRegex(ValueError,'NEW_ARCHIVE_GIT_BLOB_MISMATCH'):
                file_pins(p,3,'0'*40)
            with self.assertRaisesRegex(ValueError,'NEW_ARCHIVE_SIZE_MISMATCH'):
                file_pins(p,4,pin)

    def test_blind_target_and_whole_day_before_history_update(self):
        def row(day,rid):
            r={'day':day,'race_id':rid,'result_rows':[{'rank':1}],
               'finish':[1,2,3],'top3':[1,2,3],'result_status':'COMPLETE',
               'archived_weather':{'wind':99}}
            r['input_sha256']=input_digest(r)
            return r
        rows=[row('2026-11-22','old'),row(DAYS[0],'a'),row(DAYS[0],'b'),
              row(DAYS[1],'c')]
        events=[]
        class Builder:
            def transform(self,r):
                events.append(('predict',r['race_id']))
                self_check.assertNotIn('top3',r)
                self_check.assertNotIn('result_rows',r)
                self_check.assertNotIn('archived_weather',r)
                return r
            def update_day(self,rs):
                events.append(('history',','.join(r['race_id'] for r in rs)))
        self_check=self
        with patch('research.chatgpt_dt_r1.frozen_followup.FeatureBuilder',Builder):
            target_features(rows)
        self.assertEqual(events,[('history','old'),('predict','a'),('predict','b'),
                                 ('history','a,b'),('predict','c'),('history','c')])
        self.assertEqual(input_digest(blind_target(rows[1])),rows[1]['input_sha256'])
