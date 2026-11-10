"""Manual Viewer witness shell gate; no network or credentials."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.test_official_future_source_workflow import jobs,steps,ident,script,WORKFLOW


class HistoryWitnessWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.jobs=jobs(WORKFLOW.read_text());self.viewer=self.jobs['viewer_contract'];self.steps=steps(self.viewer)
        self.step=ident(self.steps,'history_witness_check')
    def test_existing_read_only_viewer_checks_owner_request_before_heavy_tests_without_keys(self):
        self.assertIsNotNone(self.step)
        for clause in ("github.repository == 'haji84/RACE-AI'",'github.event.pull_request.number == 71',
            'github.event.pull_request.head.repo.full_name == github.repository',"github.actor == 'haji84'",
            "github.actor_id == '173585154'","github.triggering_actor == 'haji84'","github.run_attempt == '1'"):
            self.assertIn(clause,self.step)
        self.assertIn('GH_TOKEN: ${{ github.token }}',self.step)
        self.assertNotIn('RACE_AI_STATE_KEY',self.step);self.assertNotIn('secrets.',self.step)
        self.assertNotIn('continue-on-error',self.step);self.assertNotIn('contents: write',self.viewer)
        position=self.steps.index(self.step)
        self.assertTrue(any('requirements-history.txt' in s for s in self.steps[:position]))
        self.assertTrue(any('path: pr64-reference' in s for s in self.steps[:position]))
        self.assertTrue(any('path: pr72-reference' in s for s in self.steps[:position]))
        # The complete Python suite moved to a separate read-only sharded job.
        # It cannot borrow owner secrets or bypass the first-attempt gate.
        sharded = self.jobs.get('viewer_python_full')
        self.assertIsNotNone(sharded)
        self.assertIn('shard: [0, 1, 2, 3]', sharded)
        self.assertIn('python -m scripts.ci_unittest_shard', sharded)
        self.assertIn('ref: ${{ github.sha }}', sharded)
        self.assertNotIn('secrets.', sharded)
        self.assertNotIn('RACE_AI_STATE_KEY', sharded)
        self.assertNotIn('contents: write', sharded)
        self.assertLess(position, next(i for i,s in enumerate(self.steps) if 'id: official_recovery_preflight' in s))
    def test_manual_prefix_and_fixed_file_only_invoke_one_cli_and_preserve_failure(self):
        self.assertIsNotNone(self.step)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);commands=root/'bin';commands.mkdir();log=root/'calls'
            for name,body in (('git','printf "%s\\n" "$SUBJECT"'),('python','printf "%s\\n" "$*" >> "$LOG"; exit "$EXIT"')):
                path=commands/name;path.write_text('#!/bin/sh\n'+body+'\n');path.chmod(0o700)
            manifest=root/'audit/state/boat-venue-future-grid-input.json';manifest.parent.mkdir(parents=True)
            for subject,present,exit_code,expected in (
                ('routine CI',True,0,0),('official-future-source-capture: test',True,0,0),
                ('official-future-result-capture: test',True,0,0),('official-results-collect: test',True,0,0),
                ('prefix history-witness-check: test',True,0,0),('history-witness-check',True,0,0),
                ('history-witness-check: test',False,0,0),('history-witness-check: test',True,0,1),
                ('history-witness-check: test',True,1,1)):
                if log.exists():log.unlink()
                if present:manifest.write_text('{}')
                elif manifest.exists():manifest.unlink()
                env=dict(os.environ,PATH=str(commands)+os.pathsep+os.environ['PATH'],SUBJECT=subject,LOG=str(log),EXIT=str(exit_code))
                result=subprocess.run(['bash','-e','-o','pipefail','-c',script(self.step)],cwd=root,env=env,capture_output=True,text=True)
                calls=log.read_text().splitlines() if log.exists() else []
                with self.subTest(subject=subject,present=present,exit_code=exit_code):
                    self.assertEqual(calls,['-m scripts.boat_history_witness_check'] if expected else [])
                    self.assertEqual(result.returncode,exit_code if expected else 0)


if __name__=='__main__':unittest.main()
