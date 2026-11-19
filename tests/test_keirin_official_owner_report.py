"""Owner-view rendering with invented races only; no real private predictions."""
from copy import deepcopy
import unittest

from bs4 import BeautifulSoup

from race_ai import keirin_official_owner_report as view

DAY = "2026-11-19"


def examples():
    a = {"ranked_tickets": [[1, 2, 3], [2, 1, 3]]}
    b = {"ranked_tickets": [[3, 2, 1], [3, 1, 2]]}
    result = {"race_id": "202611192601", "status": "FINAL_NORMAL",
              "refund_status": "NONE", "winning_triples": [[1, 2, 3]],
              "payouts_100yen": [{"triple": [1, 2, 3], "yen": 1200}]}
    rows = [
        {"race_id": "202611192601", "venue": "架空会場", "race_no": 1,
         "official_cutoff_at": "2026-11-19T10:47:00+09:00",
         "state": "AB_SETTLED_FROM_INDEPENDENT_RECEIPTS", "A": a, "B": b,
         "result": result},
        {"race_id": "202611192602", "venue": "架空会場", "race_no": 2,
         "official_cutoff_at": None, "state": "HOLD_NO_PRE_CUTOFF_FORECAST",
         "A": None, "B": None, "result": None},
        {"race_id": "202611192603", "venue": "架空会場", "race_no": 3,
         "official_cutoff_at": "2026-11-19T12:00:00+09:00",
         "state": "CANCELLED_FULL_REFUND_NO_MODEL_SCORE", "A": a, "B": b,
         "result": {"race_id": "202611192603", "status": "CANCELLED",
                    "refund_status": "FULL", "winning_triples": [],
                    "payouts_100yen": []}},
        {"race_id": "202611192604", "venue": "別の架空会場", "race_no": 4,
         "official_cutoff_at": "2026-11-19T19:00:00+09:00",
         "state": "HOLD_NO_OFFICIAL_RESULT", "A": a, "B": None, "result": None},
    ]
    report = {"day_jst": DAY, "registered_races": 4, "paired_A_B_scored": 1,
              "confirmed_cancelled_full_refund_races": 1,
              "scorecard": {
                  "A_existing": {"eligible": 1, "hit_at_1": 1, "hit_at_all": 1,
                                 "hit_at_1_rate": 1.0, "hit_at_all_rate": 1.0,
                                 "stake_yen": 200, "payout_yen": 1200,
                                 "virtual_roi": 6.0, "virtual_profit_yen": 1000},
                  "B_six_phase": {"eligible": 1, "hit_at_1": 0, "hit_at_all": 0,
                                  "hit_at_1_rate": 0.0, "hit_at_all_rate": 0.0,
                                  "stake_yen": 200, "payout_yen": 0,
                                  "virtual_roi": 0.0, "virtual_profit_yen": -200},
              }}
    return report, deepcopy(rows)


def pending_examples():
    report, rows = examples()
    report["paired_A_B_scored"] = 0
    report["confirmed_cancelled_full_refund_races"] = 0
    for arm in report["scorecard"].values():
        arm.update({"eligible": 0, "hit_at_1": 0, "hit_at_all": 0,
                    "hit_at_1_rate": None, "hit_at_all_rate": None,
                    "stake_yen": 0, "payout_yen": 0,
                    "virtual_roi": None, "virtual_profit_yen": 0})
    for row in rows:
        row["state"] = "HOLD_NO_OFFICIAL_RESULT"
        row["result"] = None
    return report, rows


