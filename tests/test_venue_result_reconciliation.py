import unittest
from datetime import date
from race_ai.core import SourceError
from race_ai.venue_result_reconciliation import reconcile_results

DAY=date(2026,10,14)
RID="20261014-18-03"


def fixture():
    entries=[{"race_id":RID,"lane":i,"racer_registration_id":str(4000+i),
              "motor_no":i} for i in range(1,7)]
    results=[{"race_id":RID,"lane":i,"racer_registration_id":str(4000+i),
              "finish":i,"actual_course":i,"verified_official":True,
              "source_url":"https://www.boatrace-tokuyama.jp/verified-result",
              "captured_at":"2026-10-14T12:00:00+09:00"} for i in range(1,7)]
    return entries,results


class VenueResultReconciliationTests(unittest.TestCase):
    def test_six_lanes_joined(self):
        entries,results=fixture()
        report=reconcile_results(entries,results,day=DAY)
        self.assertEqual(len(report["entries"]),6)
        self.assertEqual(report["entries"][0]["finish"],1)

    def test_wrong_racer_rejected(self):
        entries,results=fixture()
        results[0]["racer_registration_id"]="9999"
        with self.assertRaises(SourceError):
            reconcile_results(entries,results,day=DAY)

    def test_partial_result_rejected(self):
        entries,results=fixture()
        with self.assertRaises(SourceError):
            reconcile_results(entries,results[:-1],day=DAY)

    def test_unverified_result_rejected(self):
        entries,results=fixture()
        results[0]["verified_official"]=False
        with self.assertRaises(SourceError):
            reconcile_results(entries,results,day=DAY)
