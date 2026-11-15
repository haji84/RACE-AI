"""Synthetic tests, not official source acceptance or future model accuracy."""
import unittest
from datetime import date, timedelta
from race_ai.boat_dynamic_tactical_context import (
    TILT_REFERENCES, entry_response_profile, p1_tilt_entry_context,
    qualifying_standings, six_way_research_context)

NOW="2026-11-09T12:00:00+09:00"
PROOF={"captured_at":"2026-11-09T11:00:00+09:00","source_sha256":"a"*64}

def history():
    formations=([1,3,4,5,6,2],[2,3,4,5,1,6],[1,2,3,4,5,6],[1,2,3,4,5,6])
    methods=((6,"sashi"),(5,"nige"),(4,"makuri"),(6,"makurizashi"))
    rows=[]
    for i,(courses,(winner,method)) in enumerate(zip(formations,methods)):
        day=date(2026,11,1)+timedelta(days=i)
        ordered=[winner]+[f for f in range(1,7) if f!=winner]
        places={f:p for p,f in enumerate(ordered,1)}
        rows.append({"race_id":f"{day:%Y%m%d}-04-01",
            "cutoff_at":f"{day}T12:00:00+09:00",
            "result_captured_at":f"{day}T12:25:00+09:00",
            "winner_method":method,"source_sha256":"b"*64,
            "entries":[{"frame":f,"course":courses[f-1],"racer_id":str(4100+f),
                        "finish":places[f]} for f in range(1,7)]})
    return rows

def exhibition():
    return [{"frame":f,"course":f,"racer_id":str(4100+f),
             "tilt_deg":3. if f==6 else 2. if f==5 else -.5} for f in range(1,7)]

def rule():
    return {"venue_code":"04","effective_on_jst":"2026-11-09",
            "allowed_angles":[-.5,0,.5,1.,1.5,2.,3.],"receipt":PROOF.copy()}

def tilt(slow=4,current=True):
    return p1_tilt_entry_context(race_id="20261109-04-01",venue_code="04",
        as_of=NOW,cutoff_at="2026-11-09T12:30:00+09:00",
        exhibition=exhibition(),receipt=PROOF.copy(),slow_count=slow,
        current_venue_rule=rule() if current else None)

def standings():
    return [{"racer_id":str(4100+i),"official_rank":i,
             "total_points":float(40+i),"deductions":0.,
             "official_rate":round(10-i*.2,2),"starts":5,
             "remaining_starts":1,"eligibility":"ELIGIBLE"}
            for i in range(1,21)]

def board(complete=True):
    return qualifying_standings(event_id="20261109-04-event",venue_code="04",
        as_of=NOW,event_rules={"event_id":"20261109-04-event","venue_code":"04",
            "qualifying_slots":18,"minimum_starts":4,"receipt":PROOF.copy()},
        standings=standings(),standings_receipt=PROOF.copy(),board_complete=complete)

