"""Synthetic scenarios only; no target-day race results are read."""
from copy import deepcopy
import unittest

from race_ai import keirin_nationwide_auto_generator as model


def fixture():
    rows=[]
    for c in range(1,8):
        rows.append(dict(car=c,name=f"Synthetic {c}",athlete_id=None,
            mark_rank=c if c < 5 else "UNMARKED",competition_points=90-c,
            win_rate=28-c,top2_rate=50-c,top3_rate=70-c,
            h_count=8 if c in (1,4,6) else 0,b_count=10 if c in (1,4,6) else 0,
            S=c,nige=5 if c in (1,4,6) else 0,makuri=3 if c in (1,4,6) else 0,
            sashi=4 if c in (2,3,5,7) else 0,mark=4 if c in (2,3,5,7) else 0,
            style="NIGE" if c in (1,4,6) else "MARK",gear=3.92,
            comment="自力。" if c in (1,4,6) else "前の選手へ。",
            field_sources={"statistics":"https://example.org/pre-race","comment":"https://example.org/pre-race"}))
    return dict(race_id="SYNTHETIC",riders=rows,line_groups=[[1,2,3],[4,5],[6,7]],line_warnings=[])


class EvidenceSelection(unittest.TestCase):
    def test_variable_selector_is_not_a_twelve_item_slice(self):
        single=[dict(ticket=[1,2,3],support=1.0,scenario_ids=["s0"],reasons=["single supported finish"])]
        selected,meta=model.select_evidence_tickets(single,market="3t")
        self.assertEqual([x["ticket"] for x in selected],[[1,2,3]])
        self.assertEqual(meta["point_count"],1)
        broad=[]
        for a in range(1,6):
            for b in range(1,6):
                if a!=b: broad.append(dict(ticket=[a,b,6],support=1.0,scenario_ids=[f"{a}-{b}"],reasons=["equally supported finish"]))
        selected,meta=model.select_evidence_tickets(broad,market="3t")
        self.assertEqual(len(selected),0)
        self.assertEqual(meta["held_count"],20)
        self.assertEqual(meta["excluded_count"],0)

    def test_complete_generator_can_select_one_or_more_than_twelve(self):
        dominant=fixture()
        for row in dominant["riders"]:
            car=row["car"]
            row["competition_points"]={1:100,2:90,3:80}.get(car,50)
            row["win_rate"]={1:90,2:1,3:0}.get(car,0)
            row["top2_rate"]={1:95,2:80,3:1}.get(car,0)
            row["top3_rate"]={1:100,2:90,3:80}.get(car,0)
        generated=model.generate_evidence_analysis(dominant)
        for arm in ("A","B"):
            self.assertEqual(generated[arm]["ranked_tickets"],[[1,2,3]])
            self.assertEqual(generated[arm]["ranked_2ren_tan"],[[1,2]])
        broad=fixture()
        for row in broad["riders"]:
            weak=row['car']==7
            row.update(competition_points=60 if weak else 90,
                win_rate=0 if weak else 20,top2_rate=0 if weak else 40,
                top3_rate=0 if weak else 60,mark_rank="UNMARKED",
                h_count=8,b_count=10,S=0,nige=5,makuri=3,sashi=4,mark=4,
                style="ALLROUND")
        broad['line_groups']=[[row['car']] for row in broad['riders']]
        generated=model.generate_evidence_analysis(broad)
        self.assertGreater(generated["A"]["point_count_3t"],12)
        self.assertGreater(generated["B"]["point_count_3t"],12)

    def test_no_mutation_and_all_tickets_have_scenario_trace(self):
        snap=fixture(); original=deepcopy(snap)
        out=model.generate_evidence_analysis(snap)
        self.assertEqual(snap,original)
        for arm in ("A","B"):
            packet=out[arm]
            scenarios={x["scenario_id"]:x for x in packet["six_phase_scenarios"]}
            for key,size,mkt in (("ranked_tickets",3,"3t"),("ranked_2ren_tan",2,"2t")):
                tickets=packet[key]
                self.assertEqual(len(tickets),packet[f"point_count_{mkt}"])
                self.assertEqual(len(tickets),len(set(map(tuple,tickets))))
                for evidence in packet["ticket_evidence"][mkt]:
                    self.assertIn(evidence["ticket"],tickets)
                    self.assertTrue(evidence["scenario_ids"])
                    self.assertTrue(evidence["reasons"])
                    for sid in evidence["scenario_ids"]:
                        self.assertEqual(scenarios[sid]["projected_3ren_tan"][:size],evidence["ticket"])
            for scenario in scenarios.values():
                self.assertEqual([p["phase"] for p in scenario["six_phases"]],list(model.PHASES))
                self.assertEqual(scenario["six_phases"][-1]["projected_top3"],scenario["projected_3ren_tan"])
                for p in scenario["six_phases"]:
                    self.assertEqual(sorted(p["projected_order"]),list(range(1,8)))

    def test_two_car_pool_is_built_before_three_car_selection(self):
        # Several weak thirds combine into the strongest pair. A truncated
        # 3T list would drop it. Independent market aggregation must retain it.
        scenarios=[dict(scenario_id="a",projected_3ren_tan=[3,4,5],support_A=1.0,support_B=1.0,pair_support_A=1.0,pair_support_B=1.0,rationale=["strong single third"]),
                   dict(scenario_id="weak",projected_3ren_tan=[5,6,7],support_A=.1,support_B=.1,pair_support_A=.1,pair_support_B=.1,rationale=["weak pair"])]
        for third in (3,4,5,6,7):
            scenarios.append(dict(scenario_id=f"b{third}",projected_3ren_tan=[1,2,third],support_A=.2,support_B=.2,pair_support_A=1.0,pair_support_B=1.0,rationale=["second place stable, third open"]))
        markets=model.select_scenario_markets(scenarios,arm="A")
        self.assertNotIn([1,2,3],markets["ranked_tickets"])
        self.assertIn([1,2],markets["ranked_2ren_tan"])

    def test_fade_tracks_original_attacker_after_follower_pass(self):
        result=model.generate_evidence_analysis(fixture())
        fades=[s for s in result["B"]["six_phase_scenarios"] if s["branch_kind"]=="ATTACKER_FADE"]
        self.assertTrue(fades)
        for s in fades:
            self.assertEqual(s["faded_car"],s["attacking_car"])
            self.assertNotEqual(s["projected_3ren_tan"][0],s["faded_car"])
            self.assertNotIn(s["faded_car"],s["projected_3ren_tan"][:2])
            self.assertEqual(s["six_phases"][3]["projected_order"][0],s["faded_car"])
            self.assertGreaterEqual(s["six_phases"][-1]["projected_order"].index(s["faded_car"]),2)
            self.assertTrue(any(f"CAR_{s['faded_car']}" in x for x in s["six_phases"][-1]["hypothesis_actions"]))

    def test_observed_decisive_moves_change_scenario_support(self):
        original=fixture(); changed=deepcopy(original)
        changed["riders"][1].update(sashi=0,mark=0,style="UNKNOWN")
        a=model.generate_evidence_analysis(original)
        b=model.generate_evidence_analysis(changed)
        sig=lambda x:[(s["branch_kind"],s["projected_3ren_tan"],s["support_B"]) for s in x["B"]["six_phase_scenarios"]]
        self.assertNotEqual(sig(a),sig(b))

    def test_missing_points_are_unknown_not_zero_ability(self):
        snap=fixture(); snap["riders"][2]["competition_points"]=0
        result=model.generate_evidence_analysis(snap)
        self.assertIn("riders.3.competition_points",result["feature_audit"]["missing"])
        self.assertIsNone(result["feature_audit"]["riders"][2]["observed"]["competition_points"])
        self.assertIn("UNAVAILABLE_SOURCE_VALUE",result["feature_audit"]["riders"][2]["warnings"])

    def test_missing_line_only_stops_B_and_conflict_is_not_hidden(self):
        snap=fixture(); snap["line_groups"]=None
        result=model.generate_evidence_analysis(snap)
        self.assertTrue(result["A"]["ranked_tickets"])
        self.assertEqual(result["B"]["state"],"UNGENERATED_LINE_EVIDENCE_MISSING")
        for scenario in result["A"]["six_phase_scenarios"]:
            self.assertFalse(scenario["known_line_hypothesis"])
            for phase in scenario["six_phases"][:-1]:
                self.assertIsNone(phase["projected_order"])
                self.assertIsNone(phase["projected_top3"])
                self.assertTrue(phase["position_unknown"])
        snap=fixture();snap["line_warnings"]=["Two published lineups conflict"]
        result=model.generate_evidence_analysis(snap)
        self.assertIn("Two published lineups conflict",result["B"]["rationale"])

    def test_conditions_do_not_invent_medical_deduction(self):
        snap=fixture();snap["condition_evidence"]=[dict(car=1,fact="Self-reported pain after a fall",source_url="https://example.org/interview",prediction_effect="unknown")]
        result=model.generate_evidence_analysis(snap)
        self.assertFalse(result["condition_sensitivity"]["medical_state_inferred"])
        self.assertEqual(result["condition_sensitivity"]["unverified_rows"],1)
        self.assertFalse(result["condition_sensitivity"]["applied"])

    def test_negative_self_propulsion_comment_is_not_an_affirmative(self):
        snap=fixture()
        snap["riders"][1].update(comment="自力は出さず、番手を回る。",style="MARK",h_count=0,b_count=0,nige=0,makuri=0)
        result=model.generate_evidence_analysis(snap)
        self.assertFalse(result["feature_audit"]["riders"][1]["comment_attack_intent"])
        self.assertFalse(result["feature_audit"]["riders"][1]["explicit_attack"])
        for phrase in ("自力。", "自力自在。", "自力で頑張ります。", "先行勝負はしない。"):
            snap["riders"][1]["comment"]=phrase
            result=model.generate_evidence_analysis(snap)
            self.assertEqual(result["feature_audit"]["riders"][1]["comment_attack_intent"],phrase!="先行勝負はしない。")

    def test_numeric_gear_text_is_recorded_without_claimed_power_bonus(self):
        snap=fixture();snap["riders"][0]["gear"]="3.92"
        result=model.generate_evidence_analysis(snap)
        self.assertEqual(result["feature_audit"]["riders"][0]["observed"]["gear"],3.92)
        self.assertIn("gear",result["feature_audit"]["recorded_not_scored"])


if __name__=="__main__":unittest.main()
