"""Encrypted fictional artifact intake; no live key, receipt fetch or provider."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_pairs as pairs
from race_ai.boat_observed_pairwise_models import MODEL_IDS as OBSERVED
from tests import test_all_existing_model_pairs as pair_fixtures
from tests.test_observed_weight_learning import NOW

FORECAST_NOW = pair_fixtures.FORECAST_NOW
HEAD = pair_fixtures.HEAD


class AllExistingModelIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from race_ai.all_existing_model_learning import fit
        from tests.test_all_existing_model_learning import observed_records
        cls.records = observed_records()
        cls.training = fit(cls.records, now=NOW)

    def setUp(self):
        # Reuse the existing actual codec/metadata fixture without inheriting
        # its tests. Its environment contains only a fresh ephemeral test key.
        fixture = pair_fixtures.AllExistingModelPrivatePairsTests(methodName="runTest")
        fixture.records = self.records
        fixture.training = self.training
        fixture.cell = next(iter(self.training["models"]))
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.requests = fixture.extra_native_requests()+[
            dict(cell_key="boat/"+mid, native_payload=fixture.native()) for mid in OBSERVED]
        # Preserve all source evidence, including a derived composite and its
        # exact upstream hashes, without treating it as a permission grant.
        clite = self.requests[2]["native_payload"]
        clite["source_evidence"] = [dict(source_ref="synthetic://program", source_rights_ref="fixture",
            source_sha256="a"*64, evidence_basis="HTTP_BODY_SHA256"),
            dict(source_ref="synthetic://preview", source_rights_ref="fixture",
                 source_sha256="b"*64, evidence_basis="HTTP_BODY_SHA256"),
            dict(source_ref="synthetic://preview", source_rights_ref="fixture",
                 source_sha256=hashlib.sha256(("a"*64+"b"*64).encode()).hexdigest(),
                 evidence_basis="DERIVED_COMPOSITE_SHA256", upstream_source_sha256=["a"*64, "b"*64],
                 derivation="SHA256_UTF8_CONCAT_PROGRAM_AND_BEFOREINFO_HEX_V1")]
        pairs.make_private_pairs(fixture.context, self.requests, fixture.root/"pairs",
                                 now=FORECAST_NOW, allow_source=lambda *_: True)
        self.raw, _ = fixture.archive()
        self.metadata = fixture.metadata(self.raw)
        self.now = FORECAST_NOW+timedelta(hours=1)

    def module(self):
        name = "race_ai.all_existing_model_intake"
        self.assertIsNotNone(importlib.util.find_spec(name), "authenticated native training intake is missing")
        return importlib.import_module(name)

    def generic(self, **changes):
        value = self.fixture.observation()
        value.update(source_ref="synthetic://official-result", source_rights_ref="synthetic-result-v1",
                     published_at=(FORECAST_NOW+timedelta(minutes=20, seconds=30)).isoformat())
        value.update(changes)
        return value

    def old_boat(self, **changes):
        from tests.test_frozen_day_cycle import observation
        info = self.generic()
        row = dict(race_id="20300401-24-12", cutoff_at=(FORECAST_NOW+timedelta(minutes=20)).isoformat(),
                   top8=[info["ordered_top3"]], roster=info["roster"])
        result = observation(row)
        result.update(captured_at=info["captured_at"],
                      source_url="https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20300401&jcd=24&rno=12")
        result.update(changes)
        return result

    def intake(self, observations=None, *, raw=None, metadata=None):
        return self.module().records_from_private_artifact(
            self.raw if raw is None else raw, self.metadata if metadata is None else metadata,
            [self.generic()] if observations is None else observations, now=self.now,
            expected_run_id=99, expected_head_sha=HEAD)

    def repack(self, payloads):
        from race_ai.boat_venue_learning import seal_candidate
        folder = Path(tempfile.mkdtemp(prefix="intake-repack-", dir=self.fixture.root))
        body = io.BytesIO()
        with zipfile.ZipFile(body, "w", zipfile.ZIP_DEFLATED) as archive:
            for payload in payloads:
                payload["summary"] = pairs._summary(payload)
                key = pairs.partition_key(payload["pair"])
                target = folder/key
                seal_candidate(payload, target)
                for name in ("learning.json", "learning.enc", "summary.json"):
                    archive.writestr(key+"/"+name, (target/name).read_bytes())
        raw = body.getvalue()
        return raw, self.fixture.metadata(raw)

    def private_payloads(self):
        from race_ai.boat_venue_learning import read_candidate
        return [read_candidate(folder) for folder in sorted((self.fixture.root/"pairs").iterdir()) if folder.is_dir()]

    def test_actual_encrypted_capsules_become_only_their_five_native_records(self):
        api = self.module()
        before = deepcopy((self.requests, self.metadata))
        result = self.intake()
        self.assertEqual(len(result["records"]), 5)
        self.assertEqual({row["model_id"] for row in result["records"]},
                         {request["cell_key"].split("/", 1)[1] for request in self.requests})
        for row in result["records"]:
            request = next(request for request in self.requests if request["cell_key"] == "boat/"+row["model_id"])
            self.assertEqual(row["native_payload"], request["native_payload"])
            self.assertEqual(row["input_sha256"], digest(request["native_payload"]))
            self.assertEqual(row["input_saved_at"], self.metadata["created_at"])
            self.assertEqual(row["input_receipt"]["artifact_id"], 800)
            self.assertEqual(row["input_receipt"]["digest"], self.metadata["digest"])
            self.assertEqual(row["input_receipt"]["workflow_run_id"], 99)
            self.assertEqual(row["input_receipt"]["head_sha"], HEAD)
            self.assertEqual(row["result"]["roster"], self.generic()["roster"])
            self.assertEqual(row["result"]["published_at"], self.generic()["published_at"])
            self.assertNotIn("observed_row", row)
            self.assertNotIn("observed_result", row)
            self.assertEqual(row["result_observation"], self.generic())
        summary = result["summary"]
        self.assertEqual(summary["admitted_record_count"], 5)
        self.assertEqual(summary["captured_unfitted_native_input_count"], 3)
        self.assertEqual(summary["uncaptured_cell_count"], 26)
        self.assertTrue(summary["independent_pre_cutoff_receipt_verified"])
        for secret in ("native_payload", "roster", "ordered_top3", "program_source_sha256", "source_ref"):
            self.assertNotIn(secret, json.dumps(summary))
        self.assertEqual((self.requests, self.metadata), before)
        json.dumps(result, allow_nan=False)

    def test_old_normalized_boat_alias_keeps_exact_roster_and_does_not_invent_publication(self):
        old = self.old_boat()
        result = self.intake([old])
        self.assertEqual(len(result["records"]), 5)
        for row in result["records"]:
            self.assertIsNone(row["result"]["published_at"])
            self.assertEqual(row["result"]["source_ref"], old["source_url"])
            self.assertEqual(row["result"]["source_rights_ref"],
                             "OWNER_PERSONAL_OFFICIAL_RESULT_EVALUATION_20261106")
            self.assertEqual(row["result"]["ordered_top3"], old["data"]["top3"])
            self.assertEqual(row["result_observation"], old)

    def test_authentication_precedes_any_observation_or_capsule_use(self):
        api = self.module()
        with patch("race_ai.all_existing_model_receipt._verified_private_pairs_artifact",
                   side_effect=ValueError("authentication first")) as authenticate:
            with self.assertRaisesRegex(ValueError, "authentication first"):
                api.records_from_private_artifact(b"bad", {}, object(), now=self.now,
                    expected_run_id=99, expected_head_sha=HEAD)
            self.assertEqual(authenticate.call_count, 1)
        with self.assertRaises(ValueError):
            self.intake(metadata=dict(self.metadata, digest="sha256:"+"0"*64))

    def test_identical_capsules_deduplicate_across_two_fitted_partitions_and_conflicts_stop(self):
        payloads = self.private_payloads()
        carrier = next(payload for payload in payloads if payload.get("captured_native_inputs"))
        other = next(payload for payload in payloads if payload is not carrier)
        other["captured_native_inputs"] = deepcopy(carrier["captured_native_inputs"])
        raw, metadata = self.repack(payloads)
        result = self.intake(raw=raw, metadata=metadata)
        self.assertEqual(len(result["records"]), 5)
        self.assertEqual(result["summary"]["duplicate_native_input_count"], 5)
        changed = next(capsule for capsule in other["captured_native_inputs"]
                       if "source" in capsule["native_payload"])
        changed["native_payload"]["source"]["boats"][0]["national_win_rate"] += .1
        changed["input_sha256"] = digest(changed["native_payload"])
        raw, metadata = self.repack(payloads)
        with self.assertRaisesRegex(ValueError, "CONFLICTING_NATIVE_INPUT"):
            self.intake(raw=raw, metadata=metadata)

    def test_missing_unmatched_pending_and_special_results_stay_counted_not_losses(self):
        self.assertEqual(self.intake([])["summary"]["missing_result_native_input_count"], 5)
        for value, name in ((self.generic(status="pending", ordered_top3=[]), "pending_result_native_input_count"),
                            (self.generic(status="special", ordered_top3=[]), "special_result_native_input_count"),
                            (self.generic(refund_numbers=[6]), "special_result_native_input_count")):
            result = self.intake([value])
            self.assertEqual(result["records"], [])
            self.assertEqual(result["summary"][name], 5)
        unavailable = self.old_boat(status="UNAVAILABLE")
        unavailable.pop("data")
        self.assertEqual(self.intake([unavailable])["summary"]["pending_result_native_input_count"], 5)
        unmatched = self.generic(race_id="boat:2030-04-01:boatrace-jcd-23:12")
        result = self.intake([self.generic(), unmatched])
        self.assertEqual(len(result["records"]), 5)
        self.assertEqual(result["summary"]["unmatched_result_count"], 1)

    def test_future_wrong_roster_unverified_wrong_cutoff_hash_and_conflicting_alias_stop(self):
        invalid = [self.generic(captured_at=(self.now+timedelta(seconds=1)).isoformat()),
                   self.generic(roster={"1": "wrong"}), self.generic(identity_verified=False),
                   self.generic(source_sha256="bad"),
                   self.old_boat(closed_at=(FORECAST_NOW+timedelta(minutes=19)).isoformat())]
        bad_registration = self.old_boat()
        bad_registration["data"]["results"][0]["racer_registration_id"] = "9999"
        invalid.append(bad_registration)
        missing_closed_at = self.old_boat()
        missing_closed_at.pop("closed_at")
        invalid.append(missing_closed_at)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.intake([value])
        duplicate = self.generic(race_id="20300401-24-12",
                                 ordered_top3=list(reversed(self.generic()["ordered_top3"])))
        with self.assertRaisesRegex(ValueError, "CONFLICTING_RESULT"):
            self.intake([self.generic(), duplicate])
        identical_alias = self.generic(race_id="20300401-24-12")
        result = self.intake([self.generic(), identical_alias])
        self.assertEqual(len(result["records"]), 5)
        self.assertEqual(result["summary"]["duplicate_result_count"], 1)


if __name__ == "__main__":
    unittest.main()
