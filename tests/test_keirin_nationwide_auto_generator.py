"""All fake rider stats and results. Only the generator contract is tested."""
from copy import deepcopy
import unittest

from race_ai import keirin_nationwide_auto_generator as model

ASOF = "2026-11-18T09:00:00+09:00"
AT = "2026-11-18T09:01:00+09:00"
CUTOFF = "2026-11-18T12:00:00+09:00"


def fixture(n=7, *, girls=False):
    groups = ([[i] for i in range(1,n+1)] if girls
              else [[1,2,3],[4,5],[6,7]] if n==7
              else [[1,2],[3,4],[5,6]] if n==6
              else [[1,2,3],[4,5],[6,7],[8,9]])
    riders = []
    for i in range(1,n+1):
        riders.append({
            "car":i, "athlete_id":f"{15000+i:06d}",
            "mark_rank":i, "competition_points":90-i*1.3,
            "recent_form_score":round(1-i/(n+1),3),
            "h_count":i%5, "b_count":i%7,
            "style":"MAKURI" if i%2 else "MARK"})
    return {
        "schema":model.SCHEMA,
        "race_id":"202611182601",
        "as_of":ASOF,
        "published_cutoff_at":CUTOFF,
        "cutoff_source":{
            "url":"https://www.keirin.jp/pc/races",
            "bytes_sha256":"a"*64,"captured_at":ASOF},
        "source_pages":[
            {"kind":k,"url":f"https://www.keirin.jp/pc/{k.lower()}",
             "bytes_sha256":ch*64,"captured_at":ASOF}
            for k,ch in (("RACECARD","b"),("MARKS","c"),("LINE","d"))],
        "competition":"GIRLS" if girls else "A1_A2",
        "round_stage":"PRELIMINARY",
        "round_rule":None,
        "line_groups":groups,
        "riders":riders,
    }


