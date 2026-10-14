import unittest
from race_ai.core import connect
from race_ai.racer_history_bridge import analyze_imported_history

ASOF="2026-10-14T09:00:00+09:00"


class RacerHistoryBridgeTests(unittest.TestCase):
    def test_imported_k_history_separates_course_and_lane(self):
        db=connect(":memory:")
        db.execute("INSERT INTO provenance VALUES (?,?,?,?,?,?,?)",
                   ("a"*64,"K","fixture.txt",ASOF,ASOF,ASOF,0))
        db.execute("INSERT INTO starts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   ("20261013-18-01",1,"4001",2,0.12,"OK",1,
                    "2026-10-13T10:00:00+00:00",ASOF,ASOF,"a"*64))
        result=analyze_imported_history(db,racer_id="4001",asof=ASOF)
        groups=result["conditional_form"]["groups"]
        self.assertTrue(any(x["dimension"]=="lane" and x["number"]==1 for x in groups))
        self.assertTrue(any(x["dimension"]=="actual_course" and x["number"]==2 for x in groups))
        self.assertEqual(result["win_loss_patterns"]["wins_by_own_winning_method"],{"未取得":1})
        self.assertEqual(result["winner_method_status"],"NOT_STORED_IN_K_STARTS")

    def test_future_snapshot_not_used(self):
        db=connect(":memory:")
        db.execute("INSERT INTO provenance VALUES (?,?,?,?,?,?,?)",
                   ("b"*64,"K","fixture.txt",ASOF,ASOF,ASOF,0))
        db.execute("INSERT INTO starts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   ("20261015-18-01",1,"4001",1,0.10,"OK",1,
                    "2026-10-15T10:00:00+00:00","2026-10-15T11:00:00+00:00",
                    "2026-10-15T11:00:00+00:00","b"*64))
        result=analyze_imported_history(db,racer_id="4001",asof=ASOF)
        self.assertEqual(result["conditional_form"]["status"],"NO_VERIFIED_HISTORY")
