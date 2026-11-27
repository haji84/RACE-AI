"""Security and ordering contracts for the trusted official-result job."""
from pathlib import Path
from types import SimpleNamespace as NS
import fnmatch
import re
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/keirin-nationwide-ab-auto.yml'


def jobs():
    text = WORKFLOW.read_text(encoding='utf-8')
    parts = re.split(r'^  ([a-z][a-z0-9-]+):\n', text.split('jobs:\n', 1)[1], flags=re.M)
    return text, dict(zip(parts[1::2], parts[2::2]))


class OfficialWorkflow(unittest.TestCase):
    def test_existing_private_key_is_only_referenced_by_trusted_result_readiness_and_saved_jobs(self):
        text, blocks = jobs()
        key = 'secrets.RACE_AI_KEIRIN_PRIVATE_RSA_PEM'
        self.assertEqual({name for name, block in blocks.items() if key in block},
                         {'github-only-research-results', 'source-free-readiness', 'saved-only-replay',
                          'form-canary-settle', 'official-sp-capture', 'official-sp-publish',
                          'official-sp-settle'})
        for name in ('official-sp-capture','official-sp-publish','official-sp-settle'):
            for guard in ("github.repository == 'haji84/RACE-AI'",
                          "github.repository_id == '1416489937'",
                          "github.ref == 'refs/heads/main'"):
                self.assertIn(guard, blocks[name].split('    runs-on:',1)[0])
        result = blocks['github-only-research-results']
        self.assertIn(key, result)
        for guard in ("github.repository == 'haji84/RACE-AI'", "github.ref == 'refs/heads/main'",
                      "vars.RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED == 'true'",
                      "vars.RACE_AI_AB_SOURCE_S3_PREFIX == ''"):
            self.assertIn(guard, result)
        self.assertIn('actions: read', result)
        self.assertIn('GITHUB_TOKEN: ${{ github.token }}', result)

    def test_readiness_secret_is_admitted_only_after_tests_on_trusted_main_push_or_readiness_dispatch(self):
        _, blocks = jobs()
        self.assertIn('source-free-readiness', blocks)
        block = blocks['source-free-readiness']
        expression = block.split('    if: >-\n', 1)[1].split('    runs-on:', 1)[0]
        expression = ' '.join(expression.split()).replace('needs.source-free-tests', 'needs.tests')
        expression = expression.replace('&&', ' and ').replace('||', ' or ')
        for changes, expected in (
            ({}, True),
            ({'event': 'workflow_dispatch', 'mode': 'readiness'}, True),
            ({'event': 'workflow_dispatch', 'mode': 'test'}, False),
            ({'event': 'workflow_dispatch', 'mode': 'run'}, False),
            ({'event': 'schedule'}, False), ({'event': 'pull_request'}, False),
            ({'repo': 'fork/RACE-AI'}, False), ({'repo_id': '999'}, False),
            ({'ref': 'refs/heads/feature'}, False), ({'result': 'failure'}, False),
        ):
            values = dict(event='push', mode='', repo='haji84/RACE-AI',
                          repo_id='1416489937', ref='refs/heads/main', result='success')
            values.update(changes)
            context = {'github': NS(repository=values['repo'], repository_id=values['repo_id'],
                                   ref=values['ref'], event_name=values['event']),
                       'inputs': NS(mode=values['mode']),
                       'needs': NS(tests=NS(result=values['result']))}
            with self.subTest(changes=changes):
                self.assertEqual(bool(eval(expression, {'__builtins__': {}}, context)), expected)
        self.assertIn('contents: read', block)
        self.assertNotIn('contents: write', block)
        self.assertIn('persist-credentials: false', block)
        self.assertIn('scripts.keirin_official_readiness --repo', block)
        self.assertNotIn('scripts.keirin_official_day_pipeline capture', block)
        self.assertNotIn('scripts.keirin_official_day_pipeline settle', block)

    def test_saved_only_secret_requires_explicit_trusted_main_dispatch_after_tests(self):
        text, blocks = jobs()
        self.assertIn('saved-only', text.split('  schedule:', 1)[0])
        self.assertIn('saved-only-replay', blocks)
        block = blocks['saved-only-replay']
        expression = block.split('    if: >-\n', 1)[1].split('    runs-on:', 1)[0]
        expression = ' '.join(expression.split()).replace('needs.source-free-tests', 'needs.tests')
        expression = expression.replace('&&', ' and ').replace('||', ' or ')
        for changes, expected in (
            ({}, True), ({'event': 'push'}, False), ({'event': 'schedule'}, False),
            ({'event': 'pull_request'}, False), ({'mode': 'run'}, False),
            ({'mode': 'readiness'}, False), ({'mode': 'test'}, False),
            ({'repo': 'fork/RACE-AI'}, False), ({'repo_id': '999'}, False),
            ({'ref': 'refs/heads/feature'}, False), ({'result': 'failure'}, False),
        ):
            values = dict(event='workflow_dispatch', mode='saved-only', repo='haji84/RACE-AI',
                          repo_id='1416489937', ref='refs/heads/main', result='success')
            values.update(changes)
            context = {'github': NS(repository=values['repo'], repository_id=values['repo_id'],
                                   ref=values['ref'], event_name=values['event']),
                       'inputs': NS(mode=values['mode']),
                       'needs': NS(tests=NS(result=values['result']))}
            with self.subTest(changes=changes):
                self.assertEqual(bool(eval(expression, {'__builtins__': {}}, context)), expected)
        self.assertIn('contents: read', block)
        self.assertNotIn('contents: write', block)
        self.assertNotIn('vars.', block)
        self.assertNotIn('GITHUB_TOKEN:', block)
        self.assertIn('persist-credentials: false', block)
        self.assertIn('scripts.keirin_official_saved_check', block)
        self.assertNotIn('scripts.keirin_official_day_pipeline', block)
        self.assertIn('exit "$status"', block)
        self.assertIn("inputs.mode == 'saved-only'", blocks['source-free-tests'])
        self.assertIn('tests.test_keirin_official_saved_check', blocks['source-free-tests'])
        paths = re.findall(r'^\s+(?:path: )?(\$\{\{ runner.temp \}\}/[^\n]+)$', block, flags=re.M)
        self.assertEqual(len(paths), 3)
        self.assertTrue(all(path.endswith(('/safe.json', '/batch-safe.json', '/owner-view.sealed.json'))
                            for path in paths))
        self.assertNotIn('owner-report.html', block)
        self.assertIn('if: always()', block)
        self.assertIn('rm -rf -- "$root"', block)

    def test_saved_only_dispatch_cannot_admit_capture_or_live_settlement_even_if_opted_in(self):
        _, blocks = jobs()
        values = NS(RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED='true',
                    RACE_AI_AB_PUBLIC_CAPTURE_ENABLED='true',
                    RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED='true', RACE_AI_AB_SOURCE_S3_PREFIX='',
                    RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED='true')
        for name in ('github-only-owner-capture', 'github-only-research-results'):
            block = blocks[name]
            expression = block.split('    if: >-\n', 1)[1].split('    runs-on:', 1)[0]
            expression = ' '.join(expression.split()).replace('&&', ' and ').replace('||', ' or ').replace('false', 'False')
            context = {'github': NS(repository='haji84/RACE-AI', repository_id='1416489937',
                                   ref='refs/heads/main', event_name='workflow_dispatch'),
                       'inputs': NS(mode='saved-only'), 'vars': values, 'always': lambda: True}
            self.assertFalse(bool(eval(expression, {'__builtins__': {}}, context)), name)

    def test_main_push_readiness_matches_only_its_reviewed_code_and_workflow_paths(self):
        text, _ = jobs()
        self.assertIn('  push:\n', text)
        section = re.search(r'(?ms)^  push:\n(.*?)(?=^  [a-z]|\Z)', text).group(1)
        self.assertIn('branches: [main]', section)
        patterns = re.findall(r"^      - '([^']+)'", section, flags=re.M)
        for path, expected in (
            ('.github/workflows/keirin-nationwide-ab-auto.yml', True),
            ('scripts/keirin_official_readiness.py', True),
            ('scripts/keirin_official_day_pipeline.py', True),
            ('race_ai/keirin_nationwide_auto_storage.py', True),
            ('tests/test_keirin_official_readiness.py', True),
            ('README.md', False), ('unrelated/other_sport.py', False),
        ):
            with self.subTest(path=path):
                self.assertEqual(any(fnmatch.fnmatchcase(path, item) for item in patterns), expected)

    def test_current_readback_precedes_settlement_but_prior_races_can_resume(self):
        _, blocks = jobs()
        result = blocks['github-only-research-results']
        self.assertIn('needs: [github-only-owner-capture, github-only-independent-archive-readback]', result)
        self.assertIn('always() &&', result)
        self.assertIn('scripts.keirin_official_day_pipeline settle', result)
        self.assertIn('scripts.keirin_official_day_pipeline settle-days', result)
        self.assertIn('--day auto', result)
        self.assertIn('exit "$status"', result)
        self.assertIn('status=$?', result)

    def test_legacy_result_job_keeps_its_source_gates_but_cannot_double_poll(self):
        # This is not permission to query a provider: source authorization is
        # represented by a separate explicit official-source owner opt-in.
        _, blocks = jobs()
        result = blocks["github-only-research-results"]
        self.assertIn("needs: [github-only-owner-capture, github-only-independent-archive-readback]", result)
        self.assertIn("always() &&", result)
        self.assertIn("vars.RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED == 'true'", result)
        self.assertIn("vars.RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED == 'true'", result)
        self.assertNotIn("vars.RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED", result)
        self.assertNotIn("vars.RACE_AI_AB_PUBLIC_CAPTURE_ENABLED", result)
        expression = result.split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0]
        expression = " ".join(expression.split()).replace("&&", " and ").replace("||", " or ").replace('false','False')
        for overrides, expected in (
            ({}, True),
            ({"official": "false"}, False),
            ({"store": "false"}, False),
            ({"s3": "incompatible-store"}, False),
            ({"ref": "refs/heads/untrusted"}, False),
            ({"event": "workflow_dispatch", "mode": "saved-only"}, False),
            ({"event": "workflow_dispatch", "mode": "run"}, True),
        ):
            v = dict(repo="haji84/RACE-AI", ref="refs/heads/main", event="schedule",
                     mode="", official="true", store="true", s3="")
            v.update(overrides)
            context = {"github": NS(repository=v["repo"], ref=v["ref"], event_name=v["event"]),
                       "inputs": NS(mode=v["mode"]),
                       "vars": NS(RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED=v["store"],
                                  RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED=v["official"],
                                  RACE_AI_AB_SOURCE_S3_PREFIX=v["s3"]),
                       "always": lambda: True}
            with self.subTest(overrides=overrides):
                self.assertFalse(bool(eval(expression, {"__builtins__": {}}, context)))

    def test_artifact_paths_never_include_plaintext_report_or_source_directory(self):
        _, blocks = jobs()
        result = blocks['github-only-research-results']
        paths = re.findall(r'^\s+(?:path: )?(\$\{\{ runner.temp \}\}/[^\n]+)$', result, flags=re.M)
        self.assertEqual(len(paths), 3)
        self.assertTrue(any(p.endswith('/*/safe.json') for p in paths))
        self.assertTrue(any(p.endswith('/*/owner-view.sealed.json') for p in paths))
        self.assertTrue(all('owner-report.html' not in p and '/raw' not in p for p in paths))
        self.assertIn('Destroy ephemeral plaintext', result)
        self.assertGreaterEqual(result.count('if: always()'), 3)

    def test_official_settlement_signals_the_public_publisher_without_private_data(self):
        _, blocks = jobs()
        event = 'keirin-official-sp-settled'
        settle = blocks['official-sp-settle']
        self.assertIn('      - name: Request public result refresh\n', settle)
        prior, signal = settle.split('      - name: Request public result refresh\n', 1)
        self.assertIn('Destroy temporary official result plaintext', prior)
        self.assertIn("jq -e '.provider_denied == false and .source_unavailable == false'", prior)
        self.assertIn("if: success() && steps.official-settlement.outputs.refresh_public_results == 'true'", signal)
        self.assertIn('continue-on-error: true', signal)
        self.assertIn('GH_TOKEN: ${{ github.token }}', signal)
        self.assertIn('timeout 15s gh api --method POST --silent repos/haji84/RACE-AI/dispatches', signal)
        self.assertIn(f'-f event_type={event}', signal)
        self.assertNotIn('client_payload', signal)
        self.assertNotIn('secrets.', signal)

        publisher = WORKFLOW.with_name('keirin-public-site-results.yml').read_text(encoding='utf-8')
        self.assertIn(f'  repository_dispatch:\n    types: [{event}]', publisher)
        self.assertIn('  schedule:', publisher)
        publish = publisher.split('  publish-public-site-results:\n', 1)[1]
        guard = publish.split('    if: >-\n', 1)[1].split('    concurrency:', 1)[0]
        guard = ' '.join(guard.split()).replace('&&', ' and ').replace('||', ' or ')
        for overrides, expected in (
            ({}, True),
            ({'actor_id': '1'}, False),
            ({'repository_id': '1'}, False),
            ({'repository': 'fork/RACE-AI'}, False),
            ({'ref': 'refs/heads/feature'}, False),
            ({'event_name': 'pull_request'}, False),
            ({'event_name': 'schedule', 'actor_id': '1'}, True),
            ({'event_name': 'workflow_dispatch', 'actor_id': '1'}, True),
        ):
            github = dict(repository='haji84/RACE-AI', repository_id='1416489937',
                          ref='refs/heads/main', event_name='repository_dispatch', actor_id='41898282')
            github.update(overrides)
            with self.subTest(overrides=overrides):
                self.assertEqual(bool(eval(guard, {'__builtins__': {}}, {'github': NS(**github)})), expected)
        self.assertIn('group: keirin-public-site-results-state', publish)
        self.assertNotIn('secrets.', publish)

    def test_public_dispatch_can_trigger_private_readback_only_from_the_actions_bot(self):
        readback = WORKFLOW.with_name('keirin-joint-original-readback.yml').read_text(encoding='utf-8')
        guard = readback.split('  independent-owner-readback:\n', 1)[1].split('    if: >-\n', 1)[1]
        guard = guard.split('    runs-on:', 1)[0]
        guard = ' '.join(guard.split()).replace('&&', ' and ').replace('||', ' or ')
        github = NS(repository='haji84/RACE-AI', repository_id='1416489937', ref='refs/heads/main',
                    event_name='workflow_run')
        for event, actor, expected in (
            ('repository_dispatch', 41898282, True),
            ('repository_dispatch', 123, False),
            ('schedule', 123, True),
            ('workflow_dispatch', 123, True),
        ):
            github.event = NS(workflow_run=NS(event=event, actor=NS(id=actor), conclusion='success',
                                             head_branch='main', head_repository=NS(full_name=github.repository)))
            with self.subTest(event=event, actor=actor):
                self.assertEqual(bool(eval(guard, {'__builtins__': {}}, {'github': github})), expected)

    def test_production_uses_official_capture_and_one_concurrency_group(self):
        text, blocks = jobs()
        capture = blocks['github-only-owner-capture']
        self.assertIn('scripts.keirin_official_day_pipeline capture', capture)
        self.assertIn('vars.RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED', capture)
        self.assertIn('mkdir -m 700 -p "$root/safe"', capture)
        self.assertIn('group: keirin-nationwide-ab-${{ github.ref }}\n', text)

    def test_historical_live_probes_and_external_store_cannot_auto_run(self):
        _, blocks = jobs()
        for name, block in blocks.items():
            if name.startswith('real-') and '\n    if: ' in block and 'needs:' not in block:
                self.assertIn('\n    if: false && ', block, name)
        self.assertIn('if: >-\n      false &&', blocks['owner-auto-generate'])


if __name__ == '__main__':
    unittest.main()
