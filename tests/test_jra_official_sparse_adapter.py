"""Authored HTML fixtures; no real horses, source bytes or permission claims."""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import importlib
import json
import unittest

from race_ai.comprehensive_four_sport_models import validate, SCHEMA_SPARSE
from race_ai.existing_common_parameter_adapters import predict
from race_ai.four_sport_model_suite import ALL_MODELS


CARD_URL = "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0103202603011120261107/AA"
RULE_URL = "https://www.jra.go.jp/dento/soku/instructions/hatsubai/jra.html"
NOW = datetime.fromisoformat("2026-11-07T01:10:00+00:00")
RIGHTS = "SYNTHETIC_PERSONAL_SOURCE"


def history(index, finish=2, *, venue="福島", surface="芝", distance=1200, field_size=10):
    date = f"2026年{10-index}月1日"
    return f'''<td class="past p{index+1}"><div class="date_line"><div class="date">{date}</div><div class="rc">{venue}</div></div>
    <div class="race_line"><a href="/JRADB/accessS.html?CNAME=pw01sde010320260201012026{10-index:02d}01/AA">創作過去走</a></div>
    <div class="place_line"><div class="place">{finish}着</div><div class="num">{field_size}頭 1番 9番人気</div></div>
    <div class="info_line2"><div class="line">{distance}{surface}<p class="time">1:10.0</p></div><div class="line">良</div></div></td>'''


def card():
    rows = []
    for no in range(1, 4):
        prior = "".join(history(i, no+1) for i in range(4))
        rows.append(f'''<tr><td class="waku"><img alt="1枠"></td><td class="num">{no}<span class="horse_icon blinker"></span></td>
        <td class="horse"><div class="name_line"><a href="/JRADB/accessU.html?CNAME=pw01dud00202000000{no}/AA">創作馬{no}</a></div>
        <span class="odds">999.9 単勝オッズ 人気</span></td><td class="jockey">創作騎手</td>{prior}</tr>''')
    html = '''<html><head><meta charset="shift_jis"></head><body><h1>出馬表 2026年11月7日（土曜）3回福島1日 11レース</h1>
    <div class="cell time">発走時刻：15時20分</div><div class="cell course">コース：1,200メートル（芝・右）</div>
    <table class="basic narrow-xy mt20"><tr><th>枠</th><th>馬番</th><th>馬名</th><th>騎手</th><th>前走</th><th>前々走</th><th>3走前</th><th>4走前</th></tr>'''+"".join(rows)+'''</table>
    <table class="basic narrow-xy"><tr><td class="num">18</td><td class="horse">調教表の創作馬</td></tr></table></body></html>'''
    return html.encode("cp932")


def metadata(raw, url=CARD_URL, *, completed="2026-11-07T01:00:03+00:00"):
    return dict(source_url=url, final_url=url, status=200, byte_count=len(raw), source_sha256=sha256(raw).hexdigest(),
                fetched_at="2026-11-07T01:00:00+00:00", response_received_at=completed,
                headers={"Content-Type": "text/html"}, scope="SYNTHETIC_ONLY")


def evidence():
    raw = '<html><meta charset="utf-8"><h1>即PAT会員の発売時間（2026年）</h1><table><tr><th>土曜日全レース</th><th>発売締切時刻</th><td>各レース 発走時刻1分前</td></tr></table></html>'.encode()
    return dict(raw=raw, metadata=metadata(raw, RULE_URL), sales_channel="SOKU_PAT_JRA_CENTRAL_ORDINARY_BET",
                rule_id="JRA_2026_SATURDAY_ALL_RACES_START_MINUS_60_SECONDS")


