"""Synthetic HTML contracts only; real notice documents remain owner-private."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import unittest
from urllib.error import HTTPError

from race_ai import keirin_official_refund_notice as notice


UTSU_URL = "https://blog.utsunomiya-keirin.jp/notification/2025/02/fii-a267.html"
KUMA_URL = (
    "https://www.kumamotokeirin.jp/news/"
    "%E3%80%90%E3%81%8A%E7%9F%A5%E3%82%89%E3%81%9B%EF%BD%9C"
    "%E7%86%8A%E6%9C%AC%E5%B8%82%E5%96%B6%E7%AB%B6%E8%BC%AA%E3%80%91"
    "5%E6%9C%8829%E6%97%A5%EF%BC%88%E9%87%91%EF%BC%891%E6%97%A5%E7%9B%AE9r%E4%B8%80/"
)
NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)


def utsu_html():
    return """<!doctype html><html><body>
    <h2 class="date-header">2025年2月17日 (月)</h2>
    <div class="entry">
      <h3 class="entry-header">２月１７日（月）宇都宮競輪（FII）初日・第１０レース中止のお知らせ</h3>
      <div class="entry-body"><p>本日（2/17）宇都宮競輪（FII）初日・第１０レースは中止となりました。
      購入された当該レースの車券につきましては、すべて返還となります。</p></div>
      <span class="post-footers">投稿時刻 16:14 <a>レース情報</a></span>
    </div><aside>合成テスト用の欄外</aside></body></html>"""


def kuma_html(*, datetime_attribute=' datetime="2026-05-29T15:27:34+09:00"'):
    return """<!doctype html><html><body><article class="c-post">
      <header><time class="c-post__date"%s>2026.05.29</time>
      <h1 class="c-post__heading">【お知らせ｜熊本市営競輪】5月29日（金）1日目9R一部返還のお知らせ</h1></header>
      <div class="c-editor"><p>本日5月29日（金）の熊本競輪（ＦⅡ・1日目）第9レースは、落車棄権のため、2車のみの入着となりました。</p>
      <p>これに伴い、３連勝式（３連勝複式および３連勝単式）に関する投票は不成立となり、返還させていただきます。</p>
      </div></article><footer>合成テスト用の欄外</footer></body></html>""" % datetime_attribute


def snapshot(url, html, *, observed_at=None):
    raw = html.encode("utf-8")
    return {"url": url, "raw_bytes": raw, "source_sha256": sha256(raw).hexdigest(),
            "observed_at": observed_at or NOW.isoformat()}


class RefundNoticeContract(unittest.TestCase):
    def utsu(self, html=None):
        return notice.parse_refund_notice(snapshot(UTSU_URL, html or utsu_html()))

    def kuma(self, html=None):
        return notice.parse_refund_notice(snapshot(KUMA_URL, html or kuma_html()))

    def test_cancelled_race_has_all_market_scope_without_invented_timestamp(self):
        result = self.utsu()
        self.assertEqual(result["race_id"], "202502172410")
        self.assertEqual(result["day_jst"], "2025-02-17")
        self.assertEqual(result["race_status"], "CANCELLED")
        self.assertEqual(result["market_scope"], {"kind": "ALL_MARKETS", "markets": []})
        self.assertEqual(result["refund_status"], "FULL_IN_SCOPE")
        self.assertIsNone(result["finishers_reported"])
        self.assertIsNone(result["source_published_at"])
        self.assertEqual(result["source_posted_time_displayed"], "16:14")
        self.assertEqual(result["source_published_date"], "2025-02-17")
        self.assertEqual(result["source_time_basis"], "DATE_WITH_UNZONED_DISPLAY_TIME")
        self.assertEqual(result["source_available_no_later_than"], NOW.isoformat())
        self.assertFalse(result["source_first_publication_verified"])
        self.assertFalse(result["settlement_e2e_verified"])
        self.assertTrue(notice.reparse_refund_notice(result))

    def test_market_refund_preserves_race_status_and_explicit_article_datetime(self):
        result = self.kuma()
        self.assertEqual(result["race_id"], "202605298709")
        self.assertEqual(result["race_status"], "FINISHERS_REPORTED")
        self.assertEqual(result["finishers_reported"], 2)
        self.assertEqual(result["market_scope"], {
            "kind": "MARKET_SET", "markets": ["TRIFECTA", "TRIO"]})
        self.assertEqual(result["refund_status"], "FULL_IN_SCOPE")
        self.assertEqual(result["source_published_at"], "2026-05-29T15:27:34+09:00")
        self.assertEqual(result["source_time_basis"], "HTML_ARTICLE_DATETIME")
        self.assertFalse(result["source_first_publication_verified"])
        self.assertTrue(notice.reparse_refund_notice(result))

    def test_date_only_article_has_no_synthetic_midnight(self):
        result = self.kuma(kuma_html(datetime_attribute=""))
        self.assertIsNone(result["source_published_at"])
        self.assertEqual(result["source_published_date"], "2026-05-29")
        self.assertEqual(result["source_time_basis"], "DATE_ONLY")
        self.assertEqual(result["source_available_no_later_than"], NOW.isoformat())

    def test_inconsistent_or_ambiguous_identity_is_refused(self):
        cases = [
            (UTSU_URL, utsu_html().replace("2025年2月17日", "2025年2月18日")),
            (UTSU_URL, utsu_html().replace("2025年2月17日", "2月17日")),
            (UTSU_URL, utsu_html().replace("本日（2/17）", "本日（2/18）")),
            (UTSU_URL, utsu_html().replace("第１０レースは", "第９レースは")),
            (UTSU_URL, utsu_html().replace("宇都宮競輪", "架空競輪")),
            (KUMA_URL, kuma_html().replace("2026.05.29", "2025.05.29")),
            (KUMA_URL, kuma_html().replace("本日5月29日", "本日5月30日")),
            (KUMA_URL, kuma_html().replace("第9レースは", "第8レースは")),
            (KUMA_URL, kuma_html().replace("5月29日（金）", "5月29日（土）")),
        ]
        for url, html in cases:
            with self.subTest(url=url, html=html[:80]):
                with self.assertRaises(notice.RefundNoticeError):
                    notice.parse_refund_notice(snapshot(url, html))
        with self.assertRaises(notice.RefundNoticeError):
            notice.parse_refund_notice(snapshot(UTSU_URL, utsu_html()),
                                       expected_race_id="202502172409")

    def test_unknown_partial_market_and_contradictory_supplement_are_refused(self):
        cases = [
            (UTSU_URL, utsu_html().replace("すべて返還", "一部返還")),
            (UTSU_URL, utsu_html().replace("すべて返還となります", "すべて返還となりません")),
            (UTSU_URL, utsu_html().replace("</p>", "ただし３連単は返還しません。</p>")),
            (KUMA_URL, kuma_html().replace("３連勝複式および３連勝単式", "３連勝単式")),
            (KUMA_URL, kuma_html().replace("３連勝複式および３連勝単式", "２連勝単式および３連勝単式")),
            (KUMA_URL, kuma_html().replace("投票は不成立", "一部の投票は不成立")),
            (KUMA_URL, kuma_html().replace("返還させていただきます", "返還はありません")),
            (KUMA_URL, kuma_html().replace("2車のみ", "3車のみ")),
        ]
        for url, html in cases:
            with self.subTest(url=url, html=html[:80]):
                with self.assertRaises(notice.RefundNoticeError):
                    notice.parse_refund_notice(snapshot(url, html))

    def test_missing_duplicate_or_hidden_article_evidence_is_refused(self):
        for html in (
            utsu_html().replace('class="entry-body"', 'class="unrecognized-body"'),
            utsu_html() + utsu_html(),
            utsu_html().replace('class="entry-body"', 'class="entry-body" hidden'),
            '<script>' + utsu_html() + '</script>',
        ):
            with self.subTest(html=html[:80]), self.assertRaises(notice.RefundNoticeError):
                self.utsu(html)

    def test_hash_tampering_and_normalized_scope_changes_fail_reparse(self):
        raw = snapshot(UTSU_URL, utsu_html())
        raw["raw_bytes"] += b"tampered"
        with self.assertRaises(notice.RefundNoticeError):
            notice.parse_refund_notice(raw)
        for key, value in (
            ("race_status", "CANCELLED"),
            ("market_scope", {"kind": "ALL_MARKETS", "markets": []}),
            ("source_published_at", "2026-05-29T00:00:00+09:00"),
            ("settlement_e2e_verified", True),
        ):
            changed = deepcopy(self.kuma())
            changed[key] = value
            with self.subTest(key=key):
                self.assertFalse(notice.reparse_refund_notice(changed))

    def test_unqualified_or_inconsistent_clocks_are_refused(self):
        for stamp in ("2026-11-19", "2026-11-19T03:00:00", "2024-01-01T00:00:00Z"):
            with self.subTest(observed=stamp), self.assertRaises(notice.RefundNoticeError):
                notice.parse_refund_notice(snapshot(UTSU_URL, utsu_html(), observed_at=stamp))
        for stamp in ("2026-05-29", "2026-05-29T15:27:34", "2026-05-30T15:27:34+09:00",
                      "2026-05-29T99:27:34+09:00"):
            with self.subTest(published=stamp), self.assertRaises(notice.RefundNoticeError):
                self.kuma(kuma_html(datetime_attribute=' datetime="' + stamp + '"'))

    def test_fetch_records_exact_bytes_and_stops_on_provider_refusal(self):
        raw = kuma_html().encode("utf-8")
        result = notice.fetch_refund_notice(KUMA_URL, fetcher=lambda url: raw, clock=lambda: NOW)
        self.assertEqual(result["snapshot"]["raw_bytes"], raw)
        self.assertEqual(result["source_sha256"], sha256(raw).hexdigest())
        self.assertTrue(notice.reparse_refund_notice(result))
        for status in (403, 429):
            calls = []
            def refused(url):
                calls.append(url)
                raise HTTPError(url, status, "provider refused", {}, None)
            with self.subTest(status=status):
                with self.assertRaises(notice.RefundNoticeProviderStop) as caught:
                    notice.fetch_refund_notice(KUMA_URL, fetcher=refused)
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(calls, [KUMA_URL])

    def test_other_url_is_rejected_before_transport(self):
        def unwanted_transport(url):
            self.fail("unsupported URLs must never reach transport")
        for url in (UTSU_URL + "?other=1", UTSU_URL.replace("https:", "http:"),
                    "https://example.invalid/notice", KUMA_URL + "#fragment"):
            with self.subTest(url=url), self.assertRaises(notice.RefundNoticeError):
                notice.fetch_refund_notice(url, fetcher=unwanted_transport)

    def test_safe_receipt_contains_counts_hashes_and_fixed_state_only(self):
        originals = [self.utsu(), self.kuma()]
        result = notice.summarize_refund_notices(originals)
        self.assertEqual(set(result), {
            "state", "verified_notice_count", "cancelled_race_notice_count",
            "market_scoped_notice_count", "source_sha256", "receipt_sha256",
            "settlement_e2e_count"})
        self.assertEqual(result["state"], "OFFICIAL_REFUND_NOTICE_SOURCE_SUPPORTED")
        self.assertEqual(result["verified_notice_count"], 2)
        self.assertEqual(result["cancelled_race_notice_count"], 1)
        self.assertEqual(result["market_scoped_notice_count"], 1)
        self.assertEqual(result["settlement_e2e_count"], 0)
        self.assertEqual(result["source_sha256"], sorted(item["source_sha256"] for item in originals))
        rendered = json.dumps(result, ensure_ascii=False)
        for private in (UTSU_URL, KUMA_URL, "202502172410", "202605298709", "宇都宮", "熊本", "<html>"):
            self.assertNotIn(private, rendered)
        self.assertEqual(len(result["receipt_sha256"]), 2)
        self.assertTrue(all(len(value) == 64 for value in result["receipt_sha256"]))
        with self.assertRaises(notice.RefundNoticeError):
            notice.summarize_refund_notices([originals[0], originals[0]])
        originals[1]["market_scope"] = {"kind": "ALL_MARKETS", "markets": []}
        with self.assertRaises(notice.RefundNoticeError):
            notice.summarize_refund_notices(originals)


if __name__ == "__main__":
    unittest.main()
