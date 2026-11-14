"""Synthetic official program structures, never retained source payloads."""
from datetime import date
from hashlib import sha256
import importlib
import json
import unittest


try:
    adapter = importlib.import_module("race_ai.boat_official_program")
except ModuleNotFoundError:
    adapter = None

DAY = date(2030, 4, 1)
CAPTURED = "2030-04-01T18:00:00+09:00"


def source_url(venue="12", race_no=12, kind="racelist"):
    return (f"https://www.boatrace.jp/owpc/pc/race/{kind}"
            f"?rno={race_no}&jcd={venue}&hd=20300401")


def profile(lane, *, photo=False, registration=None, name=None):
    registration = registration or str(4000 + lane)
    text = '<img src="/synthetic.jpg"/>' if photo else name or f"合成 選手{lane}"
    return f'<a href="/owpc/pc/data/racersearch/profile?toban={registration}">{text}</a>'


def entrant(lane, *, withdrawn=False, identities=True, national="5.80<br>30.00<br>45.00",
            local="6.20<br>40.00<br>55.00", st="F0<br>L0<br>.15", name=None,
            missing_column=None, layout="br"):
    slots = {
        "st": st, "national": national, "local": local,
        "motor": f"{10 + lane}<br>35.00<br>50.00",
        "boat": f"{30 + lane}<br>36.00<br>51.00",
    }
    if layout == "blocks":
        slots = {key: "".join(f"<div>{part}</div>" for part in value.split("<br>"))
                 for key, value in slots.items()}
    elif layout == "spaces":
        slots = {key: value.replace("<br>", " ") for key, value in slots.items()}
    identity = (f'<div>{4000 + lane} / A1</div><div>{profile(lane, name=name)}</div>'
                if identities else "&nbsp;")
    photo = profile(lane, photo=True) if identities else "&nbsp;"
    marker = '<span class="is-fColor1">欠場</span>' if withdrawn else ""
    metrics = "".join(f'<td rowspan="4">{value}</td>' for key, value in slots.items()
                      if key != missing_column)
    return (f'<tbody><tr><td rowspan="4" class="is-boatColor{lane}">{lane}</td>'
            f'<td rowspan="4">{photo}</td><td rowspan="4">{identity}{marker}</td>{metrics}'
            '<td>1</td></tr><tr><td>2</td></tr><tr><td>3</td></tr><tr><td>4</td></tr></tbody>')


def program_table(*, lanes=(1, 2, 3, 4, 5, 6), withdrawn=(), missing_column=None,
                  layout="br", row_options=None):
    headers = {
        "st": "F数<br>L数<br>平均ST", "national": "全国<br>勝率<br>2連率<br>3連率",
        "local": "当地<br>勝率<br>2連率<br>3連率", "motor": "モーター<br>No.<br>2連率<br>3連率",
        "boat": "ボート<br>No.<br>2連率<br>3連率",
    }
    metrics = "".join(f'<th rowspan="2">{value}</th>' for key, value in headers.items()
                      if key != missing_column)
    rows = "".join(entrant(lane, withdrawn=lane in withdrawn, missing_column=missing_column,
                           layout=layout, **(row_options or {}).get(lane, {})) for lane in lanes)
    return ('<div class="table1 is-tableFixed__3rdadd"><table><thead><tr>'
            '<th rowspan="2">枠</th><th colspan="2">ボートレーサー</th>' + metrics +
            '<th rowspan="2">今節成績</th></tr><tr><th>写真</th>'
            '<th>登録番号 / 級別<br>氏名</th></tr></thead>' + rows + '</table></div>')


def page(*, venue="12", race_no=12, sg=False, content=None, selected=None, **table_options):
    selected = {race_no} if selected is None else set(selected)
    headers = "".join(
        f'<th class="{("" if number in selected else "is-thColor2")}">'
        f'<a href="/owpc/pc/race/racelist?rno={number}&amp;jcd={venue}&amp;hd=20300401">{number}R</a></th>'
        for number in range(1, 13))
    times = "".join('<td>20:30</td>' for _ in range(12))
    kinds = ("odds3t", "beforeinfo", "pcexpect", "myexpect", "raceresult")
    if sg:
        kinds += ("racelist", "pitreport", "pointchart")
    tabs = "".join(f'<li><a href="/owpc/pc/race/{kind}?rno={race_no}&amp;jcd={venue}&amp;hd=20300401">{kind}</a></li>'
                   for kind in kinds)
    if sg:
        tabs += f'<li><a href="/owpc/pc/race/pointrank?jcd={venue}&amp;hd=20300401">rank</a></li>'
    return ('<div class="contentsFrame1_inner"><table><thead><tr><th>レース</th>' + headers +
            '</tr></thead><tbody><tr><td>締切予定時刻</td>' + times + '</tr></tbody></table>'
            '<div class="tab3"><ul>' + tabs + '</ul></div>' +
            (program_table(**table_options) if content is None else content) + '</div>').encode()


