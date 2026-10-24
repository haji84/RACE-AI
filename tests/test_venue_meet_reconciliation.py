import unittest
from datetime import date
from race_ai.core import SourceError
from race_ai.venue_meet_reconciliation import reconcile

DAY=date(2026,10,14)
MID="18-20261010-20261015"


def fixture():
    races=[]
    allocations=[]
    for n in range(1,13):
        boats=[]
        for lane in range(1,7):
            name=f"選手{n}-{lane}"
            boats.append({"lane":lane,"name":name})
            allocations.append({"name":name,"racer_registration_id":str(4000+n*6+lane),
                                "motor_no":n*6+lane,"meet_id":MID})
        races.append({"race_id":f"20261014-18-{n:02d}","boats":boats})
    index={"date_jst":DAY.isoformat(),"venue":"18","races":races}
    meet={"meet_id":MID,"start_date":"2026-10-10",
          "end_date":"2026-10-15","identity_verified":True}
    return index,allocations,meet


class MeetReconciliationTests(unittest.TestCase):
    def test_complete_72_entries(self):
        index,allocations,meet=fixture()
        result=reconcile(index,allocations,day=DAY,meet=meet,
                         race_meet_id=MID,motor_meet_id=MID)
        self.assertEqual(len(result["entries"]),72)

    def test_wrong_meet_rejected(self):
        index,allocations,meet=fixture()
        with self.assertRaises(SourceError):
            reconcile(index,allocations,day=DAY,meet=meet,
                      race_meet_id=MID,motor_meet_id="18-20261001-20261006")

    def test_missing_lane_rejected(self):
        index,allocations,meet=fixture()
        index["races"][0]["boats"].pop()
        with self.assertRaises(SourceError):
            reconcile(index,allocations,day=DAY,meet=meet,
                      race_meet_id=MID,motor_meet_id=MID)

    def test_absent_racer_rejected_until_updated(self):
        index,allocations,meet=fixture()
        index["races"][0]["boats"][0]["status"]="ABSENT"
        with self.assertRaises(SourceError):
            reconcile(index,allocations,day=DAY,meet=meet,
                      race_meet_id=MID,motor_meet_id=MID)
