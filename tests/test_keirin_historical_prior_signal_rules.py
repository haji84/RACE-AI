"""Fictional past results only: fixed v1 historical feature rules."""
from copy import deepcopy
from datetime import datetime, timedelta
import unittest

from race_ai.keirin_historical_prior_signal_rules import (
    SCHEMA, OUTPUT_SCHEMA, FORMULA_VERSION,
    compute_prior_signal_candidates, PriorSignalError
)

FUTURE="2030-01-15T09:10:00+09:00"
CUTOFF="2030-01-15T10:00:00+09:00"
SHA="a"*64
FAKE="https://example.invalid/fictional-sources"


def example(n=11, with_splits=True):
    events=[]
    for k in range(n):
        day=(datetime.fromisoformat("2029-12-01T09:00:00+09:00")+
             timedelta(days=k))
        def stamp(hour,minute=0):
            return day.replace(hour=hour,minute=minute).isoformat()
        entries=[]
        for rider in range(1,8):
            rank=((rider+k-1)%7)+1
            # True contiguous timed segment information exists in *fiction*,
            # not in the actual owner racecard archives.
            splits=([{"distance_m":100,"elapsed_s":5+rider*.05},
                     {"distance_m":100,"elapsed_s":4.9+rider*.04}]
                    if with_splits and k<4 else None)
            entries.append({
                "rider_id":f"fictional-{rider}",
                "finish_rank":rank,
                "line_id":"L1" if rider<=3 else "L2" if rider<=6 else None,
                "agari_s":11 + rider * .12 + k*.005,
                "final_two_splits":splits,
            })
        events.append({
            "race_id":f"fictional-race-{k}",
            "started_at":stamp(10), "ended_at":stamp(10,5),
            "lineup_published_at":stamp(9),
            "result_published_at":stamp(11),
            "lineup_source_url":FAKE,
            "result_source_url":FAKE,
            "lineup_source_sha256":"b"*64,
            "result_source_sha256":SHA,
            "venue":"fictional-home" if k<6 else "fictional-away",
            "race_class":"FICTIONAL_A",
            "race_category":"men",
            "distance_m":2000,
            "starters":entries,
        })
    return {
        "schema":SCHEMA,
        "target":{
            "race_id":"fictional-target-20300115-01",
            "as_of":FUTURE, "cutoff":CUTOFF,
            "rider_id":"fictional-1","venue":"fictional-home",
            "race_class":"FICTIONAL_A",
            "distance_m":2000,"race_category":"men",
        },
        "prior_events":events,
    }


