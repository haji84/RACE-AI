"""Missing observed families run on real native fixture inputs after saved A/B."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai import boat_all_model_cycle as cycle
from race_ai.boat_all_model_inputs import build_native_inputs
from race_ai.boat_ab_shadow import MODEL_IDS as AB
from race_ai.boat_observed_pairwise_models import MODEL_IDS as OBSERVED
from race_ai.existing_model_dispatch import dispatch
from race_ai.observed_p1_connection import build_bundle
from tests.test_boat_all_model_inputs import official_inputs, ASOF
from tests import test_boat_all_model_cycle as fixtures


class ObservedCompletionTests(unittest.TestCase):
    def test_native_snapshot_matches_existing_adapter_and_binds_query_free_sources(self):
        program, before = official_inputs()
        built = build_native_inputs(program, before, as_of=ASOF)
        self.assertIn("boat_observed", built["native_inputs"])
        native = built["native_inputs"]
        expected = build_bundle(native["boat_ab"]["source"], native["boat_clite"]["extra"], ASOF,
            program_url=program["source_url"], preview_url=before["source_url"],
            program_captured_at=program["captured_at"], preview_captured_at=before["captured_at"], owner_reviewed=True)
        self.assertEqual(native["boat_observed"]["snapshot"], expected["snapshot"])
        self.assertEqual(built["readiness"]["boat_observed"], dict(state="READY", reasons=[]))
        refs = {(e["source_ref"], e["source_rights_ref"]) for e in built["source_evidence"]}
        for source in expected["snapshot"]["sources"]:
            self.assertIn((source["source_url"], source["source_rights_ref"]), refs)
            self.assertIn(dict(source_ref=source["source_url"], source_rights_ref=source["source_rights_ref"],
                source_sha256=source["source_sha256"], captured_at=source["captured_at"], published_at=source["published_at"]), built["source_evidence"])
        report = dispatch([dict(race_id=program["race_id"], sport="boat", stage="P1", cutoff_at=program["closed_at"])],
            {program["race_id"]: {"P1": {"boat_observed": native["boat_observed"]}}}, now=ASOF,
            allow_source=lambda ref, rights, purpose: purpose == "analysis" and (ref, rights) in refs)
        slots = {s["model_id"]: s for s in report["slots"]}
        for mid in OBSERVED:
            self.assertEqual(slots[mid]["status"], "GENERATED_UNATTESTED", slots[mid].get("reason"))
            self.assertEqual(len(slots[mid]["prediction"]["candidates"]), 6)

    def test_saved_ab_does_not_block_generating_both_missing_observed_models(self):
        with tempfile.TemporaryDirectory() as folder:
            self.root = Path(folder)
            runtime = fixtures.AllModelCycleTests.runtime(self)
            ctx = fixtures.source_context(); rid = ctx["program"]["race_id"]
            with patch("race_ai.existing_model_dispatch.build_pair", side_effect=AssertionError("saved A/B regenerated")):
                payload = cycle.forecast_round([ctx], runtime, now=fixtures.NOW, issued_models={rid: list(AB)})
            slots = {s["model_id"]: s for s in payload["dispatch_reports"][0]["slots"]}
            for mid in AB:
                self.assertEqual(slots[mid]["status"], "RULE_FILTERED")
            for mid in OBSERVED:
                self.assertEqual(slots[mid]["status"], "GENERATED_UNATTESTED", slots[mid].get("reason"))
                self.assertEqual(len(slots[mid]["prediction"]["candidates"]), 60)
                self.assertEqual({lane for row in slots[mid]["prediction"]["candidates"] for lane in row["combination"]}, {1, 2, 3, 4, 5})
