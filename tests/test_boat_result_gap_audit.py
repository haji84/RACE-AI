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


class GapWorkflowProjectionTests(unittest.TestCase):
    def query(self, payload):
        import json,re,subprocess
        from pathlib import Path
        text=(Path(__file__).resolve().parents[1]/'.github/workflows/boat-result-gap-recovery.yml').read_text()
        observed=text.split('\n  observed_gap:\n',1)[1].split('\n  fresh_result:\n',1)[0]
        step=observed.split('- name: Read actual GitHub schedule history only',1)[1].split('- name: Audit source-free recovery eligibility',1)[0]
        self.assertEqual(step.count('gh api'),1)
        self.assertIn('actions/workflows/boat-racer-daily.yml/runs?event=schedule&per_page=100',step)
        self.assertNotIn('--paginate',step)
        match=re.search(r"--jq '([^']+)'",step)
        self.assertIsNotNone(match,'full unused API metadata still reaches the bounded audit file')
        return subprocess.run(['jq','-c',match[1]],input=json.dumps(payload).encode(),
                              capture_output=True,timeout=10)

    def project(self, payload):
        import json
        result=self.query(payload)
        self.assertEqual(result.returncode,0,'history projection rejected a valid fixture')
        return json.loads(result.stdout)

    def test_rich_metadata_is_compacted_before_the_unchanged_file_bound(self):
        import io,json,tempfile
        from contextlib import redirect_stdout
        from pathlib import Path
        from unittest.mock import patch
        from scripts.boat_result_gap_audit import main
        data=dict(total_count=245,workflow_runs=[
            dict(item(number,'2026-11-12T08:24:30Z'),
                 repository=dict(unused_fixture_padding='x'*6000))
            for number in range(1,101)])
        before=deepcopy(data)
        raw=json.dumps(data).encode()
        self.assertGreater(len(raw),512000)
        projected=self.project(data)
        self.assertEqual(len(projected['workflow_runs']),100)
        self.assertEqual([row['id'] for row in projected['workflow_runs']],list(range(1,101)))
        self.assertEqual(set(projected),{'workflow_runs'})
        self.assertTrue(all(set(row)=={'id','name','event','created_at'} for row in projected['workflow_runs']))
        compact=json.dumps(projected).encode()
        self.assertLessEqual(len(compact),512000)
        self.assertEqual(inspect_runs(projected,now=NOW),inspect_runs(data,now=NOW))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'runs.json'; output=root/'proof.json'
            source.write_bytes(raw)
            args=['--runs',str(source),'--output',str(output),'--now',NOW.isoformat()]
            with self.assertRaisesRegex(ValueError,'^BOAT_GAP_INPUT_BOUND$'): main(args)
            self.assertFalse(output.exists())
            source.write_bytes(compact)
            with patch('urllib.request.urlopen',side_effect=AssertionError('official GET')),redirect_stdout(io.StringIO()):
                self.assertEqual(main(args),0)
            self.assertEqual(json.loads(output.read_bytes()),inspect_runs(data,now=NOW))
        self.assertEqual(data,before)

    def test_projection_preserves_gap_recent_inactive_and_empty_decisions(self):
        for rows,now in (([item(1,'2026-11-12T06:43:51Z')],NOW),
                         ([item(1,'2026-11-12T08:24:30Z')],NOW),
                         ([],NOW),
                         ([],datetime(2026,11,12,16,30,tzinfo=timezone.utc)),
                         ([item(1,'2026-11-12T08:24:30Z','push'),
                           item(2,'2026-11-12T08:24:30Z',name='unrelated')],NOW)):
            data=dict(workflow_runs=rows)
            with self.subTest(rows=len(rows),hour=now.hour):
                report=inspect_runs(self.project(data),now=now)
                self.assertEqual(report,inspect_runs(data,now=now))
                self.assertEqual(report['requested_source_gets'],0)
                self.assertFalse(report['source_budget_extended'])
                self.assertFalse(report['source_get_recovery_proven'])

    def test_projection_does_not_launder_bad_envelopes_or_drop_extra_rows(self):
        for data in ([],{},dict(workflow_runs=None),dict(workflow_runs={}),
                     dict(workflow_runs=[None]),dict(workflow_runs=[1]),
                     dict(workflow_runs=['bad']),
                     dict(workflow_runs=[item(n,'2026-11-12T08:24:30Z') for n in range(1,102)])):
            with self.subTest(kind=type(data).__name__):
                self.assertNotEqual(self.query(data).returncode,0)

    def test_required_field_types_future_and_conflicting_identity_still_refuse(self):
        samples=([item(True,'2026-11-12T08:24:30Z')],
                 [item('1','2026-11-12T08:24:30Z')],
                 [item(1.5,'2026-11-12T08:24:30Z')],
                 [item(1,None)],[item(1,'2026-11-13T02:00:00Z')],
                 [item(1,'2026-11-12T08:10:00Z'),item(1,'2026-11-12T08:11:00Z')])
        for rows in samples:
            data=dict(workflow_runs=rows)
            with self.subTest(rows=len(rows)):
                with self.assertRaises(ValueError): inspect_runs(data,now=NOW)
                with self.assertRaises(ValueError): inspect_runs(self.project(data),now=NOW)

    def test_compacted_input_keeps_path_and_output_refusals(self):
        import json,tempfile
        from pathlib import Path
        from scripts.boat_result_gap_audit import main
        data=self.project(dict(workflow_runs=[]))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'runs.json'; output=root/'proof.json'
            source.write_text(json.dumps(data)); link=root/'linked.json'; link.symlink_to(source)
            with self.assertRaisesRegex(ValueError,'^BOAT_GAP_INPUT_BOUND$'):
                main(['--runs',str(link),'--output',str(output),'--now',NOW.isoformat()])
            self.assertFalse(output.exists())
            output.write_text('preserved')
            with self.assertRaisesRegex(ValueError,'^BOAT_GAP_OUTPUT_EXISTS$'):
                main(['--runs',str(source),'--output',str(output),'--now',NOW.isoformat()])
            self.assertEqual(output.read_text(),'preserved')

if __name__=='__main__':unittest.main()
