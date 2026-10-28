"""Pinned PR71 -> PR72 per-model settlement, FICTIONAL OFFLINE EVIDENCE ONLY.

Actual existing local research functions run against authored PR71 fixtures.
Source permissions, times, GitHub responses, receipts and official results are
all synthetic. This script grants no rights and establishes no real freeze.
"""
from copy import deepcopy
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch


HERE = Path(__file__).resolve().parent.parent
REFERENCE = HERE / "pr71-private-transport-reference"
PINNED_PR71 = "ebe93f13062cf0461b81b924a5dc0482ada37b56"
PINNED_FILES = (
    "race_ai/comprehensive_four_sport_models.py",
    "race_ai/four_sport_matchup_models.py", "race_ai/four_sport_model_suite.py",
    "race_ai/four_sport_learning.py", "race_ai/permissioned_source_delivery.py",
    "race_ai/github_freeze_receipt.py", "tests/test_comprehensive_four_sport_models.py",
    "tests/test_permissioned_source_delivery.py",
    "race_ai/private_delivery_codec.py",
)


def check_reference():
    if not REFERENCE.is_dir():
        raise RuntimeError("independent pinned PR71 settlement checkout missing")
    if (REFERENCE / ".git").exists():
        actual = subprocess.check_output(["git", "-C", str(REFERENCE), "rev-parse", "HEAD"],
                                         text=True).strip()
        if actual != PINNED_PR71:
            raise RuntimeError("PR71 settlement reference HEAD differs from pinned revision")
        changed = subprocess.check_output(["git", "-C", str(REFERENCE), "status", "--porcelain",
                                           "--", *PINNED_FILES], text=True)
        if changed:
            raise RuntimeError("pinned PR71 settlement inputs have local modifications")
    else:
        # Parent may materialize git blobs locally without creating a nested
        # checkout. Verify every loaded file against the exact local git object.
        for relative in PINNED_FILES:
            expected = subprocess.check_output(["git", "-C", str(HERE), "show",
                                                PINNED_PR71 + ":" + relative])
            # Windows checkouts can use CRLF. Normalize source-code line ends
            # only; original forecast/evidence payload bytes are never changed.
            actual = (REFERENCE / relative).read_bytes().replace(b"\r\n", b"\n")
            if actual != expected.replace(b"\r\n", b"\n"):
                raise RuntimeError("materialized PR71 settlement reference differs: " + relative)


check_reference()
sys.path.insert(0, str(HERE))
import race_ai
import tests

race_ai.__path__.append(str(REFERENCE / "race_ai"))
tests.__path__.append(str(REFERENCE / "tests"))
sys.path.insert(0, str(REFERENCE / "tests"))

from test_permissioned_source_delivery import AT, gate, raw_feed
from race_ai.comprehensive_four_sport_models import digest, validate
from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.permissioned_source_delivery import deliver
from race_ai.private_delivery_codec import serialize_private_delivery, deserialize_private_delivery
from race_ai.github_freeze_receipt import BASE, verify_github_freeze
from race_ai.append_only_freeze_writer import prepare_anchor
from race_ai.model_suite_settlement import audit_model_settlements
from race_ai.pr71_delivery_binding import bind_audit_to_delivery
from race_ai.race_bound_freeze_receipt import verify_bound_receipt


# Version values are declared independently of observed output payloads. This
# literal matches the four fixed families at the separately pinned PR71 commit.
PREDECLARED_VERSIONS = {name: "0.1.0-UNTRAINED" for name in ALL_MODELS}
PREDECLARED_MODELS = tuple((name, PREDECLARED_VERSIONS[name], PINNED_PR71) for name in ALL_MODELS)


def rehash_delivery(delivery):
    snapshot_hash = digest(delivery["snapshot"])
    suite = delivery["research_suite"]
    delivery["feature_snapshot_sha256"] = snapshot_hash
    suite["input_sha256"] = snapshot_hash
    for model in suite["models"].values():
        model["snapshot_sha256"] = snapshot_hash
        model["prediction_sha256"] = digest({k: v for k, v in model.items()
                                              if k != "prediction_sha256"})
    suite["suite_sha256"] = digest({k: v for k, v in suite.items() if k != "suite_sha256"})
    delivery["delivery_sha256"] = digest({k: v for k, v in delivery.items()
                                          if k != "delivery_sha256"})


def expect_rejected(function):
    try:
        function()
    except ValueError:
        return
    raise AssertionError("malformed synthetic evidence was accepted")


