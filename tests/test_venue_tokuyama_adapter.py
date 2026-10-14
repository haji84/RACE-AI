import unittest
from datetime import date
from race_ai.core import SourceError
from race_ai.venue_tokuyama_adapter import parse_tokuyama_race_index

URL="https://www.boatrace-tokuyama.jp/modules/raceinfo/?page=index_raceindex&targetday=20261014"
HTML="<table><tr><th>レース</th>"+"".join(f"<th>{i}</th>" for i in range(1,7))+"</tr><tr><td>1R</td>"+"".join(f"<td>選手{i}</td>" for i in range(1,7))+"</tr></table>"


class TokuyamaAdapterTests(unittest.TestCase):
    def test_six_lanes_without_invented_ids(self):
        result=parse_tokuyama_race_index(HTML,day=date(2026,10,14),source_url=URL)
        self.assertEqual(result["races"][0]["race_id"],"20261014-18-01")
        self.assertEqual(len(result["races"][0]["boats"]),6)
        self.assertIsNone(result["races"][0]["boats"][0]["racer_registration_id"])
        self.assertFalse(result["redistribution_authorized"])

    def test_wrong_day_rejected(self):
        with self.assertRaises(SourceError):
            parse_tokuyama_race_index(HTML,day=date(2026,10,13),source_url=URL)

    def test_missing_lane_rejected(self):
        with self.assertRaises(SourceError):
            parse_tokuyama_race_index(HTML.replace("<td>選手6</td>",""),day=date(2026,10,14),source_url=URL)

    def test_duplicate_race_rejected(self):
        duplicate=HTML.replace("</table>","<tr><td>1R</td>"+"".join(f"<td>別選手{i}</td>" for i in range(1,7))+"</tr></table>")
        with self.assertRaises(SourceError):
            parse_tokuyama_race_index(duplicate,day=date(2026,10,14),source_url=URL)
