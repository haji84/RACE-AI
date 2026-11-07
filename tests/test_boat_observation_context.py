"""Synthetic official-structure fragments; no captured page text is committed."""
from copy import deepcopy
from hashlib import sha256
import importlib
import json
import unittest


try:
    context = importlib.import_module("race_ai.boat_observation_context")
except ModuleNotFoundError:
    context = None

DAY = "20300401"
RACE_ID = "20300401-12-12"
CAPTURED = "2030-04-01T18:00:00+09:00"
ROSTER = [{"lane": lane, "registration_number": str(4000 + lane), "name": f"選手 {lane}"}
          for lane in range(1, 7)]


def url(kind="beforeinfo", venue="12"):
    return f"https://www.boatrace.jp/owpc/pc/race/{kind}?rno=12&jcd={venue}&hd={DAY}"


def frame(content, kind="beforeinfo"):
    headers = "".join(
        f'<th class="{("is-thColor2" if n != 12 else "")}"><a href="/owpc/pc/race/{kind}?rno={n}&amp;jcd=12&amp;hd={DAY}">{n}R</a></th>'
        for n in range(1, 13))
    times = "".join(f'<td class="{("is-activeColor1" if n == 7 else "")}">20:30</td>'
                    for n in range(1, 13))
    tabs = "".join(f'<li><a href="/owpc/pc/race/{name}?rno=12&amp;jcd=12&amp;hd={DAY}">{name}</a></li>'
                   for name in ("racelist", "odds3t", "beforeinfo", "raceresult"))
    return (f'<div class="contentsFrame1_inner"><table><thead><tr><th>レース</th>{headers}</tr></thead>'
            f'<tbody><tr><td>締切予定時刻</td>{times}</tr></tbody></table>'
            f'<div class="tab3"><ul>{tabs}</ul></div>{content}</div>').encode()


def profile(lane, *, image=False):
    inner = '<img src="/placeholder.jpg"/>' if image else f"選手 {lane}"
    return f'<a href="/owpc/pc/data/racersearch/profile?toban={4000 + lane}">{inner}</a>'


def before_table(*, display="&nbsp;", tilt="&nbsp;", marker="&nbsp;", parts="", adjustment="0.0"):
    bodies = "".join(
        f'<tbody><tr><td class="is-boatColor{lane}" rowspan="4">{lane}</td>'
        f'<td rowspan="4">{profile(lane, image=True)}</td><td rowspan="4">{profile(lane)}</td>'
        f'<td rowspan="2">52.0kg</td><td rowspan="4">{display}</td><td rowspan="4">{tilt}</td>'
        f'<td rowspan="4">{marker}</td><td rowspan="4"><ul class="labelGroup1">{parts}</ul></td>'
        '<td>R</td><td>3</td></tr><tr><td>進入</td><td>2</td></tr>'
        f'<tr><td rowspan="2">{adjustment}</td><td>ST</td><td>.16</td></tr>'
        '<tr><td>着順</td><td>1</td></tr></tbody>' for lane in range(1, 7))
    return '<table><thead><tr><th>枠 写真 ボートレーサー 体重 展示タイム チルト プロペラ 部品交換 調整重量 前走成績</th></tr></thead>' + bodies + '</table>'


def starts(*, populated=False, flying=False):
    if populated:
        rows = "".join(
            f'<tr><td colspan="3"><span class="table1_boatImage1Number">{position}</span>'
            f'<img src="/static_extra/pc/images/img_boat2_{lane}.png"/>'
            f'<span class="table1_boatImage1Time">{("F.03" if flying and lane == 1 else ".12")}</span></td></tr>'
            for position, lane in enumerate((2, 1, 3, 4, 5, 6), 1))
    else:
        rows = '<tr><td colspan="3">&nbsp;</td></tr>' * 6
    return '<table><thead><tr><th>スタート展示</th></tr><tr><th>コース</th><th>並び</th><th>ST</th></tr></thead><tbody>' + rows + '</tbody></table>'


