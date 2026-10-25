"""Offline, payload-bound comparisons of unchanged PR71 model forecasts.

No model execution, fetching, writing, rights grant or external attestation.
The injected snapshot validator must be the pinned PR71 comprehensive model
validator, not a payload flag. All callbacks are trust interfaces: their
answers remain CALLBACK_ATTESTED until independently audited by the caller.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re

from .pr71_delivery_binding import bind_audit_to_delivery, _digest, _stamp
from .proof_aware_settlement import audit_settlement
from .model_case_contracts import cardinality, MAX8, NEW_PIN


SCHEMA = "RACE_AI_MODEL_SUITE_SETTLEMENT_V1"
_FREEZE_FIELDS = {"race_id", "model_id", "prediction_sha256", "generated_at",
                  "persisted_at", "cutoff_at", "receipt"}


class ModelSettlementError(ValueError):
    """Inconsistent identities, hashes or evidence must fail closed."""


def _copy(value):
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
        # PR71 has integer diagnostic keys. A JSON roundtrip turns them into
        # strings and changes canonical sort order for 10+ entrants, breaking
        # original forecast hashes. Validate finiteness without rewriting keys.
        return deepcopy(value)
    except (TypeError, ValueError) as exc:
        raise ModelSettlementError("finite JSON evidence required") from exc


def _list(value, maximum, name):
    if not isinstance(value, list) or len(value) > maximum:
        raise ModelSettlementError("bounded " + name + " list required")


def _identity(value):
    return isinstance(value, str) and 1 <= len(value) <= 128


def _snapshot_admitted(snapshot, validator, source_check):
    if not callable(validator) or not callable(source_check):
        return False
    checks = []

    def permission(source_ref, rights_ref, purpose):
        # PR71's existing validator asks for analysis rights on every observed
        # feature. A structural validator which never checks a purpose is not
        # sufficient for promotion into formal metrics.
        accepted = purpose == "analysis" and source_check(source_ref, rights_ref, purpose) is True
        checks.append(accepted)
        return accepted

    candidate = _copy(snapshot)
    original_hash = _digest(snapshot)
    try:
        checked = validator(candidate, allow_source=permission)
    except ValueError:
        if checks and not all(checks):
            return False
        raise
    if (_digest(candidate) != original_hash or not isinstance(checked, dict)
            or checked.get("snapshot_sha256") != original_hash):
        raise ModelSettlementError("trusted validator did not bind unchanged input snapshot")
    return bool(checks and all(checks))


def audit_model_settlements(ledger, results, deliveries, freezes, *, expected_model_ids,
                            expected_model_versions=None, expected_model_source_sha40=None,
                            validate_snapshot=None, allow_source=None,
                            admit_model_roster=None, verify_result=None,
                            verify_cutoff=None, verify_model_freeze=None,
                            verify_coverage=None, model_contract='EXACT8_LEGACY'):
    """Evaluate each predeclared model against the same complete source ledger.

    deliveries: [{race_id: SOURCE_ID, delivery: original_PR71_private_delivery}]
    freezes: [{race_id, model_id, prediction_sha256, generated_at, persisted_at,
               cutoff_at, receipt}]. Independent replacement picks are forbidden.

    validate_snapshot(snapshot, *, allow_source) must use the pinned PR71
      comprehensive_four_sport_models.validate and return its snapshot_sha256.
    allow_source(source_ref, rights_ref, "analysis") and
      admit_model_roster(declaration) default deny. declaration is the complete
      immutable tuple of (model_id, expected_version, expected_source_sha40)
      triples in expected_model_ids order. That independent authority must
      establish the versions and source pin were declared prospectively.
    expected_model_versions must map exactly the declared IDs to bounded
      versions; expected_model_source_sha40 must be a lowercase 40-hex commit
      pin. Missing declarations deny both formal scores and freeze acceptance.
      These claims do not authenticate which code actually produced a payload;
      producer execution requires separately audited external evidence.
    verify_model_freeze(receipt, sha, persisted_at, cutoff_at, *,
                        expected_race_id) must independently verify the pinned
      external witness, including the original MODEL race ID (horse aliases).
    Other callback signatures match proof_aware_settlement.audit_settlement.

    This slice admits fixed, untrained models only. Learned artifacts require
    separate prospective availability evidence and are deliberately rejected.
    A missing model output/receipt is a missing forecast, never a smaller
    denominator. All inputs and original prediction hashes remain unchanged.
    """
    try:
        cardinality(model_contract)
    except ValueError:
        raise ModelSettlementError('fixed cardinality contract rejected') from None
    if model_contract == MAX8 and expected_model_source_sha40 != NEW_PIN:
        raise ModelSettlementError('explicit maximum-eight source declaration required')
    if (not isinstance(expected_model_ids, (list, tuple))
            or not 1 <= len(expected_model_ids) <= 8
            or any(not _identity(x) for x in expected_model_ids)
            or len(set(expected_model_ids)) != len(expected_model_ids)):
        raise ModelSettlementError("fixed distinct expected model roster required")
    roster = tuple(expected_model_ids)
    if expected_model_versions is not None:
        if (not isinstance(expected_model_versions, dict)
                or set(expected_model_versions) != set(roster)
                or any(not _identity(value) for value in expected_model_versions.values())):
            raise ModelSettlementError("version declaration must match the complete model roster")
        versions = {name: expected_model_versions[name] for name in roster}
    else:
        versions = None
    if (expected_model_source_sha40 is not None
            and (not isinstance(expected_model_source_sha40, str)
                 or re.fullmatch(r"[0-9a-f]{40}", expected_model_source_sha40) is None)):
        raise ModelSettlementError("lowercase 40-hex model source pin required")
    declaration = (tuple((name, versions[name], expected_model_source_sha40) for name in roster)
                   if versions is not None and expected_model_source_sha40 is not None else None)
    _list(deliveries, 10000, "private delivery")
    _list(freezes, 80000, "freeze metadata")
    ledger, results, deliveries, freezes = map(_copy, (ledger, results, deliveries, freezes))

    # Reuse the existing strict ledger/result/revision parser without calling
    # any authority. Complete local validation precedes external callbacks.
    audit_settlement(ledger, results, [])
    rows = {row["race_id"]: row for row in ledger["records"]}
    for result in results:
        cutoff = rows[result["race_id"]].get("sales_cutoff_at")
        if (result["status"] == "FINAL" and cutoff is not None
                and _stamp(result["confirmed_at"]) <= _stamp(cutoff)):
            raise ModelSettlementError("final result must follow sales cutoff")

    bound = {}
    model_payloads = {}
    model_race_sources = {}
    for item in deliveries:
        if not isinstance(item, dict) or set(item) != {"race_id", "delivery"}:
            raise ModelSettlementError("strict source race/private delivery wrapper required")
        race_id = item["race_id"]
        if not isinstance(race_id, str) or race_id not in rows or race_id in bound:
            raise ModelSettlementError("duplicate or unlisted source delivery race")
        delivery = item["delivery"]
        binding = bind_audit_to_delivery(ledger, delivery, race_id=race_id, model_contract=model_contract)
        model_race_id = binding["model_race_id"]
        if model_race_id in model_race_sources:
            raise ModelSettlementError("source races collide on one original model race identity")
        model_race_sources[model_race_id] = race_id
        snapshot = delivery["snapshot"]
        suite = delivery["research_suite"]
        if (snapshot.get("scope") != suite["scope"]
                or type(snapshot["race"].get("race_revision")) is not int
                or snapshot["race"]["race_revision"] < 1
                or type(suite.get("race_revision")) is not int
                or suite.get("race_revision") != snapshot["race"]["race_revision"]):
            raise ModelSettlementError("snapshot/suite scope or race revision mismatch")
        for name, model in suite["models"].items():
            if name not in roster:
                raise ModelSettlementError("model outside predeclared comparison roster")
            if (model.get("as_of") != suite["as_of"]
                    or type(model.get("race_revision")) is not int
                    or model.get("race_revision") != suite["race_revision"]
                    or not _identity(model.get("model_version"))):
                raise ModelSettlementError("model as-of, revision or version mismatch")
            if versions is not None and model["model_version"] != versions[name]:
                raise ModelSettlementError("model version differs from prospective declaration")
            if (model.get("trained") is not False or "model_sha256" in model
                    or name == "multisport-chronological-ranker-v1"):
                raise ModelSettlementError("learned artifact availability is outside this bridge")
            for hash_field in ("snapshot_sha256", "input_sha256"):
                if hash_field in model and model[hash_field] != binding["feature_snapshot_sha256"]:
                    raise ModelSettlementError("models do not share the unchanged input snapshot")
            model_payloads[(race_id, name)] = model
        bound[race_id] = (binding, delivery)

    prepared = {name: [] for name in roster}
    used_keys, used_receipts = set(), set()
    for freeze in freezes:
        if not isinstance(freeze, dict) or set(freeze) != _FREEZE_FIELDS:
            raise ModelSettlementError("strict freeze metadata; independent picks forbidden")
        race_id, model_id = freeze["race_id"], freeze["model_id"]
        if not isinstance(race_id, str) or not _identity(model_id):
            raise ModelSettlementError("freeze source/model identity missing")
        key = (race_id, model_id)
        if key in used_keys or key not in model_payloads:
            raise ModelSettlementError("duplicate or unbound model freeze")
        used_keys.add(key)
        receipt = freeze["receipt"]
        if (not isinstance(receipt, dict) or set(receipt) != {"run_id", "path"}
                or type(receipt["run_id"]) is not int or not 1 <= receipt["run_id"] <= 10**15
                or not isinstance(receipt["path"], str) or not 1 <= len(receipt["path"]) <= 512):
            raise ModelSettlementError("separate bounded GitHub witness receipt required")
        receipt_hash = _digest(receipt)
        if receipt_hash in used_receipts:
            raise ModelSettlementError("copied receipt cannot attest another model or race")
        used_receipts.add(receipt_hash)
        model = model_payloads[key]
        binding, delivery = bound[race_id]
        if (freeze["prediction_sha256"] != model["prediction_sha256"]
                or freeze["cutoff_at"] != binding["model_claimed_cutoff_at"]):
            raise ModelSettlementError("freeze does not bind original model hash/cutoff")
        generated, persisted, cutoff = map(_stamp, (freeze["generated_at"],
                                                    freeze["persisted_at"], freeze["cutoff_at"]))
        if not (_stamp(delivery["ingested_at"]) <= generated <= persisted < cutoff
                and _stamp(delivery["snapshot"]["race"]["as_of"]) <= generated):
            raise ModelSettlementError("actual separate generation/persistence chronology required")
        prepared[model_id].append({"race_id": race_id,
                                   "model_race_id": binding["model_race_id"],
                                   "model_id": model_id,
                                   "ordered_top8": _copy(model["ordered_top8"]),
                                   "prediction_sha256": model["prediction_sha256"],
                                   "generated_at": freeze["generated_at"],
                                   "persisted_at": freeze["persisted_at"],
                                   "cutoff_at": freeze["cutoff_at"], "receipt": receipt})

    roster_ok = (declaration is not None and callable(admit_model_roster)
                 and admit_model_roster(declaration) is True)
    admissions = {race_id: _snapshot_admitted(delivery["snapshot"], validate_snapshot, allow_source)
                  for race_id, (_, delivery) in bound.items()}
    inputs_ok = (callable(validate_snapshot) and callable(allow_source)
                 and all(admissions.values()))

    # Verify each shared fact once, then score every model from that same
    # immutable evidence decision. Re-querying a changing authority per model
    # would make the supposedly shared denominator depend on evaluation order.
    coverage_ok = bool(roster_ok and inputs_ok and callable(verify_coverage)
                       and verify_coverage(_copy(ledger)) is True)
    result_verdicts = {_digest(result): callable(verify_result)
                       and verify_result(_copy(result)) is True for result in results}
    cutoff_verdicts = {race_id: callable(verify_cutoff)
                       and verify_cutoff(_copy(row)) is True for race_id, row in rows.items()}

    def coverage_check(source_ledger):
        return coverage_ok

    def result_check(result):
        return result_verdicts[_digest(result)]

    def cutoff_check(row):
        return cutoff_verdicts[row["race_id"]]

    def freeze_check(forecast, source_race_id):
        if not (roster_ok and admissions.get(source_race_id) and callable(verify_model_freeze)):
            return False
        binding, _ = bound[source_race_id]
        return verify_model_freeze(_copy(forecast["receipt"]), forecast["prediction_sha256"],
                                   forecast["persisted_at"], forecast["cutoff_at"],
                                   expected_race_id=binding["model_race_id"]) is True

    comparisons = {name: audit_settlement(ledger, results, prepared[name],
                                         verify_result=result_check, verify_cutoff=cutoff_check,
                                         verify_freeze=freeze_check, verify_coverage=coverage_check)
                   for name in roster}
    record = {"schema": SCHEMA,
              "evidence_status": "CALLBACK_ATTESTED_UNLESS_INDEPENDENTLY_AUDITED",
              "expected_model_ids": list(roster), "models": comparisons,
              "expected_model_versions": versions,
              "expected_model_source_sha40": expected_model_source_sha40,
              "model_declaration_sha256": _digest(declaration) if declaration is not None else None,
              "producer_execution_authenticated_by_library": False,
              "model_roster_admitted_by_callback": bool(roster_ok),
              "all_supplied_snapshots_admitted_by_callback": bool(inputs_ok),
              "source_ledger_sha256": _digest(ledger),
              "official_result_claims_sha256": _digest(results),
              "freeze_metadata_sha256": _digest(freezes),
              "deliveries": [{"race_id": race_id,
                              "model_race_id": binding["model_race_id"],
                              "private_delivery_sha256": delivery["delivery_sha256"],
                              "feature_snapshot_sha256": binding["feature_snapshot_sha256"],
                              "snapshot_admitted_by_callback": admissions[race_id],
                              "models": [{"model_id": name,
                                          "model_version": model["model_version"],
                                          "prediction_sha256": model["prediction_sha256"]}
                                         for name, model in delivery["research_suite"]["models"].items()]}
                             for race_id, (binding, delivery) in bound.items()],
              "official_prediction": False, "externally_persisted": False,
              "eligible_for_website_publication": False, "automatic_betting": False}
    record["evaluation_sha256"] = _digest(record)
    return record