class TacticalDynamicTests(unittest.TestCase):
    def test_2025_venue_24_options_are_dated(self):
        self.assertEqual(len(TILT_REFERENCES),24)
        for venue,maximum in (("02",.5),("01",1.),("12",1.5),("22",1.5),("18",2.),("04",3.)):
            self.assertEqual(max(TILT_REFERENCES[venue]),maximum)
        for venue,opts in TILT_REFERENCES.items():
            self.assertEqual(2.5 in opts,venue in ("06","11","20"))

    def test_kado_and_uke_shift_when_slow_group_changes(self):
        a=tilt(slow=4)
        self.assertEqual(a["formation"]["kado_course"],5)
        self.assertEqual(a["formation"]["kado_uke_course"],4)
        self.assertEqual(a["outer_high_tilt_courses"],[5,6])
        self.assertIsNone(a["calibrated_attack_probability"])
        b=tilt(slow=2)
        self.assertEqual((b["formation"]["kado_course"],b["formation"]["kado_uke_course"]),(3,2))

    def test_venue_proof_hold_and_forbidden_angle(self):
        self.assertEqual(tilt(current=False)["rule_status"],
                         "HOLD_CURRENT_VENUE_TILT_RULE_UNVERIFIED")
        narrow=rule();narrow["allowed_angles"]=[-.5,0,.5,1.,1.5]
        with self.assertRaisesRegex(ValueError,"TACTICS_TILT_NOT_ALLOWED"):
            p1_tilt_entry_context(race_id="20261109-04-01",venue_code="04",
                as_of=NOW,cutoff_at="2026-11-09T12:30:00+09:00",
                exhibition=exhibition(),receipt=PROOF.copy(),slow_count=4,
                current_venue_rule=narrow)

    def test_moving_inward_vs_resisting_and_outward(self):
        data=history()
        fifth=entry_response_profile(data,racer_id="4105",as_of=NOW)
        self.assertEqual(fifth["moved_inward"]["starts"],1)
        self.assertEqual(fifth["moved_inward"]["wins"],1)
        self.assertEqual(fifth["moved_outward"]["starts"],1)
        first=entry_response_profile(data,racer_id="4101",as_of=NOW)
        self.assertEqual(first["outer_racer_entered_inside_original_frame"]["starts"],1)
        self.assertEqual(first["moved_outward_in_that_setting"]["starts"],1)
        self.assertFalse(first["direct_defense_observed"])

    def test_cannot_use_future_history(self):
        data=history();data[0]["result_captured_at"]="2026-11-10T00:00:00+09:00"
        with self.assertRaises(ValueError):
            entry_response_profile(data,racer_id="4105",as_of=NOW)

    def test_event_specific_current_cutline_not_qualifying_certification(self):
        a=board()
        self.assertEqual(a["provisional_cutline_rate"],6.4)
        self.assertEqual(a["rate_gap_to_current_cutline"]["4117"],.2)
        self.assertFalse(a["final_qualification_certified"])
        self.assertIsNone(a["needed_points_for_final_qualification"])
        self.assertIsNone(board(complete=False)["provisional_cutline_rate"])

    def test_future_or_missing_event_rules_hold(self):
        future=PROOF.copy();future["captured_at"]="2026-11-10T11:00:00+09:00"
        with self.assertRaises(ValueError):
            qualifying_standings(event_id="e",venue_code="04",as_of=NOW,
                event_rules={"event_id":"e","venue_code":"04","qualifying_slots":18,
                             "minimum_starts":4,"receipt":future},
                standings=standings(),standings_receipt=PROOF.copy(),
                board_complete=True)

    def test_six_way_5_and_6_attacks_remain_separate(self):
        entries={c:str(4100+c) for c in range(1,7)}
        profile={rid:entry_response_profile(history(),racer_id=rid,as_of=NOW)
                 for rid in entries.values()}
        features={"5_makuri":.2,"5_makurizashi":.1,"6_makuri":.1,"6_makurizashi":.2}
        output=six_way_research_context(
            {"schema":"RACE_AI_BOAT_SIX_COURSE_MATCHUP_V1",
             "by_course_racer_ids":entries,"features":features},
            tilt(),profile,qualification=board())
        self.assertEqual(output["six_course_features"],features)
        self.assertEqual(output["formation"]["kado_course"],5)
        self.assertEqual(output["entry_tilt_cross_features"]["6"]["frame"],6)
        self.assertIsNone(output["conditional_escape_probability"])
        self.assertFalse(output["future_calibration_completed"])
        bad=tilt();bad["rows"][0]["racer_id"]="4999"
        with self.assertRaises(ValueError):
            six_way_research_context(
                {"schema":"RACE_AI_BOAT_SIX_COURSE_MATCHUP_V1",
                 "by_course_racer_ids":entries,"features":features},bad,profile)

if __name__=="__main__":
    unittest.main()