def weather(title="水面気象情報 6R時点"):
    units = "".join(f'<div class="weather1_bodyUnit {css}"><span class="weather1_bodyUnitLabelTitle">{label}</span><span class="weather1_bodyUnitLabelData">{value}</span></div>'
                    for css, label, value in (("is-direction", "気温", "14.0℃"),
                    ("is-weather", "曇り", ""), ("is-wind", "風速", "0m"),
                    ("is-waterTemperature", "水温", "16.0℃"), ("is-wave", "波高", "0cm")))
    return f'<div class="weather1"><p class="weather1_title">{title}</p>{units}<div class="weather1_bodyUnit is-windDirection"><p class="is-wind17"></p></div></div>'


def pit_table():
    bodies = "".join(f'<tbody><tr><td class="is-boatColor{lane}">{lane}</td><td>{profile(lane, image=True)}</td>'
                     f'<td><div>{4000 + lane} / A1</div><div>{profile(lane)}</div></td>'
                     f'<td class="is-alignL is-p0-10">{("調整を続ける。(コメント自信度・・★★☆)" if lane == 2 else "&nbsp;")}</td><td></td></tr></tbody>'
                     for lane in range(1, 7))
    return '<table><thead><tr><th>枠 ボートレーサー ピットレポート 前走結果 登録番号/級別 氏名</th></tr></thead>' + bodies + '</table><div class="text"><p class="h-floatR">レポーター： 記者 名</p></div>'


def program_table():
    bodies = "".join(
        f'<tbody><tr><td class="is-boatColor{lane}" rowspan="4">{chr(0xFF10 + lane)}</td>'
        f'<td rowspan="4">{profile(lane, image=True)}</td>'
        f'<td rowspan="4"><div>{4000 + lane} / A1</div>{profile(lane)}</td>'
        '<td>unparsed ST</td><td>unparsed national</td><td>unparsed local</td>'
        '<td>unparsed motor</td><td>unparsed boat</td></tr>'
        '<tr><td></td></tr><tr><td></td></tr><tr><td></td></tr></tbody>'
        for lane in range(1, 7))
    return ('<div class="table1 is-tableFixed__3rdadd"><table><thead><tr>'
            '<th>枠 ボートレーサー 写真 登録番号/級別 氏名 全国 当地 モーター ボート</th>'
            '</tr></thead>' + bodies + '</table></div>')


def sg_program():
    extra = ('<li><a href="/owpc/pc/race/pitreport?rno=12&amp;jcd=12&amp;hd=20300401">report</a></li>'
             '<li><a href="/owpc/pc/race/pointrank?jcd=12&amp;hd=20300401">rank</a></li>'
             '<li><a href="/owpc/pc/race/pointchart?rno=12&amp;jcd=12&amp;hd=20300401">chart</a></li>')
    return frame(program_table(), "racelist").replace(b'</ul></div>', extra.encode() + b'</ul></div>', 1)


class BoatObservationContextTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(context, "supplemental BOAT context parser is missing")

    def parse(self, raw=None, *, kind="beforeinfo", **kwargs):
        method = context.parse_beforeinfo if kind == "beforeinfo" else context.parse_pitreport
        return method(raw if raw is not None else frame(before_table() + starts() + weather()),
                      source_url=kwargs.pop("source_url", url(kind)), captured_at=kwargs.pop("captured_at", CAPTURED),
                      expected_race_id=kwargs.pop("expected_race_id", RACE_ID), roster=kwargs.pop("roster", ROSTER), **kwargs)

    def test_empty_exhibition_keeps_published_weights_weather_and_missing_metrics(self):
        raw = frame(before_table() + starts() + weather())
        result = self.parse(raw)
        self.assertEqual(result["status"], "PARSED")
        self.assertFalse(result["forecast_ready"])
        self.assertEqual(result["roster_binding_status"], "VERIFIED")
        self.assertEqual(result["source"]["sha256"], sha256(raw).hexdigest())
        self.assertEqual(result["source"]["source_url"], url())
        self.assertEqual(result["source"]["captured_at"], CAPTURED)
        self.assertIsNone(result["source"]["published_at"])
        first = result["participants"][0]
        self.assertEqual((first["lane"], first["registration_number"]), (1, "4001"))
        self.assertEqual((first["bodyweight_kg"], first["adjustmentweight_kg"]), (52.0, 0.0))
        for key in ("tilt", "display_time", "exhibition_st", "exhibition_course"):
            self.assertIsNone(first[key], key)
        self.assertEqual(first["exhibition_st_status"], "NOT_PUBLISHED")
        self.assertEqual(first["propeller_change_status"], "NOT_PUBLISHED")
        self.assertIsNone(first["parts_replacement"])
        self.assertEqual(result["weather"]["wind_speed_mps"], 0.0)
        self.assertEqual(result["weather"]["wave_height_cm"], 0.0)
        self.assertEqual(result["weather"]["air_temperature_c"], 14.0)
        self.assertEqual(result["weather"]["wind_direction_source_code"], 17)
        self.assertEqual(result["weather"]["reported_race_no"], 6)
        self.assertEqual(result["weather"]["freshness_status"], "UNKNOWN_SOURCE_TIME_HAS_NO_DATE")
        self.assertEqual(set(result["visual_observations"].values()), {"UNAVAILABLE_FROM_SOURCE"})
        json.dumps(result, allow_nan=False)

    def test_explicit_metrics_parts_marker_and_exhibition_dispositions_remain_distinct(self):
        raw = frame(before_table(display="6.82", tilt="-0.5", marker="新", parts="<li>リング×2</li><li>電気</li>", adjustment="1.5") + starts(populated=True, flying=True))
        result = self.parse(raw)
        first = result["participants"][0]
        self.assertEqual(first["display_time"], 6.82)
        self.assertEqual(first["tilt"], -0.5)
        self.assertEqual(first["adjustmentweight_kg"], 1.5)
        self.assertEqual(first["propeller_change_marker"], "新")
        self.assertEqual(first["propeller_change_status"], "REPORTED_NEW")
        self.assertEqual(first["parts_replacement"], ["リング×2", "電気"])
        self.assertIsNone(first["exhibition_st"])
        self.assertEqual(first["exhibition_st_status"], "F")
        self.assertEqual(first["exhibition_st_raw"], "F.03")
        self.assertEqual(first["exhibition_source_position_number"], 2)
        self.assertIsNone(first["exhibition_course"])
        self.assertEqual(result["participants"][1]["exhibition_st"], 0.12)
        self.assertFalse(result["forecast_ready"])

    def test_weather_clock_without_date_is_never_promoted_to_publication_timestamp(self):
        result = self.parse(frame(before_table() + starts() + weather("水面気象情報 17:55現在")))
        self.assertEqual(result["weather"]["source_reported_local_time"], "17:55")
        self.assertIsNone(result["weather"]["reported_at"])
        self.assertIsNone(result["source"]["published_at"])
        self.assertEqual(result["source"]["freshness_status"], "UNKNOWN")

    def test_pit_comments_keep_text_reporter_and_racer_attribution_without_scores(self):
        result = self.parse(frame(pit_table(), "pitreport"), kind="pitreport")
        self.assertEqual(result["status"], "PARSED")
        self.assertEqual(result["reporter"], "記者 名")
        row = result["participants"][1]
        self.assertEqual(row["comment"], "調整を続ける。(コメント自信度・・★★☆)")
        self.assertEqual(row["comment_status"], "REPORTED")
        self.assertEqual(row["comment_attribution"], {"racer_name": "選手 2", "reporter": "記者 名", "kind": "OFFICIAL_PIT_REPORT"})
        self.assertIsNone(result["participants"][0]["comment"])
        self.assertNotIn("sentiment", json.dumps(result))

    def test_explicit_not_offered_has_no_verified_roster_or_invented_comments(self):
        result = self.parse(frame('<h3>※ ピットレポートの表示対象レースではありません。</h3>', "pitreport"), kind="pitreport")
        self.assertEqual(result["status"], "NOT_OFFERED")
        self.assertEqual(result["participants"], [])
        self.assertEqual(result["roster_binding_status"], "NOT_PUBLISHED")

    def test_unknown_structures_are_explicit_and_empty_values_never_become_zero(self):
        result = self.parse(frame('<div>new unknown layout</div>'))
        self.assertEqual(result["status"], "UNSUPPORTED_STRUCTURE")
        self.assertEqual(result["participants"], [])
        raw = frame(before_table(adjustment="&nbsp;") + starts())
        self.assertIsNone(self.parse(raw)["participants"][0]["adjustmentweight_kg"])

    def test_wrong_day_venue_selected_race_or_detached_identity_fails_closed(self):
        raw = frame(before_table() + starts())
        for bad in (raw.replace(b"hd=20300401", b"hd=20300402"),
                    raw.replace(b"jcd=12", b"jcd=15"),
                    raw.replace(b'<th class="is-thColor2"><a href="/owpc/pc/race/beforeinfo?rno=1&', b'<th class=""><a href="/owpc/pc/race/beforeinfo?rno=1&'),
                    b'<a href="' + url().encode() + b'">12R</a>' + before_table().encode()):
            with self.subTest(body=bad[:50]), self.assertRaises(ValueError):
                self.parse(bad)
        with self.assertRaises(ValueError):
            self.parse(raw, expected_race_id="20300401-12-11")

    def test_roster_registration_name_and_profile_disagreement_fail_closed(self):
        raw = frame(before_table() + starts())
        bad_roster = deepcopy(ROSTER)
        bad_roster[0]["registration_number"] = "4999"
        bad_name = deepcopy(ROSTER)
        bad_name[0]["name"] = "別人"
        for roster in (bad_roster, bad_name, ROSTER[:5], ROSTER + [ROSTER[0]]):
            with self.subTest(roster=roster), self.assertRaises(ValueError):
                self.parse(raw, roster=roster)
        with self.assertRaises(ValueError):
            self.parse(raw.replace(b"toban=4001", b"toban=4999", 1))
        with self.assertRaises(ValueError):
            self.parse(raw.replace(b"toban=4001", b"unknown=4001"))

    def test_malformed_numbers_unknown_propeller_and_duplicate_rows_do_not_parse(self):
        for content in (before_table(tilt="NaN") + starts(),
                        before_table(marker="unknown") + starts(),
                        before_table().replace('is-boatColor6', 'is-boatColor1').replace('>6</td>', '>1</td>') + starts()):
            with self.subTest(content=content[-30:]), self.assertRaises(ValueError):
                self.parse(frame(content))

    def test_pre_cutoff_capture_eligibility_is_separate_from_unknown_freshness(self):
        result = self.parse()
        before = context.eligibility_for_cutoff(result, cutoff_at="2030-04-01T20:30:00+09:00")
        self.assertTrue(before["captured_before_cutoff"])
        self.assertTrue(before["pre_cutoff_eligible"])
        self.assertEqual(before["publication_freshness_status"], "UNKNOWN")
        after = context.eligibility_for_cutoff(result, cutoff_at=CAPTURED)
        self.assertFalse(after["pre_cutoff_eligible"])
        self.assertEqual(after["reason"], "CAPTURED_AT_OR_AFTER_CUTOFF")
        wrong_day = context.eligibility_for_cutoff(result, cutoff_at="2030-04-02T20:30:00+09:00")
        self.assertFalse(wrong_day["pre_cutoff_eligible"])
        historical = self.parse(captured_at="2030-04-02T08:00:00+09:00")
        self.assertFalse(context.eligibility_for_cutoff(historical, cutoff_at="2030-04-01T20:30:00+09:00")["pre_cutoff_eligible"])

    def test_timestamps_require_timezones_and_urls_are_exact_official_endpoints(self):
        for captured_at in ("2030-04-01T18:00:00", "not a time"):
            with self.assertRaises(ValueError):
                self.parse(captured_at=captured_at)
        for source_url in (url().replace("www.boatrace.jp", "evil.example"), url() + "&hd=20300401", url("pitreport"), url().replace("https:", "http:")):
            with self.assertRaises(ValueError):
                self.parse(source_url=source_url)

    def test_later_caller_cutoff_cannot_admit_capture_after_official_body_cutoff(self):
        late = self.parse(captured_at="2030-04-01T21:00:00+09:00")
        eligibility = context.eligibility_for_cutoff(late, cutoff_at="2030-04-01T22:00:00+09:00")
        self.assertFalse(eligibility["pre_cutoff_eligible"])
        self.assertEqual(eligibility["reason"], "CAPTURED_AT_OR_AFTER_CUTOFF")

    def program_roster(self, raw):
        self.assertTrue(hasattr(context, "parse_program_roster"), "metadata-only official program parser is missing")
        return context.parse_program_roster(raw, source_url=url("racelist"), captured_at=CAPTURED,
                                            expected_race_id=RACE_ID)

    def test_program_roster_accepts_valid_sg_navigation_without_parsing_forecast_stats(self):
        raw = sg_program()
        result = self.program_roster(raw)
        self.assertEqual(result["race_id"], RACE_ID)
        self.assertEqual(result["source_cutoff_at"], "2030-04-01T20:30:00+09:00")
        self.assertEqual(result["participants"], ROSTER)
        self.assertEqual(result["source"]["sha256"], sha256(raw).hexdigest())
        self.assertEqual(result["source"]["source_url"], url("racelist"))
        self.assertEqual(result["source"]["captured_at"], CAPTURED)
        self.assertEqual(set(result["participants"][0]), {"lane", "registration_number", "name"})

    def test_program_roster_requires_body_day_venue_and_selected_race_proof(self):
        raw = sg_program()
        for bad in (raw.replace(b"hd=20300401", b"hd=20300402"),
                    raw.replace(b"jcd=12", b"jcd=15"),
                    b'<a href="' + url("racelist").encode() + b'">12R</a>' + program_table().encode()):
            with self.subTest(body=bad[:30]), self.assertRaises(ValueError):
                self.program_roster(bad)

    def test_program_roster_rejects_wrong_sg_nav_scope_and_extra_blank_query(self):
        raw = sg_program()
        for bad in (raw.replace(b'pointrank?jcd=12&amp;hd=20300401', b'pointrank?jcd=12&amp;hd=20300402'),
                    raw.replace(b'pointrank?jcd=12&amp;hd=20300401', b'pointrank?jcd=12&amp;hd=20300401&amp;extra=')):
            with self.subTest(body=bad[-100:]), self.assertRaises(ValueError):
                self.program_roster(bad)

    def test_program_roster_rejects_missing_duplicate_or_unbound_profile_identities(self):
        raw = sg_program()
        for bad in (frame('<div>no roster</div>', 'racelist'),
                    raw.replace(b'toban=4001', b'toban=4999', 1),
                    raw.replace(b'toban=4006', b'toban=4001'),
                    raw.replace(b'4001 / A1', b'4999 / A1'),
                    raw.replace(b'is-boatColor6', b'is-boatColor1')):
            with self.subTest(body=bad[-100:]), self.assertRaises(ValueError):
                self.program_roster(bad)


if __name__ == "__main__":
    unittest.main()
