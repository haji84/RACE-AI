"""No-network contract tests for one-shot official result format probe."""
from datetime import datetime, timezone
import unittest

from race_ai.keirin_official_result_page import (
    ACK, OfficialResultTransportError, probe_one_result, result_url, MAX_BODY,
)


class Response:
    def __init__(self, url, body, status=200, content_type="text/html; charset=utf-8"):
        self.url = url
        self.body = body
        self.status = status
        self.headers = {"Content-Type": content_type}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return self.url
    def read(self, limit):
        return self.body[:limit]


class Opener:
    def __init__(self, body, *, status=200, redirected=False,
                 ct="text/html; charset=utf-8"):
        self.body = body
        self.status = status
        self.redirected = redirected
        self.ct = ct
        self.calls = 0
        self.timeout = None
    def open(self, request, timeout):
        self.calls += 1
        self.timeout = timeout
        url = request.full_url + ("/redirected" if self.redirected else "")
        return Response(url, self.body, self.status, self.ct)


GOOD = "<html><body>2026年3月21日 小倉 第11レース 競走結果 3連単 払戻</body></html>".encode()


class OfficialPageTests(unittest.TestCase):
    def test_one_canonical_official_endpoint(self):
        self.assertEqual(result_url(81, "20260321", 11),
                         "https://keirin.jp/pc/dfw/dataplaza/guest/raceresult?"
                         "KCD=81&KBI=20260321&RNO=11")
        self.assertEqual(result_url(36, "20261103", 1).split("RNO=")[-1], "01")

    def test_refuse_bad_venue_race_day(self):
        for args in ((0, "20260321", 11),
                     (81, "20260230", 11),
                     (81, "20260321", 13),
                     (True, "20260321", 11)):
            with self.assertRaises(OfficialResultTransportError):
                result_url(*args)

    def test_no_ack_never_fetches(self):
        client = Opener(GOOD)
        with self.assertRaisesRegex(OfficialResultTransportError,
                                    "ONE_SHOT_EXPLICIT_SCOPE_REQUIRED"):
            probe_one_result(81, "20260321", 11,
                             acknowledgement="not approved", opener=client)
        self.assertEqual(client.calls, 0)

    def test_positive_transport_not_result_authentication(self):
        client = Opener(GOOD)
        report = probe_one_result(81, "20260321", 11, acknowledgement=ACK,
                opener=client,
                observed_at=datetime(2026, 3, 21, tzinfo=timezone.utc))
        self.assertEqual(client.calls, 1)
        self.assertEqual(client.timeout, 8)
        self.assertTrue(report["event_date_marker_in_body"])
        self.assertTrue(report["race_number_marker_in_body"])
        self.assertTrue(report["threefold_bet_label_present"])
        self.assertFalse(report["result_finalized_verified"])
        self.assertFalse(report["persistent_monitoring_enabled"])
        self.assertFalse(report["source_html_persisted"])

    def test_false_result_marker_does_not_claim_final(self):
        client = Opener(b"<html><body>Official schedule only</body></html>")
        report = probe_one_result(81, "20260321", 11,
                                  acknowledgement=ACK, opener=client)
        self.assertFalse(report["event_date_marker_in_body"])
        self.assertFalse(report["race_number_marker_in_body"])
        self.assertFalse(report["result_finalized_verified"])

    def test_unexpected_redirect_rejected(self):
        with self.assertRaisesRegex(OfficialResultTransportError,
                                    "OFFICIAL_RESPONSE_IDENTITY_MISMATCH"):
            probe_one_result(81, "20260321", 11, acknowledgement=ACK,
                             opener=Opener(GOOD, redirected=True))

    def test_http_error_status_rejected(self):
        with self.assertRaisesRegex(OfficialResultTransportError,
                                    "OFFICIAL_RESPONSE_IDENTITY_MISMATCH"):
            probe_one_result(81, "20260321", 11, acknowledgement=ACK,
                             opener=Opener(GOOD, status=403))

    def test_real_http_status_surfaced_without_leaking_body(self):
        from urllib.error import HTTPError

        class RefusingOpener:
            def open(self, request, timeout):
                raise HTTPError(request.full_url, 403, "refused", None, None)

        with self.assertRaisesRegex(OfficialResultTransportError,
                                    "OFFICIAL_PAGE_HTTP_403"):
            probe_one_result(81, "20260321", 11, acknowledgement=ACK,
                             opener=RefusingOpener())

    def test_non_html_rejected(self):
        with self.assertRaisesRegex(OfficialResultTransportError,
                                    "UNEXPECTED_PROVIDER_MIME"):
            probe_one_result(81, "20260321", 11, acknowledgement=ACK,
                             opener=Opener(GOOD, ct="application/json"))

    def test_size_limit_rejected(self):
        with self.assertRaisesRegex(OfficialResultTransportError,
                                    "OFFICIAL_PAGE_SIZE_INVALID"):
            probe_one_result(81, "20260321", 11, acknowledgement=ACK,
                             opener=Opener(b"x"*(MAX_BODY+1)))

    def test_windows_japanese_encoding(self):
        body = b'<meta charset="Shift_JIS">' + (
            "2026年3月21日 小倉 第11レース 払戻".encode("cp932"))
        report = probe_one_result(81, "20260321", 11, acknowledgement=ACK,
                                  opener=Opener(body, ct="text/html"))
        self.assertEqual(report["source_charset"], "cp932")
        self.assertTrue(report["event_date_marker_in_body"])

    def test_url_not_influenced_by_page_body(self):
        bad = b"<a href='https://evil.example'>go</a>"
        report = probe_one_result(81, "20260321", 11, acknowledgement=ACK,
                                  opener=Opener(bad))
        self.assertNotIn("evil.example", str(report))
        self.assertFalse(report["result_finalized_verified"])


if __name__ == "__main__":
    unittest.main()
