import gzip
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from lxml import html

from scripts import keirin_video_archive_index as audit


DAY = date(2024, 8, 5)
BASE = audit.DOMAIN
DETAIL = f"{BASE}/hakodate/racedetail/1120240804020001/"
MEETING = f"{BASE}/hakodate/raceresult/11202408040200/"
REPLAY = f"{BASE}/stadium/digest/?kyogijoCd=11&amp;kaisaiDate=20240805&amp;gradeCd=1&amp;raceNo=1"
POPUP = f"""<a onclick="windowOpen('{REPLAY}', '', '710,460') ;" href="javascript:void(0);">[映像]</a>"""
CALENDAR = f"""<html><head><link rel="canonical" href="{BASE}/raceresult/2024/08/05/"></head>
<body><h2>2024年08月05日 レース結果一覧</h2><div class="raceinfo_table"><table><tr><td>
<a href="{MEETING}">一覧</a><a href="{DETAIL}?pageType=showResult">1R</a>
</td></tr></table></div></body></html>"""


class ArchiveReplays(unittest.TestCase):
    def test_reference_is_a_published_visible_link_with_unambiguous_race(self):
        self.assertEqual(
            audit.declared_replay(html.fromstring(POPUP)),
            ("20240805-11-01", REPLAY.replace("&amp;", "&")),
        )
        for malformed in (
            POPUP.replace("keirin.kdreams.jp", "example.invalid"),
            POPUP.replace("raceNo=1", "raceNo=1&amp;raceNo=3"),
            POPUP.replace("kaisaiDate=20240805", "kaisaiDate=20241390"),
            POPUP.replace("[映像]", "関連情報"),
            POPUP.replace("windowOpen", "other"),
        ):
            with self.subTest(malformed=malformed):
                self.assertIsNone(audit.declared_replay(html.fromstring(malformed)))

    def test_public_tab_is_separate_from_initially_displayed_and_disabled(self):
        for attrs in (
            'aria-disabled="true"',
            'class="disabled"',
            'style="display:none"',
        ):
            button = html.fromstring(f"<div {attrs}>{POPUP}</div>")[0]
            self.assertIsNone(audit.control_surface(button, True))
        table = html.fromstring(
            f'<table class="past_racecard_table none"><tr><td>{POPUP}</td></tr></table>'
        )
        (button,) = table.xpath("//a")
        self.assertIsNone(audit.control_surface(button, False))
        self.assertEqual(
            audit.control_surface(button, True), "public_previous_runs_tab"
        )
        self.assertEqual(
            audit.control_surface(html.fromstring(POPUP), False), "normal_markup"
        )

    def test_crosschecks_venue_and_dated_index(self):
        tree = html.fromstring(CALENDAR)
        self.assertEqual(
            audit.daily_targets(tree, DAY), {"20240805-11-01": (DETAIL, MEETING)}
        )
        with self.assertRaises(ValueError):
            audit.daily_targets(
                html.fromstring(CALENDAR.replace("11202408040200/", "11202408040300/")),
                DAY,
            )

    def test_supplement_binds_each_button_to_visible_race_heading(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            saved = work / "venue.html"
            saved.write_text(
                f'<link rel="canonical" href="{MEETING}"><div class="header"><p class="race"><a href="{DETAIL}">1R</a></p><ul><li class="btn_digest">{POPUP}</li></ul></div>'
            )
            obs = audit.venue_observation(saved)
            self.assertEqual(
                set(obs["buttons_bound_to_race_headings"]), {"20240805-11-01"}
            )
            (work / "2024-08-05.html.gz").write_bytes(gzip.compress(CALENDAR.encode()))
            queue = work / "queue"
            queue.write_text(
                json.dumps(
                    {
                        "race_id": "20240805-11-01",
                        "race_date": str(DAY),
                        "race_detail_url": DETAIL,
                        "stage": "source",
                    }
                )
            )
            _, counts = audit.evidence(queue, work, [], obs)
            self.assertEqual(counts["target_races_with_link_in_normal_markup"], 1)
            self.assertEqual(counts["separate_venue_races_already_in_archive"], 0)
            obs["source_page"] = obs["source_page"].replace("hakodate", "other")
            with self.assertRaises(ValueError):
                audit.evidence(queue, work, [], obs)
            saved.write_text(saved.read_text().replace("raceNo=1", "raceNo=2"))
            with self.assertRaises(ValueError):
                audit.venue_observation(saved)

    def test_index_alone_is_not_a_movie_and_deduplicates_documents(self):
        with tempfile.TemporaryDirectory() as work:
            base = Path(work)
            (base / f"{DAY}.html.gz").write_bytes(gzip.compress(CALENDAR.encode()))
            queue = base / "queue"
            queue.write_text(
                json.dumps(
                    {
                        "race_id": "20240805-11-01",
                        "race_date": str(DAY),
                        "race_detail_url": DETAIL,
                        "stage": "source",
                    }
                )
            )
            rows, counts = audit.evidence(queue, base, [])
            self.assertEqual(counts["target_races_with_only_calendar_detail"], 1)
            doc = base / "detail.html"
            doc.write_text(
                f'<html><head><link rel="canonical" href="{DETAIL}"></head><body>{POPUP}</body></html>'
            )
            rows, counts = audit.evidence(queue, base, [doc, doc])
            self.assertEqual(counts["target_races_with_published_replay_link"], 1)
            self.assertEqual(counts["saved_official_detail_or_venue_documents"], 1)
            self.assertEqual(
                len(rows["20240805-11-01"]["published_replay_references"]), 1
            )