class AutoSixPhaseGeneration(unittest.TestCase):
    def test_automatically_build_A_and_B_from_sufficient_source(self):
        source=fixture()
        original=deepcopy(source)
        r=model.generate_A_B(source,generated_at=AT)
        self.assertEqual(r["schema"],model.PREDICTION)
        self.assertEqual(r["race_id"],source["race_id"])
        self.assertEqual(r["source_facts_sha256"],model.digest(source))
        self.assertEqual(source,original,"input source is immutable")
        self.assertTrue(1<=len(r["A"]["ranked_tickets"])<=12)
        self.assertTrue(1<=len(r["B"]["ranked_tickets"])<=12)
        self.assertTrue(r["B"]["six_phase_scenarios"])
        self.assertEqual(r["C"]["state"],
                         "HOLD_NO_INDEPENDENT_HISTORICAL_FOLLOW_LABELS")
        self.assertFalse(r["old_PR71_four_models_required"])
        self.assertFalse(r["official_cutoff_independently_authenticated"])
        self.assertEqual(r["prediction_sha256"],
                         model.digest({k:v for k,v in r.items()
                                       if k!="prediction_sha256"}))
        self.assertNotEqual(r["A"]["model"],r["B"]["model"])

    def test_each_scenario_traverses_all_six_phases_without_losing_riders(self):
        s=fixture(9)
        r=model.generate_A_B(s,generated_at=AT)
        for branch in r["B"]["six_phase_scenarios"]:
            self.assertEqual([x["phase"] for x in branch["six_phases"]],
                             list(model.PHASES))
            self.assertEqual(branch["projected_3ren_tan"],
                             branch["six_phases"][-1]["projected_top3"])
            for step in branch["six_phases"]:
                self.assertEqual(sorted(step["projected_order"]),list(range(1,10)))
                self.assertFalse(step["actual_rider_position_video_verified"])
        self.assertAlmostEqual(sum(x["relative_research_weight"] for x in
                                   r["B"]["six_phase_scenarios"]),1.0)
        self.assertTrue(r["branch_weights_are_not_calibrated_probabilities"])

    def test_six_and_seven_and_nine_starters_supported(self):
        for n in (6,7,9):
            with self.subTest(n=n):
                r=model.generate_A_B(fixture(n),generated_at=AT)
                self.assertTrue(r["A"]["ranked_tickets"])
                self.assertTrue(r["B"]["ranked_tickets"])
                self.assertTrue(all(set(ticket)<=set(range(1,n+1))
                    for ticket in r["B"]["ranked_tickets"]))

    def test_girls_all_solo_does_not_create_fictitious_permanent_line(self):
        r=model.generate_A_B(fixture(7,girls=True),generated_at=AT)
        self.assertGreaterEqual(len(r["B"]["six_phase_scenarios"]),2)
        snap=fixture(7,girls=True)
        snap["line_groups"]=[[1,2],[3],[4],[5],[6],[7]]
        with self.assertRaisesRegex(model.AutomaticForecastError,"GIRLS_PERMANENT"):
            model.generate_A_B(snap,generated_at=AT)

    def test_post_cutoff_and_schedule_drift_are_refused(self):
        for at in ("2026-11-18T11:59:10+09:00",
                   "2026-11-18T12:01:00+09:00"):
            with self.subTest(at=at):
                with self.assertRaisesRegex(model.AutomaticForecastError,
                                            "TOO_CLOSE_TO_PUBLISHED_CUTOFF"):
                    model.generate_A_B(fixture(),generated_at=at)

    def test_rider_input_is_not_fabricated_if_missing(self):
        for key in ("competition_points","recent_form_score",
                    "mark_rank","h_count","b_count"):
            snap=fixture()
            del snap["riders"][0][key]
            with self.subTest(missing=key):
                with self.assertRaisesRegex(model.AutomaticForecastError,
                                             "RIDER_FACTS_INCOMPLETE"):
                    model.generate_A_B(snap,generated_at=AT)

    def test_incomplete_source_pages_are_hold_not_predictions(self):
        snap=fixture()
        snap["source_pages"]=[x for x in snap["source_pages"]
                              if x["kind"]!="MARKS"]
        with self.assertRaisesRegex(model.AutomaticForecastError,
                                    "RACECARD_MARKS_AND_LINES_REQUIRED"):
            model.generate_A_B(snap,generated_at=AT)

    def test_duplicate_cars_or_rider_ids_are_rejected(self):
        snap=fixture()
        snap["riders"][1]["car"]=1
        with self.assertRaisesRegex(model.AutomaticForecastError,
                                    "CAR_MARK_OR_PERSISTENT_RIDER_ID_DUPLICATE"):
            model.generate_A_B(snap,generated_at=AT)
        snap=fixture()
        snap["riders"][1]["athlete_id"]=snap["riders"][0]["athlete_id"]
        with self.assertRaisesRegex(model.AutomaticForecastError,
                                    "CAR_MARK_OR_PERSISTENT_RIDER_ID_DUPLICATE"):
            model.generate_A_B(snap,generated_at=AT)
        snap=fixture()
        snap["line_groups"]=[[1,2,3],[4,5],[6,6]]
        with self.assertRaisesRegex(model.AutomaticForecastError,
                                    "PREDICTED_LINE_GROUPS_REQUIRED"):
            model.generate_A_B(snap,generated_at=AT)

    def test_published_mark_ties_are_not_invented_as_new_ranks(self):
        snap=fixture()
        snap["riders"][1]["mark_rank"]=snap["riders"][0]["mark_rank"]
        result=model.generate_A_B(snap,generated_at=AT)
        self.assertTrue(result["A"]["ranked_tickets"])
        self.assertEqual(snap["riders"][1]["mark_rank"],1)

    def test_program_unknown_is_not_assumed(self):
        r=model.generate_A_B(fixture(),generated_at=AT)
        self.assertEqual(r["B"]["round_objective_source"],"UNKNOWN_NOT_IMPUTED")
        self.assertFalse(r["formal_model_promoted"])
        snap=fixture()
        snap["round_rule"]={"objective":"DIRECT_QUALIFY","evidence_sha256":"e"*64}
        r=model.generate_A_B(snap,generated_at=AT)
        self.assertEqual(r["B"]["round_objective_source"],"SOURCE_EVIDENCED")

    def test_source_captured_after_snapshot_not_allowed(self):
        snap=fixture()
        snap["source_pages"][0]["captured_at"]="2026-11-18T09:00:30+09:00"
        with self.assertRaisesRegex(model.AutomaticForecastError,
                                    "SOURCE_PAGE_UNATTESTED_OR_AFTER_ASOF"):
            model.generate_A_B(snap,generated_at=AT)

    def test_bets_are_never_placed(self):
        r=model.generate_A_B(fixture(),generated_at=AT)
        self.assertFalse(r["real_money_wager_placed"])
        self.assertFalse(r["official_result_observed"])
