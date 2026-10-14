import unittest
from datetime import date
from race_ai.core import SourceError
from race_ai.venue_result_bridge import parse_and_reconcile

DAY=date(2026,10,14)
URL="https://www.boatrace.jp/owpc/pc/race/raceresult?rno=3&jcd=18&hd=20261014"
MAP={"finish":0,"lane":1,"registration":2,"name":3,"st":4}
HTML="<table>"+"".join(f"<tr><td>{i}</td><td>{i}</td><td>{4000+i}</td><td>選手{i}</td><td>0.1{i}</td></tr>" for i in range(1,7))+"</table>"
ENTRIES=[{"race_id":"20261014-18-03","lane":i,"racer_registration_id":str(4000+i),
          "motor_no":i} for i in range(1,7)]


class ResultBridgeTests(unittest.TestCase):
    def test_full_six_boat_identity(self):
        result=parse_and_reconcile(HTML,source_url=URL,day=DAY,race_no=3,
            column_map=MAP,table_index=0,entries=ENTRIES,
            captured_at="2026-10-14T12:00:00+09:00",independently_verified=True)
        self.assertEqual(len(result["entries"]),6)
        self.assertIsNone(result["entries"][0]["actual_course"])

    def test_mismatched_registration_rejected(self):
        bad=[dict(x) for x in ENTRIES]
        bad[0]["racer_registration_id"]="9999"
        with self.assertRaises(SourceError):
            parse_and_reconcile(HTML,source_url=URL,day=DAY,race_no=3,
                column_map=MAP,table_index=0,entries=bad,
                captured_at="2026-10-14T12:00:00+09:00",independently_verified=True)

    def test_unverified_source_rejected(self):
        with self.assertRaises(SourceError):
            parse_and_reconcile(HTML,source_url=URL,day=DAY,race_no=3,
                column_map=MAP,table_index=0,entries=ENTRIES,
                captured_at="2026-10-14T12:00:00+09:00",independently_verified=False)
