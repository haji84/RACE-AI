import unittest
from datetime import date
from race_ai.core import SourceError
from race_ai.venue_individual_result import parse_individual_result

URL="https://www.boatrace.jp/owpc/pc/race/raceresult?rno=3&jcd=18&hd=20261014"
MAP={"finish":0,"lane":1,"registration":2,"name":3,"st":4}
HTML="<table>"+"".join(f"<tr><td>{i}</td><td>{i}</td><td>{4000+i}</td><td>選手{i}</td><td>0.1{i}</td></tr>" for i in range(1,7))+"</table>"

class IndividualResultTests(unittest.TestCase):
    def test_six_boats_and_unknown_actual_course(self):
        result=parse_individual_result(HTML,source_url=URL,day=date(2026,10,14),
                                       race_no=3,column_map=MAP,table_index=0)
        self.assertEqual(len(result["results"]),6)
        self.assertIsNone(result["results"][0]["actual_course"])
        self.assertEqual(result["results"][0]["racer_registration_id"],"4001")

    def test_wrong_race_rejected(self):
        with self.assertRaises(SourceError):
            parse_individual_result(HTML,source_url=URL,day=date(2026,10,14),
                                    race_no=4,column_map=MAP,table_index=0)

    def test_duplicate_lane_rejected(self):
        bad=HTML.replace("<td>2</td><td>2</td>","<td>2</td><td>1</td>")
        with self.assertRaises(SourceError):
            parse_individual_result(bad,source_url=URL,day=date(2026,10,14),
                                    race_no=3,column_map=MAP,table_index=0)
