"""Production gates for the result observer, separate from forecast jobs."""
from pathlib import Path
import re
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT/'.github/workflows/keirin-result-live.yml'


class LiveWorkflowTests(unittest.TestCase):
    def text(self): return PATH.read_text()

    def job(self): return self.text().split('  observe-results:\n',1)[1]

    def test_observer_runs_independently_of_forecast_capture_with_same_permissions(self):
        block = self.job()
        self.assertNotIn('github-only-owner-capture', block)
        self.assertIn('needs: tests', block)
        self.assertIn('contents: write', block)
        self.assertIn('actions: read', block)
        self.assertNotIn('id-token:', self.text())
        self.assertIn('cancel-in-progress: false', self.text())
        self.assertIn('scripts.keirin_result_watch', block)
        self.assertIn('--interval-seconds 60', block)
        self.assertIn('--duration-seconds 540', block)
        self.assertIn('--max-ticks 10', block)

    def test_secret_job_only_admits_reviewed_main_for_independently_gated_sources(self):
        expression = self.job().split('    if: >-\n',1)[1].split('    runs-on:',1)[0]
        expression = ' '.join(expression.split()).replace('&&',' and ').replace('||',' or ').replace('!cancelled()', 'not cancelled()')
        for changes, wanted in [({},True),({'source':'false'},True),({'store':'false'},True),
                ({'event':'pull_request'},False),({'ref':'refs/heads/feature'},False),
                ({'repo':'fork/RACE-AI'},False),({'id':'0'},False),
                ({'event':'workflow_dispatch','mode':'saved-only','source':'false','store':'false'},True),
                ({'event':'workflow_dispatch','mode':'saved-only','tests':'failure'},False),
                ({'event':'workflow_dispatch','mode':'observe','tests':'failure'},False),
                ({'event':'workflow_dispatch','mode':'test'},False),
                ({'event':'push'},False),({'cancelled':True},False),
                ({'prefix':'external-source'},False),
                ({'event':'workflow_dispatch','mode':'observe'},True)]:
            v=dict(event='schedule',ref='refs/heads/main',repo='haji84/RACE-AI',id='1416489937',
                   source='true',store='true',mode='observe',tests='success',cancelled=False,prefix='');v.update(changes)
            context=dict(github=NS(event_name=v['event'],ref=v['ref'],repository=v['repo'],repository_id=v['id']),
                inputs=NS(mode=v['mode']),needs=NS(tests=NS(result=v['tests'])),
                vars=NS(RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED=v['store'],
                        RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED=v['source'],RACE_AI_AB_SOURCE_S3_PREFIX=v['prefix']),
                always=lambda:True,cancelled=lambda:v['cancelled'])
            with self.subTest(changes=changes):
                self.assertEqual(bool(eval(expression,{'__builtins__':{}},context)),wanted)

    def test_continuation_does_not_turn_on_the_legacy_source_variable(self):
        block = self.job()
        self.assertIn("RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED: 'true'", block)
        self.assertIn('RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED: ${{ vars.RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED }}', block)
        self.assertNotIn("RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED: 'true'", block)
        self.assertIn('tests.test_keirin_official_source_continuation', self.text())
        self.assertIn('tests.test_keirin_official_nationwide_continuation', self.text())

    def test_only_safe_receipt_uploaded_and_plaintext_cleaned(self):
        job=self.job()
        paths=re.findall(r'^\s+path: (.+)$',job,flags=re.M)
        self.assertEqual(paths,['${{ runner.temp }}/keirin-result-live-${{ github.run_id }}/safe/summary.json'])
        self.assertIn('if: always()',job)
        self.assertIn('rm -rf -- "$root"',job)
        self.assertNotIn('RACE_AI_STATE_KEY',job)
        self.assertNotIn('contents: write',self.text().split('  observe-results:',1)[0])

    def test_legacy_result_job_cannot_be_a_second_provider_poller(self):
        text=(ROOT/'.github/workflows/keirin-nationwide-ab-auto.yml').read_text()
        block=text.split('  github-only-research-results:\n',1)[1].split('  form-canary-window:',1)[0]
        self.assertIn('false &&',block.split('    runs-on:',1)[0])
        self.assertIn('keirin-result-live.yml',block)


if __name__=='__main__':unittest.main()
