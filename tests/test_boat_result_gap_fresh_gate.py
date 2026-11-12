"""Synthetic fail-closed contract for a missed BOAT schedule fresh-result attempt."""
import unittest
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from scripts.boat_result_gap_fresh_gate import inspect,FRESH,BOAT
NOW=datetime(2030,4,1,12,0,tzinfo=timezone.utc)
def stamp(minutes):return (NOW+timedelta(minutes=minutes)).isoformat()
def run(ident,minutes,event='schedule',name=BOAT,status='completed',title=''):
    return dict(id=ident,created_at=stamp(minutes),event=event,name=name,
                head_branch='main',status=status,display_title=title)
def fixture():
    boat=dict(workflow_runs=[run(50,-150),run(51,-120)])
    recovery=dict(workflow_runs=[run(99,-1,'workflow_run','BOAT schedule-gap retained-result recovery')])
    source=dict(last_checked_at=stamp(-130),due_count=17,boatrace_hold_until=None)
    return boat,recovery,[],source
class FreshGateTests(unittest.TestCase):
    def decision(self,parts=None,**overrides):
        return inspect(*(parts or fixture()),now=overrides.get('now',NOW),
                       current_run_id=overrides.get('current_run_id',99),
                       run_attempt=overrides.get('run_attempt',1))
    def test_adaptive_bounded_source_gets_preserve_owner_240(self):
        ans=self.decision();self.assertEqual(ans['status'],'FRESH_RESULT_GET_ADMITTED')
        self.assertEqual(ans['authorized_source_gets'],17)
        self.assertTrue(ans['source_owner_240_unchanged'])

    def test_recovery_schedule_uses_same_guards_as_workflow_run_and_never_resets_budget(self):
        parts=list(fixture())
        parts[1]['workflow_runs'][0]['event']='schedule'
        actual=self.decision(parts)
        self.assertEqual(actual['status'],'FRESH_RESULT_GET_ADMITTED')
        self.assertEqual(actual['authorized_source_gets'],17)
        self.assertTrue(actual['source_owner_240_unchanged'])
        self.assertEqual(self.decision(parts,run_attempt=2)['status'],'HOLD_ATTEMPT_RETRY')
        parts[0]['workflow_runs'].append(run(52,-4))
        self.assertEqual(self.decision(parts)['status'],'HOLD_SCHEDULE_RECENT')
        parts[0]['workflow_runs'].pop()
        parts[2].append(dict(run_id=98,created_at=stamp(-10),job_name=FRESH))
        self.assertEqual(self.decision(parts)['status'],'HOLD_ALREADY_ATTEMPTED_IN_WINDOW')

    def test_backlog_above_thirty_six_uses_strict_36_not_unlimited(self):
        p=list(fixture());p[3]['due_count']=85
        d=self.decision(p)
        self.assertEqual(d['authorized_source_gets'],36)
        self.assertTrue(d['source_owner_240_unchanged'])
        p[3]['due_count']=3
        self.assertEqual(self.decision(p)['authorized_source_gets'],12)
        p[3]['due_count']=24
        self.assertEqual(self.decision(p)['authorized_source_gets'],24)
        p[3]['boatrace_hold_until']=stamp(200)
        self.assertEqual(self.decision(p)['authorized_source_gets'],0)

    def test_only_within_live_jst_window(self):
        a=self.decision(now=datetime(2030,4,1,15,0,tzinfo=timezone.utc))
        self.assertEqual(a['status'],'HOLD_OUTSIDE_JST_WINDOW')
    def test_recent_schedule_blocks(self):
        parts=list(fixture());parts[0]['workflow_runs'].append(run(52,-5))
        self.assertEqual(self.decision(parts)['status'],'HOLD_SCHEDULE_RECENT')
    def test_missing_schedule_blocks_even_if_long_gap(self):
        parts=list(fixture());parts[0]['workflow_runs']=[]
        self.assertEqual(self.decision(parts)['status'],'HOLD_NO_TRUSTED_SCHEDULE')
    def test_recent_encrypted_state_or_active_denial_blocks(self):
        parts=list(fixture());parts[3]['last_checked_at']=stamp(-10)
        self.assertEqual(self.decision(parts)['status'],'HOLD_SOURCE_RECENT')
        parts=list(fixture());parts[3]['boatrace_hold_until']=stamp(200)
        self.assertEqual(self.decision(parts)['status'],'HOLD_PROVIDER_DENIAL')
    def test_no_due_result_blocks(self):
        parts=list(fixture());parts[3]['due_count']=0
        self.assertEqual(self.decision(parts)['status'],'HOLD_NO_PENDING_DUE_RESULTS')
    def test_one_attempt_per_30_minute_window_including_failed_attempt(self):
        parts=list(fixture());parts[2].append(dict(run_id=98,created_at=stamp(-3),job_name=FRESH))
        self.assertEqual(self.decision(parts)['status'],'HOLD_ALREADY_ATTEMPTED_IN_WINDOW')
        parts[2][0]['created_at']=stamp(-40)
        self.assertEqual(self.decision(parts)['status'],'FRESH_RESULT_GET_ADMITTED')
    def test_queued_collector_blocks_to_preserve_single_writer(self):
        for status in ['queued','pending','in_progress','waiting']:
            parts=list(fixture());parts[0]['workflow_runs'].append(run(53,-80,'workflow_dispatch',status=status))
            self.assertEqual(self.decision(parts)['status'],'HOLD_ORIGINAL_COLLECTOR_ACTIVE')
    def test_recent_manual_result_job_blocks_but_sourcefree_push_does_not(self):
        parts=list(fixture());parts[0]['workflow_runs'].append(run(53,-5,'push',title='boat-result-refresh: test'))
        self.assertEqual(self.decision(parts)['status'],'HOLD_ORIGINAL_COLLECTOR_RECENT')
        parts[0]['workflow_runs'][-1]['display_title']='boat-owner-readback: no GET'
        self.assertEqual(self.decision(parts)['status'],'FRESH_RESULT_GET_ADMITTED')
    def test_no_retry_or_duplicate_origin_or_history_truncation(self):
        self.assertEqual(self.decision(run_attempt=2)['status'],'HOLD_ATTEMPT_RETRY')
        parts=list(fixture());parts[1]['workflow_runs']=[]
        with self.assertRaisesRegex(ValueError,'CURRENT_ORIGIN'):self.decision(parts)
        parts=list(fixture());parts[0]['workflow_runs']=[run(i,-i*0.1) for i in range(1,101)]
        with self.assertRaisesRegex(ValueError,'RUN_HISTORY_TRUNCATED'):self.decision(parts)

    def test_strict_real_readback_python_is_syntax_valid_and_source_free(self):
        import ast
        import textwrap
        from pathlib import Path
        workflow=Path('.github/workflows/boat-result-gap-recovery.yml').read_text()
        for label in (
            'Read sealed source freshness and genuinely due result count without provider GET',
            'Require actual new official result and no source-limit bypass',
            'Reopen actual saved AES result and verify unchanged prediction inventory',
        ):
            segment=workflow.split('      - name: '+label+'\n',1)[1]
            source=segment.split("python - <<'PY'\n",1)[1].split('\n          PY',1)[0]
            ast.parse(textwrap.dedent(source),filename=label)
        assert "assert after_final>baseline['before_final']" in workflow
        assert "assert digest==os.environ['EXPECTED_RESULT_DIGEST']" in workflow
        assert "assert inventory==os.environ['EXPECTED_INVENTORY_DIGEST']" in workflow
        assert "assert loaded['previous']['head']['cipher_sha256']==os.environ['EXPECTED_SOURCE_CIPHER']" in workflow
        assert "assert 0<report['source_requests']<=12" in workflow
