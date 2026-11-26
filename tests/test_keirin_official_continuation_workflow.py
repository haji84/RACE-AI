"""Real workflow boundaries for the authenticated official-SP continuation."""
from types import SimpleNamespace as NS
import re
import subprocess
import textwrap
import unittest

from tests.test_keirin_official_workflow import jobs


class ContinuationWorkflowTests(unittest.TestCase):
    def allowed(self, name, **changes):
        _, blocks = jobs()
        expr = blocks[name].split('    if: >-\n', 1)[1].split('    runs-on:', 1)[0]
        expr = ' '.join(expr.split()).replace('&&',' and ').replace('||',' or ')
        expr = expr.replace('!cancelled()', 'not cancelled()')
        for old,new in (('source-free-tests','tests'),('official-sp-capture','capture'),
                        ('official-sp-independent-readback','readback')):
            expr = expr.replace('needs.'+old, 'needs.'+new)
        v = dict(repo='haji84/RACE-AI', repo_id='1416489937', ref='refs/heads/main',
                 event='workflow_dispatch', mode='official-continue', tests='success',
                 capture='success', archived='true', readback='success', prefix='', cancelled=False)
        v.update(changes)
        context = dict(github=NS(repository=v['repo'],repository_id=v['repo_id'],
                                ref=v['ref'],event_name=v['event']),
                       inputs=NS(mode=v['mode']),always=lambda:True,
                       cancelled=lambda:v['cancelled'],
                       vars=NS(RACE_AI_AB_SOURCE_S3_PREFIX=v['prefix']),
                       needs=NS(tests=NS(result=v['tests']),
                                capture=NS(result=v['capture'],outputs=NS(archived=v['archived'])),
                                readback=NS(result=v['readback'])))
        return bool(eval(expr, {'__builtins__':{}}, context))

    def test_source_capture_never_starts_from_a_push_fork_or_failed_manual_gate(self):
        self.assertTrue(self.allowed('official-sp-capture'))
        self.assertTrue(self.allowed('official-sp-capture',event='schedule',tests='skipped'))
        for changes in ({'event':'push'},{'event':'pull_request'},{'tests':'failure'},
                        {'mode':'test'},{'mode':'form-canary-reconcile'},
                        {'repo':'fork/RACE-AI'},{'repo_id':'0'},
                        {'ref':'refs/heads/feature'},{'prefix':'external'},{'cancelled':True}):
            with self.subTest(changes=changes):
                self.assertFalse(self.allowed('official-sp-capture',**changes))

    def test_recovery_settlement_waits_for_writers_without_requiring_their_success(self):
        self.assertTrue(self.allowed('official-sp-settle',capture='failure',readback='failure'))
        self.assertTrue(self.allowed('official-sp-settle',capture='skipped',readback='skipped'))
        for changes in ({'event':'schedule'},{'event':'push'},{'tests':'failure'},
                        {'mode':'test'},{'ref':'refs/heads/feature'},{'cancelled':True}):
            with self.subTest(changes=changes):
                self.assertFalse(self.allowed('official-sp-settle',**changes))
        _, blocks = jobs()
        self.assertIn('needs: [source-free-tests, official-sp-capture, official-sp-publish]',
                      blocks['official-sp-settle'])

    def test_saved_baselines_need_a_distinct_successful_readback_before_publication(self):
        self.assertTrue(self.allowed('official-sp-independent-readback'))
        self.assertFalse(self.allowed('official-sp-independent-readback',capture='failure'))
        self.assertFalse(self.allowed('official-sp-independent-readback',archived='false'))
        self.assertTrue(self.allowed('official-sp-publish'))
        self.assertFalse(self.allowed('official-sp-publish',readback='failure'))
        self.assertFalse(self.allowed('official-sp-publish',capture='failure'))
        self.assertTrue(self.allowed('official-sp-publish',archived='false',readback='skipped'))
        self.assertFalse(self.allowed('official-sp-publish',archived='false',cancelled=True))
        for name in ('official-sp-independent-readback','official-sp-publish'):
            for changes in ({'repo':'fork/RACE-AI'},{'repo_id':'0'},{'ref':'refs/heads/feature'}):
                with self.subTest(job=name,changes=changes):
                    self.assertFalse(self.allowed(name,**changes))
        self.assertFalse(self.allowed('official-sp-publish',event='push'))

    def test_capture_and_readback_artifacts_keep_the_dynamic_origin_contract(self):
        _, blocks = jobs()
        capture, reader = blocks['official-sp-capture'], blocks['official-sp-independent-readback']
        self.assertIn('name: keirin-official-sp-receipt-${{ github.run_id }}',capture)
        self.assertIn('name: keirin-official-sp-receipt-${{ github.run_id }}',reader)
        self.assertIn('name: keirin-official-sp-readback-${{ github.run_id }}',reader)
        self.assertIn('scripts.keirin_github_only_ab_readback',reader)
        self.assertIn('/keirin-git-independent.json',reader)
        self.assertIn('contents: read',reader)
        self.assertNotIn('PRIVATE_RSA',reader)
        self.assertNotIn('contents: write',reader)
        self.assertIn('persist-credentials: false',reader)

    def test_private_jobs_upload_only_safe_receipts_and_keep_existing_keys(self):
        _, blocks = jobs()
        for name in ('official-sp-capture','official-sp-publish','official-sp-settle'):
            block=blocks[name]
            with self.subTest(job=name):
                self.assertIn('RACE_AI_KEIRIN_PRIVATE_RSA_PEM',block)
                self.assertNotIn('RACE_AI_STATE_KEY',block)
                self.assertNotIn('id-token:',block)
                self.assertNotIn('RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED:',block)
                self.assertIn('rm -rf -- "$root"',block)
                paths=re.findall(r'^\s+path: (.+)$',block,flags=re.M)
                self.assertEqual(len(paths),1)
                self.assertTrue(paths[0].endswith('/safe/summary.json'))
        self.assertIn('--max-races 8',blocks['official-sp-capture'])

    def test_every_new_shell_step_parses_without_expanding_the_workflow_expressions(self):
        _, blocks = jobs()
        for name in ('official-sp-capture','official-sp-independent-readback',
                     'official-sp-publish','official-sp-settle'):
            block=blocks[name]
            matches=list(re.finditer(r'^        run: \|\n((?:          .*\n|\n)+)',block,re.M))
            self.assertGreater(len(matches),0)
            for i,match in enumerate(matches):
                script=textwrap.dedent(match.group(1))
                with self.subTest(job=name,step=i):
                    result=subprocess.run(['bash','-n'],input=script,text=True,capture_output=True,timeout=5)
                    self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__':
    unittest.main()
