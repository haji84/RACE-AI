"""Source-free early BOAT owner admissibility when scheduled GitHub jobs are late.

The 2026-11-14 05:57 JST BOAT scheduled owner launcher was held because the
existing gate rejected all JST times before 06:00. The next observed eligible
BOAT run was 10:28 JST. This tests the simple fail-closed warm-start candidate,
not the cause of GitHub schedule delay or a real full-day forecast.
"""
import base64
from datetime import datetime
from zoneinfo import ZoneInfo
import unittest
from scripts.boat_main_dispatch_gate import decide, RELEASE_REF, RELEASE_SHA, RELEASE_TOKEN

JST=ZoneInfo('Asia/Tokyo')

def plan(at):
    return decide(now=datetime.fromisoformat(at),
        release=dict(ref='refs/heads/'+RELEASE_REF,object=dict(sha=RELEASE_SHA)),
        owner_doc=dict(encoding='base64',content=base64.b64encode(RELEASE_TOKEN.encode()).decode()),
        history=dict(total_count=0,workflow_runs=[]))

class EarlyOwnerAdmissionTests(unittest.TestCase):
    def test_actual_20261114_0557_jst_sourcefree_warm_start_can_prevent_first_gap(self):
        actual=plan('2026-11-14T05:57:00+09:00')
        self.assertTrue(actual['dispatch_allowed'])
        self.assertEqual(actual['status'],'READY_EXISTING_OWNER_WORKFLOW_ONLY')
        self.assertEqual(actual['official_source_requests'],0)
        self.assertFalse(actual['future_real_forecast_proven'])

    def test_previous_day_late_schedule_and_jst_0529_do_not_open_the_new_day(self):
        for instant in ('2026-11-13T23:57:00+09:00',
                        '2026-11-14T00:02:00+09:00',
                        '2026-11-14T05:29:59+09:00'):
            with self.subTest(instant=instant):
                out=plan(instant)
                # Normal old-day permissions elsewhere still exist; no access
                # to the following day is falsely authorized at midnight.
                self.assertFalse(out['dispatch_allowed'])
                self.assertEqual(out['status'],'HOLD_OUTSIDE_OWNER_DAYTIME_WINDOW')

    def test_0530_is_first_eligible_window_but_still_not_forecast_proof(self):
        for instant in ('2026-11-14T05:30:00+09:00','2026-11-14T06:20:00+09:00'):
            with self.subTest(at=instant):
                result=plan(instant)
                self.assertTrue(result['dispatch_allowed'])
                self.assertFalse(result['future_real_forecast_proven'])
                self.assertEqual(result['official_source_requests'],0)

    def test_bad_ref_policy_or_unknown_run_history_still_fails_closed(self):
        now=datetime.fromisoformat('2026-11-14T05:57:00+09:00')
        good=dict(ref='refs/heads/'+RELEASE_REF,object=dict(sha=RELEASE_SHA))
        base=dict(now=now,release=good,
                  owner_doc=dict(encoding='base64',content=base64.b64encode(RELEASE_TOKEN.encode()).decode()),
                  history=dict(total_count=0,workflow_runs=[]))
        for patch in (dict(release=dict(ref='refs/heads/'+RELEASE_REF,object=dict(sha='0'*40))),
                      dict(owner_doc=dict(encoding='base64',content=base64.b64encode(b'UNRELEASED').decode())),
                      dict(history=dict(total_count=10,workflow_runs=[]))):
            with self.subTest(changed=patch):
                args=dict(base,**patch)
                self.assertFalse(decide(**args)['dispatch_allowed'])

if __name__=='__main__':
    unittest.main()
