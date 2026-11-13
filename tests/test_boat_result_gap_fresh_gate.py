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
    def test_adaptive_bounded_source_gets_without_hourly_cap(self):
        ans=self.decision();self.assertEqual(ans['status'],'FRESH_RESULT_GET_ADMITTED')
        self.assertEqual(ans['authorized_source_gets'],17)
        self.assertTrue(ans['recovery_hourly_cap_removed'])
        self.assertTrue(ans['source_owner_240_unchanged'])

    def test_recovery_schedule_respects_guard_not_hourly_timer(self):
        parts=list(fixture())
        parts[1]['workflow_runs'][0]['event']='schedule'
        self.assertEqual(self.decision(parts)['authorized_source_gets'],17)
        self.assertEqual(self.decision(parts,run_attempt=2)['status'],'HOLD_ATTEMPT_RETRY')
        parts[0]['workflow_runs'].append(run(52,-4))
        self.assertEqual(self.decision(parts)['status'],'HOLD_SCHEDULE_RECENT')
        parts[0]['workflow_runs'].pop()
        parts[2].append(dict(run_id=98,created_at=stamp(-10),
                             job_status='completed',job_name=FRESH))
        self.assertEqual(self.decision(parts)['authorized_source_gets'],17)

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
    def test_recent_encrypted_state_does_not_force_pause_but_denial_stops(self):
        parts=list(fixture());parts[3]['last_checked_at']=stamp(-10)
        self.assertEqual(self.decision(parts)['status'],'FRESH_RESULT_GET_ADMITTED')
        parts=list(fixture());parts[3]['boatrace_hold_until']=stamp(200)
        self.assertEqual(self.decision(parts)['status'],'HOLD_PROVIDER_DENIAL')
    def test_no_due_result_blocks(self):
        parts=list(fixture());parts[3]['due_count']=0
        self.assertEqual(self.decision(parts)['status'],'HOLD_NO_PENDING_DUE_RESULTS')
    def test_back_to_back_attempts_no_30m_or_60m_pause(self):
        parts=list(fixture());parts[3]['due_count']=85
        for idx in range(15):
            parts[2].append(dict(run_id=100+idx,created_at=stamp(-idx-1),
                                 job_status='completed',job_name=FRESH,
                                 provider_step_attempted=True))
        result=self.decision(parts)
        self.assertEqual(result['status'],'FRESH_RESULT_GET_ADMITTED')
        self.assertEqual(result['authorized_source_gets'],36)
        self.assertTrue(result['recovery_hourly_cap_removed'])

    def test_completed_primary_runs_do_not_create_hidden_hourly_limit(self):
        parts=list(fixture());parts[3]['due_count']=85
        for idx in range(20):
            parts[0]['workflow_runs'].append(
                run(60+idx,-idx-20,'workflow_dispatch',status='completed'))
        result=self.decision(parts)
        self.assertEqual(result['authorized_source_gets'],36)

    def test_active_prior_source_job_blocks_without_timer(self):
        parts=list(fixture())
        parts[2].append(dict(run_id=97,created_at=stamp(-1),
                             job_status='in_progress',job_name=FRESH))
        self.assertEqual(self.decision(parts)['status'],
                         'HOLD_PRIOR_SOURCE_JOB_ACTIVE')
        parts[2][-1]['job_status']='completed'
        self.assertEqual(self.decision(parts)['status'],'FRESH_RESULT_GET_ADMITTED')

    def test_failed_preflight_does_not_create_hourly_pause(self):
        parts=list(fixture());parts[3]['due_count']=85
        for number in range(91,94):
            parts[2].append(dict(run_id=number,created_at=stamp(-4),
                                 provider_step_attempted=False,
                                 job_status='completed',job_name=FRESH))
        self.assertEqual(self.decision(parts)['authorized_source_gets'],36)

    def test_queued_collector_blocks_to_preserve_single_writer(self):
        for status in ['queued','pending','in_progress','waiting']:
            parts=list(fixture());parts[0]['workflow_runs'].append(run(53,-80,'workflow_dispatch',status=status))
            self.assertEqual(self.decision(parts)['status'],'HOLD_ORIGINAL_COLLECTOR_ACTIVE')
    def test_recent_manual_result_job_blocks_but_sourcefree_push_does_not(self):
        parts=list(fixture());parts[0]['workflow_runs'].append(run(53,-5,'push',title='boat-result-refresh: test'))
        self.assertEqual(self.decision(parts)['status'],'FRESH_RESULT_GET_ADMITTED')
        parts[0]['workflow_runs'][-1]['display_title']='boat-owner-readback: no GET'
        self.assertEqual(self.decision(parts)['status'],'FRESH_RESULT_GET_ADMITTED')
    def test_no_retry_or_duplicate_origin_or_history_truncation(self):
        self.assertEqual(self.decision(run_attempt=2)['status'],'HOLD_ATTEMPT_RETRY')
        parts=list(fixture());parts[1]['workflow_runs']=[]
        with self.assertRaisesRegex(ValueError,'CURRENT_ORIGIN'):self.decision(parts)
        parts=list(fixture());parts[0]['workflow_runs']=[run(i,-i*0.1) for i in range(1,101)]
        with self.assertRaisesRegex(ValueError,'RUN_HISTORY_TRUNCATED'):self.decision(parts)

    def test_verified_new_result_dispatch_has_no_30_minute_sleep_or_source_get(self):
        from pathlib import Path
        workflow=Path('.github/workflows/boat-result-gap-recovery.yml').read_text()
        assert "options: ['2', 'catchup']" in workflow
        section=workflow.split('\n  source_free_followup:\n',1)[1]
        assert 'needs: [fresh_result, fresh_readback]' in section
        assert "needs.fresh_result.outputs.new_results == 'true'" in section
        assert "needs.fresh_readback.result == 'success'" in section
        assert 'gh workflow run boat-result-gap-recovery.yml --repo "$GITHUB_REPOSITORY" --ref main -f cycle=catchup' in section
        assert 'sync-results' not in section and 'www.boatrace.jp' not in section
        assert "RACE_AI_BOAT_RESULT_GET_CAP" in workflow
        assert "\n  source_free_followup:\n" not in workflow.split(
            '\n  observed_gap:\n',1)[0]
        assert "inputs.cycle == 'catchup'" in workflow
        gate=Path('scripts/boat_result_gap_fresh_gate.py').read_text()
        assert 'RECOVERY_BUDGET_60M' not in gate
        assert 'OWNER_BUDGET_60M' not in gate
        assert 'MAX_RECOVERY_GETS_PER_CYCLE=36' in gate

    def test_no_new_formal_final_is_source_free_hold_without_followup(self):
        from pathlib import Path
        workflow=Path('.github/workflows/boat-result-gap-recovery.yml').read_text()
        source=workflow.split(
            '      - name: Require actual new official result and no source-limit bypass',1
        )[1].split('      - name:',1)[0]
        self.assertIn("assert after_final>=baseline['before_final']",source)
        self.assertIn("assert inventory==baseline['inventory_digest']",source)
        self.assertIn("if after_final==baseline['before_final']:",source)
        self.assertIn("'BOAT_NO_NEW_FORMAL_FINAL_HOLD'",source)
        self.assertIn('raise SystemExit(0)',source)
        self.assertIn('assert after_final>baseline[',source)
        self.assertLess(source.index("assert inventory==baseline['inventory_digest']"),
                        source.index("if after_final==baseline['before_final']:"))
        self.assertLess(source.index('raise SystemExit(0)'),
                        source.index("stream.write('new_results=true"))
        follow=workflow.split('  source_free_followup:',1)[1]
        self.assertIn("needs.fresh_result.outputs.new_results == 'true'",follow)

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
            tree=ast.parse(textwrap.dedent(source),filename=label)
            # Syntax parsing alone does not detect an undefined os variable.
            # Keep the owner preflight from silently failing before provider GET.
            if any(isinstance(node,ast.Name) and node.id=='os'
                   for node in ast.walk(tree)):
                self.assertTrue(any(isinstance(node,ast.Import) and
                    any(alias.name=='os' for alias in node.names)
                    for node in tree.body), 'os used without import: '+label)
        assert "assert after_final>baseline['before_final']" in workflow
        assert "assert digest==os.environ['EXPECTED_RESULT_DIGEST']" in workflow
        assert "assert inventory==os.environ['EXPECTED_INVENTORY_DIGEST']" in workflow
        assert "assert loaded['previous']['head']['cipher_sha256']==os.environ['EXPECTED_SOURCE_CIPHER']" in workflow
        assert "assert 0<report['source_requests']<=int(os.environ['EXPECTED_SOURCE_GET_CAP'])<=36" in workflow
        assert "source_get_cap" in workflow
