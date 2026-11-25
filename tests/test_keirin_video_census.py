import gzip
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts import keirin_video_census as census


class TestCensus(unittest.TestCase):
    def test_daily_links_require_matching_date_and_label(self):
        day = date(2023, 12, 2)
        url = "https://keirin.kdreams.jp/kochi/racedetail/7420231201020001/"
        html = f"""<h2>2023年12月02日 レース結果一覧</h2><div class="raceinfo_table"><table>
        <tr><td><a href="{url}?pageType=showResult">1R</a></td></tr></table></div>"""
        self.assertEqual(census.calendar_links(html, day), {"20231202-74-01": url})
        for damaged in (html.replace("02日", "03日"), html.replace("1R", "2R"),
                        html.replace("keirin.kdreams.jp", "other.invalid")):
            with self.assertRaises(ValueError):
                census.calendar_links(damaged, day)

    def test_verified_card_and_partial_archives_are_kept(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            html = """<h2>2023年12月02日 レース結果一覧</h2><div class="raceinfo_table"><table><tr><td>
            <a href="/kochi/racedetail/7420231201020001/">1R</a>
            <a href="/kochi/racedetail/7420231201020002/">2R</a></td></tr></table></div>"""
            with gzip.open(root / '2023-12-02.html.gz', 'wt') as stream:
                stream.write(html)
            day = date(2023, 12, 2)
            db = census.Census(day, day)
            db.add_calendars(root)
            db.register("20231202-74-01", "programme", {1: "012345", 2: None})
            db.register("20231202-74-01", "monthly", {1: "067890", 2: "013579", 3: None})
            db.register("20231202-74-03", "sqlite", {4: "012345", 5: "012345"})
            rows = list(db.records())
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["riders"], [{"car": 1, "rider_id": None}, {"car": 2, "rider_id": "013579"}])
            self.assertEqual(rows[0]["roster_status"], "conflict")
            self.assertEqual(rows[1]["roster_status"], "unavailable")
            self.assertIsNone(rows[2]["race_detail_url"])
            self.assertTrue(all(r["rider_id"] is None for r in rows[2]["riders"]))

    def test_special_finishes_preserve_observed_starters_and_exclude_dns(self):
        entries = [("20240101", "74", 1, car, str(car), str(car), finish)
                   for car, finish in enumerate(("1", "失", "落", "3", "故", "欠"), start=1)]
        self.assertEqual(census.starter_field(entries), ({1, 2, 3, 4, 5}, {6}))
        entries[0] = (*entries[0][:-1], "")
        self.assertIsNone(census.starter_field(entries))

    def test_complete_public_starters_bind_both_sources_and_canonical_event(self):
        key = "20231202-74-01"
        kd_url = "https://keirin.kdreams.jp/kochi/racedetail/7420231201020001/"
        net_url = "https://keirin.netkeiba.com/race/result/?race_id=202312027401"
        entrants = "".join(f'<tr><td class="num">{i}</td><td class="rider">Rider{i}<br><span class="home">神奈川/21/98</span></td></tr>'
                           for i in range(1, 7))
        kd_results = "".join(f'<tr><td></td><td>{i}</td><td>{i}</td><td>Rider{i}</td></tr>' for i in range(1, 7))
        net_results = "".join(
            f'<tr class="PlayerList"><td class="Result_Num">{i}着</td><td></td><td class="Waku{i}">{i}</td>'
            f'<td class="Player_Info"><a class="Player01" href="https://keirin.netkeiba.com/db/profile/?id=1500{i}">'
            f'<span class="PlayerName">Rider{i}</span></a><dd class="PlayerFrom"><span>神奈</span>21歳</dd>'
            f'<dd class="PlayerClass">98期 Ａ3</dd></td></tr>' for i in range(1, 7))
        kd = f'<link rel="canonical" href="{kd_url}"><table class="racecard_table">{entrants}</table>'
        kd += f'<table class="result_table">{kd_results}</table>'
        net = f'<link rel="canonical" href="{net_url}"><table class="ResultRefund">{net_results}</table>'
        witnessed = census.defaultdict(set)
        self.assertEqual(census.public_starters(key, kd_url, kd, net, witnesses=witnessed),
                         ({i: f"01500{i}" for i in range(1, 7)}, set()))
        self.assertEqual(witnessed["Rider2", 98, "神奈川"], {"015002"})
        for bad in (net.replace("Rider2", "Unknown"), net.replace("20231202", "20231203"),
                    net.replace("15002", "15001"), net.replace("Waku2", "Waku3")):
            with self.assertRaises(ValueError):
                census.public_starters(key, kd_url, kd, bad)

    def test_cached_calendar_fetch_is_resumable(self):
        day = date(2023, 12, 2)
        html = """<h2>2023年12月02日 レース結果一覧</h2><div class="raceinfo_table">
        <a href="/kochi/racedetail/7420231201020001/">1R</a></div>""".encode()
        with tempfile.TemporaryDirectory() as folder:
            requests = []
            def fetch(url):
                requests.append(url)
                return html
            for _ in range(2):
                census.cache_calendars(Path(folder), day, day, fetch=fetch, pause=lambda _: None)
            self.assertEqual(requests, ["https://keirin.kdreams.jp/raceresult/2023/12/02/"])
            db = census.Census(day, day)
            db.add_calendars(Path(folder))
            self.assertEqual(len(list(db.records())), 1)

    def test_historical_ids_require_matching_name_cohort_and_region(self):
        base = census.IdentityIndex([], [])
        records = {("田中太郎", 90, "東京"): {"015432"}}
        joined = census.WitnessedIdentityIndex(base, records)
        self.assertEqual(joined.bind(("田中太郎", 90, "東京"), from_csv=False), "015432")
        self.assertEqual(joined.bind(("田中太郎東", 90, "京"), from_csv=True), "015432")
        for candidate in (("田中太郎", 91, "東京"), ("田中太郎", 90, "京都"), ("田中", 90, "東京")):
            self.assertIsNone(joined.bind(candidate, from_csv=False))
        records["田中太郎", 90, "東京"].add("012345")
        db = census.Census(date(2024, 1, 1), date(2024, 1, 1))
        self.assertIsNone(census._bind(joined, "田中太郎", "90", "東京", False, db, "20240101-25-01", 2))
        self.assertIn(("20240101-25-01", 2), db.conflicts)

    def test_csv_metadata_does_not_choose_a_finish_or_discard_incident(self):
        self.assertEqual(census.monthly_key("7420231201020001", "2023-12-01", "1"), "20231202-74-01")
        self.assertEqual(census.monthly_key("7420231201020001", "2023-12-02", "1"), "20231202-74-01")
        self.assertEqual(census.monthly_key("2620240204020101", "2024-02-04", "1"), "20240206-26-01")
        self.assertEqual(census.monthly_key("2620240204020101", "2024-02-04", "101"), "20240206-26-01")
        for row in (("7420231201020001", "2023-12-03", "1"),
                    ("7420231201020001", "2023-12-02", "2")):
            with self.assertRaises(ValueError):
                census.monthly_key(*row)
