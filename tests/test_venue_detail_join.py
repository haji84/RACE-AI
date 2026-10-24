import unittest
from datetime import date
from race_ai.core import SourceError
from race_ai.venue_detail_join import join_verified_details

DAY=date(2026,10,14)
RID="20261014-18-01"


def fixture():
    index={"date_jst":DAY.isoformat(),"venue":"18","races":[{
        "race_id":RID,"boats":[{"lane":i,"name":f"選手{i}",
            "racer_registration_id":None,"motor_no":None} for i in range(1,7)]}]}
    details=[{"race_id":RID,"lane":i,"name":f"選手{i}",
        "racer_registration_id":str(4000+i),"motor_no":i,
        "verified_source":True,"source_url":"https://example.org/verified",
        "captured_at":"2026-10-14T08:00:00+09:00"} for i in range(1,7)]
    return index,details


class VenueDetailJoinTests(unittest.TestCase):
    def test_all_lanes_joined(self):
        index,details=fixture()
        result=join_verified_details(index,details,day=DAY)
        self.assertEqual(result["races"][0]["boats"][0]["racer_registration_id"],"4001")
        self.assertFalse(result["redistribution_authorized"])

    def test_name_conflict_rejected(self):
        index,details=fixture()
        details[0]["name"]="別人"
        with self.assertRaises(SourceError):
            join_verified_details(index,details,day=DAY)

    def test_partial_evidence_rejected(self):
        index,details=fixture()
        with self.assertRaises(SourceError):
            join_verified_details(index,details[:-1],day=DAY)

    def test_unverified_evidence_rejected(self):
        index,details=fixture()
        details[0]["verified_source"]=False
        with self.assertRaises(SourceError):
            join_verified_details(index,details,day=DAY)
