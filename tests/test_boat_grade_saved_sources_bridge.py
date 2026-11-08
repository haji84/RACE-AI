"""Fake retained archives: no provider, no secrets and no real racer claims."""
import json
import unittest

from race_ai.boat_grade_saved_sources_bridge import build_saved_grade_input
from race_ai.boat_racer_term import term_info


def roster():
    return [{"boat":c, "racer_id":str(4100+c),
             "program_class":"B1" if c<5 else "B2"} for c in range(1,7)]


def doc(rid,term,current_grade,previous=None):
    info=term_info(term)
    return json.dumps({
        "racer_id":rid,"term":term,"recorded_class":current_grade,
        "record_sha256":"b"*64,"period_start":info["period_start"],
        "period_end":info["period_end"],
        "previous_classes":previous if previous is not None else ["A1","",""],
    })


class FakeCursor:
    def __init__(self,values):
        self.values=values
    def fetchone(self):
        return self.values[0] if self.values else None
    def __iter__(self):
        return iter(self.values)


class FakeDB:
    def __init__(self):
        self.sources={
            1:("a"*64,term_info("2026-2")["source_url"],"2026-07-02T10:00:00+09:00"),
            2:("c"*64,term_info("2027-1")["source_url"],"2026-11-01T17:00:00+09:00"),
        }
        self.documents={
            1:[("4101",doc("4101","2026-2","B1")),
               ("4102",doc("4102","2026-2","B1",["","",""])),
               ("4105",doc("4105","2026-2","B2",["A1","A2",""]))],
            2:[("4101",doc("4101","2027-1","A2")),
               ("4102",doc("4102","2027-1","A1"))],
        }
    def execute(self,query,args):
        sid=args[0]
        if query.startswith("SELECT sha,url,captured_at"):
            return FakeCursor([self.sources[sid]])
        if query.startswith("SELECT racer_id,document"):
            return FakeCursor(self.documents[sid])
        raise AssertionError("unsupported private DB query")


class FakeRacerDB:
    def __init__(self):
        self.db=FakeDB()
        self.admitted=[]
    def _latest_sources(self,kind,at):
        assert kind=="TERM"
        from datetime import datetime
        at=datetime.fromisoformat(at)
        return {term:sid for term,sid in (("2026-2",1),("2027-1",2))
                if datetime.fromisoformat(self.db.sources[sid][2])<=at}
    def _admit(self,sid,at,allow_source):
        assert allow_source(self.db.sources[sid][1],
                            "OFFICIAL_DOWNLOAD_PERSONAL_RESEARCH","analysis")
        self.admitted.append(sid)


class FakeHistory:
    def __init__(self,rows=None):
        self.rows=rows or []
        self.calls=0
    def history_rows(self,ids,as_of):
        self.calls+=1
        assert "4101" in ids
        return self.rows


def start(racer="4101",date="2026-11-02",finish=2):
    return {"racer_id":racer,"race_id":date.replace("-","")+"-04-01",
        "participation":"CONFIRMED_START",
        "cutoff_at":date+"T12:00:00+09:00",
        "available_at":date+"T17:00:00+09:00","finish":finish,
        "source_sha256":"d"*64}


def build(db=None,history=None,**kwargs):
    db=db or FakeRacerDB()
    history=history or FakeHistory()
    return build_saved_grade_input(
        db,history,race_id=kwargs.get("race_id","20261109-04-01"),
        as_of=kwargs.get("as_of","2026-11-09T07:00:00+09:00"),
        roster=kwargs.get("roster",roster()),
        allow_source=kwargs.get("allow_source",lambda u,p,a: True))


class OfflineGradeBridgeTests(unittest.TestCase):
    def test_current_next_and_prior_from_saved_terms(self):
        db=FakeRacerDB()
        out=build(db)
        self.assertEqual(out["schema"],"RACE_AI_BOAT_GRADE_TRANSITION_RESEARCH_V1")
        self.assertEqual(out["start_records"],[])
        self.assertEqual(db.admitted,[1,2])
        self.assertEqual(len(out["term_records"]),5)
        actual={ (r["racer_id"],r["term"]):r for r in out["term_records"]}
        self.assertEqual(actual["4101","2026-2"]["recorded_class"],"B1")
        self.assertEqual(actual["4101","2027-1"]["recorded_class"],"A2")
        self.assertEqual(actual["4101","2027-1"]["status"],"ANNOUNCED_PENDING")
        self.assertEqual(actual["4105","2026-2"]["previous_classes"],["A1","A2",""])
        self.assertFalse(out["future_formal_grade_confirmed"])
        self.assertTrue(out["source_authentication_requires_Actions_readback"])

    def test_future_fan_term_not_available_at_prior_asof(self):
        out=build(as_of="2026-10-30T07:00:00+09:00",
                  race_id="20261030-04-01")
        self.assertFalse(any(r["term"]=="2027-1" for r in out["term_records"]))

    def test_official_start_clock_and_nonnumeric_result(self):
        h=FakeHistory([start(),start(date="2026-11-03",finish=None),
                       {**start(date="2026-11-05"),"participation":"UNRESOLVED"}])
        out=build(history=h)
        self.assertEqual(h.calls,1)
        self.assertEqual(len(out["start_records"]),2)
        self.assertIsNone(out["start_records"][1]["finish"])
        self.assertEqual(out["race_time_basis"],
                         "B_PRINTED_CUTOFF_DAY_NOT_ACTUAL_START_INSTANT")

    def test_future_result_is_rejected(self):
        a=start()
        a["available_at"]="2026-11-10T18:00:00+09:00"
        with self.assertRaisesRegex(ValueError,"GRADE_BRIDGE_RESULT_CLOCK_OR_VALUE_INVALID"):
            build(history=FakeHistory([a]))

    def test_duplicate_start_rejected(self):
        with self.assertRaisesRegex(ValueError,"GRADE_BRIDGE_DUPLICATE_START"):
            build(history=FakeHistory([start(),start()]))

    def test_wrong_assessment_period_is_rejected(self):
        db=FakeRacerDB()
        row=json.loads(db.db.documents[2][0][1])
        row["period_start"]="2026-01-01"
        db.db.documents[2][0]=("4101",json.dumps(row))
        with self.assertRaisesRegex(ValueError,"GRADE_BRIDGE_TERM_ROW_UNVERIFIED"):
            build(db)

    def test_missing_future_not_invented_and_denial_propagates(self):
        db=FakeRacerDB()
        del db.db.sources[2]
        # The test DB is deliberately missing its later source entirely.
        db._latest_sources=lambda kind,at:{"2026-2":1}
        out=build(db)
        self.assertTrue(all(r["term"]=="2026-2" for r in out["term_records"]))
        with self.assertRaises(AssertionError):
            build(FakeRacerDB(),allow_source=lambda u,p,a: False)

    def test_wrong_roster_or_event_day_rejected(self):
        bad=roster()
        bad[1]["racer_id"]="4101"
        with self.assertRaisesRegex(ValueError,"GRADE_BRIDGE_ROSTER_INVALID"):
            build(roster=bad)
        with self.assertRaisesRegex(ValueError,"GRADE_BRIDGE_EVENT_INVALID"):
            build(race_id="20261110-04-01")


if __name__=="__main__":
    unittest.main()
