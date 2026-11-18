"""Security and ordering contracts for the trusted official-result job."""
from pathlib import Path
import re
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/keirin-nationwide-ab-auto.yml'


def jobs():
    text = WORKFLOW.read_text(encoding='utf-8')
    parts = re.split(r'^  ([a-z][a-z0-9-]+):\n', text.split('jobs:\n', 1)[1], flags=re.M)
    return text, dict(zip(parts[1::2], parts[2::2]))


class OfficialWorkflow(unittest.TestCase):
    def test_existing_private_key_is_only_referenced_by_trusted_result_job(self):
        text, blocks = jobs()
        key = 'secrets.RACE_AI_KEIRIN_PRIVATE_RSA_PEM'
        self.assertEqual(text.count(key), 1)
        result = blocks['github-only-research-results']
        self.assertIn(key, result)
        for guard in ("github.repository == 'haji84/RACE-AI'", "github.ref == 'refs/heads/main'",
                      "vars.RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED == 'true'",
                      "vars.RACE_AI_AB_SOURCE_S3_PREFIX == ''"):
            self.assertIn(guard, result)
        self.assertIn('actions: read', result)
        self.assertIn('GITHUB_TOKEN: ${{ github.token }}', result)

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