def verify_sport(sport, run_offset):
    policy = gate()
    delivery = deliver(raw_feed(sport), policy, at=AT, persist=False)
    before = deepcopy(delivery)
    race = delivery["snapshot"]["race"]
    source_sport = "horse_local" if sport == "horse" else sport
    day, venue, cutoff = race["event_date_jst"], race["venue"], race["sales_cutoff_at"]
    source_ids = [f"{source_sport}:{day}:{venue}:{n}" for n in (1, 2)]
    ledger = {"schema": "RACE_AI_FORECAST_AUDIT_V1", "dataset_status": "AUDIT_ONLY",
              "event_date_jst": day,
              "records": [{"race_id": identity, "sport": source_sport, "venue": venue,
                           "race_no": n, "sales_cutoff_at": cutoff, "cutoff_verified": False,
                           "prediction": None, "result": None}
                          for n, identity in enumerate(source_ids, 1)]}
    results = [{"race_id": identity, "status": "FINAL", "trifecta_offered": True,
                "payouts": [{"combination": [1, 2, 3], "yen_per_100": 1000}],
                "refund_status": "NONE", "revision_no": 1,
                "confirmed_at": day + "T11:00:00+09:00",
                "source_ref": "https://example.org/fictional-result"} for identity in source_ids]
    binding = bind_audit_to_delivery(ledger, delivery, race_id=source_ids[0])
    generated, persisted = day + "T09:20:00+09:00", day + "T09:35:00+09:00"
    api, freezes = {}, []
    for index, name in enumerate(ALL_MODELS):
        prepared = prepare_anchor(binding, name, generated, persisted)
        run_id = run_offset + index
        commit = f"{run_id:040x}"
        api[f"{BASE}/actions/runs/{run_id}"] = {
            "id": run_id, "event": "push", "head_sha": commit,
            "repository": {"full_name": "haji84/RACE-AI"},
            "created_at": day + "T00:40:00Z"}
        api[f"{BASE}/contents/{prepared['path']}?ref={commit}"] = {
            "type": "file", "encoding": "base64",
            "content": base64.b64encode(json.dumps(prepared["anchor"]).encode()).decode()}
        freezes.append({"race_id": source_ids[0], "model_id": name,
                        "prediction_sha256": prepared["anchor"]["prediction_sha256"],
                        "generated_at": generated, "persisted_at": persisted, "cutoff_at": cutoff,
                        "receipt": {"run_id": run_id, "path": prepared["path"]}})
    receipt_calls = []

    def synthetic_freeze(receipt, sha, persisted_at, cutoff_at, *, expected_race_id):
        receipt_calls.append(sha)
        return verify_bound_receipt(receipt, sha, persisted_at, cutoff_at,
                                    expected_race_id=expected_race_id,
                                    trusted_legacy_verifier=verify_github_freeze,
                                    github_fetch=lambda url: deepcopy(api[url]))

    result_hashes = {digest(result) for result in results}
    gates = {"validate_snapshot": validate, "allow_source": policy.authorize,
             "expected_model_versions": PREDECLARED_VERSIONS,
             "expected_model_source_sha40": PINNED_PR71,
             "admit_model_roster": lambda declaration: declaration == PREDECLARED_MODELS,
             "verify_result": lambda result: digest(result) in result_hashes,
             "verify_cutoff": lambda row: row["sales_cutoff_at"] == cutoff,
             "verify_model_freeze": synthetic_freeze,
             "verify_coverage": lambda observed: digest(observed) == digest(ledger)}
    deliveries = [{"race_id": source_ids[0], "delivery": delivery}]

    def evaluate(supplied=deliveries, metadata=freezes, callbacks=gates):
        return audit_model_settlements(ledger, results, supplied, metadata,
                                       expected_model_ids=ALL_MODELS, **callbacks)

    result = evaluate()
    assert len(result["models"]) == 4
    assert result["evidence_status"] == "CALLBACK_ATTESTED_UNLESS_INDEPENDENTLY_AUDITED"
    assert result["model_declaration_sha256"] == digest(PREDECLARED_MODELS)
    assert result["expected_model_source_sha40"] == PINNED_PR71
    assert result["producer_execution_authenticated_by_library"] is False
    for name, comparison in result["models"].items():
        original = before["research_suite"]["models"][name]
        n = len(before["snapshot"]["participants"])
        assert original["candidate_count"] == n * (n - 1) * (n - 2)
        assert original["snapshot_sha256"] == before["feature_snapshot_sha256"]
        assert comparison["eligible_verified_subset"] == 2
        assert comparison["formal_capture_rate"] == 0.5
        expected_hit = 0.5 if [1, 2, 3] in original["ordered_top8"] else 0
        assert comparison["formal_hit_at_8_all"] == expected_hit
    assert delivery == before
    assert all(x["formal_hit_at_8_all"] is None for x in evaluate(callbacks={})["models"].values())
    # Preserve the legacy rejection: sorted ordinary JSON changes model order
    # in every sport, and integer diagnostic key semantics for horse. Never
    # infer lost types/order from an old file or mint replacement original hashes.
    reloaded = json.loads(json.dumps(delivery, sort_keys=True, ensure_ascii=False))
    expect_rejected(lambda: evaluate(supplied=[{"race_id": source_ids[0], "delivery": reloaded}]))
    print("SYNTHETIC_LEGACY_SORTED_JSON_REJECTED", sport)

    # Explicit opt-in local transport has its own checksum. Fictional temporary
    # disk persistence is not an external server-time or source-rights witness.
    wire = serialize_private_delivery(delivery)
    with tempfile.TemporaryDirectory(prefix="race-ai-synthetic-transport-") as directory:
        path = Path(directory) / "fictional-private-delivery.json"
        with path.open("xb") as stream:
            stream.write(wire)
        decoded = deserialize_private_delivery(path.read_bytes(),
                      expected_delivery_sha256=before["delivery_sha256"])
    assert decoded is not delivery and decoded["research_suite"] is not delivery["research_suite"]
    assert digest(decoded) == digest(before)
    assert list(decoded["research_suite"]["models"]) == list(before["research_suite"]["models"])
    assert evaluate(supplied=[{"race_id": source_ids[0], "delivery": decoded}]) == result
    assert delivery == before
    expect_rejected(lambda: deserialize_private_delivery(wire,
                          expected_delivery_sha256="0" * 64))
    print("SYNTHETIC_LOCAL_TRANSPORT_TO_UNCHANGED_SETTLEMENT_PASS", sport,
          "WIRE_BYTES", len(wire), "ORIGINAL_HASHES_AND_FULL_DENOMINATORS_UNCHANGED")

    # Tampering cannot borrow an unchanged, otherwise accepted original hash.
    changed = deepcopy(deliveries)
    changed[0]["delivery"]["research_suite"]["models"][ALL_MODELS[0]]["ordered_top8"].reverse()
    receipt_calls.clear()
    expect_rejected(lambda: evaluate(supplied=changed))
    assert not receipt_calls

    # A fully rehashed replacement still fails the original pinned anchor.
    changed = deepcopy(deliveries)
    changed[0]["delivery"]["research_suite"]["models"][ALL_MODELS[0]]["research_note"] = "replacement"
    rehash_delivery(changed[0]["delivery"])
    changed_freezes = deepcopy(freezes)
    changed_freezes[0]["prediction_sha256"] = changed[0]["delivery"]["research_suite"]["models"][ALL_MODELS[0]]["prediction_sha256"]
    expect_rejected(lambda: evaluate(supplied=changed, metadata=changed_freezes))

    # A new receipt accepting a new hash cannot retrospectively select a
    # different model version under an already declared model ID.
    changed = deepcopy(deliveries)
    changed[0]["delivery"]["research_suite"]["models"][ALL_MODELS[0]]["model_version"] = "new-unapproved-version"
    rehash_delivery(changed[0]["delivery"])
    metadata = deepcopy(freezes)
    metadata[0]["prediction_sha256"] = changed[0]["delivery"]["research_suite"]["models"][ALL_MODELS[0]]["prediction_sha256"]
    metadata[0]["receipt"] = {"run_id": 9999,
                               "path": "audit/freezes/" + day + "/new-unapproved-version.json"}
    newly_accepted = []

    def synthetic_new_receipt(*args, **kwargs):
        newly_accepted.append(args)
        return True

    changed_gates = dict(gates, verify_model_freeze=synthetic_new_receipt)
    expect_rejected(lambda: evaluate(supplied=changed, metadata=metadata, callbacks=changed_gates))
    assert not newly_accepted
    wrong_source = evaluate(callbacks=dict(gates, expected_model_source_sha40="f" * 40))
    assert wrong_source["model_roster_admitted_by_callback"] is False
    assert all(x["formal_hit_at_8_all"] is None for x in wrong_source["models"].values())
    assert all(x["freeze_verified_subset"] == 0 for x in wrong_source["models"].values())

    # Cryptographically consistent envelopes do not bypass actual PR71 input
    # validation: neither market fields nor unknown publication times qualify.
    for invalid in ("odds", "missing_publication", "missing_required"):
        changed = deepcopy(deliveries)
        snapshot = changed[0]["delivery"]["snapshot"]
        if invalid == "odds":
            snapshot["participants"][0]["features"]["odds"] = deepcopy(snapshot["participants"][0]["features"]["ability"])
        elif invalid == "missing_publication":
            snapshot["participants"][0]["features"]["ability"]["published_at"] = None
        else:
            del snapshot["participants"][0]["features"]["ability"]
        rehash_delivery(changed[0]["delivery"])
        metadata = deepcopy(freezes)
        for freeze in metadata:
            freeze["prediction_sha256"] = changed[0]["delivery"]["research_suite"]["models"][freeze["model_id"]]["prediction_sha256"]
        receipt_calls.clear()
        expect_rejected(lambda: evaluate(supplied=changed, metadata=metadata))
        assert not receipt_calls

    print("SYNTHETIC_ONLY_PR71_MODEL_SETTLEMENT_PASS", sport,
          "4_MODELS; 2_ELIGIBLE_EACH; 1_FROZEN_EACH; ORIGINAL_HASHES_UNCHANGED")


with patch("socket.create_connection", side_effect=AssertionError("network forbidden in synthetic verification")):
    for index, sport in enumerate(("boat", "keirin", "autorace", "horse")):
        verify_sport(sport, 4000 + index * 10)
print("SYNTHETIC_IN_MEMORY_AND_OPT_IN_LOCAL_TRANSPORT_ONLY: NO_REAL_FREEZE_PRODUCER_RIGHTS_OR_ACCURACY_CLAIM", PINNED_PR71)
