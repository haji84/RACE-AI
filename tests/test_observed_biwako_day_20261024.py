"""Real manually observed official race-day times; all forecasts absent."""
from datetime import datetime
import json
from pathlib import Path
import unittest
from race_ai.operator_export_intake import SCHEMA,transform,IntakeError
from race_ai.discovery_audit_cli import audit
SRC=Path(__file__).resolve().parents[1]/"docs/evidence/2026-10-24-biwako-12r-official-schedule.json"

def records(data):
    assert data["schema"]=="RACE_AI_OFFICIAL_BOAT_DAY_SCHEDULE_OBSERVATION_V1"
    assert data["source_access_basis"]=="PUBLIC_WEB_VIEW_ONLY_NOT_REVIEWED_FOR_AUTOMATED_FETCH"
    assert data["event_date_jst"]=="2026-10-24"
    assert data["venue_jcd"]=="11"
    assert data["source_url"]=="https://www.boatrace.jp/owpc/pc/race/racelist?hd=20261024&jcd=11&rno=1"
    assert len(data["scheduled_close_jst"])==12
    previous=None
    assembled=[]
    for number,s in enumerate(data["scheduled_close_jst"],1):
        clock=datetime.fromisoformat("2026-10-24T"+s+":00+09:00")
        if previous is not None and clock<=previous:
            raise IntakeError("non-increasing official scheduled close time")
        previous=clock
        assembled.append({"sport":"boat","venue":"boatrace-jcd-11",
                          "race_no":number,"sales_cutoff_at":clock.isoformat(),
                          "offering_status":"UNKNOWN"})
    return transform({"schema":SCHEMA,"event_date_jst":"2026-10-24",
       "source_ref":data["source_url"],"source_rights_ref":"PUBLIC_VIEW_ONLY_NOT_FETCH_APPROVAL",
       "captured_at":data["observed_at_claimed"],"races":assembled},"b"*64)

class OfficialDayObservation(unittest.TestCase):
    def test_actual_source_advertised_12_races_all_audit_only(self):
        actual=json.loads(SRC.read_text())
        ledger=records(actual)
        self.assertEqual(len(ledger["records"]),12)
        self.assertEqual(ledger["records"][0]["race_id"],"boat:2026-10-24:boatrace-jcd-11:1")
        self.assertEqual(ledger["records"][-1]["sales_cutoff_at"],"2026-10-24T15:50:00+09:00")
        self.assertTrue(all(r["prediction"] is None and not r["cutoff_verified"] for r in ledger["records"]))
        manual={"scope":"MANUAL_REFERENCE_ONLY","event_date_jst":"2026-10-24",
                "venues":[{"sport":"boat","venue":"boatrace-jcd-11","race_numbers":list(range(1,13))}]}
        result=audit(manual,ledger)
        self.assertFalse(result["official_completeness_verified"])
        self.assertEqual(result["status"],"UNRESOLVED_COVERAGE_OR_PROOF")
    def test_tampered_real_snapshot_fails(self):
        data=json.loads(SRC.read_text())
        data["scheduled_close_jst"][2]="10:20"
        with self.assertRaisesRegex(IntakeError,"non-increasing"):
            records(data)
        data=json.loads(SRC.read_text());data["source_access_basis"]="APPROVED"
        with self.assertRaises(AssertionError):
            records(data)
if __name__=="__main__":unittest.main()
