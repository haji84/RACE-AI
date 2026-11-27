"""Production gates for the result observer, separate from forecast jobs."""
from pathlib import Path
import re
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT/'.github/workflows/keirin-result-live.yml'


class LiveWorkflowTests(unittest.TestCase):
    def text(self): return PATH.read_text()

    def job(self): return self.text().split('  observe-results:\n',1)[1].split('  publish-rider-dossiers:\n',1)[0]

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
                ({'event':'workflow_dispatch','mode':'dossier-context','tests':'failure'},False),
                ({'event':'workflow_dispatch','mode':'combined-study','tests':'failure'},False),
                ({'event':'workflow_dispatch','mode':'combined-study','ref':'refs/heads/feature'},False),
                ({'event':'workflow_dispatch','mode':'test'},False),
                ({'event':'push'},False),({'cancelled':True},False),
                ({'prefix':'external-source'},False),
                ({'event':'workflow_dispatch','mode':'observe'},True),
                ({'event':'workflow_dispatch','mode':'dossier-context'},True),
                ({'event':'workflow_dispatch','mode':'combined-study'},True)]:
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
        safe = '${{ runner.temp }}/keirin-result-live-${{ github.run_id }}/safe/'
        self.assertEqual(paths, [safe + 'summary.json', safe + 'combined-study-*.sealed.json'])
        self.assertIn('if: always()',job)
        self.assertIn('rm -rf -- "$root"',job)
        self.assertNotIn('RACE_AI_STATE_KEY',job)
        self.assertNotIn('contents: write',self.text().split('  observe-results:',1)[0])

    def test_legacy_result_job_cannot_be_a_second_provider_poller(self):
        text=(ROOT/'.github/workflows/keirin-nationwide-ab-auto.yml').read_text()
        block=text.split('  github-only-research-results:\n',1)[1].split('  form-canary-window:',1)[0]
        self.assertIn('false &&',block.split('    runs-on:',1)[0])
        self.assertIn('keirin-result-live.yml',block)

    def test_dossier_update_reuses_scheduled_result_run_or_source_free_dispatch(self):
        text = self.text()
        job = text.split('  publish-rider-dossiers:\n', 1)[1].split('  measured-results:\n', 1)[0]
        self.assertIn('options: [test, saved-only, observe, rider-dossiers, dossier-context, measure-results, combined-study]', text)
        self.assertIn('needs: [tests, observe-results]', job)
        self.assertIn('scripts.keirin_daily_rider_update', job)
        self.assertNotIn('scripts.keirin_result_watch', job)
        self.assertNotIn('RACE_AI_STATE_KEY', job)
        observer = self.job()
        manual = observer.split('if [ "$RESULT_MODE" = dossier-context ]; then',1)[1].split('          fi',1)[0]
        self.assertIn('scripts.keirin_publish_rider_context', manual)
        self.assertIn('exit 0', manual)
        self.assertNotIn('scripts.keirin_result_watch', manual)
        expression = job.split('    if: >-\n', 1)[1].split('    runs-on:', 1)[0]
        expression = ' '.join(expression.split()).replace('&&', ' and ').replace('||', ' or ').replace('!cancelled()', 'not cancelled()')
        for event, ref, mode, tests, expected in [
            ('schedule', 'refs/heads/main', '', 'skipped', True),
            ('pull_request', 'refs/heads/main', '', 'success', False),
            ('workflow_dispatch', 'refs/heads/main', 'rider-dossiers', 'success', True),
            ('workflow_dispatch', 'refs/heads/other', 'rider-dossiers', 'success', False),
            ('workflow_dispatch', 'refs/heads/main', 'rider-dossiers', 'failure', False),
            ('workflow_dispatch', 'refs/heads/main', 'saved-only', 'success', False),
        ]:
            with self.subTest(event=event, ref=ref, mode=mode, tests=tests):
                context = dict(github=NS(event_name=event, ref=ref, repository='haji84/RACE-AI',
                                         repository_id='1416489937'), inputs=NS(mode=mode),
                               needs=NS(tests=NS(result=tests)),
                               vars=NS(RACE_AI_AB_SOURCE_S3_PREFIX=''),
                               always=lambda: True, cancelled=lambda: False)
                self.assertEqual(bool(eval(expression, {'__builtins__': {}}, context)), expected)

    def test_measurement_is_a_separate_readback_on_existing_schedule(self):
        job = self.text().split('  measured-results:\n', 1)[1]
        self.assertIn('needs: [tests, observe-results]', job)
        self.assertIn('github.ref == \'refs/heads/main\'', job)
        self.assertIn('inputs.mode == \'measure-results\'', job)
        self.assertIn('scripts.keirin_official_measured_outcomes', job)
        self.assertNotIn('scripts.keirin_result_watch', job)
        self.assertNotIn('RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED', job)
        self.assertNotIn('RACE_AI_STATE_KEY', job)

    def test_combined_study_exits_before_the_live_poll(self):
        job = self.job()
        branch = job.split('if [ "$RESULT_MODE" = combined-study ]; then', 1)[1].split('          fi', 1)[0]
        self.assertIn('scripts.keirin_official_measured_outcomes', branch)
        self.assertIn('--combined-holdout-from', branch)
        self.assertNotIn('--publish', branch)
        self.assertIn('exit 0', branch)
        self.assertLess(job.index(branch), job.index('scripts.keirin_result_watch'))


if __name__=='__main__':unittest.main()