class OfficialProgramTests(unittest.TestCase):
    def parse(self, raw=None, *, venue="12", race_no=12, **kwargs):
        self.assertIsNotNone(adapter, "owned official program adapter is missing")
        return adapter.parse_program(page(venue=venue, race_no=race_no) if raw is None else raw,
                                     day=kwargs.pop("day", DAY), venue=venue, race_no=race_no,
                                     source_url=kwargs.pop("source_url", source_url(venue, race_no)),
                                     captured_at=kwargs.pop("captured_at", CAPTURED), **kwargs)

    def test_program_values_identity_names_and_pinned_provenance(self):
        raw = page()
        result = self.parse(raw)
        self.assertEqual(result["race_id"], "20300401-12-12")
        self.assertEqual(result["status"], "OFFICIAL_BODY_IDENTITY_VERIFIED")
        self.assertEqual(result["closed_at"], "2030-04-01T20:30:00+09:00")
        self.assertEqual((result["date_jst"], result["venue"]), ("2030-04-01", "12"))
        self.assertEqual(result["source_sha256"], sha256(raw).hexdigest())
        self.assertEqual(result["first_observed_at"], CAPTURED)
        self.assertEqual(result["captured_at"], CAPTURED)
        self.assertTrue(result["pre_cutoff_eligible"])
        row = result["boats"][0]
        self.assertEqual((row["lane"], row["racer_registration_id"], row["name"]), (1, "4001", "合成 選手1"))
        self.assertEqual((row["motor_no"], row["boat_no"], row["average_st"]), (11, 31, .15))
        self.assertEqual((row["national_win_rate"], row["local_win_rate"]), (5.8, 6.2))
        self.assertEqual(row["entry_status"], "listed")
        self.assertEqual(row["missing_fields"], {})
        self.assertIsNone(result["source"]["published_at"])
        self.assertEqual(result["source"]["freshness_status"], "UNKNOWN")
        json.dumps(result, allow_nan=False)

    def test_all24_venue_identities_accept_sg_navigation_and_block_stat_variants(self):
        for number in range(1, 25):
            venue = f"{number:02d}"
            with self.subTest(venue=venue):
                result = self.parse(page(venue=venue, sg=True, layout="blocks"), venue=venue)
                self.assertEqual(result["race_id"], f"20300401-{venue}-12")
                self.assertEqual(result["boats"][5]["national_win_rate"], 5.8)
        self.assertEqual(self.parse(page(layout="spaces"))["boats"][0]["average_st"], .15)

    def test_blank_win_rate_preserves_its_slot_and_never_uses_second_stat(self):
        result = self.parse(page(row_options={1: dict(national="&nbsp;<br>30.00<br>45.00", st="F0<br>L0<br>&nbsp;")}))
        row = result["boats"][0]
        self.assertIsNone(row["national_win_rate"])
        self.assertIsNone(row["average_st"])
        self.assertEqual(row["missing_fields"]["national_win_rate"], "NOT_PUBLISHED")
        self.assertEqual(row["missing_fields"]["average_st"], "NOT_PUBLISHED")
        self.assertEqual(row["entry_status"], "listed")

    def test_absent_stat_column_is_distinct_from_present_blank(self):
        result = self.parse(page(missing_column="local"))
        self.assertIsNone(result["boats"][0]["local_win_rate"])
        self.assertEqual(result["boats"][0]["missing_fields"]["local_win_rate"], "FIELD_NOT_IN_SOURCE")
        self.assertEqual(result["boats"][0]["motor_no"], 11)

    def test_real_zeros_remain_observed_and_bad_stats_are_rejected(self):
        row = self.parse(page(row_options={1: dict(national="0.00<br>0.00<br>0.00", st="F0<br>L0<br>0.00")}))["boats"][0]
        self.assertEqual(row["national_win_rate"], 0.0)
        self.assertEqual(row["average_st"], 0.0)
        self.assertEqual(row["missing_fields"], {})
        for value in ("NaN", "Infinity", "10.01", "-1", "unparsed"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse(page(row_options={1: dict(national=f"{value}<br>30.0<br>40.0")}))

    def test_withdrawals_keep_official_identities_and_noncontiguous_active_lanes(self):
        result = self.parse(page(withdrawn=(2, 5)))
        self.assertEqual(len(result["boats"]), 6)
        self.assertEqual(result["active_lanes"], [1, 3, 4, 6])
        self.assertEqual(result["boats"][1]["entry_status"], "withdrawn")
        self.assertEqual(result["boats"][1]["racer_registration_id"], "4002")
        self.assertTrue(result["trifecta_available"])
        result = self.parse(page(withdrawn=(2,), row_options={2: dict(identities=False)}))
        self.assertIsNone(result["boats"][1]["racer_registration_id"])
        self.assertEqual(result["boats"][1]["missing_fields"]["racer_registration_id"], "EXPLICIT_WITHDRAWAL")
        with self.assertRaises(ValueError):
            self.parse(page(row_options={2: dict(identities=False)}))

    def test_actual3to6_entrant_tables_preserve_physical_lane_numbers(self):
        for lanes in ((1, 3, 6), (1, 2, 4, 6), (1, 2, 3, 4, 6), (1, 2, 3, 4, 5, 6)):
            with self.subTest(lanes=lanes):
                result = self.parse(page(lanes=lanes))
                self.assertEqual(result["active_lanes"], list(lanes))
                self.assertTrue(result["trifecta_available"])
        result = self.parse(page(withdrawn=(2, 3, 4, 5)))
        self.assertEqual(result["active_lanes"], [1, 6])
        self.assertFalse(result["trifecta_available"])
        self.assertEqual(result["trifecta_status"], "FEWER_THAN_THREE_ACTIVE_ENTRANTS")

    def test_wrong_race_day_venue_url_and_ambiguous_selection_fail_closed(self):
        raw = page(sg=True)
        bodies = [raw.replace(b"hd=20300401", b"hd=20300402"),
                  raw.replace(b"jcd=12", b"jcd=14"), page(race_no=11),
                  page(selected={11, 12}), page(selected=set()),
                  b'<a href="' + source_url().encode() + b'">12R</a>' + program_table().encode()]
        for body in bodies:
            with self.subTest(size=len(body)), self.assertRaises(ValueError):
                self.parse(body)
        for url in (source_url().replace("https:", "http:"), source_url().replace("www.boatrace.jp", "elsewhere.example"),
                    source_url() + "&hd=20300401", source_url() + "&extra=", source_url(kind="beforeinfo")):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.parse(raw, source_url=url)

    def test_sg_navigation_still_requires_exact_race_or_venue_day_scope(self):
        raw = page(sg=True)
        for bad in (raw.replace(b"pointrank?jcd=12&amp;hd=20300401", b"pointrank?jcd=14&amp;hd=20300401"),
                    raw.replace(b"pointrank?jcd=12&amp;hd=20300401", b"pointrank?jcd=12&amp;hd=20300401&amp;extra="),
                    raw.replace(b"pointchart?rno=12", b"pointchart?rno=11"),
                    raw.replace(b"pitreport?rno=12", b"pitreport?rno=11")):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                self.parse(bad)

    def test_profile_printed_registration_and_duplicate_allocations_are_validated(self):
        raw = page()
        for bad in (raw.replace(b"toban=4001", b"toban=4999", 1),
                    raw.replace(b"4001 / A1", b"4999 / A1"),
                    raw.replace(b"toban=4006", b"toban=4001").replace(b"4006 / A1", b"4001 / A1"),
                    raw.replace(b"toban=4001", b"toban=4001&amp;extra="),
                    raw.replace(b"is-boatColor6", b"is-boatColor1"),
                    raw.replace(b">16<br>35.00", b">11<br>35.00"),
                    raw.replace(b">36<br>36.00", b">31<br>36.00")):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                self.parse(bad)

    def test_unicode_name_is_preserved_without_registration_grade_or_branch_text(self):
        name = "合成　髙﨑 さくら"
        raw = page(row_options={1: dict(name=name)})
        self.assertEqual(self.parse(raw)["boats"][0]["name"], name)
        with self.assertRaises(ValueError):
            self.parse(page(row_options={1: dict(name=" ")}))

    def test_historical_receipt_is_explicitly_ineligible_without_backdated_time(self):
        for at in ("2030-04-01T20:30:00+09:00", "2030-04-02T18:00:00+09:00", "2030-03-31T18:00:00+09:00"):
            with self.subTest(at=at):
                result = self.parse(captured_at=at)
                self.assertFalse(result["pre_cutoff_eligible"])
                self.assertEqual(result["first_observed_at"], at)
                self.assertIsNone(result["source"]["published_at"])
        for at in ("2030-04-01T18:00:00", "not-a-time"):
            with self.subTest(at=at), self.assertRaises(ValueError):
                self.parse(captured_at=at)

    def test_missing_or_ambiguous_tables_and_malformed_original_bytes_fail_closed(self):
        for raw in (page(content="<div>unknown layout</div>"), page(content=program_table() * 2),
                    page().replace(b"</tbody>", b"", 1), b"\xff", b"", "not-original-bytes"):
            with self.subTest(kind=type(raw).__name__), self.assertRaises(ValueError):
                self.parse(raw)

    def test_historical_absence_does_not_withdraw_the_current_entry(self):
        raw = page().replace(b'<td>2</td>', '<td>欠場</td>'.encode(), 1)
        result = self.parse(raw)
        self.assertEqual(result["boats"][0]["entry_status"], "listed")
        self.assertEqual(result["active_lanes"], [1, 2, 3, 4, 5, 6])

    def test_identity_cannot_be_detached_from_its_four_row_entry(self):
        raw = page()
        for broken in (raw.replace(b'rowspan="4" class="is-boatColor1"', b'rowspan="3" class="is-boatColor1"'),
                       raw.replace(b'<tr><td>4</td></tr>', b'', 1)):
            with self.subTest(size=len(broken)), self.assertRaises(ValueError):
                self.parse(broken)

    def test_real_three_row_header_maps_statistics_beneath_spanning_racer_heading(self):
        table = program_table()
        old = table[table.index('<thead>'):table.index('</thead>') + len('</thead>')]
        new = ('<thead><tr><th rowspan="3">枠</th><th colspan="3">ボートレーサー</th>'
               '<th>全国</th><th>当地</th><th>モーター</th><th>ボート</th>'
               '<th rowspan="3">今節成績</th></tr><tr>'
               '<th rowspan="2">写真</th><th rowspan="2">登録番号 / 級別<br>氏名</th>'
               '<th rowspan="2">F数<br>L数<br>平均ST</th>'
               '<th rowspan="2">勝率<br>2連率<br>3連率</th>'
               '<th rowspan="2">勝率<br>2連率<br>3連率</th>'
               '<th rowspan="2">No<br>2連率<br>3連率</th>'
               '<th rowspan="2">No<br>2連率<br>3連率</th></tr><tr></tr></thead>')
        result = self.parse(page(content=table.replace(old, new)))
        self.assertEqual(result["boats"][0]["average_st"], .15)
        self.assertEqual(result["boats"][0]["boat_no"], 31)

    def test_cancelled_unpublished_and_no_contest_have_explicit_nonforecast_states(self):
        for notice, state in (("このレースは中止となりました。", "CANCELLED"),
                              ("このレースは不成立となりました。", "NO_CONTEST"),
                              ("出走表はまだ掲載されていません。", "NOT_PUBLISHED")):
            with self.subTest(state=state):
                result = self.parse(page(content=f"<h3>{notice}</h3>"))
                self.assertEqual(result["race_status"], state)
                self.assertEqual(result["boats"], [])
                self.assertFalse(result["trifecta_available"])
        raw = page(content='<h3>このレースは中止となりました。</h3>' + program_table())
        result = self.parse(raw)
        self.assertEqual(len(result["boats"]), 6)
        self.assertFalse(result["trifecta_available"])
        self.assertEqual(result["race_status"], "CANCELLED")

    def test_notice_about_a_previous_race_does_not_cancel_selected_race(self):
        raw = page(content='<p>前日のレースは中止となりました。</p>' + program_table())
        result = self.parse(raw)
        self.assertEqual(result["race_status"], "LISTED")
        self.assertTrue(result["trifecta_available"])

    def test_all_source_top2_top3_rates_are_retained_for_native_models(self):
        row = self.parse()["boats"][0]
        expected = {"national_top2_rate": 30.0, "national_top3_rate": 45.0,
                    "local_top2_rate": 40.0, "local_top3_rate": 55.0,
                    "motor_top2_rate": 35.0, "motor_top3_rate": 50.0,
                    "boat_top2_rate": 36.0, "boat_top3_rate": 51.0}
        for field, value in expected.items():
            with self.subTest(field=field):
                self.assertEqual(row.get(field), value)

    def test_missing_rate_slot_remains_missing_without_shifting_top3(self):
        row = self.parse(page(row_options={1: dict(national="5.80<br>&nbsp;<br>45.00")}))["boats"][0]
        self.assertIsNone(row.get("national_top2_rate"))
        self.assertEqual(row.get("national_top3_rate"), 45.0)
        self.assertEqual(row["missing_fields"].get("national_top2_rate"), "NOT_PUBLISHED")
        row = self.parse(page(missing_column="local"))["boats"][0]
        for field in ("local_win_rate", "local_top2_rate", "local_top3_rate"):
            self.assertIsNone(row[field])
            self.assertEqual(row["missing_fields"][field], "FIELD_NOT_IN_SOURCE")


if __name__ == "__main__":
    unittest.main()
