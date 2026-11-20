"""Source-free DOM examples shaped like published public racecard tables.

All row values in this test are EXAMPLE DATA, not an independent
pre-cutoff source receipt. A successful CI cannot stand in for real GET.
"""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import unittest

from race_ai import keirin_public_two_source_normalizer as adapter
from race_ai import keirin_nationwide_auto_generator as auto

RID="202611182401"
NOW="2026-11-18T09:02:00+09:00"
SEEN="2026-11-18T09:00:00+09:00"
NET="https://keirin.netkeiba.com/race/entry/?race_id=202611182401"
KD="https://keirin.kdreams.jp/utsunomiya/racedetail/2420261117020001/"
SHORT=("小出慎","橋本祐","関　敬","松本一","服部竜","廣川貞")


def pages():
    rows=[]
    for car in range(1,7):
        # 23 cells in the publicly displayed main netkeirin table.
        cells=[
            str(car),str(car),"",str([1,5,2,5,4,3][car-1]),
            SHORT[car-1],f"{75-car:.2f}",
            ("1逃" if car in (1,4) else "3追"),
            "2","0",str(car%7),"1","1","1","1",
            "2","3","1","18",f"{car*3:.1f}%","24.0%","34.0%",
            "3.92","自力" if car in (1,4) else "前へ"
        ]
        rows.append("<tr>"+ "".join("<td>"+x+"</td>" for x in cells)+"</tr>")
    net=(
        '<html><body><h1>宇都宮競輪 1R チャレンジ一般</h1>'
        '<table><tr><th>枠</th><th>車</th><th>本紙</th><th>競走得点</th>'
        '<th>脚質</th><th>勝率</th></tr>'+
        "".join(rows)+"</table></body></html>").encode("utf-8")
    kd=(
        "<html><body><h1>宇都宮競輪 レース詳細 チャレンジ一般</h1>"
        "<p>発走予定 20:50</p><p>投票締切 20:45</p>"
        "<h2>並び予想</h2>"
        "<p>← 1先行 5追込 2追上 4押え先 3追込 6追込</p>"
        "<h2>レース評</h2><p>本命の紹介</p></body></html>").encode("utf-8")
    return net,kd


def build(*,net=None,kdreams=None,now=NOW,kd_url=KD):
    a,b=pages()
    return adapter.merge_pre_race_pages(
        race_id=RID,
        netkeirin_raw=net if net is not None else a,
        netkeirin_url=NET,netkeirin_captured_at=SEEN,
        kdreams_raw=kdreams if kdreams is not None else b,
        kdreams_url=kd_url,kdreams_captured_at=SEEN,
        created_at=now)


def scoped_kdreams(*,title="Ａ級準決勝",leading_follower=False):
    """Invented race facts in the published header/line DOM shape."""
    groups=[[1,5],[2],[4,3,6]]
    spans=['<span class="icon_p"><span class="p000">←</span></span>']
    for group in groups:
        for offset,car in enumerate(group):
            role="追込" if offset or leading_follower else "先行"
            spans.append('<span class="icon_p"><span>'+str(car)+
                         '</span><span>'+role+'</span></span>')
        spans.append('<span class="icon_p space"></span>')
    return (f'<html><head><link rel="canonical" href="{KD}"></head><body>'
            '<nav>S級決勝 L級ガールズ 並び予想</nav>'
            '<p>別レース 投票締切 00:01</p>'
            '<div class="racecard_header"><div class="inner cf">'
            f'<h2 class="title"><span class="status">{title}</span></h2>'
            '<dl class="time"><dt class="start">発走</dt><dd>20:50</dd>'
            '<dt class="bet">締切</dt><dd>20:45</dd></dl></div></div>'
            '<h2>並び予想</h2><div class="line_position">'+''.join(spans)+
            '</div><h2>レース評</h2></body></html>').encode()


