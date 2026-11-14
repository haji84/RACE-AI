"""Source-free synthetic contract tests; not evidence of real racing accuracy."""
import unittest
from copy import deepcopy
from datetime import date, timedelta

from race_ai.boat_six_course_tactical_features import (
    analyze_racer, matchup_features, prior_analogue_escape, CONDITIONS)

NOW = "2026-11-09T01:00:00+09:00"


def past():
    decisions = [(1, "nige"), (4, "makuri"), (5, "makurizashi"),
                 (6, "makuri"), (2, "sashi"), (1, "nige"),
                 (3, "makuri"), (1, "nige"), (5, "makuri"),
                 (6, "makurizashi"), (1, "nige"), (4, "makurizashi")]
    rows = []
    for i, (winner, method) in enumerate(decisions, 1):
        day = (date(2026,10,20)+timedelta(days=i)).strftime("%Y%m%d")
        finishes, place = {}, 2
        for c in range(1,7):
            if c == winner: finishes[c] = 1
            else:
                finishes[c] = place
                place += 1
        rows.append({
            "race_id": f"{day}-04-01",
            "cutoff_at": f"{day[:4]}-{day[4:6]}-{day[6:]}T12:00:00+09:00",
            "result_captured_at": f"{day[:4]}-{day[4:6]}-{day[6:]}T12:25:00+09:00",
            "winner_method": method, "source_sha256": "a"*64,
            "entries": [{"frame":c, "course":c, "racer_id":str(4100+c),
                         "finish":finishes[c]} for c in range(1,7)]})
    return rows


def formed():
    return {r["race_id"]:{"slow_count":3, "corner_course":4,
                          "captured_at":r["result_captured_at"],
                          "source_sha256":"b"*64} for r in past()}


