"""One-shot public web probe tests; only synthetic HTML and simulated 403."""
from __future__ import annotations

from datetime import datetime
from urllib.error import HTTPError
import unittest

from scripts.keirin_public_source_smoke import (
    TARGETS, SourceProbeError, probe, summarize_html, validate_public_url,
    preloaded_schema_only,
)

BEFORE="2026-11-09T08:40:00+09:00"
AFTER="2026-11-09T09:30:00+09:00"

class PublicSourceSmokeTests(unittest.TestCase):
    def test_four_exact_public_pages_only(self):
        for name,url in TARGETS:
            self.assertEqual(validate_public_url(url),url)
        for bogus in (
            "https://api.winticket.jp/internal/secret",
            "https://www.winticket.jp/keirin/other",
            "https://keirin.kdreams.jp/aomori/odds",
            "https://www.winticket.jp/keirin/aomori/odds/2026110812/2/3#private",
            "http://www.winticket.jp/keirin/odds/20261109",
        ):
            with self.subTest(url=bogus),self.assertRaises(SourceProbeError):
                validate_public_url(bogus)

    def test_real_shaped_html_is_not_miscounted_as_210_odds(self):
        html=(
            "<html><body><h1>青森 3連単</h1>"
            "<table><tr><th>1</th><th>2</th><th>3</th></tr>"
            "<tr><td>3.2</td></tr></table>"
            '<script type="application/ld+json">{"@type":"Data"}</script>'
            "</body></html>"
        ).encode("utf-8")
        report=summarize_html(html)
        self.assertEqual(report["html_table_count"],1)
        self.assertEqual(report["html_row_count"],2)
        self.assertTrue(report["contains_trifecta_label"])
        self.assertTrue(report["contains_aomori_label"])
        self.assertFalse(report["odds_210_all_values_validated"])

    def test_embedded_preloaded_state_exposes_only_structure_not_odds_values(self):
        import json
        raw=json.dumps({
            "schedule":{"raceId":"fictional"},
            "oddsState":{"trifectaOdds":[{"triple":[1,2,3],
                                         "decimal":17.8} for _ in range(210)]}
        },separators=(",",":"))
        shape=preloaded_schema_only("window.__PRELOADED_STATE__ = "+raw+";")
        self.assertEqual(shape["status"],"PRELOADED_JSON_PARSED")
        self.assertIn("oddsState.trifectaOdds",
                      shape["array_length_210_paths"])
        self.assertFalse(shape["full_210_prices_verified"])
        self.assertEqual(shape["trifecta_row_shapes"][0]["count"],210)
        self.assertEqual(shape["trifecta_row_shapes"][0]["field_type_histograms"]["decimal"]["numeric_rows"],210)
        self.assertNotIn("17.8",json.dumps(shape))
        self.assertEqual(preloaded_schema_only("no state")["status"],
                         "NO_PRELOADED_STATE")

    def test_long_inline_script_never_shadows_http_original_sha(self):
        from hashlib import sha256
        html=(
            "<html><head><script>"
            "window.PUBLIC_METADATA={" + '"odds":' + '"redacted-shape";'
            + '"publicKey":"' + ("x"*500) + '"};'
            + "</script></head></html>"
        ).encode("utf-8")
        report=summarize_html(html)
        self.assertEqual(report["response_bytes"],len(html))
        self.assertEqual(report["response_sha256"],sha256(html).hexdigest())
        self.assertGreaterEqual(len(report["inline_script_structural_shapes"]),1)
        self.assertTrue(report["inline_script_structural_shapes"][0][
            "contains_odds_marker"])

    def test_one_shot_receipts_do_not_claim_real_forecasts(self):
        observed=[]
        def fake(url):
            observed.append(url)
            return b"<html><body>fiction only</body></html>"
        r=probe(fetcher=fake,clock=lambda:datetime.fromisoformat(BEFORE))
        self.assertEqual(observed,[url for _,url in TARGETS])
        self.assertEqual(r["successful_public_html_pages"],len(TARGETS))
        self.assertTrue(r["observed_before_cutoff"])
        self.assertEqual(r["independently_admitted_trifecta_210_count"],0)
        self.assertFalse(r["actual_two_version_forecast_saved"])
        self.assertFalse(r["private_plaintext_uploaded"])

    def test_http_403_stops_following_same_host_instead_of_bypass(self):
        calls=[]
        def fake(url):
            calls.append(url)
            if "winticket" in url:
                raise HTTPError(url,403,"forbidden",{},None)
            return b"<html>available</html>"
        r=probe(fetcher=fake,clock=lambda:datetime.fromisoformat(BEFORE))
        self.assertEqual(len(calls),2)
        self.assertEqual(r["results"][0]["http_status"],403)
        self.assertEqual(r["results"][1]["status"],
                         "HOST_BLOCKED_EARLIER_RESPECT_ACCESS_CONTROL")
        self.assertEqual(r["successful_public_html_pages"],1)

    def test_post_cutoff_cannot_be_labelled_pre_cutoff(self):
        r=probe(fetcher=lambda _:b"<html>fixture</html>",
                clock=lambda:datetime.fromisoformat(AFTER))
        self.assertFalse(r["observed_before_cutoff"])
        self.assertFalse(r["full_347_factor_preflight_verified"])
        self.assertFalse(r["actual_two_version_forecast_saved"])

if __name__=="__main__":
    unittest.main()