class OwnerRaceReport(unittest.TestCase):
    def test_all_races_coverage_and_same_denominator_are_visible(self):
        report, rows = examples()
        soup = BeautifulSoup(view.render_private_report(report, rows), "html.parser")
        self.assertEqual(len(soup.select("article[data-race-id]")), 4)
        coverage = soup.select_one("#coverage").get_text(" ", strip=True)
        self.assertIn("登録レース", coverage)
        self.assertEqual(soup.select_one('#coverage [data-metric="registered_races"]').text, "4")
        self.assertEqual(soup.select_one('#coverage [data-metric="paired_forecasts"]').text, "2")
        self.assertEqual(soup.select_one('#coverage [data-metric="paired_A_B_scored"]').text, "1")
        self.assertIn("同じ1レース", soup.select_one("#comparison").text)
        scored = soup.select_one('article[data-race-id="202611192601"]')
        self.assertEqual(scored.select_one('[data-model="A"] .outcome').text, "的中")
        self.assertEqual(scored.select_one('[data-model="B"] .outcome').text, "不的中")
        self.assertIn("1,200円", scored.text)

    def test_missing_forecast_and_full_refund_are_never_misses(self):
        report, rows = examples()
        soup = BeautifulSoup(view.render_private_report(report, rows), "html.parser")
        missing = soup.select_one('article[data-race-id="202611192602"]')
        self.assertEqual([node.text for node in missing.select(".outcome")],
                         ["予測なし", "予測なし"])
        self.assertIn("照合待ち", missing.text)
        cancelled = soup.select_one('article[data-race-id="202611192603"]')
        self.assertIn("中止・全額返還", cancelled.text)
        self.assertEqual([node.text for node in cancelled.select(".outcome")],
                         ["集計対象外", "集計対象外"])
        self.assertNotIn("不的中", cancelled.text)

    def test_none_is_uncomputed_while_real_zero_remains_zero(self):
        report, rows = pending_examples()
        soup = BeautifulSoup(view.render_private_report(report, rows), "html.parser")
        a = soup.select_one('#comparison [data-model="A"]')
        self.assertEqual(a.select_one('[data-metric="hit_at_1_rate"]').text, "未集計")
        self.assertEqual(a.select_one('[data-metric="virtual_roi"]').text, "未集計")
        self.assertEqual(a.select_one('[data-metric="payout_yen"]').text, "0円")
        self.assertEqual(a.select_one('[data-metric="hit_at_1"]').text, "0件")
        self.assertNotIn("不的中", " ".join(x.text for x in soup.select("article .outcome")))

    def test_unverified_final_page_does_not_become_a_hit_or_miss(self):
        report, rows = pending_examples()
        _, original = examples()
        rows[0]["result"] = original[0]["result"]
        soup = BeautifulSoup(view.render_private_report(report, rows), "html.parser")
        card = soup.select_one('article[data-race-id="202611192601"]')
        self.assertEqual([node.text for node in card.select(".outcome")],
                         ["照合待ち", "照合待ち"])
        self.assertNotIn("1,200円", card.text)

    def test_source_text_is_escaped_and_unselected_private_fields_are_not_embedded(self):
        report, rows = examples()
        rows[0]["venue"] = '<img src="https://example.org/x" onerror="steal()"> & 会場'
        rows[0]["source_raw"] = "PRIVATE_RAW_SOURCE_SENTINEL"
        rows[0]["A"]["source_raw"] = "PRIVATE_RAW_SOURCE_SENTINEL"
        report["owner_private_pem"] = "PRIVATE_KEY_SENTINEL"
        html = view.render_private_report(report, rows)
        soup = BeautifulSoup(html, "html.parser")
        self.assertIsNone(soup.find("img"))
        self.assertIsNone(soup.find("script"))
        self.assertIn(rows[0]["venue"], soup.get_text())
        self.assertNotIn("PRIVATE_RAW_SOURCE_SENTINEL", html)
        self.assertNotIn("PRIVATE_KEY_SENTINEL", html)

    def test_missing_or_duplicate_races_cannot_shrink_or_inflate_coverage(self):
        report, rows = examples()
        with self.assertRaises(ValueError):
            view.render_private_report(report, rows[:-1])
        rows[-1] = deepcopy(rows[0])
        with self.assertRaises(ValueError):
            view.render_private_report(report, rows)

    def test_different_ab_denominators_are_rejected(self):
        report, rows = examples()
        report["scorecard"]["B_six_phase"]["eligible"] = 2
        with self.assertRaises(ValueError):
            view.render_private_report(report, rows)

    def test_report_is_self_contained_without_external_assets_or_scripts(self):
        report, rows = examples()
        soup = BeautifulSoup(view.render_private_report(report, rows), "html.parser")
        self.assertEqual(soup.html.get("lang"), "ja")
        self.assertIn("width=device-width", soup.find("meta", attrs={"name": "viewport"})["content"])
        self.assertIsNotNone(soup.find("style"))
        self.assertEqual(soup.select("script,link,iframe,object,embed,form,img"), [])
        self.assertEqual(soup.select("[src],[srcset]"), [])
        self.assertIn("script-src 'none'", soup.find("meta", attrs={"http-equiv": "Content-Security-Policy"})["content"])

    def test_coverage_describes_loaded_audit_evidence_and_accepts_escaped_scope_note(self):
        report, rows = examples()
        report["evidence_scope_note"] = "今回確認した原本のみ。<script>untrusted()</script>"
        soup = BeautifulSoup(view.render_private_report(report, rows), "html.parser")
        self.assertIn("読込", soup.select_one("#coverage").text)
        self.assertIn(report["evidence_scope_note"], soup.select_one("#coverage").text)
        self.assertIsNone(soup.find("script"))
        missing = soup.select_one('article[data-race-id="202611192602"]')
        self.assertIn("今回の照合", missing.text)
        self.assertIn("読み込めた原本", soup.select_one(".page-footer").text)
        self.assertIn("研究用", soup.select_one('#comparison [data-model="B"]').text)
        self.assertIn("的中確率ではありません", soup.select_one('#comparison [data-model="B"]').text)

    def test_provider_hold_notice_distinguishes_saved_verified_numbers_from_this_poll(self):
        report, rows = examples()
        report["provider_state"] = 'HOLD_PROVIDER_<img src="x" onerror="steal()">'
        soup = BeautifulSoup(view.render_private_report(report, rows), "html.parser")
        notice = soup.select_one(".provider-notice")
        self.assertIsNotNone(notice)
        self.assertIn("今回の取得は保留中", notice.text)
        self.assertIn("保存・検証", notice.text)
        self.assertIn(report["provider_state"], notice.text)
        self.assertIsNone(notice.find("img"))
        self.assertEqual(soup.select_one('#coverage [data-metric="paired_A_B_scored"]').text, "1")

    def test_abc_all_three_models_visible_without_c_original(self):
        report, rows = examples()
        soup = BeautifulSoup(view.render_private_report(report, rows), "html.parser")
        card = soup.select_one('article[data-race-id="202611192601"]')
        self.assertEqual([p.get("data-model") for p in card.select(".arm")],
                         ["A", "B", "C"])
        self.assertEqual([p.text for p in card.select(".pick-count strong")],
                         ["2点", "2点", "0点"])
        self.assertEqual([x.text for x in card.select(".outcome")],
                         ["的中", "不的中"])
        self.assertEqual(card.select_one('[data-model="C"] .c-outcome').text, "未生成")
        self.assertEqual(len(card.select('[data-model="A"] .ticket')), 2)
        self.assertEqual(len(card.select('[data-model="B"] .ticket')), 2)
        self.assertEqual(len(card.select('[data-model="C"] .ticket')), 0)
        self.assertIn("A/B", soup.select_one(".coverage-note").text)

    def test_unverified_c_payload_does_not_leak_or_block_a_b(self):
        report, rows = examples()
        rows[0]["C"] = {"ranked_tickets": [[1, 3, 2]],
                        "secret_token": "PRIVATE_C_RAW_SENTINEL"}
        soup = BeautifulSoup(view.render_private_report(report, rows), "html.parser")
        card = soup.select_one('article[data-race-id="202611192601"]')
        self.assertEqual(card.select_one('[data-model="A"] .outcome').text, "的中")
        self.assertEqual(card.select_one('[data-model="B"] .outcome').text, "不的中")
        self.assertEqual(card.select_one('[data-model="C"] .c-outcome').text, "認証待ち")
        self.assertEqual(card.select('[data-model="C"] .ticket'), [])
        self.assertNotIn("PRIVATE_C_RAW_SENTINEL", str(soup))

    def test_optional_c_only_after_trusted_external_verifier(self):
        report, rows = examples()
        rows[0]["C"] = {"ranked_tickets": [[1, 2, 3], [1, 3, 2]],
                        "owner_private_key": "PRIVATE_KEY_MUST_NOT_RENDER"}
        # A toy callback is used only in this invented offline test; real code
        # must verify authenticated C origin / cutoff / follow-label evidence.
        verifier = lambda row: row["race_id"] == "202611192601"
        soup = BeautifulSoup(
            view.render_private_report(report, rows, verify_optional_c=verifier),
            "html.parser")
        card = soup.select_one('article[data-race-id="202611192601"]')
        self.assertEqual(card.select_one('[data-model="C"] .c-outcome').text, "的中")
        self.assertEqual(len(card.select('[data-model="C"] .ticket')), 2)
        self.assertEqual(len(card.select('[data-model="A"] .ticket')), 2)
        self.assertEqual(len(card.select('[data-model="B"] .ticket')), 2)
        self.assertNotIn("PRIVATE_KEY_MUST_NOT_RENDER", str(soup))
        self.assertEqual(soup.select_one('#comparison [data-model="A"] [data-metric="hit_at_all"]').text, "1件")

    def test_invalid_c_is_held_without_hiding_valid_a_b(self):
        report, rows = examples()
        rows[0]["C"] = {"ranked_tickets": [[1, 2, 3], [1, 2, 3]]}
        soup = BeautifulSoup(view.render_private_report(
            report, rows, verify_optional_c=lambda row: True), "html.parser")
        card = soup.select_one('article[data-race-id="202611192601"]')
        self.assertEqual(card.select_one('[data-model="C"] .c-outcome').text, "認証待ち")
        self.assertEqual(len(card.select('[data-model="C"] .ticket')), 0)
        self.assertEqual(len(card.select('[data-model="A"] .ticket')), 2)

    def test_b_six_phases_explicitly_hypothetical_and_all_picks_visible(self):
        report, rows = examples()
        rows[0]["A"]["ranked_tickets"] = [
            [1, 2, 3], [2, 1, 3], [1, 3, 2], [3, 1, 2],
            [2, 3, 1], [3, 2, 1], [4, 1, 2], [4, 2, 1],
            [4, 3, 1], [4, 1, 3], [1, 4, 2], [2, 4, 1],
        ]
        phases = ["INITIAL", "BELL", "FINAL_HOME", "FINAL_BACK",
                  "FOURTH_CORNER", "GOAL"]
        rows[0]["B"]["six_phase_scenarios"] = [{
            "scenario_id": "L1_V0",
            "six_phases": [{"phase": p, "projected_top3": [3, 2, 1]}
                           for p in phases],
        }]
        soup = BeautifulSoup(view.render_private_report(report, rows), "html.parser")
        card = soup.select_one('article[data-race-id="202611192601"]')
        self.assertEqual(len(card.select('[data-model="A"] .ticket')), 12)
        self.assertEqual(card.select_one('[data-model="A"] .pick-count strong').text, "12点")
        self.assertEqual(len(card.select('[data-model="B"] .phase-steps li')), 6)
        self.assertEqual(len(card.select('[data-model="B"] .ticket')), 2)
        self.assertIn("実映像で確認した着順・確率ではありません", card.text)

    def test_bad_six_phase_is_not_claimed_as_verified_tactical_detail(self):
        report, rows = examples()
        rows[0]["B"]["six_phase_scenarios"] = [{
            "six_phases": [{"phase": "GOAL", "projected_top3": [1, 2, 3]}]
        }]
        soup = BeautifulSoup(view.render_private_report(report, rows), "html.parser")
        card = soup.select_one('article[data-race-id="202611192601"]')
        self.assertEqual(len(card.select('[data-model="B"] .ticket')), 2)
        self.assertEqual(len(card.select('[data-model="B"] .phase-steps li')), 0)
        self.assertIn("6局面の順序を検証できません", card.text)


if __name__ == "__main__":
    unittest.main()
