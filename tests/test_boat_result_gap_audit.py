"""GitHub-only BOAT schedule liveness tests; no official source requests."""
from datetime import datetime,timezone
from copy import deepcopy
import unittest
from scripts.boat_result_gap_audit import inspect_runs,BOAT

NOW=datetime(2026,11,12,8,30,tzinfo=timezone.utc)
def item(id,at,event='schedule',name=BOAT,conclusion='success'):
    return dict(id=id,created_at=at,event=event,name=name,
                status='completed',conclusion=conclusion)

class GapAuditTests(unittest.TestCase):
    def test_missing_schedule_at_active_jst_time_is_a_real_gap_not_new_get_budget(self):
        data=dict(workflow_runs=[
            item(42,'2026-11-12T06:43:51Z'),
            item(50,'2026-11-12T08:25:00Z','push'),
            item(49,'2026-11-12T08:29:00Z','schedule','KEIRIN scheduled unrelated')])
        before=deepcopy(data)
        report=inspect_runs(data,now=NOW)
        self.assertEqual(report['status'],'SCHEDULE_GAP_CONFIRMED')
        self.assertEqual(report['latest_scheduled_at'],'2026-11-12T06:43:51+00:00')
        self.assertGreater(report['latest_scheduled_age_seconds'],3600)
        self.assertEqual(report['requested_source_gets'],0)
        self.assertFalse(report['source_budget_extended'])
        self.assertFalse(report['source_get_recovery_proven'])
        self.assertEqual(data,before)

    def test_real_recent_schedule_not_misclassified(self):
        data=dict(workflow_runs=[item(1,'2026-11-12T08:24:30Z')])
        report=inspect_runs(data,now=NOW)
        self.assertEqual(report['status'],'SCHEDULE_EVENT_SEEN')
        self.assertEqual(report['checked_run_count'],1)

    def test_no_schedule_not_invented_out_of_normal_window(self):
        late=datetime(2026,11,12,16,30,tzinfo=timezone.utc)
        data=dict(workflow_runs=[item(1,'2026-11-12T06:43:51Z')])
        report=inspect_runs(data,now=late)
        self.assertEqual(report['status'],'SCHEDULE_WINDOW_INACTIVE')
        self.assertFalse(report['window_active'])

    def test_no_schedule_history_returns_hold_not_fake_live(self):
        report=inspect_runs(dict(workflow_runs=[]),now=NOW)
        self.assertEqual(report['status'],'SCHEDULE_GAP_CONFIRMED')
        self.assertIsNone(report['latest_scheduled_at'])
        self.assertEqual(report['requested_source_gets'],0)

    def test_untrusted_future_or_conflicting_run_identity_fails_closed(self):
        sample=dict(workflow_runs=[item(1,'2026-11-12T08:10:00Z'),
                                   item(1,'2026-11-12T08:11:00Z')])
        with self.assertRaises(ValueError):inspect_runs(sample,now=NOW)
        with self.assertRaises(ValueError):
            inspect_runs(dict(workflow_runs=[item(1,'2026-11-13T02:00:00Z')]),now=NOW)
        with self.assertRaises(ValueError):
            inspect_runs(dict(workflow_runs=[]),now=NOW,gap_minutes=1)

if __name__=='__main__':unittest.main()
