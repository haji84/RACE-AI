import tempfile
import unittest
from datetime import date,datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from race_ai.day_feed_store import write_day_snapshot,read_current_snapshot

JST=ZoneInfo("Asia/Tokyo")


def fixture(day):
    return {"date_jst":day.isoformat(),"source_url":"https://example.org/synthetic",
            "source_sha256":"a"*64,"first_observed_at":datetime.combine(day,datetime.min.time(),tzinfo=JST).isoformat(),
            "venues":[{"venue":"18","races":[{"race_id":day.strftime("%Y%m%d")+"-18-01",
                "boats":[{"lane":i,"racer_registration_id":str(4000+i),"motor_no":None}
                         for i in range(1,7)]}]}]}

def approval():
    return {"redistribution_authorized":True,"source_url":"https://example.org/synthetic",
            "evidence_reference":"synthetic-test-only","reviewed_by":"test"}


class DayFeedStoreTests(unittest.TestCase):
    def test_atomic_current_day_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            day=date(2026,10,14)
            store=Path(tmp)
            write_day_snapshot(store,fixture(day),approval(),today=day)
            data=read_current_snapshot(store,today=day)
            self.assertEqual(data["date_jst"],"2026-10-14")
            with self.assertRaises(ValueError):
                read_current_snapshot(store,today=date(2026,10,15))

    def test_denied_publication_never_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            day=date(2026,10,14)
            with self.assertRaises(ValueError):
                write_day_snapshot(Path(tmp),fixture(day),{},today=day)
            self.assertEqual(list(Path(tmp).glob("*.json")),[])
