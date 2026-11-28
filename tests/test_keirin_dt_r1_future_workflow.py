"""Guard future evidence modes at the existing main/manual job boundary."""
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODES = ('dt-r1-shadow', 'dt-r1-readback', 'dt-r1-settle', 'dt-r1-retain')


class FutureWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / '.github/workflows/keirin-result-live.yml').read_text()
        self.job = self.text.split('  observe-results:\n', 1)[1].split('  publish-rider-dossiers:\n', 1)[0]

    def test_new_manual_modes_cannot_bypass_main_repository_and_required_tests(self):
        expression = self.job.split('    if: >-\n', 1)[1].split('    runs-on:', 1)[0]
        expression = ' '.join(expression.split()).replace('&&', ' and ').replace('||', ' or ')
        expression = expression.replace('!cancelled()', 'not cancelled()')
        for mode in MODES:
            for changes, wanted in [({}, True), ({'ref': 'refs/heads/research'}, False),
                    ({'repo': 'fork/RACE-AI'}, False), ({'repo_id': '0'}, False),
                    ({'event': 'pull_request'}, False), ({'event': 'push'}, False),
                    ({'tests': 'failure'}, False), ({'prefix': 'external'}, False),
                    ({'cancelled': True}, False)]:
                values = dict(ref='refs/heads/main', repo='haji84/RACE-AI', repo_id='1416489937',
                    event='workflow_dispatch', tests='success', prefix='', cancelled=False)
                values.update(changes)
                context = dict(github=NS(ref=values['ref'], repository=values['repo'],
                    repository_id=values['repo_id'], event_name=values['event']), inputs=NS(mode=mode),
                    needs=NS(tests=NS(result=values['tests'])), vars=NS(RACE_AI_AB_SOURCE_S3_PREFIX=values['prefix']),
                    always=lambda: True, cancelled=lambda: values['cancelled'])
                with self.subTest(mode=mode, changes=changes):
                    self.assertEqual(bool(eval(expression, {'__builtins__': {}}, context)), wanted)

    def test_new_modes_exit_before_provider_poll_and_reuse_existing_secret_scope(self):
        self.assertEqual(self.job.count('secrets.RACE_AI_KEIRIN_PRIVATE_RSA_PEM'), 1)
        self.assertNotIn('id-token:', self.text)
        for mode in MODES:
            self.assertIn(mode, self.text.split('  schedule:', 1)[0])
        start = self.job.index('if [[ "$RESULT_MODE" = dt-r1-shadow')
        end = self.job.index('python -m pip install --disable-pip-version-check \'cryptography>=44,<48\'', start)
        branch = self.job[start:end]
        self.assertIn('exit 0', branch)
        self.assertNotIn('scripts.keirin_result_watch', branch)
        self.assertNotIn('RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED', branch)
        self.assertIn('env -u RACE_AI_KEIRIN_PRIVATE_RSA_PEM', branch)
        self.assertIn('scripts.keirin_dt_r1_future_readback', branch)

    def test_settlement_is_manual_source_free_and_uses_existing_secret_scope(self):
        start = self.job.index('if [ "$RESULT_MODE" = dt-r1-settle ]; then')
        end = self.job.index('if [[ "$RESULT_MODE" = dt-r1-shadow', start)
        branch = self.job[start:end]
        self.assertIn('scripts.keirin_dt_r1_future_settle', branch)
        self.assertIn('env -u RACE_AI_KEIRIN_PRIVATE_RSA_PEM -u GITHUB_TOKEN', branch)
        self.assertIn('exit 0', branch)
        self.assertNotIn('scripts.keirin_result_watch', branch)
        self.assertNotIn('RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED', branch)

    def test_personal_study_is_opt_in_for_protected_shadow_and_retrospective_settlement(self):
        self.assertIn('dt_r1_compare_personal:', self.text.split('  schedule:', 1)[0])
        start = self.job.index('if [ "$RESULT_MODE" = dt-r1-settle ]; then')
        end = self.job.index('if [ "$RESULT_MODE" = dt-r1-official-holdout ]; then', start)
        self.assertEqual(self.job.count('--compare-personal-history'), 2)
        branch = self.job[start:end]
        self.assertIn('if [[ "$DT_R1_COMPARE_PERSONAL" == true ]]; then', branch)
        self.assertIn('[[ -n "$DOSSIER_DAY" ]]', branch)
        self.assertIn('day_arg+=(--compare-personal-history)', branch)
        shadow_start = self.job.index('if [ "$RESULT_MODE" = dt-r1-shadow ]; then')
        shadow_end = self.job.index('python -m scripts.keirin_dt_r1_future_shadow', shadow_start)
        self.assertIn('[[ -n "$DOSSIER_DAY" ]]', self.job[shadow_start:shadow_end])
        self.assertIn('if [[ "$DT_R1_COMPARE_PERSONAL" == true ]]; then', self.job[shadow_start:shadow_end])
        self.assertIn('dt_shadow_args+=(--compare-personal-history)', self.job[shadow_start:shadow_end])

    def test_earlier_holdout_batch_is_distinct_from_the_single_day_argument(self):
        start = self.job.index('if [ "$RESULT_MODE" = dt-r1-official-holdout ]; then')
        end = self.job.index('if [ "$RESULT_MODE" = dt-r1-retain ]; then', start)
        branch = self.job[start:end]
        self.assertEqual(self.job.count('--earlier-batch'), 1)
        self.assertIn('if [[ "$DT_R1_EARLIER_HOLDOUT" == true ]]; then', branch)
        self.assertIn('[[ -z "$DOSSIER_DAY" ]]', branch)
        self.assertIn('holdout_args+=(--earlier-batch)', branch)

    def test_retention_asks_for_an_independent_run_and_uses_no_private_key(self):
        start = self.job.index('if [ "$RESULT_MODE" = dt-r1-retain ]; then')
        end = self.job.index('if [[ "$RESULT_MODE" = dt-r1-shadow', start)
        branch = self.job[start:end]
        self.assertIn('dt_r1_readback_run', branch)
        self.assertIn('env -u RACE_AI_KEIRIN_PRIVATE_RSA_PEM', branch)
        self.assertIn('scripts.keirin_dt_r1_future_retain', branch)
        self.assertNotIn('scripts.keirin_result_watch', branch)
        self.assertIn('exit 0', branch)

    def test_only_encrypted_producer_bundle_is_added_to_public_uploads(self):
        artifact = self.job.split('name: keirin-dt-r1-future-cipher-${{ github.run_id }}', 1)[1]
        self.assertIn('/safe/dt-future-cipher/', artifact.split('retention-days:', 1)[0])
        self.assertIn("inputs.mode == 'dt-r1-shadow'", self.job)
        self.assertIn('rm -rf -- "$root"', self.job)
        research = (ROOT / '.github/workflows/keirin-chatgpt-dt-r1.yml').read_text()
        self.assertIn('tests.test_keirin_dt_r1_future_shadow', research)
        self.assertIn('tests.test_keirin_dt_r1_future_readback', research)


if __name__ == '__main__':
    unittest.main()
