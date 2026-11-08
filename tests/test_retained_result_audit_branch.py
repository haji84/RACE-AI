"""Existing worker branch routing, with inert commands and no credentials."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
BRANCH='codex/retained-result-audit-20261108'


class RetainedResultAuditBranchTests(unittest.TestCase):
    def setUp(self):
        self.workflow=yaml.load((ROOT/'.github/workflows/boat-racer-daily.yml').read_text(),Loader=yaml.BaseLoader)
        self.step=next(s for s in self.workflow['jobs']['daily']['steps'] if s.get('name','').startswith('Reflect confirmed'))

    def run_script(self,*,branch=BRANCH,subject='retained-result-audit: inspect retained fields',actor='173585154',daily='false',browser=False,fail_replay=False):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);commands=root/'bin';commands.mkdir();log=root/'calls'
            for name,body in [('git','printf "%s\\n" "$SUBJECT"'),('python','printf "%s\\n" "$*" >> "$LOG"\ncase "$*" in *--replay-retained-results*) [ "$FAIL_REPLAY" != true ] || exit 2;; esac'),('node','printf "node %s\\n" "$*" >> "$LOG"')]:
                path=commands/name;path.write_text('#!/bin/sh\n'+body+'\n');path.chmod(0o700)
            env=dict(os.environ,PATH=str(commands)+os.pathsep+os.environ['PATH'],LOG=str(log),SUBJECT=subject,
                     GITHUB_REF='refs/heads/'+branch,GITHUB_EVENT_NAME='push',GITHUB_ACTOR_ID=actor,
                     GITHUB_REPOSITORY_ID='1416489937',INITIALIZE='false',DAILY_RECONCILE=daily,RUNNER_TEMP=str(root),RESULT_PROBE_RACE='',FAIL_REPLAY=str(fail_replay).lower())
            step=next(s for s in self.workflow['jobs']['daily']['steps'] if s.get('name','').startswith('Verify private')) if browser else self.step
            result=subprocess.run(['bash','-e','-o','pipefail','-c',step['run']],env=env,cwd=root,capture_output=True,text=True)
            return result.returncode,log.read_text().splitlines() if log.exists() else []

    def test_explicit_branch_uses_only_the_existing_count_audit_even_with_daily_flag(self):
        self.assertEqual(self.run_script(daily='true'),(0,['-m scripts.boat_remaining_completion_audit --input audit/state/remaining-completion-audit-input.json --retained-sp-only']))

    def test_wrong_subject_or_actor_cannot_fall_through_to_source_worker(self):
        for values in [dict(subject='routine update'),dict(actor='1')]:
            code,calls=self.run_script(**values)
            self.assertNotEqual(code,0);self.assertEqual(calls,[])

    def test_site_verification_keeps_the_source_free_audit_and_explicit_historical_day(self):
        subject='retained-result-audit: verify-site after full-refund repair'
        code,calls=self.run_script(subject=subject)
        self.assertEqual(code,0);self.assertEqual(len(calls),1)
        self.assertIn('--retained-sp-only',calls[0]);self.assertNotIn('racer_intraday_refresh',calls[0])
        code,calls=self.run_script(subject=subject,browser=True)
        self.assertEqual(code,0);self.assertEqual(len(calls),2)
        self.assertIn('--day 2026-11-07',calls[0]);self.assertNotIn('--latest-saved-day',calls[0])
        self.assertIn('--check-current-day',calls[1])

    def test_browser_guard_refuses_wrong_actor_or_subject_before_loading_private_context(self):
        for values in [dict(actor='1',subject='retained-result-audit: verify-site'),dict(subject='retained-result-audit: other')]:
            code,calls=self.run_script(browser=True,**values)
            self.assertNotEqual(code,0);self.assertEqual(calls,[])

    def test_current_day_check_requires_a_real_future_native_forecast(self):
        code,calls=self.run_script(subject='retained-result-audit: verify-site current-day',browser=True)
        self.assertEqual(code,0);self.assertEqual(len(calls),2)
        self.assertIn('--require-future',calls[0]);self.assertNotIn('--latest-saved-day',calls[0])
        self.assertNotIn('--day ',calls[0]);self.assertIn('--check-current-day',calls[1])

    def test_exact_repair_prefix_replays_then_audits_without_collecting_or_initializing(self):
        subject='retained-result-audit: verify-site repair-retained-results'
        code,calls=self.run_script(subject=subject,daily='true')
        self.assertEqual(code,0);self.assertEqual(len(calls),2)
        self.assertIn('-m scripts.racer_intraday_refresh ',calls[0]);self.assertIn('--replay-retained-results',calls[0])
        self.assertNotIn('--sync-results',calls[0]);self.assertNotIn('--initialize',calls[0])
        self.assertIn('--retained-sp-only',calls[1])
        code,calls=self.run_script(subject=subject,actor='1')
        self.assertNotEqual(code,0);self.assertEqual(calls,[])

    def test_failed_replay_stops_before_the_after_audit(self):
        code,calls=self.run_script(subject='retained-result-audit: verify-site repair-retained-results',fail_replay=True)
        self.assertNotEqual(code,0);self.assertEqual(len(calls),1)
        self.assertIn('--replay-retained-results',calls[0])

    def test_existing_racer_worker_and_daily_reconcile_are_unchanged(self):
        code,calls=self.run_script(branch='main',subject='routine update',daily='true')
        self.assertEqual(code,0);self.assertEqual(len(calls),1)
        self.assertIn('-m scripts.racer_intraday_refresh ',calls[0]);self.assertIn('--daily-reconcile',calls[0])
        self.assertNotIn('completion_audit',calls[0])

    def test_no_new_workflow_job_schedule_permissions_or_concurrency(self):
        w=self.workflow
        self.assertEqual(set(w['jobs']),{'daily'})
        self.assertEqual(w['permissions'],{'contents':'read'})
        self.assertEqual(w['jobs']['daily']['permissions'],{'contents':'write'})
        self.assertEqual(w['concurrency'],{'group':'boat-racer-daily-statistics','cancel-in-progress':'false'})
        self.assertEqual(w['on']['schedule'],[{'cron':'*/5 0-14,22-23 * * *'},{'cron':'20 21 * * *'}])
        self.assertEqual(w['on']['workflow_dispatch']['inputs']['mode']['options'],['intraday','daily'])
        self.assertIn(BRANCH,w['on']['push']['branches'])
        self.assertEqual(w['on']['push']['paths'],['docs/evidence/racer-daily-refresh-trigger.txt','docs/evidence/racer-intraday-refresh-trigger.txt'])


if __name__=='__main__':unittest.main()
