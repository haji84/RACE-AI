"""Optional seller execution uses fictional authenticated B and rating sources."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import boat_all_model_cycle as cycle
from race_ai.boat_observed_pairwise_models import FEATURE_RANGES, predict_pair
from race_ai.boat_seller_inputs import official_b_cards_source
from tests import test_boat_all_model_cycle as cycle_fixtures
from tests.test_boat_observed_pairwise_models import fixture as observed_fixture
from tests.test_boat_seller_official_source import fixture, waku_source, DAY, AT, reseal

MID = "seller-shadow-v1-20261104"
NOW = datetime.fromisoformat(AT)


def original_p0():
    raw, document, receipt = fixture()
    suites = []
    for row in document["predictions"]:
        snapshot = observed_fixture(research=True, all_missing=True)
        snapshot.update(race_id=f"boat:{DAY}:boatrace-jcd-17:{int(row['race_id'][-2:])}",
            event_date_jst=DAY, venue="boatrace-jcd-17", sales_cutoff_at=row["sales_cutoff_at"],
            as_of=row["as_of"], race_source_id="official-B", sources=deepcopy(row["source_evidence"]),
            participants=deepcopy(row["observations"]))
        for participant in snapshot["participants"]:
            participant["features"]["national_win_rate"]["transform_id"] = "official_B_national_win_rate_points_v1"
            participant["missing"] = {field: "MISSING" for field in FEATURE_RANGES if field != "national_win_rate"}
        suites.append(predict_pair(snapshot, allow_source=lambda *_: True))
    document.update(predictions=suites, model_forecast_count=2*len(suites))
    reseal(document, receipt)
    return raw, document, receipt


@patch("race_ai.existing_model_coverage.RETIRED_MODEL_IDS", frozenset())
class SavedP0SellerSourcesTests(unittest.TestCase):
    """Historical synthetic compatibility; not current model execution."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw, self.document, self.receipt = original_p0()
        self.files = cycle_fixtures.AllModelCycleTests.runtime(self)

    def sources(self, *, waku=True):
        return {"cards": official_b_cards_source(self.raw, self.document, self.receipt, day=DAY, as_of=NOW),
                "waku10": waku_source() if waku else None}

    def run_p0(self, sources, **options):
        self.assertIn("seller_sources", inspect.signature(cycle.forecast_saved_p0).parameters,
                      "saved P0 seller source connection is absent")
        return cycle.forecast_saved_p0(self.document, self.receipt, self.files,
            now=options.pop("now", NOW), seller_sources=sources, **options)

    def slots(self, payload):
        return [slot for report in payload["dispatch_reports"] for slot in report["slots"] if slot["model_id"] == MID]

    def test_authentic_daily_sources_dispatch_five_once_and_freeze_registered_native_inputs(self):
        sources = self.sources(); before = deepcopy((self.document, self.receipt, sources))
        payload = self.run_p0(sources)
        self.assertEqual((self.document, self.receipt, sources), before)
        self.assertEqual(Counter(slot["status"] for slot in self.slots(payload)),
                         {"GENERATED_UNATTESTED": 5, "RULE_FILTERED": 3})
        self.assertEqual(payload["seller_input_readiness"]["readiness"]["seller"]["state"], "READY")
        self.assertEqual(payload["source_requests"], 0)
        capsules = cycle.verify_native_input_capsules(payload)
        self.assertEqual(len(capsules), 8)
        for capsule in capsules:
            seller = capsule["native_inputs"]["seller"]
            self.assertEqual(seller["as_of"], NOW.isoformat())
            self.assertEqual(seller["registered_roster"]["roster"], {str(n): str(4000+n) for n in range(1, 7)})
            self.assertEqual(seller["registered_roster"]["native_input_sha256"],
                             digest({k: seller[k] for k in ("cards", "waku", "day")}))
            self.assertEqual(len(seller["cards"]), 8)
        view = cycle.project_round(payload, cycle_fixtures.receipt(payload, saved=DAY+"T06:30:05+09:00"))
        sellers = [p for r in view["records"] for p in ([r["prediction"]] if r["prediction"] else [])
                   + r["comparison_predictions"] if p["model_id"] == MID]
        self.assertEqual(len(sellers), 5)
        self.assertTrue(all(p["eligible_pre_cutoff"] for p in sellers))

    def test_missing_waku_is_explicit_without_seller_payload_and_other_families_still_run(self):
        payload = self.run_p0(self.sources(waku=False))
        report = payload["seller_input_readiness"]
        self.assertEqual(report["readiness"]["race_cards"]["state"], "READY")
        self.assertEqual(report["readiness"]["seller"]["reasons"], ["SAME_FRAME_WIN_RATING_WAKU10_REQUIRED"])
        self.assertEqual(report["coverage"]["card_races"], 8)
        self.assertEqual(report["coverage"]["card_entrants"], 48)
        self.assertEqual({s["reason"] for s in self.slots(payload)}, {"SAME_FRAME_WIN_RATING_WAKU10_REQUIRED"})
        self.assertTrue(all("seller" not in c["native_inputs"] for c in payload["native_input_capsules"]))
        self.assertEqual(payload["summary"]["generated_forecasts"], 32)
        cycle.verify_native_input_capsules(payload)

    def test_actual_0700_clock_blocks_seller_even_with_complete_original_sources(self):
        payload = self.run_p0(self.sources(), now=datetime.fromisoformat(DAY+"T07:00:00+09:00"))
        self.assertEqual({s["status"] for s in self.slots(payload)}, {"DEADLINE_PASSED"})
        self.assertEqual({s["reason"] for s in self.slots(payload)}, {"SELLER_0700_WINDOW_PASSED"})
        self.assertTrue(all("seller" not in c["native_inputs"] for c in payload["native_input_capsules"]))
        self.assertEqual(payload["summary"]["generated_forecasts"], 32)

    def test_wrong_source_hash_or_fraction_semantics_only_rejects_the_seller(self):
        for case in ("hash", "fraction"):
            sources = self.sources()
            if case == "hash": sources["cards"]["raw"] += b"changed"
            else: sources["waku10"]["metric_semantics"] = "SAME_FRAME_WIN_FRACTION_0_1"
            payload = self.run_p0(sources)
            with self.subTest(case=case):
                self.assertEqual({s["status"] for s in self.slots(payload)}, {"INPUT_REJECTED"})
                self.assertTrue(all("seller" not in c["native_inputs"] for c in payload["native_input_capsules"]))
                self.assertEqual(payload["summary"]["generated_forecasts"], 32)

    def test_source_from_a_different_authenticated_p0_cannot_be_silently_substituted(self):
        changed = deepcopy(self.document); proof = deepcopy(self.receipt)
        changed["source_record_note"] = "another original"
        reseal(changed, proof)
        sources = {"cards": official_b_cards_source(self.raw, changed, proof, day=DAY, as_of=NOW), "waku10": waku_source()}
        payload = self.run_p0(sources)
        self.assertEqual({s["status"] for s in self.slots(payload)}, {"INPUT_REJECTED"})
        self.assertTrue(all("seller" not in c["native_inputs"] for c in payload["native_input_capsules"]))

    def test_any_previously_issued_seller_preserves_its_daily_decision_without_reranking(self):
        payload = self.run_p0(self.sources(), issued_models={"20300115-17-08": [MID]})
        self.assertEqual({s["status"] for s in self.slots(payload)}, {"RULE_FILTERED"})
        self.assertEqual(payload["seller_input_readiness"]["readiness"]["seller"]["reasons"],
                         ["SAVED_SELLER_DAILY_DECISION_RETAINED_NO_RERANK"])
        self.assertFalse(any(i["native_group"] == "seller" for r in payload["dispatch_reports"] for i in r["native_invocations"]))
        self.assertEqual(payload["summary"]["generated_forecasts"], 32)

    def test_explicit_none_preserves_existing_payload_hash_and_capsules(self):
        omitted = cycle.forecast_saved_p0(self.document, self.receipt, self.files, now=NOW)
        explicit = self.run_p0(None)
        self.assertEqual(explicit, omitted)
        self.assertEqual(digest(explicit), "af872beaf23ef959a6d39133c185f5fad76fd48f99ff82ce219c218908f21a54")
        self.assertNotIn("seller_input_readiness", explicit)



class RemovedSellerP0Tests(unittest.TestCase):
    def test_complete_missing_and_invalid_seller_inputs_do_not_change_active_p0(self):
        fixture = SavedP0SellerSourcesTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        before = deepcopy((fixture.document, fixture.receipt))
        expected = fixture.run_p0(None)
        for sources in (fixture.sources(), fixture.sources(waku=False), {'unusable': True}):
            with self.subTest(sources=list(sources)):
                payload = fixture.run_p0(sources)
                self.assertEqual(payload, expected)
                self.assertEqual(fixture.slots(payload), [])
                self.assertNotIn('seller_input_readiness', payload)
                self.assertTrue(all('seller' not in c['native_inputs']
                                    for c in payload['native_input_capsules']))
                self.assertEqual(payload['summary']['generated_forecasts'], 32)
        self.assertEqual((fixture.document, fixture.receipt), before)


if __name__ == "__main__":
    unittest.main()
