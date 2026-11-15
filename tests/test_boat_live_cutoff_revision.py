"""Source-free, fictional BOAT cutoff shifts: not live-result evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from race_ai.boat_live_cutoff_revision import resolve_cutoff

DAY="2030-04-01"
RID="20300401-01-02"
OLD="2030-04-01T12:00:00+09:00"
NEW="2030-04-01T12:01:00+09:00"
NOW="2030-04-01T11:42:00+09:00"
PROGRAM="https://www.boatrace.jp/owpc/pc/race/racelist?hd=20300401&jcd=01&rno=2"
BEFORE="https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20300401&jcd=01&rno=2"


def example(*,old=OLD,new=NEW,notice=True):
    schedule=dict(race_id=RID,cutoff_at=old,
        schedule_captured_at="2030-04-01T11:00:00+09:00",source_sha256="a"*64)
    program=dict(schema="RACE_AI_BOAT_OFFICIAL_PROGRAM_V1",race_id=RID,
        date_jst=DAY,closed_at=new,status="OFFICIAL_BODY_IDENTITY_VERIFIED",
        body_identity_verified=True,schedule_change_notice=notice,
        captured_at="2030-04-01T11:40:00+09:00",
        source_url=PROGRAM,source_sha256="b"*64,
        source=dict(source_url=PROGRAM,sha256="b"*64,
                    captured_at="2030-04-01T11:40:00+09:00"))
    before=dict(schema="RACE_AI_BOAT_ACTIVE_EXHIBITION_V1",race_id=RID,
        closed_at=new,status="PENDING",information_phase="pre_race",
        body_identity_verified=True,source_url=BEFORE,source_sha256="c"*64,
        captured_at="2030-04-01T11:41:00+09:00",
        context=dict(status="PARSED",race_id=RID,source_cutoff_at=new,
                     source=dict(source_url=BEFORE,sha256="c"*64,
                                 captured_at="2030-04-01T11:41:00+09:00")))
    return schedule,program,before


class LiveCutoffRevisionTests(unittest.TestCase):
    def decide(self,*,now=NOW,old=OLD,new=NEW,notice=True):
        source=example(old=old,new=new,notice=notice)
        return resolve_cutoff(*source,now=now),source

    def test_extended_official_closing_grid_is_accepted_before_both_cutoffs(self):
        result,source=self.decide()
        self.assertEqual(result["status"],"VERIFIED_PRE_CLOSE_CUTOFF_REVISION")
        self.assertEqual(result["effective_cutoff_at"],NEW)
        proof=result["cutoff_revision"]
        self.assertEqual(proof["change_seconds"],60)
        self.assertEqual(proof["evidence_basis"],"OFFICIAL_NOTICE_AND_TWO_SOURCE_AGREEMENT")
        self.assertFalse(proof["actual_voting_close_verified"])
        self.assertFalse(proof["independent_aes_save_verified"])
        self.assertEqual(source[0]["cutoff_at"],OLD)
        self.assertEqual(source[1]["closed_at"],NEW)
        self.assertEqual(source[2]["closed_at"],NEW)

    def test_shortening_is_conservatively_admitted_with_two_sources(self):
        early="2030-04-01T11:59:00+09:00"
        result,_=self.decide(new=early,notice=False)
        self.assertEqual(result["status"],"VERIFIED_PRE_CLOSE_CUTOFF_REVISION")
        self.assertEqual(result["effective_cutoff_at"],early)
        self.assertEqual(result["cutoff_revision"]["change_seconds"],-60)
        self.assertEqual(result["cutoff_revision"]["evidence_basis"],
            "CONSERVATIVE_EARLIER_TWO_SOURCE_AGREEMENT")

    def test_later_planned_time_without_explicit_change_notice_remains_hold(self):
        result,_=self.decide(notice=False)
        self.assertEqual(result["status"],
            "HOLD_CUTOFF_EXTENSION_WITHOUT_OFFICIAL_CHANGE_NOTICE")
        self.assertIsNone(result["effective_cutoff_at"])

    def test_observed_after_original_deadline_never_backdates_revision(self):
        s,p,b=example()
        p["captured_at"]=p["source"]["captured_at"]="2030-04-01T12:00:02+09:00"
        b["captured_at"]=b["context"]["source"]["captured_at"]="2030-04-01T12:00:03+09:00"
        result=resolve_cutoff(s,p,b,now="2030-04-01T12:00:04+09:00")
        self.assertEqual(result["status"],"HOLD_CUTOFF_EARLY_DEADLINE_NOT_PROVEN_OPEN")

    def test_no_model_work_inside_old_cutoff_margin_even_after_extension(self):
        result,_=self.decide(now="2030-04-01T11:57:00+09:00")
        self.assertEqual(result["status"],"HOLD_CUTOFF_EARLY_DEADLINE_NOT_PROVEN_OPEN")

    def test_disagreement_between_racelist_and_exhibition_is_not_corrected(self):
        s,p,b=example()
        b["context"]["source_cutoff_at"]="2030-04-01T11:59:00+09:00"
        result=resolve_cutoff(s,p,b,now=NOW)
        self.assertEqual(result["status"],"HOLD_CUTOFF_DUAL_SOURCE_IDENTITY_OR_CLOCK_UNVERIFIED")

    def test_untrusted_or_after_time_source_hash_and_identity_are_rejected(self):
        bad=[]
        def changed(index,path,value):
            s,p,b=example()
            item=(s,p,b)[index]
            if len(path)==1:item[path[0]]=value
            else:item[path[0]][path[1]]=value
            return (s,p,b)
        bad.extend([
            changed(1,["source_sha256"],"bad"),
            changed(2,["source_url"],BEFORE.replace("jcd=01","jcd=02")),
            changed(2,["context","race_id"],"20300401-01-03"),
            changed(1,["body_identity_verified"],False),
            changed(0,["source_sha256"],"bad"),
        ])
        for s,p,b in bad:
            with self.subTest(value=(s,p,b)):
                self.assertEqual(resolve_cutoff(s,p,b,now=NOW)["status"],
                    "HOLD_CUTOFF_DUAL_SOURCE_IDENTITY_OR_CLOCK_UNVERIFIED")

    def test_delayed_start_does_not_change_sales_cutoff(self):
        s,p,b=example(old=OLD,new=OLD)
        s["actual_start_at"]="2030-04-01T12:20:00+09:00"
        result=resolve_cutoff(s,p,b,now=NOW)
        self.assertEqual(result["status"],"UNCHANGED_OFFICIAL_CUTOFF")
        self.assertEqual(result["effective_cutoff_at"],OLD)
        self.assertIsNone(result["cutoff_revision"])

    def test_bad_timezones_and_official_race_date_rejected(self):
        for new in ("2030-04-02T12:01:00+09:00",
                    "2030-04-01T12:01:00", "2030-04-01T03:01:00Z"):
            with self.subTest(new=new):
                s,p,b=example(new=new)
                self.assertEqual(resolve_cutoff(s,p,b,now=NOW)["status"],
                    "HOLD_CUTOFF_INVALID_CLOCK_OR_IDENTITY")

    def test_untouched_input_and_no_forecast_source_side_effects(self):
        s,p,b=example(); inputs=deepcopy((s,p,b))
        result=resolve_cutoff(s,p,b,now=NOW)
        self.assertEqual((s,p,b),inputs)
        self.assertEqual(result["cutoff_revision"]["original_schedule_source_sha256"],"a"*64)
        self.assertFalse(result["cutoff_revision"]["original_forecast_modified"])


if __name__=="__main__":
    unittest.main()
