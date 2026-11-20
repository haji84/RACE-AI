"""Source-free examples of the observed public HTML/JSON grammar.

Names, registrations and outcomes below are invented test data.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
import unittest

from race_ai import keirin_official_form_history as form


NOW = datetime(2026, 11, 20, 5, 0, tzinfo=timezone.utc)
TOKEN = "A" * 43


def profile(reg="000001", extra=""):
    labels = {99: "2026/11/20 07:04 更新", 1: "試験選手", 2: "福岡県",
              3: "100期", 4: "30", 5: "Ｌ級１班", 7: "2", 8: "1",
              9: "1", 10: "2", 11: "1", 12: "0", 13: "7", 14: "28.5",
              15: "42.8", 16: "57.1", 17: "2", 18: "3", 19: "51.00"}
    spans = "".join(f'<span id="UNQ_orlabel_{k}">{v}</span>' for k, v in labels.items())
    return (f'<html><head><title>選手近況成績｜KEIRIN.JP</title></head><body>{spans}'
            f'<table><tr><td id="regnum">{reg}</td></tr></table>'
            '<input type="hidden" id="raceResultURL" value="/sp/race" />'
            '<table><tr id="RaceResults_1"><td><span>11/10</span><span>倉</span>'
            '<span>Ｆ２</span></td><td><table><tr><td>'
            f'<span onclick="btnResultClick(\'{TOKEN}\')"><img alt="落" '
            'src="/sp/static/img/icon/print/setP-normal-raku.png" /></span>'
            '</td></tr></table></td></tr><tr id="RaceResults_2"><td><span>10/01</span>'
            '<span>倉</span><span>Ｆ２</span></td><td>病気欠場</td></tr></table>'
            f'{extra}</body></html>').encode()


def result(reg="000001", state="落車棄権", place="", date="2026/11/10"):
    rows = [dict(sensyuRegistNo=f"00000{i}", sensyuName=f"試験{i}", syaban=str(i),
                 tyaku=str(i - 1) if i > 1 else place,
                 kojinStateItemSubData=[dict(kojinState=state, tyakuNote="")]
                 if i == 1 else []) for i in range(1, 8)]
    rows[0]["sensyuRegistNo"] = reg
    header = dict(txtEventDate=date, txtKikan="2026/11/10～2026/11/12", joName="小倉",
                  selRaceNo=1, flgRaceCancel=False)
    doc = dict(resultCd=0, tyakujyunDispFlg=True, lastUpdateTime="2026/11/10 21:06&nbsp;更新",
               digestUrl="https://wm.st.keirin.jp/wm-keirin81/20261110-81-02-01-01-00.mp4",
               tyakujyunItemSubData=rows)
    return ("<html><head><title>レース結果｜KEIRIN.JP</title></head><body><script>"
            "var jsonData = {};" + "jsonData['SC0201'] = " + json.dumps(dict(resultCd=0, C0201data=header))
            + ";jsonData['SJ0326'] = " + json.dumps(doc) + ";</script></body></html>").encode()


def final_result():
    raw = result().decode()
    raw = raw.replace('"flgRaceCancel": false',
                      '"flgRaceCancel": false, "flgKekkaRefund": false, "aftBetDate": "202611102027"')
    raw = raw.replace('"tyakujyunDispFlg": true',
                      '"tyakujyunDispFlg": true, "haraiGakuDispFlg": true, "bikouDispFlg": false, '
                      '"haraiGakuSubData": {"APartReturnDispFlg": false, "RT3HaraiGakuDispItemSubData": '
                      '[{"kumiBan": "2-3-4", "haraiGaku": "1,230", "kumiDispFlg": true}]}')
    return raw.encode()


class OfficialFormHistoryTests(unittest.TestCase):
    def ref(self):
        return form.parse_profile(profile(), expected_registration_id="000001", observed_at=NOW)["history_references"][0]

    def test_profile_identity_stats_and_explicit_unknown_absence_end(self):
        parsed = form.parse_profile(profile(), expected_registration_id="000001", observed_at=NOW)
        self.assertEqual(parsed["registration_id"], "000001")
        self.assertEqual(parsed["stats"]["h_count"], 2)
        self.assertEqual(parsed["stats"]["competition_points"], 51.0)
        self.assertEqual(parsed["history_references"][0]["token"], TOKEN)
        self.assertEqual(parsed["absence_observations"][0]["status_text"], "病気欠場")
        self.assertIsNone(parsed["absence_observations"][0]["end_date"])
        self.assertIsNone(parsed["original_publication_time"])
        self.assertEqual(parsed["source_sha256"], sha256(profile()).hexdigest())

    def test_profile_mismatched_or_duplicated_identity_rejected(self):
        for raw in (profile("000002"), profile(extra='<td id="regnum">000001</td>')):
            with self.assertRaises(form.OfficialFormHistoryError):
                form.parse_profile(raw, expected_registration_id="000001", observed_at=NOW)

    def test_future_profile_update_rejected(self):
        with self.assertRaises(form.OfficialFormHistoryError):
            form.parse_profile(profile().replace(b"2026/11/20", b"2026/11/21"),
                               expected_registration_id="000001", observed_at=NOW)

    def test_unpublished_or_executable_navigation_not_accepted(self):
        raw = profile().replace(TOKEN.encode(), (TOKEN + "');other('").encode())
        with self.assertRaises(form.OfficialFormHistoryError):
            form.parse_profile(raw, expected_registration_id="000001", observed_at=NOW)

    def test_more_less_control_row_is_not_a_history_meeting(self):
        raw = profile(extra='<table><tr id="table_view6"><td>閉じる もっと見る</td></tr></table>')
        parsed = form.parse_profile(raw, expected_registration_id="000001", observed_at=NOW)
        self.assertEqual(len(parsed["history_references"]), 1)

    def test_unfinished_symbol_is_kept_but_not_relabelled_finished(self):
        raw = profile().replace('alt="落"'.encode(), 'alt="未"'.encode())
        parsed = form.parse_profile(raw, expected_registration_id="000001", observed_at=NOW)
        self.assertEqual(parsed["history_references"][0]["observed_status_symbol"], "未")

    def test_actual_result_binds_registered_rider_date_and_field(self):
        parsed = form.parse_history_result(result(), expected_registration_id="000001",
                                           observed_at=NOW, expected_reference=self.ref())
        self.assertEqual(parsed["race_id"], "202611108101")
        self.assertEqual(parsed["field_size"], 7)
        self.assertEqual(parsed["status"], "FALL_DNF")
        self.assertIsNone(parsed["place"])
        self.assertEqual(parsed["source_updated_at"], "2026-11-10T12:06:00+00:00")

    def test_result_cannot_bind_a_different_rider(self):
        with self.assertRaises(form.OfficialFormHistoryError):
            form.parse_history_result(result(reg="999999"), expected_registration_id="000001",
                                      observed_at=NOW, expected_reference=self.ref())

    def test_video_date_and_header_must_agree(self):
        with self.assertRaises(form.OfficialFormHistoryError):
            form.parse_history_result(result(date="2026/11/11"), expected_registration_id="000001",
                                      observed_at=NOW, expected_reference=self.ref())

    def test_profile_symbol_and_actual_result_must_agree(self):
        with self.assertRaises(form.OfficialFormHistoryError):
            form.parse_history_result(result(state="", place="1"), expected_registration_id="000001",
                                      observed_at=NOW, expected_reference=self.ref())

    def test_fall_slide_finish_is_retained_as_fall_not_normal_finish(self):
        ref = form.parse_profile(profile().replace('alt="落"'.encode(), b'alt="1"'),
                                 expected_registration_id="000001", observed_at=NOW)["history_references"][0]
        parsed = form.parse_history_result(result(state="落滑入", place="1"),
                                           expected_registration_id="000001", observed_at=NOW,
                                           expected_reference=ref)
        self.assertEqual(parsed["status"], "FALL_FINISHED")

    def test_dns_excluded_from_field_crash_starter_kept(self):
        raw = result().decode()
        raw = raw.replace('"tyaku": "6", "kojinStateItemSubData": []',
                          '"tyaku": "", "kojinStateItemSubData": [{"kojinState": "欠場"}]')
        parsed = form.parse_history_result(raw.encode(), expected_registration_id="000001",
                                           observed_at=NOW, expected_reference=self.ref())
        self.assertEqual(parsed["listed_rider_count"], 7)
        self.assertEqual(parsed["field_size"], 6)
        self.assertEqual(parsed["status"], "FALL_DNF")

    def test_newer_result_revision_than_bound_profile_is_not_silently_adopted(self):
        raw = result().replace(b"2026/11/10 21:06", b"2026/11/20 08:00")
        with self.assertRaises(form.OfficialFormHistoryError):
            form.parse_history_result(raw, expected_registration_id="000001", observed_at=NOW,
                                      expected_reference=self.ref())

    def final_reference(self):
        return dict(source_url="https://keirin.jp/sp/race", method="POST", disp="SJ0326", token=TOKEN,
                    official_cutoff_at="2026-11-10T20:27:00+09:00",
                    starters=[dict(car=i, registration_id=f"00000{i}") for i in range(1, 8)])

    def test_final_order_can_be_verified_without_inventing_payout_unit(self):
        parsed = form.parse_final_result(final_result(), expected_race_id="202611108101",
                                         observed_at=NOW, expected_reference=self.final_reference())
        self.assertEqual(parsed["winning_triples"], [[2, 3, 4]])
        self.assertEqual(parsed["payout_unit_state"], "SOURCE_UNIT_UNVERIFIED")
        self.assertNotIn("payouts_100yen", parsed)
        self.assertEqual(parsed["published_payout_amounts"], [{"triple": [2, 3, 4], "amount_yen": 1230}])

    def test_final_payout_orders_must_equal_actual_finish_order(self):
        with self.assertRaises(form.OfficialFormHistoryError):
            form.parse_final_result(final_result().replace(b'"2-3-4"', b'"3-2-4"'),
                                    expected_race_id="202611108101", observed_at=NOW,
                                    expected_reference=self.final_reference())

    def unit_evidence(self):
        url = "https://www.hofukeirin.jp/ticket/"
        excerpt = form.reviewed_unit.UNIT_URLS[url]
        raw = ("<html><body><p>" + excerpt + "</p></body></html>").encode()
        digest = sha256(raw).hexdigest()
        return dict(url=url, source_sha256=digest, observed_at=NOW.isoformat(),
                    verified_payout_basis_yen=100, exact_excerpt=excerpt), {digest: raw}

    def test_verified_exact_official_guide_enables_payout_normalization(self):
        unit, sources = self.unit_evidence()
        parsed = form.parse_final_result(final_result(), expected_race_id="202611108101",
                                         observed_at=NOW, expected_reference=self.final_reference(),
                                         verified_unit_evidence=unit, source_bytes_by_sha=sources)
        self.assertTrue(parsed["monetary_comparison_eligible"])
        self.assertEqual(parsed["payouts_100yen"], [{"triple": [2, 3, 4], "yen": 1230}])
        self.assertEqual(parsed["payout_unit_evidence"], unit)

    def test_forged_unit_assertion_without_matching_source_bytes_is_rejected(self):
        unit, sources = self.unit_evidence()
        for evidence, raw_map in ((unit, {}),
                                  (unit, {unit["source_sha256"]: b"unit not stated"}),
                                  (dict(unit, url="https://example.invalid/"), sources),
                                  (dict(unit, observed_at="2026-11-21T00:00:00+00:00"), sources)):
            with self.assertRaises(form.OfficialFormHistoryError):
                form.parse_final_result(final_result(), expected_race_id="202611108101",
                                        observed_at=NOW, expected_reference=self.final_reference(),
                                        verified_unit_evidence=evidence, source_bytes_by_sha=raw_map)


if __name__ == "__main__":
    unittest.main()