class ActualSourceShapeAdapter(unittest.TestCase):
    def parse_scoped(self,**options):
        try:
            return adapter.parse_kdreams(raw=scoped_kdreams(**options),
                source_url=KD,race_id=RID,captured_at=SEEN,
                starter_cars=[1,2,3,4,5,6])
        except adapter.PublicPageNormalizeError as exc:
            self.fail("Published structured race facts were rejected: "+str(exc))

    def test_scoped_header_ignores_other_race_cutoff_class_and_final_navigation(self):
        packet=self.parse_scoped()
        self.assertEqual(packet["cutoff_at"],
                         "2026-11-18T20:45:00+09:00")
        self.assertEqual(packet["competition"],"A1_A2")
        self.assertEqual(packet["round_stage"],"SEMI_FINAL")

    def test_structured_line_spaces_preserve_group_whose_first_role_is_follower(self):
        packet=self.parse_scoped(leading_follower=True)
        self.assertEqual(packet["line_groups"],[[1,5],[2],[4,3,6]])

    def test_scoped_girls_display_positions_become_solo_research_groups(self):
        packet=self.parse_scoped(title="L級ガールズ予選")
        self.assertEqual(packet["competition"],"GIRLS")
        self.assertEqual(packet["round_stage"],"PRELIMINARY")
        self.assertEqual(packet["line_groups"],[[1],[2],[3],[4],[5],[6]])

    def test_present_canonical_for_another_race_cannot_authenticate_the_page(self):
        net,kd=pages()
        for who,raw,url in (("net",net,NET),("kd",kd,KD)):
            wrong=url.replace("0001/","0002/") if who=="kd" else url[:-2]+"02"
            bound=raw.replace(b"<html>",(
                '<html><head><link rel="canonical" href="'+wrong+'"></head>').encode())
            with self.subTest(source=who),self.assertRaisesRegex(
                    adapter.PublicPageNormalizeError,"SOURCE_CANONICAL_URL_RACE_MISMATCH"):
                build(**({"net":bound} if who=="net" else {"kdreams":bound}))

    def test_conflicting_canonical_tags_are_held(self):
        net,kd=pages()
        net=net.replace(b"<html>",(
            '<html><head><link rel="canonical" href="'+NET+'">'
            '<link rel="canonical" href="'+NET[:-2]+'02"></head>').encode())
        with self.assertRaisesRegex(adapter.PublicPageNormalizeError,
                                    "SOURCE_CANONICAL_URL_RACE_MISMATCH"):
            build(net=net)

    def test_netkeirin_marks_and_kdreams_line_meeting_day2(self):
        parsed=build()
        s=parsed["source_packet"]
        self.assertEqual(s["race_id"],RID)
        self.assertEqual(s["published_cutoff_at"],
                         "2026-11-18T20:45:00+09:00")
        self.assertEqual(s["line_groups"],[[1,5],[2],[4,3,6]])
        self.assertEqual([r["mark_rank"] for r in s["riders"]],
                         [1,5,2,5,4,3])
        self.assertTrue(all(r["athlete_id"] is None for r in s["riders"]))
        self.assertTrue(parsed["provider_H_B_definition_not_cross_conflated"])
        self.assertTrue(parsed[
            "recent_form_is_observed_last_four_month_win_rate_proxy"])
        self.assertFalse(parsed[
            "organizer_actual_close_instant_independently_verified"])

    def test_existing_generator_completes_A_B_without_official_reg_ids(self):
        parsed=build()
        preds=auto.generate_A_B(parsed["source_packet"],generated_at=NOW)
        self.assertTrue(preds["A"]["ranked_tickets"])
        self.assertTrue(preds["B"]["ranked_tickets"])
        self.assertEqual(len(preds["B"]["six_phase_scenarios"])>=2,True)
        self.assertTrue(all(len(s["six_phases"])==6 for s in
                            preds["B"]["six_phase_scenarios"]))
        self.assertEqual(preds["C"]["state"],
                         "HOLD_NO_INDEPENDENT_HISTORICAL_FOLLOW_LABELS")

    def test_girls_without_explicit_lineup_is_solo_research_only(self):
        a,b=pages()
        title="宇都宮競輪 レース詳細 チャレンジ一般".encode()
        b=b.replace(title,"宇都宮競輪 レース詳細 L級 ガールズ予選".encode())
        b=b.replace(
            "<h2>並び予想</h2>".encode()+
            "<p>← 1先行 5追込 2追上 4押え先 3追込 6追込</p>".encode(),
            b"")
        out=build(kdreams=b)
        snap=out["source_packet"]
        self.assertEqual(snap["competition"],"GIRLS")
        self.assertEqual(snap["line_groups"],[[1],[2],[3],[4],[5],[6]])
        forecast=auto.generate_A_B(snap,generated_at=NOW)
        self.assertFalse(forecast["all_six_phase_orders_are_hypotheses_not_video_truth"] is False)

    def test_identical_desktop_mobile_rows_may_repeat_without_duplicate_car(self):
        a,b=pages()
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(a.decode("utf-8"),"html.parser")
        table=soup.find("table")
        self.assertIsNotNone(table)
        copy=BeautifulSoup(str(table),"html.parser")
        soup.body.append(copy)
        out=build(net=str(soup).encode())["source_packet"]
        self.assertEqual(len(out["riders"]),6)

    def test_conflicting_desktop_mobile_rider_stat_is_hold_not_merge(self):
        a,b=pages()
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(a.decode("utf-8"),"html.parser")
        table=soup.find("table")
        copy=BeautifulSoup(str(table),"html.parser")
        # Mutate one visible duplicate metric while retaining same car.
        cells=copy.find_all("tr")[1].find_all("td")
        cells[5].string="66.99"
        soup.body.append(copy)
        with self.assertRaisesRegex(adapter.PublicPageNormalizeError,
                                    "NETKEIRIN_CONFLICTING_CAR_ROWS"):
            build(net=str(soup).encode())

    def test_A_class_ordinary_race_not_girls_because_navigation_mentions_L_class(self):
        a,b=pages()
        b=b.replace("チャレンジ一般".encode(),"A級特一般".encode())
        b=b.replace(b"<body>", "<body><nav>L級ガールズ</nav>".encode())
        packet=build(kdreams=b)["source_packet"]
        self.assertEqual(packet["competition"],"A1_A2")
        self.assertEqual(packet["line_groups"],[[1,5],[2],[4,3,6]])

    def test_last_race_lineup_section_not_site_navigation_anchor(self):
        a,b=pages()
        b=b.replace(
            "<h2>並び予想</h2>".encode(),
            "<nav>並び予想</nav><h2>並び予想</h2>".encode())
        packet=build(kdreams=b)["source_packet"]
        self.assertEqual(packet["line_groups"],[[1,5],[2],[4,3,6]])

    def test_line_prefix_rejects_other_car_numbers(self):
        a,b=pages()
        b=b.replace("← 1先行".encode(),
                    "3-5-6 ← 1先行".encode())
        with self.assertRaisesRegex(adapter.PublicPageNormalizeError,
                                    "KDREAMS_LINE_PREFIX_AMBIGUOUS"):
            build(kdreams=b)

    def test_wrong_meeting_start_day_or_race_rejected(self):
        with self.assertRaisesRegex(adapter.PublicPageNormalizeError,
                                    "KDREAMS_RACE_DETAIL_ID_MISMATCH"):
            build(kd_url="https://keirin.kdreams.jp/utsunomiya/racedetail/2420261117010001/")
        with self.assertRaisesRegex(adapter.PublicPageNormalizeError,
                                    "KDREAMS_RACE_DETAIL_ID_MISMATCH"):
            build(kd_url="https://keirin.kdreams.jp/utsunomiya/racedetail/2420261117020002/")

    def test_incomplete_runner_roster_is_hold(self):
        a,b=pages()
        a=a.replace(b"<td>6</td><td>6</td>",b"<td>6</td><td>9</td>")
        with self.assertRaisesRegex(adapter.PublicPageNormalizeError,
                                    "NETKEIRIN_COMPLETE_SOURCED_ENTRANTS_MISSING"):
            build(net=a)

    def test_missing_factual_rider_stat_rejected(self):
        a,b=pages()
        a=a.replace(b"<td>74.00</td>",b"<td>???</td>")
        with self.assertRaisesRegex(adapter.PublicPageNormalizeError,
                                    "PUBLISHED_NUMERIC_ROW_INVALID"):
            build(net=a)

    def test_late_source_or_capture_is_not_backdated(self):
        with self.assertRaisesRegex(adapter.PublicPageNormalizeError,
                                    "SOURCE_NOT_COLLECTED_BEFORE_NORMALIZATION"):
            build(now="2026-11-18T08:59:00+09:00")
        with self.assertRaises(auto.AutomaticForecastError):
            build(now="2026-11-18T20:44:00+09:00")

    def test_explicit_source_byte_hash_retained_to_auto_input(self):
        a,b=pages()
        s=build()["source_packet"]
        self.assertEqual(s["source_pages"][0]["bytes_sha256"],
                         sha256(a).hexdigest())
        self.assertEqual(s["cutoff_source"]["bytes_sha256"],
                         sha256(b).hexdigest())
        self.assertEqual(s["source_pages"][1]["kind"],"MARKS")
        self.assertEqual(s["source_pages"][2]["kind"],"LINE")

    def test_unrecognized_standalone_line_not_merged_by_visual_proximity(self):
        a,b=pages()
        b=b.replace("2追上".encode(), "2未分類".encode())
        # A new unsupported lineup role must not be silently joined.
        with self.assertRaisesRegex(adapter.PublicPageNormalizeError,
                                    "KDREAMS_LINE_NOT_ALL_REAL_CARS"):
            build(kdreams=b)

    def test_ties_and_unmarked_riders_preserve_published_mark_metadata(self):
        a,b=pages()
        a=a.replace(b"<td>5</td><td>\xe6\xa9\x8b",b"<td>100</td><td>\xe6\xa9\x8b")
        # Stronger source uses first ten cells; we still never assign a
        # fictitious last-place integer to a blank paper mark.
        s=build(net=a)["source_packet"]
        self.assertIn("UNMARKED",[r["mark_rank"] for r in s["riders"]])


if __name__=="__main__":
    unittest.main()