class SixCourseTacticsTests(unittest.TestCase):
    def test_all_courses_and_five_six_methods(self):
        data=past()
        five=analyze_racer(data,racer_id="4105",as_of=NOW,
            meeting={"venue":"04","first_day_jst":"2026-10-27",
                     "captured_at":"2026-10-26T10:00:00+09:00",
                     "source_sha256":"c"*64})
        six=analyze_racer(data,racer_id="4106",as_of=NOW)
        self.assertEqual(five["windows"]["last_10"]["starts"],10)
        self.assertEqual(five["windows"]["current_meeting"]["starts"],6)
        for profile,course in ((five,"5"),(six,"6")):
            self.assertEqual(profile["by_actual_course"][course]["winning_methods"]["makuri"]["wins"],1)
            self.assertEqual(profile["by_actual_course"][course]["winning_methods"]["makurizashi"]["wins"],1)
            self.assertEqual(profile["by_actual_course"][course]["winning_methods"]["makurizashi"]["per_start"],1/12)

    def test_in1_defeats_and_in2_nigashi_have_real_denominators(self):
        data=past()
        one=analyze_racer(data,racer_id="4101",as_of=NOW)
        two=analyze_racer(data,racer_id="4102",as_of=NOW)
        loss=one["first_course_losses"]["winner_method_NOT_proof_of_direct_attack"]
        self.assertEqual(loss["makuri"]["count"],4)
        self.assertEqual(loss["sashi"]["count"],1)
        self.assertEqual(loss["makurizashi"]["count"],3)
        self.assertEqual(two["second_course_nigashi"]["first_course_nige"],4)
        self.assertEqual(two["second_course_nigashi"]["rate"],4/12)

    def test_3_course_kado_is_not_invented_from_frame(self):
        data=past()
        raw=analyze_racer(data,racer_id="4103",as_of=NOW)
        self.assertIsNone(raw["third_course_kado_uke_proxy"]["fourth_course_makuri_win_rate"])
        formed3=analyze_racer(data,racer_id="4103",as_of=NOW,corner_evidence=formed())
        self.assertEqual(formed3["third_course_kado_uke_proxy"]["formation_proven_starts"],12)
        self.assertFalse(formed3["third_course_kado_uke_proxy"]["direct_blocking_observed"])
        bad=formed()
        bad[data[0]["race_id"]]["corner_course"]=5
        with self.assertRaises(ValueError):
            analyze_racer(data,racer_id="4103",as_of=NOW,corner_evidence=bad)

    def test_no_outer_lane_collapses_and_missing_cannot_become_zero(self):
        data=past()
        profiles={str(4100+c):analyze_racer(data,racer_id=str(4100+c),
                 as_of=NOW,corner_evidence=formed()) for c in range(1,7)}
        matchup=matchup_features(profiles,entrant_by_course={
            c:str(4100+c) for c in range(1,7)})
        for c in (5,6):
            for m in ("sashi","makuri","makurizashi"):
                self.assertIn(f"{c}_{m}",CONDITIONS)
            self.assertEqual(matchup["features"][f"{c}_makuri"],1/12)
            self.assertEqual(matchup["features"][f"{c}_makurizashi"],1/12)
        self.assertIsNone(matchup["conditional_escape_probability"])
        different=deepcopy(profiles)
        different["4106"]["as_of"]="2026-11-08T12:00:00+09:00"
        with self.assertRaises(ValueError):
            matchup_features(different,entrant_by_course={c:str(4100+c) for c in range(1,7)})
        self.assertIsNone(analyze_racer([],racer_id="4105",as_of=NOW)
                          ["by_actual_course"]["5"]["winning_methods"]["makurizashi"]["per_start"])

    def test_conditional_rate_requires_real_prior_support_and_cutoff(self):
        data=past()
        profiles={str(4100+c):analyze_racer(data,racer_id=str(4100+c),
                 as_of=NOW,corner_evidence=formed()) for c in range(1,7)}
        matchup=matchup_features(profiles,entrant_by_course={
            c:str(4100+c) for c in range(1,7)})
        features={k:matchup["features"][k] for k in CONDITIONS}
        analogues=[{"race_id":f"202609{1+i//12:02d}-04-{1+i%12:02d}",
                    "features_as_of":"2026-09-01T09:00:00+09:00",
                    "cutoff_at":f"2026-09-{1+i//12:02d}T10:00:00+09:00",
                    "result_captured_at":f"2026-09-{1+i//12:02d}T11:00:00+09:00",
                    "source_sha256":"d"*64,"winner_course":1 if i%2==0 else 4,
                    "winner_method":"nige" if i%2==0 else "makuri",
                    "features":dict(features)} for i in range(32)]
        out=prior_analogue_escape(matchup,analogues,as_of=NOW,
                                 current_race_id="20261109-04-01")
        self.assertEqual(out["status"],"DESCRIPTIVE_ANALOGUES_ONLY")
        self.assertEqual(out["support"],32)
        self.assertEqual(out["empirical_escape_rate"],.5)
        self.assertIsNone(out["calibrated_probability"])
        self.assertEqual(prior_analogue_escape(matchup,analogues[:2],as_of=NOW,
          current_race_id="20261109-04-01")["status"],"HOLD_INSUFFICIENT_PRIOR_ANALOGUES")
        analogues[0]["features_as_of"]="2026-09-02T12:00:00+09:00"
        with self.assertRaises(ValueError):
            prior_analogue_escape(matchup,analogues,as_of=NOW,
                                  current_race_id="20261109-04-01")

    def test_no_future_results_and_invalid_kimarite(self):
        rows=past()
        rows[0]["result_captured_at"]="2026-11-10T00:00:00+09:00"
        with self.assertRaises(ValueError):
            analyze_racer(rows,racer_id="4101",as_of=NOW)
        rows=past()
        rows[0]["winner_method"]="makurizashi"
        with self.assertRaises(ValueError):
            analyze_racer(rows,racer_id="4101",as_of=NOW)


if __name__=="__main__":
    unittest.main()
