import unittest
from datetime import date
from race_ai.core import SourceError
from race_ai.venue_meet_html import extract_meet

URL="https://www.boatrace-tokuyama.jp/modules/raceinfo/?kind=2&page=index_timerank"
HTML="<html><body><h2>一般 トライアングルカップ 最終日</h2><p>2026/10/10（土）～2026/10/14（水）</p></body></html>"


class MeetHTMLTests(unittest.TestCase):
    def test_actual_official_published_date_layout(self):
        result=extract_meet(HTML,source_url=URL,day=date(2026,10,14))
        self.assertEqual(result["meet_id"],"18-20261010-20261014")
        self.assertFalse(result["identity_verified"])

    def test_wrong_day_rejected(self):
        with self.assertRaises(SourceError):
            extract_meet(HTML,source_url=URL,day=date(2026,10,15))

    def test_conflicting_meet_rejected(self):
        with self.assertRaises(SourceError):
            extract_meet(HTML+"<p>2026/10/13（火）～2026/10/14（水）</p>",
                         source_url=URL,day=date(2026,10,14))
