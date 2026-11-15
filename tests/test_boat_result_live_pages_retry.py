"""Source-free read-only retry contract for live BOAT Pages proof.

This test runs the exact workflow's sanitizing Python snippet against
fictional failure responses. It never opens a URL, an AES key or a provider.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/boat-result-gap-recovery.yml'


def boundary():
    text = WORKFLOW.read_text(encoding='utf-8')
    site = text.split('\n  fresh_site_browser:\n', 1)[1].split(
        '\n  source_free_followup:\n', 1)[0]
    return site


def gate_source():
    site = boundary()
    return textwrap.dedent(site.split(
        "BOAT_RETRY_ATTEMPT=\"$attempt\" python - <<'PY_BROWSER_FAIL'\n", 1)[1].split(
        '\n          PY_BROWSER_FAIL', 1)[0])


class ReadOnlySiteRetryTests(unittest.TestCase):
    def test_bounded_only_after_independent_aes_and_model_readback(self):
        site = boundary()
        self.assertIn("needs: [fresh_result, fresh_readback, fresh_pdca_readback]", site)
        self.assertIn("needs.fresh_readback.result == 'success' && needs.fresh_pdca_readback.result == 'success'", site)
        self.assertIn('timeout-minutes: 35', site)
        self.assertEqual(site.count('for attempt in 1 2 3; do'), 1)
        self.assertEqual(site.count('sleep 180'), 1)
        self.assertIn('if [[ "$attempt" == 3 ]]; then', site)
        self.assertIn('BOAT_LIVE_PAGES_FAILED_AFTER_BOUNDED_RETRY', site)
        self.assertIn('exit 2', site)
        self.assertIn('env -u RACE_AI_STATE_KEY -u GH_TOKEN -u GITHUB_TOKEN node scripts/boat_saved_site_check.cjs', site)
        self.assertIn('> "$RUNNER_TEMP/boat-fresh-browser.json"', site)
        self.assertNotIn('--sync-results', site)
        self.assertNotIn('--sync-beforeinfo', site)
        self.assertNotIn('www.boatrace.jp', site)
        compile(gate_source(), 'sanitized_pages_failure_report', 'exec')

    def run_gate(self, report):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'boat-fresh-browser.json'
            p.write_text(json.dumps(report) if not isinstance(report,str) else report,encoding='utf-8')
            out=io.StringIO()
            with patch.dict(os.environ, {'RUNNER_TEMP': directory, 'BOAT_RETRY_ATTEMPT':'2'}):
                with contextlib.redirect_stdout(out):
                    exec(compile(gate_source(), 'sanitized_pages_failure_report', 'exec'), {'__name__':'__main__'})
            return json.loads(out.getvalue())

    def test_untrusted_browser_dump_cannot_leak_owner_hash_or_private_details(self):
        private='SECRET_DO_NOT_PRINT_PRIVATE_OWNER_URL_OR_AES_KEY'
        source=dict(status='LIVE_OWNER_SITE_REJECTED',
                    reason='SAVED_SITE_BROWSER_CHECK_FAILED',error_kind='TimeoutError',
                    checker_line=193,checker_column=4,
                    owner_url='https://example.invalid/#saved='+private,
                    stack=private,extra={'report':private})
        result=self.run_gate(source)
        self.assertEqual(result,dict(status='BOAT_LIVE_PAGES_BROWSER_HOLD',
                                     attempt=2,reason='BROWSER_CHECKER_FAILED',
                                     kind='TimeoutError',checker_line=193))
        self.assertNotIn(private,json.dumps(result))

    def test_invalid_status_and_untrusted_string_are_never_accepted_as_success(self):
        for value in ('not-json',{'status':'LIVE_OWNER_SITE_VERIFIED','error_kind':'TimeoutError'},
                      {'status':'LIVE_OWNER_SITE_REJECTED','reason':'OTHER_ERROR',
                       'error_kind':'Should_Not_Echo','checker_line':999999}):
            with self.subTest(value=value):
                result=self.run_gate(value)
                self.assertEqual(result['status'],'BOAT_LIVE_PAGES_BROWSER_HOLD')
                self.assertEqual(result['kind'],'UNCLASSIFIED')
                self.assertIsNone(result['checker_line'])

    def test_fixed_whitelist_enforced_for_error_type_and_line(self):
        result=self.run_gate(dict(status='LIVE_OWNER_SITE_REJECTED',
                                  reason='SAVED_SITE_BROWSER_CHECK_FAILED',
                                  error_kind='Leaked:SECRET',checker_line='1'))
        self.assertEqual(result['kind'],'UNCLASSIFIED')
        self.assertIsNone(result['checker_line'])


if __name__=='__main__':
    unittest.main()