class JraOfficialSparseAdapterTests(unittest.TestCase):
    def api(self):
        spec = importlib.util.find_spec("race_ai.jra_official_sparse_adapter")
        self.assertIsNotNone(spec, "official sparse adapter implementation is absent")
        return importlib.import_module("race_ai.jra_official_sparse_adapter").build_sparse_payload

    def build(self, raw=None, meta=None, **kw):
        raw = card() if raw is None else raw
        return self.api()(raw, metadata(raw) if meta is None else meta, now=NOW,
                          source_rights_ref=RIGHTS, cutoff_evidence=kw.pop("cutoff_evidence", evidence()), **kw)

    def test_real_shape_preserves_ids_complete_past_fields_and_native_missing_terms(self):
        result = self.build()
        self.assertEqual(result["state"], "READY")
        payload = result["native_payload"]; snapshot = payload["snapshot"]
        self.assertEqual(snapshot["schema"], SCHEMA_SPARSE)
        self.assertEqual(snapshot["race"]["sport"], "horse")
        self.assertEqual(snapshot["race"]["sales_cutoff_at"], "2026-11-07T15:19:00+09:00")
        self.assertEqual(snapshot["race"]["as_of"], NOW.isoformat())
        self.assertEqual([p["identity"] for p in snapshot["participants"]], [f"jra:202000000{i}" for i in (1, 2, 3)])
        self.assertEqual([p["draw"] for p in snapshot["participants"]], [1, 2, 3])
        self.assertEqual(len(snapshot["participants"]), 3)
        self.assertEqual(snapshot["environment"], {})
        self.assertEqual(result["summary"]["complete_history_rows"], 12)
        p = snapshot["participants"][0]
        self.assertAlmostEqual(p["features"]["ability"]["value"], 8/9)
        self.assertEqual(set(p["features"]), {"ability", "recent_form", "consistency", "course_compatibility", "stamina", "distance_surface_fit", "recent_3race_form"})
        self.assertIn("start_reliability", p["missing"])
        self.assertIn("closing_sectional", p["missing"])
        for participant in snapshot["participants"]:
            for obs in participant["features"].values():
                self.assertIsNone(obs["published_at"])
                self.assertEqual(obs["source_sha256"], metadata(card())["source_sha256"])
                self.assertGreaterEqual(datetime.fromisoformat(obs["captured_at"]), datetime.fromisoformat(metadata(card())["response_received_at"]))
        validate(snapshot)
        for mid in ALL_MODELS:
            self.assertEqual(len(predict(mid, payload, at=NOW)["candidates"]), 6)

    def test_odds_popularity_current_result_and_workout_table_are_not_native_inputs(self):
        result = self.build(); text = json.dumps(result["native_payload"], ensure_ascii=False)
        for banned in ("999.9", "単勝オッズ", "人気", "創作騎手", "調教表", "current_result"):
            self.assertNotIn(banned, text)

    def test_missing_cutoff_evidence_holds_instead_of_assuming_offset(self):
        result = self.build(cutoff_evidence=None)
        self.assertEqual(result["state"], "HOLD")
        self.assertNotIn("native_payload", result)

    def test_wrong_channel_year_weekday_or_offset_cannot_manufacture_cutoff(self):
        for field, value in (("sales_channel", "WIN5"), ("rule_id", "ARBITRARY_THREE_MINUTES")):
            proof = evidence(); proof[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): self.build(cutoff_evidence=proof)
        for before, after in (("2026年", "2025年"), ("土曜日", "日曜日"), ("1分前", "3分前")):
            proof = evidence(); proof["raw"] = proof["raw"].decode().replace(before, after).encode(); proof["metadata"] = metadata(proof["raw"], RULE_URL)
            with self.subTest(after=after), self.assertRaises(ValueError): self.build(cutoff_evidence=proof)
        proof = evidence(); proof["offset_seconds"] = 180
        with self.assertRaises(ValueError): self.build(cutoff_evidence=proof)

    def test_capture_completion_not_get_start_controls_source_availability(self):
        meta = metadata(card(), completed="2026-11-07T01:11:00+00:00")
        with self.assertRaises(ValueError): self.build(meta=meta)

    def test_source_bound_feature_capture_stays_source_completion_when_conversion_is_later(self):
        meta = metadata(card())
        result = self.build(meta=meta)
        source_capture = datetime.fromisoformat(meta["response_received_at"]).isoformat()
        self.assertNotEqual(source_capture, NOW.isoformat())
        self.assertEqual(result["summary"]["converted_at"], NOW.isoformat())
        self.assertEqual(result["native_payload"]["snapshot"]["race"]["as_of"], NOW.isoformat())
        for participant in result["native_payload"]["snapshot"]["participants"]:
            for observation in participant["features"].values():
                self.assertEqual(observation["captured_at"], source_capture)
                self.assertIsNone(observation["published_at"])
        meta = metadata(card()); meta["fetched_at"] = "2026-11-07T01:00:04+00:00"
        with self.assertRaises(ValueError): self.build(meta=meta)

    def test_source_hash_size_and_identity_metadata_are_verified_before_parsing(self):
        for field, value in (("source_sha256", "a"*64), ("byte_count", 1), ("status", 403), ("final_url", "https://bad.invalid/card")):
            meta = metadata(card()); meta[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): self.build(meta=meta)

    def test_card_day_race_and_venue_must_match_official_url_identity(self):
        for before, after in (("11レース", "10レース"), ("福島", "東京"), ("2026年11月7日", "2026年11月8日")):
            raw = card().decode("cp932").replace(before, after).encode("cp932")
            with self.subTest(after=after), self.assertRaises(ValueError): self.build(raw=raw)

    def test_incomplete_history_is_omitted_and_debutants_hold_without_fake_ability(self):
        raw = card().decode("cp932").replace("10頭", "頭", 1).encode("cp932")
        result = self.build(raw=raw)
        self.assertEqual(result["summary"]["complete_history_rows"], 11)
        self.assertEqual(result["summary"]["excluded_history_rows"], 1)
        raw = card().decode("cp932").replace("10頭", "頭").encode("cp932")
        result = self.build(raw=raw)
        self.assertEqual(result["state"], "HOLD")
        self.assertNotIn("native_payload", result)

    def test_duplicate_horse_ids_and_same_day_past_rows_reject(self):
        raw = card().replace(b"2020000002", b"2020000001")
        with self.assertRaises(ValueError): self.build(raw=raw)
        raw = card().decode("cp932").replace("2026年10月1日", "2026年11月7日").encode("cp932")
        with self.assertRaises(ValueError): self.build(raw=raw)

    def test_no_parent_supplied_source_or_rule_is_mutated(self):
        raw = card(); meta = metadata(raw); proof = evidence(); original = deepcopy((meta, proof))
        self.api()(raw, meta, now=NOW, source_rights_ref=RIGHTS, cutoff_evidence=proof)
        self.assertEqual((meta, proof), original)

    def test_all_surface_recent_three_is_separate_observation_without_filling_turf_ability(self):
        raw = card().decode("cp932").replace("1200芝", "1200ダ").encode("cp932")
        result = self.build(raw=raw)
        self.assertEqual(result["state"], "READY")
        for participant in result["native_payload"]["snapshot"]["participants"]:
            self.assertEqual(set(participant["features"]), {"recent_3race_form"})
            self.assertIn("ability", participant["missing"])
            self.assertIn("course_compatibility", participant["missing"])
            observed = participant["features"]["recent_3race_form"]
            self.assertEqual(observed["sample_n"], 3)
            self.assertEqual(observed["transform_id"], "official-prior-finish-percentile-all-surfaces-last3-v1")
            lineage = result["native_payload"]["feature_lineage"][str(participant["number"])]["recent_3race_form"]
            self.assertIs(lineage["target_surface_fit_evaluated"], False)
        self.assertAlmostEqual(result["native_payload"]["snapshot"]["participants"][0]["features"]["recent_3race_form"]["value"], 8/9)

    def test_actual_jump_category_cannot_be_misread_as_flat_turf(self):
        raw = card().decode("cp932").replace('<div class="cell time">', '<div class="cell category">障害3歳以上</div><div class="cell time">').encode("cp932")
        with self.assertRaises(ValueError): self.build(raw=raw)

    def test_optional_recent_summary_uses_only_latest_three_and_observed_sample_count(self):
        html = card().decode("cp932").replace(history(3, 2), history(3, 10))
        observed = self.build(raw=html.encode("cp932"))["native_payload"]["snapshot"]["participants"][0]["features"]["recent_3race_form"]
        self.assertEqual(observed["sample_n"], 3)
        self.assertAlmostEqual(observed["value"], 8/9)
        html = card().decode("cp932")
        for index in (1, 2, 3):
            for finish in (2, 3, 4):
                html = html.replace(history(index, finish), history(index, finish).replace("10頭", "頭"))
        result = self.build(raw=html.encode("cp932"))
        for participant in result["native_payload"]["snapshot"]["participants"]:
            self.assertEqual(participant["features"]["recent_3race_form"]["sample_n"], 1)
            self.assertIn("consistency", participant["missing"])

    def test_rule_raw_bytes_must_match_their_own_retained_source_metadata(self):
        proof = evidence(); proof["metadata"]["source_sha256"] = "f"*64
        with self.assertRaises(ValueError): self.build(cutoff_evidence=proof)

    def test_current_cancel_marker_holds_whole_race_instead_of_forecasting_withdrawn_horse(self):
        for before, after in (('創作馬1</a>', '創作馬1</a><span class="cancel">出走取消</span>'),
                              ('<td class="num">1', '<td class="num">1<span class="cancel">出走取消</span>')):
            raw = card().decode("cp932").replace(before, after, 1).encode("cp932")
            with self.subTest(location=before):
                result = self.build(raw=raw)
                self.assertEqual(result["state"], "HOLD")
                self.assertEqual(result["reasons"], ["CURRENT_ENTRANT_WITHDRAWN"])
                self.assertEqual(result["summary"]["current_withdrawal_count"], 1)
                self.assertNotIn("native_payload", result)

    def test_prior_cancel_word_or_generic_notice_does_not_cancel_current_entrant(self):
        html = card().decode("cp932").replace('創作過去走</a>', '創作過去走</a><span class="cancel">過去走で出走取消</span>', 1)
        html = html.replace('<body>', '<body><p>出走取消・除外のお知らせをご確認ください。</p>')
        result = self.build(raw=html.encode("cp932"))
        self.assertEqual(result["state"], "READY")
        self.assertEqual(result["summary"]["participant_count"], 3)

    def test_current_cell_status_class_and_multiple_withdrawals_are_counted(self):
        html = card().decode("cp932").replace('<td class="horse">', '<td class="horse cancel">', 2)
        result = self.build(raw=html.encode("cp932"))
        self.assertEqual(result["state"], "HOLD")
        self.assertEqual(result["summary"]["current_withdrawal_count"], 2)


if __name__ == "__main__": unittest.main()
