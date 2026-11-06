"""All 31 native cells fit invented data; never real coverage/accuracy proof.

Factories below are shared with pairing/hardening tests. They preserve each
native payload schema and require no keys, provider calls or persisted state.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import math
import re
import unittest

from race_ai.actions_contract import digest
from race_ai import all_existing_model_learning as learning
from race_ai import all_existing_model_registry as registry
from race_ai.four_sport_learning import LEARNED_ID
from tests.test_boat_ab_shadow import fixture as ab_fixture
from tests.test_boat_live_feature_shadow import fixture as clite_fixture
from tests.test_boat_tactical_scenarios import inputs as tactical_fixture, FORECAST_AT
from tests.test_boat_multi_feature_models import fixture as full_fixture
from tests.test_boat_observed_pairwise_models import fixture as observed_fixture
from tests.test_comprehensive_four_sport_models import sample as shared_fixture
from tests.test_autorace_personal_baseline import sample as auto_fixture
from tests.test_existing_special_parameter_adapters import seller_payload, pdca_payload


NOW = datetime(2031, 1, 1, tzinfo=timezone.utc)
SIZES = {"boat": 6, "keirin": 7, "autorace": 3, "horse": 3}


def _shift_dates(value, offset):
    """Move fictional races and their earlier source history by whole days."""
    if isinstance(value, dict):
        return {_shift_dates(k, offset): _shift_dates(v, offset) for k, v in value.items()}
    if isinstance(value, list):
        return [_shift_dates(v, offset) for v in value]
    if not isinstance(value, str):
        return value

    def iso(match):
        return (date.fromisoformat(match.group(0))+timedelta(days=offset)).isoformat()

    def compact(match):
        day = datetime.strptime(match.group(0), "%Y%m%d").date()
        return (day+timedelta(days=offset)).strftime("%Y%m%d")

    value = re.sub(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)", iso, value)
    return re.sub(r"(?<!\d)20\d{6}(?=\D|$|\d{4}(?!\d))", compact, value)


def native_payload(model_id, sport, index=0):
    """Actual existing fixture input, with its own native identity and clocks."""
    kind = registry.group(model_id)
    if kind == "boat_ab":
        payload = {"source": ab_fixture()}
    elif kind == "boat_clite":
        source, extra, at = clite_fixture()
        source["captured_at"] = at
        payload = {"base_source": source, "extra": extra}
    elif kind == "boat_tactical":
        source, histories, venue = tactical_fixture()
        source["captured_at"] = FORECAST_AT
        payload = {"source": source, "histories": histories, "venue": venue}
    elif kind == "boat_full":
        payload = {"snapshot": full_fixture()}
    elif kind == "boat_observed":
        payload = {"snapshot": observed_fixture("P1")}
    elif kind in ("shared", "shared_learned"):
        payload = {"snapshot": shared_fixture(sport, size=SIZES[sport]), "stage": "P1"}
    elif kind == "autorace_personal":
        from race_ai.autorace_ab_pdca import PHASES
        payload = {"snapshot": auto_fixture(PHASES[1], count=3)}
    elif kind == "seller":
        payload = seller_payload(count=8)
        # Opposing observed desirability orders exercise the existing two
        # second-place coefficients, rather than fitting an unchanged rule on
        # a fixture whose rankings cannot respond to either coefficient.
        for key, card in payload["cards"].items():
            for lane in range(2, 7):
                card[f"艇{lane}_全国勝率"] = str(9-lane)
                payload["waku"][key][f"艇{lane}_枠番別勝率"] = str(lane+2)
        # The highest-ranked native five include race eight. Keep the full
        # batch so native <=5-races and 3/5-ticket decisions remain observable.
        payload.update(race_id="203001151808", as_of="2030-01-15T06:30:00+09:00",
                       cutoff_at="2030-01-15T14:00:00+09:00")
    elif kind == "boat_pdca":
        payload = pdca_payload()
    else:
        raise ValueError("unregistered fixture native group")
    payload["scope"] = "SYNTHETIC_ONLY"
    if "scope" in payload.get("snapshot", {}):
        payload["snapshot"]["scope"] = "SYNTHETIC_ONLY"
    payload = _shift_dates(payload, index)
    if kind in ('seller', 'autorace_personal'):
        # These native formats contain slots and ratings only. Explicitly
        # invented identities belong in a separately source-bound envelope;
        # they must never be inferred from the lane/car number in production.
        if kind == 'autorace_personal':
            native = payload['snapshot']; race = native['race']
            rid, at, captured = race['race_id'], race['as_of_at'], race['source_captured_at']
            source = race['source_url']; source_sha = digest(native)
            roster = {'1': 'fictional-driver-alpha', '2': 'fictional-driver-beta', '3': 'fictional-driver-gamma'}
            evidence = [dict(source_ref=source, source_rights_ref='synthetic-matrix-program-v1',
                             source_sha256=source_sha, captured_at=captured)]
        else:
            native = {key: payload[key] for key in ('cards', 'waku', 'day')}
            rid, at, captured = payload['race_id'], payload['as_of'], payload['as_of']
            source = 'synthetic://matrix/seller-native-program'; source_sha = digest(payload['cards'])
            roster = {'1': '4101', '2': '4102', '3': '4103', '4': '4104', '5': '4105', '6': '4106'}
            evidence = [dict(source_ref=source, source_rights_ref='synthetic-matrix-program-v1',
                             source_sha256=source_sha, captured_at=captured),
                        dict(source_ref='synthetic://matrix/seller-native-course', source_rights_ref='synthetic-matrix-course-v1',
                             source_sha256=digest(payload['waku']), captured_at=captured)]
        payload['source_evidence'] = evidence
        payload['registered_roster'] = dict(schema=registry.ROSTER_SCHEMA, sport=sport, race_id=rid, as_of=at,
            roster=roster, native_input_sha256=digest(native), source_ref=source,
            source_rights_ref='synthetic-matrix-program-v1', source_sha256=source_sha, captured_at=captured)
    if kind == "boat_pdca":
        # report_json is an original serialized result; its binding must move
        # with these invented history dates rather than retaining an old SHA.
        for row in payload["rows"]:
            row["report_sha256"] = hashlib.sha256(row["report_json"].encode()).hexdigest()
    return payload


def native_records(model_id, sport, n=8):
    """One distinct frozen native input and separate settled outcome per race."""
    records = []
    for index in range(n):
        payload = native_payload(model_id, sport, index)
        info = registry.identity(model_id, sport, payload)
        cutoff = datetime.fromisoformat(info["race_cutoff_at"])
        as_of = datetime.fromisoformat(info["as_of"])
        winner = ([1, 2, 3], [2, 3, 1], [3, 1, 2])[index % 3]
        if registry.group(model_id) == "seller":
            winner = [1, 6, 5]
        result = dict(race_id=info["race_id"], sport=sport, status="settled",
                      ordered_top3=winner, published_at=(cutoff+timedelta(minutes=1)).isoformat(),
                      captured_at=(cutoff+timedelta(minutes=2)).isoformat(),
                      source_ref="synthetic://matrix/"+info["race_id"],
                      source_rights_ref="synthetic-matrix-result-v1",
                      source_sha256=digest(["invented-result", model_id, sport, index, winner]),
                      identity_verified=True, roster=deepcopy(info["roster"]),
                      payout_per_100_yen=1500+index*100, refund_numbers=[])
        records.append(dict(model_id=model_id, sport=sport, race_id=info["race_id"],
                            stage=info["stage"], scope="SYNTHETIC_ONLY", as_of=info["as_of"],
                            cutoff_at=info["cutoff_at"], native_payload=payload,
                            input_sha256=digest(payload),
                            input_saved_at=(as_of+timedelta(seconds=1)).isoformat(),
                            input_receipt={"kind": "SYNTHETIC_ONLY", "independently_attested": False},
                            result=result))
    return records


def all_records():
    """Eight genuine native-schema fictional races in each applicable cell."""
    return [row for cell in registry.cells()
            for row in native_records(cell["model_id"], cell["sport"])]


class AllExistingModelMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = all_records()
        cls.before = deepcopy(cls.records)
        cls.training = learning.fit(cls.records, now=NOW)

    def test_all_sixteen_families_and_thirty_one_cells_fit_six_train_two_holdout(self):
        training = self.training
        self.assertTrue(learning.verify_training(training))
        self.assertEqual(len(self.records), 248)
        self.assertEqual(len(training["models"]), 31)
        self.assertEqual(len(training["registered_model_ids"]), 16)
        self.assertEqual(set(training["models"]), {cell["cell_key"] for cell in registry.cells()})
        self.assertEqual({v["state"] for v in training["model_states"].values()}, {"FITTED_SHADOW_ONLY"})
        self.assertEqual(training["scope"], "SYNTHETIC_ONLY")
        self.assertEqual(training["source_intake_sha256"], digest(self.before))
        for cell in registry.cells():
            model = training["models"][cell["cell_key"]]
            with self.subTest(cell=cell["cell_key"]):
                self.assertEqual((model["train_races"], model["validation_races"], model["unique_races"]), (6, 2, 8))
                rows = native_records(cell["model_id"], cell["sport"])
                self.assertEqual(model["train_race_ids"], [r["race_id"] for r in rows[:6]])
                self.assertEqual(model["validation_race_ids"], [r["race_id"] for r in rows[6:]])
                self.assertFalse(set(model["train_race_ids"]) & set(model["validation_race_ids"]))
                self.assertEqual(set(model["parameters"]), set(registry.specs(cell["model_id"], cell["sport"])))
                self.assertEqual(model["model_id"], cell["model_id"])
                self.assertEqual(model["sport"], cell["sport"])
                if cell["model_id"] == LEARNED_ID:
                    artifact = model["native_training"]
                    self.assertEqual(artifact["trained_examples"], 6)
                    self.assertEqual(artifact["created_at"], NOW.isoformat())
                    self.assertEqual(artifact["weights"], list(model["parameters"].values()))
        self.assertEqual(self.records, self.before)
        self.assertFalse(training["auto_promoted"])
        self.assertFalse(training["production_promoted"])
        self.assertFalse(training["accuracy_improvement_proven"])

    def test_fitted_parameters_replay_every_native_distribution_and_seller_ticket_policy(self):
        for cell in registry.cells():
            if cell["model_id"] == LEARNED_ID:
                continue  # A 2031-created ranker cannot predict its 2030 inputs.
            mid, sport = cell["model_id"], cell["sport"]
            row = native_records(mid, sport)[-1]
            payload, before = row["native_payload"], deepcopy(row["native_payload"])
            model = self.training["models"][cell["cell_key"]]
            with self.subTest(cell=cell["cell_key"]):
                baseline = registry.predict(mid, sport, payload, None, at=row["as_of"])
                fitted = registry.predict(mid, sport, payload, model["parameters"], at=row["as_of"])
                for prediction in (baseline, fitted):
                    normalized = registry.normalize(mid, sport, payload, prediction)
                    self.assertEqual(normalized["roster"], row["result"]["roster"])
                    if normalized["kind"] == "PROBABILITY":
                        size = len(normalized["roster"])
                        self.assertEqual(len(normalized["ranked"]), size*(size-1)*(size-2))
                        self.assertAlmostEqual(math.fsum(r["score"] for r in normalized["ranked"]), 1., places=9)
                        self.assertTrue(all(math.isfinite(r["score"]) and r["score"] >= 0. for r in normalized["ranked"]))
                    else:
                        self.assertIn(normalized["selection_status"],
                                      ("LOCAL_UNATTESTED", "SHADOW_DRY_RUN", "RANK_LIMIT", "FILTERED"))
                        self.assertIn(normalized["ticket_count"], (0, 5))
                        self.assertLessEqual(len([r for r in prediction["rows"] if "tickets" in r]), 5)
                        if normalized["top"]:
                            self.assertEqual({name: plan["ticket_count"] for name, plan in normalized["plans"].items()}, {"three": 3, "five": 5})
                            self.assertEqual(normalized["stakes"], [2000]*5)
                self.assertEqual(payload, before)
                self.assertEqual(registry.predict(mid, sport, payload, None, at=row["as_of"]), baseline)


class SellerNativeMatrixSupportTests(unittest.TestCase):
    def test_seller_matrix_has_actual_native_ticket_parameter_support(self):
        fitted = learning.fit(native_records("seller-shadow-v1-20261104", "boat"), now=NOW)
        member = next(iter(fitted["models"].values()))
        self.assertTrue(any(n >= 4 for n in member["parameter_support_train"].values()),
                        "synthetic seller data must exercise its native ticket-selection coefficients")
        self.assertTrue(member["coefficients_changed"])


if __name__ == "__main__":
    unittest.main()
