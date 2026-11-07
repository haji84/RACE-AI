"""Authored official-shaped result fixtures; no preserved race originals."""
from copy import deepcopy
from datetime import datetime
import importlib
import unittest

from tests import test_jra_official_sparse_adapter as sparse_fixtures

metadata = sparse_fixtures.metadata


URL = "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1003202603011120261107/AA"
NOW = datetime.fromisoformat("2026-11-07T07:01:00+00:00")


def result_html(*, places=("1", "2", "3"), payout="3-1-2", extra_payout="", refund="", table=True):
    rows = []
    for place, number in zip(places, (3, 1, 2)):
        rows.append(f'''<tr><td class="place">{place}</td><td class="waku"><img alt="1枠"></td><td class="num">{number}</td>
        <td class="horse"><a href="/JRADB/accessU.html?CNAME=pw01dud10202000000{number}/AA">創作馬{number}</a></td>
        <td class="time">1:10.0</td><td class="pop">99 番人気</td></tr>''')
    entries = '<table class="basic narrow-xy striped"><tr><th class="place">着順</th><th class="num">馬番</th><th class="horse">馬名</th></tr>'+"".join(rows)+'</table>' if table else '<div class="race_status">レース結果は確定後に公開されます</div>'
    payments = f'''<div class="refund_area"><div class="refund_unit mt15"><ul><li class="tierce"><dl><dt>3連単</dt><dd>
        <div class="line"><div class="num">{payout}</div><div class="yen">1,230 <span class="unit">円</span></div><div class="pop">99 番人気</div></div>
        {extra_payout}</dd></dl></li>{refund}</ul></div><div class="caution">取消・返還のお知らせをご確認ください。払戻金は100円あたりです。</div></div>''' if table else ''
    return ('''<html><meta charset="shift_jis"><h1>レース結果 2026年11月7日（土曜）3回福島1日 11レース</h1>'''+entries+payments+'</html>').encode('cp932')


def source_metadata(raw):
    meta = metadata(raw, URL, completed="2026-11-07T07:00:00+00:00")
    meta["fetched_at"] = "2026-11-07T06:59:58+00:00"
    return meta


def frozen():
    return sparse_fixtures.JraOfficialSparseAdapterTests().build()["native_payload"]


class JraOfficialResultAdapterTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("race_ai.jra_official_result_adapter"), "official result adapter is absent")
        return importlib.import_module("race_ai.jra_official_result_adapter")

    def parse(self, raw=None, *, meta=None, payload=None):
        raw = result_html() if raw is None else raw
        return self.module().parse_result(raw, source_metadata(raw) if meta is None else meta,
            frozen_native_payload=frozen() if payload is None else payload, now=NOW,
            source_rights_ref="SYNTHETIC_OFFICIAL_RESULT_EVALUATION")

    def test_normal_single_trifecta_matches_full_number_horse_identity_and_finish_order(self):
        observation = self.parse()
        self.assertEqual(observation["status"], "settled")
        self.assertEqual(observation["sport"], "horse")
        self.assertEqual(observation["ordered_top3"], [3, 1, 2])
        self.assertEqual(observation["payout_per_100_yen"], 1230)
        self.assertEqual(observation["roster"], {str(i):f"jra:202000000{i}" for i in (1,2,3)})
        self.assertTrue(observation["identity_verified"])
        self.assertEqual(observation["refund_numbers"], [])
        self.assertEqual(observation["captured_at"], "2026-11-07T07:00:00+00:00")
        self.assertIsNone(observation["published_at"])
        self.assertEqual(observation["closed_at"], frozen()["snapshot"]["race"]["sales_cutoff_at"])

    def test_unpublished_result_remains_pending_without_a_loss_or_zero_payout(self):
        observation = self.parse(result_html(table=False))
        self.assertEqual(observation["status"], "pending")
        self.assertEqual(observation["ordered_top3"], [])
        self.assertIsNone(observation["payout_per_100_yen"])

    def test_tie_cancel_exclusion_nonfinish_and_multiple_payments_are_special(self):
        for placing in (("1","1","3"), ("取消","2","3"), ("除外","2","3"), ("中止","2","3"), ("失格","2","3")):
            with self.subTest(placing=placing):
                observation = self.parse(result_html(places=placing))
                self.assertEqual(observation["status"], "special")
                self.assertIsNone(observation["payout_per_100_yen"])
                self.assertEqual(observation["ordered_top3"], [])
        extra = '<div class="line"><div class="num">1-3-2</div><div class="yen">100 円</div></div>'
        self.assertEqual(self.parse(result_html(extra_payout=extra))["status"], "special")

    def test_explicit_result_refund_is_special_but_generic_refund_notice_is_not(self):
        self.assertEqual(self.parse()["status"], "settled")
        refund = '<li class="refund"><dl><dt>返還</dt><dd><div class="num">2</div></dd></dl></li>'
        observation = self.parse(result_html(refund=refund))
        self.assertEqual(observation["status"], "special")
        self.assertEqual(observation["refund_numbers"], [2])

    def test_single_payment_must_match_official_top_three_in_order(self):
        with self.assertRaises(ValueError): self.parse(result_html(payout="3-2-1"))

    def test_result_url_day_venue_and_race_must_match_body_and_frozen_input(self):
        for before, after in (("11レース", "10レース"), ("福島", "東京"), ("2026年11月7日", "2026年11月8日")):
            raw = result_html().decode('cp932').replace(before,after).encode('cp932')
            with self.subTest(after=after), self.assertRaises(ValueError): self.parse(raw)
        payload=frozen();payload["snapshot"]["race"]["race_id"]="horse:2026-11-07:jra-03:10"
        with self.assertRaises(ValueError): self.parse(payload=payload)

    def test_full_roster_stable_ids_and_slot_numbers_cannot_be_substituted(self):
        raw=result_html().replace(b"2020000002",b"2020000099")
        with self.assertRaises(ValueError): self.parse(raw)
        raw=result_html().replace(b"2020000002",b"2020000001")
        with self.assertRaises(ValueError): self.parse(raw)
        payload=frozen();payload["snapshot"]["participants"].pop()
        with self.assertRaises(ValueError): self.parse(payload=payload)

    def test_actual_completion_clock_hash_and_source_url_are_required(self):
        for field,value in (("response_received_at","2026-11-07T08:00:00+00:00"),
                            ("source_sha256","f"*64),("final_url","https://bad.invalid/result")):
            meta=source_metadata(result_html());meta[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.parse(meta=meta)
        meta=source_metadata(result_html());meta["response_received_at"]="2026-11-07T06:00:00+00:00";meta["fetched_at"]="2026-11-07T05:59:59+00:00"
        with self.assertRaises(ValueError):self.parse(meta=meta)

    def test_source_only_result_inspection_does_not_fabricate_pre_cutoff_input_proof(self):
        raw=result_html();facts=self.module().parse_official_result_source(raw,source_metadata(raw),now=NOW)
        self.assertEqual(facts["status"],"settled")
        self.assertIs(facts["future_frozen_input_paired"],False)
        self.assertNotIn("input_saved_at",facts)

    def test_postrace_popularity_does_not_mutate_or_enter_native_features(self):
        payload=frozen();before=deepcopy(payload)
        observation=self.parse(payload=payload)
        self.assertEqual(payload,before)
        self.assertFalse(any("pop" in key or "odds" in key for key in observation))

    def test_explicit_current_race_cancellation_stays_special_without_inventing_roster(self):
        raw=result_html(table=False).decode('cp932').replace('レース結果は確定後に公開されます','開催中止').encode('cp932')
        observation=self.parse(raw)
        self.assertEqual(observation['status'],'special')
        self.assertFalse(observation['identity_verified'])
        self.assertIsNone(observation['payout_per_100_yen'])

    def test_generic_native_intake_accepts_only_normal_case_and_excludes_pending_special(self):
        from race_ai.all_existing_model_intake import _ordinary_result
        from race_ai.all_existing_model_registry import identity
        from race_ai.four_sport_model_suite import ALL_MODELS
        info=identity(ALL_MODELS[0],'horse',frozen())
        label,excluded=_ordinary_result(self.parse(),info,NOW)
        self.assertIsNone(excluded)
        self.assertEqual(label['ordered_top3'],[3,1,2])
        for raw,expected in ((result_html(table=False),'pending'),(result_html(places=('1','1','3')),'special')):
            with self.subTest(expected=expected):
                label,excluded=_ordinary_result(self.parse(raw),info,NOW)
                self.assertIsNone(label)
                self.assertEqual(excluded,expected)


if __name__=="__main__":unittest.main()
