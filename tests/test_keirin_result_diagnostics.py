"""Synthetic, secret-free failure receipts; no provider requests or documents."""
from datetime import datetime
import importlib
import importlib.util
import unittest


class ResultDiagnosticsTests(unittest.TestCase):
    def api(self):
        name = 'race_ai.keirin_result_diagnostics'
        self.assertIsNotNone(importlib.util.find_spec(name), 'SAFE_RESULT_DIAGNOSTICS_REQUIRED')
        return importlib.import_module(name)

    def test_receipt_has_fixed_route_and_no_url_parameters_or_exception_text(self):
        api = self.api()
        row = api.make_diagnostic(purpose='OFFICIAL_FINAL_RESULT', stage='HTTP_RESPONSE',
            reason='HTTP_DENIED', http_status=403,
            observed_at='2026-11-20T18:24:45+09:00')
        self.assertEqual(row['source_host'], 'keirin.jp')
        self.assertEqual(row['source_path'], '/sp/race')
        self.assertEqual(row['http_status'], 403)
        self.assertEqual(set(row), {'schema', 'purpose', 'source_host', 'source_path',
            'method', 'stage', 'reason', 'http_status', 'observed_at'})
        for key, value in [('purpose', 'https://example.invalid/?secret=x'),
                           ('stage', 'Cookie: secret'), ('reason', 'Exception: token')]:
            fields = dict(purpose='OFFICIAL_FINAL_RESULT', stage='HTTP_RESPONSE',
                reason='HTTP_DENIED', http_status=403,
                observed_at='2026-11-20T18:24:45+09:00')
            fields[key] = value
            with self.assertRaises(ValueError):
                api.make_diagnostic(**fields)

    def test_passive_contact_form_recaptcha_script_is_not_an_interstitial(self):
        api = self.api()
        raw = (b'<html><body><p>Ordinary guide content</p>'
               b'<script id="google-recaptcha-js" src="https://www.google.com/recaptcha/api.js?render=fixture"></script>'
               b'<script id="wpcf7-recaptcha-js-extra">var wpcf7_recaptcha = {"sitekey":"fixture"};</script>'
               b'<script id="wpcf7-recaptcha-js" src="https://www.hofukeirin.jp/wp-content/plugins/contact-form-7/modules/recaptcha/index.js?ver=fixture"></script>'
               b'</body></html>')
        self.assertIsNone(api.challenge_reason(raw, passive_guide_scripts=True))
        self.assertEqual(api.challenge_reason(raw), 'CHALLENGE_MARKUP')

    def test_interstitial_remains_denied_even_with_guide_phrase_and_passive_script(self):
        api = self.api()
        for content in (b'<h1>Just a moment</h1>', b'<p>Verify you are human</p>',
                        b'<div class="g-recaptcha"></div>',
                        b'<script src="/cdn-cgi/challenge-platform/foo"></script>',
                        b'<script id="google-recaptcha-js" src="https://www.google.com/recaptcha/api.js?render=explicit"></script>',
                        b'<iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>'):
            with self.subTest(content=content):
                raw = b'<html><body>Ordinary guide phrase' + content + b'</body></html>'
                self.assertEqual(api.challenge_reason(raw, passive_guide_scripts=True),
                                 'CHALLENGE_MARKUP')

    def test_diagnostic_validation_rejects_extra_secret_and_unknown_http_status(self):
        api = self.api()
        row = api.make_diagnostic(purpose='OFFICIAL_PAYOUT_UNIT', stage='REQUEST',
            reason='TRANSPORT_FAILED', http_status=None,
            observed_at='2026-11-20T18:24:45+09:00')
        self.assertEqual(api.checked_diagnostics([row]), [row])
        with self.assertRaises(ValueError):
            api.checked_diagnostics([dict(row, token='secret')])
        for invalid in (0, True, '403', 999):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                api.make_diagnostic(purpose='OFFICIAL_PAYOUT_UNIT', stage='REQUEST',
                    reason='TRANSPORT_FAILED', http_status=invalid,
                    observed_at='2026-11-20T18:24:45+09:00')


if __name__ == '__main__':
    unittest.main()