class FixedHistoricalSignalTests(unittest.TestCase):
    def test_three_signals_and_actual_split_only_are_candidates(self):
        packet=example()
        original=deepcopy(packet)
        output=compute_prior_signal_candidates(packet)
        self.assertEqual(packet,original)
        self.assertEqual(output["schema"],OUTPUT_SCHEMA)
        self.assertEqual(output["formula_version"],FORMULA_VERSION)
        self.assertEqual(output["comparison_eligible_past_events"],11)
        features=output["features"]
        self.assertEqual(features["finishing_power"]["sample_count"],11)
        self.assertEqual(features["sprint_acceleration"]["sample_count"],4)
        self.assertEqual(features["line_coordination"]["sample_count"],11)
        self.assertEqual(features["bank_fit"]["same_venue_count"],6)
        self.assertEqual(features["bank_fit"]["other_venue_count"],5)
        self.assertAlmostEqual(features["finishing_power"]["candidate_value"],1)
        self.assertTrue(0<=features["sprint_acceleration"]["candidate_value"]<=1)
        # Fixed v1 baseline: home 3/6 vs other 3/5, with Beta(1,1)
        # rates 4/8 and 4/7; one and only one agreed transformation.
        self.assertAlmostEqual(features["bank_fit"]["candidate_value"],
                               .5+.5*(4/8-4/7))
        self.assertAlmostEqual(features["line_coordination"]["candidate_value"],
                               4/11)
        for name in ("finishing_power","sprint_acceleration",
                     "line_coordination","bank_fit"):
            self.assertIsNotNone(features[name]["candidate_value"])
            self.assertFalse(features[name]["approved_for_pr71_input"])
        self.assertTrue(output["no_hindsight_target_results"])
        self.assertFalse(output["source_use_rights_verified"])
        self.assertIsNone(output["real_world_accuracy"])
        self.assertFalse(output["original_pr71_forecast_exists"])

    def test_half_lap_agari_does_not_forge_acceleration(self):
        archive=example(with_splits=False)
        out=compute_prior_signal_candidates(archive)
        self.assertIsNotNone(out["features"]["finishing_power"]["candidate_value"])
        self.assertIsNone(out["features"]["sprint_acceleration"]["candidate_value"])
        self.assertEqual(out["features"]["sprint_acceleration"]["sample_count"],0)
        self.assertEqual(out["features"]["sprint_acceleration"]["status"],
                         "INSUFFICIENT_PAST_SAMPLES")

    def test_under_minimum_samples_is_unknown_not_zero(self):
        record=example(n=2)
        out=compute_prior_signal_candidates(record)["features"]
        for key in ("finishing_power","line_coordination","bank_fit"):
            self.assertIsNone(out[key]["candidate_value"])
        self.assertEqual(out["line_coordination"]["sample_count"],2)
        self.assertEqual(out["bank_fit"]["other_venue_count"],0)

    def test_changing_an_old_result_changes_research_digest_not_target(self):
        pack=example()
        baseline=compute_prior_signal_candidates(pack)
        pack["prior_events"][0]["starters"][0]["finish_rank"]=7
        # All finish ranks must remain unique for a true previous race.
        pack["prior_events"][0]["starters"][-1]["finish_rank"]=1
        changed=compute_prior_signal_candidates(pack)
        self.assertNotEqual(changed["source_packet_sha256"],
                            baseline["source_packet_sha256"])
        self.assertEqual(changed["status"],
                         "CANDIDATE_ONLY_NOT_ADMITTED_FOR_PR71")

    def test_no_later_source_or_target_outcome_can_enter_model(self):
        for mutator in [
            lambda p:p["prior_events"][0].update({
                "result_published_at":"2030-01-15T11:00:00+09:00"}),
            lambda p:p["prior_events"][0].update({
                "lineup_published_at":"2029-12-01T10:04:00+09:00"}),
            lambda p:p["prior_events"][0].update({
                "race_id":p["target"]["race_id"]}),
            lambda p:p["target"].update({"actual_finish":[1,2,3]}),
            lambda p:p["prior_events"][0]["starters"][0].update(
                {"target_result_order":[1,2,3]}),
            lambda p:p["prior_events"][0].update({
                "result_source_sha256":"zzzz"}),
        ]:
            pack=example()
            mutator(pack)
            with self.assertRaises(PriorSignalError):
                compute_prior_signal_candidates(pack)

    def test_unsupported_race_class_never_mixes_into_bank_fit(self):
        packet=example()
        for row in packet["prior_events"]:
            if row["venue"]=="fictional-away":
                row["race_class"]="FICTIONAL_B"
        features=compute_prior_signal_candidates(packet)["features"]
        self.assertEqual(features["bank_fit"]["same_venue_count"],6)
        self.assertEqual(features["bank_fit"]["other_venue_count"],0)
        self.assertIsNone(features["bank_fit"]["candidate_value"])

    def test_prior_lineup_unknown_does_not_assume_partner_or_coordination(self):
        data=example()
        for event in data["prior_events"]:
            for racer in event["starters"]:
                racer["line_id"]=None
        out=compute_prior_signal_candidates(data)["features"]
        self.assertIsNone(out["line_coordination"]["candidate_value"])
        self.assertEqual(out["line_coordination"]["sample_count"],0)

    def test_tied_agari_rates_are_not_dedicated_acceleration(self):
        sample=example(with_splits=False)
        for item in sample["prior_events"]:
            for p in item["starters"]:
                p["agari_s"]=11.7
        result=compute_prior_signal_candidates(sample)["features"]
        self.assertAlmostEqual(result["finishing_power"]["candidate_value"],.5)
        self.assertIsNone(result["sprint_acceleration"]["candidate_value"])

    def test_bad_split_and_duplicate_result_rank_rejected(self):
        for change in [
            lambda x:x["prior_events"][0]["starters"][0][
                "final_two_splits"][1].update({"distance_m":110}),
            lambda x:x["prior_events"][0]["starters"][0][
                "final_two_splits"][1].update({"elapsed_s":.01}),
            lambda x:x["prior_events"][0]["starters"][1].update(
                {"finish_rank":1}),
        ]:
            p=example()
            change(p)
            with self.assertRaises(PriorSignalError):
                compute_prior_signal_candidates(p)

    def test_empty_event_evidence_is_not_zero_score(self):
        out=compute_prior_signal_candidates(example(n=0))
        self.assertEqual(out["comparison_eligible_past_events"],0)
        for r in out["features"].values():
            self.assertIsNone(r["candidate_value"])





class PrivateCommandLineTests(unittest.TestCase):
    def test_private_cli_prints_presence_not_rider_id_or_feature_values(self):
        from scripts.keirin_historical_prior_signal_probe import main
        from contextlib import redirect_stdout
        from pathlib import Path
        import tempfile
        import io
        import json

        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"prior.json"
            p.write_text(json.dumps(example()),encoding="utf-8")
            stdout=io.StringIO()
            with redirect_stdout(stdout):
                code=main(["--owner-prior-events",str(p)])
            self.assertEqual(code,0)
            info=json.loads(stdout.getvalue())
            self.assertEqual(info["event_count_provided"],11)
            self.assertEqual(info["feature_coverage"]["line_coordination"][
                "sample_count"],11)
            self.assertTrue(info["feature_coverage"]["bank_fit"][
                "meets_fixed_minimum"])
            self.assertFalse(info["feature_coverage"]["bank_fit"][
                "approved_for_pr71_input"])
            self.assertNotIn("fictional-",stdout.getvalue())
            self.assertNotIn("candidate_value",stdout.getvalue())
            self.assertNotIn("result_source_url",stdout.getvalue())

    def test_invalid_archive_refused_without_source_echo(self):
        from scripts.keirin_historical_prior_signal_probe import main
        from contextlib import redirect_stdout
        from pathlib import Path
        import tempfile
        import io

        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bad.json"
            for bad in ("[]", '{"tag":"one","tag":"two"}', "{INVALID_PRIVATE_ID}"):
                p.write_text(bad,encoding="utf-8")
                stdout=io.StringIO()
                with redirect_stdout(stdout):
                    code=main(["--owner-prior-events",str(p)])
                self.assertEqual(code,2)
                self.assertIn("HISTORICAL_PRIOR_SIGNAL_INPUT_HOLD",
                              stdout.getvalue())
                self.assertNotIn("INVALID_PRIVATE_ID",stdout.getvalue())

if __name__=="__main__":
    unittest.main()
